"""
payouts/tests.py

Phase 4 payout API and state-machine tests.

Key design decisions:
  - Concurrency coverage uses TransactionTestCase because TestCase wraps each test in a transaction.
  - API tests patch Celery enqueue calls so assertions focus on payout creation invariants.
  - Balance assertions always compare API values against immutable ledger aggregation.
"""

import threading
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from ledger.models import LedgerEntry, get_merchant_balance
from merchants.models import BankAccount, Merchant
from payouts.models import InvalidStateTransition, PayoutRequest


def create_merchant_fixture(email="merchant@example.com", amount_paise=10_000):
    """
    Create a user, merchant, default bank account, and opening CREDIT.

    Args:
        email: Email shared by the Django user and Merchant auth mapping.
        amount_paise: Opening balance in integer paise.

    Returns:
        Tuple of (user, merchant, bank_account).
    """
    User = get_user_model()
    user = User.objects.create_user(username=email, email=email, password="playto-test")
    merchant = Merchant.objects.create(name="Test Merchant", email=email)
    bank_account = BankAccount.objects.create(
        merchant=merchant,
        account_number="50100012345678",
        ifsc_code="HDFC0001234",
        account_holder="Test Merchant",
        is_default=True,
    )
    # Opening funds are represented as immutable CREDIT rows, never a mutable balance column. (P3)
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.CREDIT,
        amount_paise=amount_paise,
        reference_id="TEST-SEED",
        description="Test opening credit",
    )
    return user, merchant, bank_account


def authenticated_client(user):
    """
    Build a DRF test client authenticated as the supplied user.

    Args:
        user: Django user whose email maps to a Merchant.

    Returns:
        APIClient with force_authenticate applied.
    """
    client = APIClient()
    # force_authenticate exercises view ownership logic without coupling tests to JWT token issuance.
    client.force_authenticate(user=user)
    return client


def ledger_balance_for(merchant):
    """
    Compute credits minus debits using the same invariant asserted by the API.

    Args:
        merchant: Merchant whose immutable ledger should be checked.

    Returns:
        Integer balance in paise.
    """
    credits = LedgerEntry.objects.filter(merchant=merchant, entry_type=LedgerEntry.CREDIT).aggregate(total=Sum("amount_paise"))["total"] or 0
    debits = LedgerEntry.objects.filter(merchant=merchant, entry_type=LedgerEntry.DEBIT).aggregate(total=Sum("amount_paise"))["total"] or 0
    return credits - debits


class PayoutIdempotencyTests(TestCase):
    """Verify Stripe-style idempotent payout creation."""

    def test_idempotency_key_replay(self):
        """
        Stripe principle P2 - Idempotency is a first-class API primitive.

        Two identical POSTs with the same key must return identical responses and create one hold.
        Reusing the same key with a different amount must return idempotency_key_conflict.
        """
        user, merchant, bank_account = create_merchant_fixture(amount_paise=20_000)
        client = authenticated_client(user)
        body = {"amount_paise": 6_000, "bank_account_id": str(bank_account.id)}
        key = str(uuid.uuid4())

        with patch("payouts.views.process_payout.delay") as delay:
            response_1 = client.post("/api/v1/payouts/", body, format="json", HTTP_IDEMPOTENCY_KEY=key)
            response_2 = client.post("/api/v1/payouts/", body, format="json", HTTP_IDEMPOTENCY_KEY=key)
            response_3 = client.post(
                "/api/v1/payouts/",
                {"amount_paise": 7_000, "bank_account_id": str(bank_account.id)},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        self.assertEqual(response_1.status_code, 201)
        self.assertEqual(response_2.status_code, 201)
        self.assertEqual(response_1.json(), response_2.json())
        self.assertEqual(response_3.status_code, 409)
        self.assertEqual(response_3.json()["error"]["code"], "idempotency_key_conflict")
        self.assertEqual(PayoutRequest.objects.filter(merchant=merchant).count(), 1)
        self.assertEqual(LedgerEntry.objects.filter(merchant=merchant, entry_type=LedgerEntry.DEBIT).count(), 1)
        self.assertEqual(delay.call_count, 1)


class PayoutStateMachineTests(TestCase):
    """Verify model-layer payout state transitions."""

    def _payout_in_state(self, state):
        """
        Create a payout in the requested state using legal transitions.

        Args:
            state: Target PayoutRequest state.

        Returns:
            PayoutRequest refreshed into that state.
        """
        _, merchant, bank_account = create_merchant_fixture(email=f"{state}-{uuid.uuid4()}@example.com")
        payout = PayoutRequest.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=1_000,
            idempotency_key=str(uuid.uuid4()),
        )
        if state == PayoutRequest.PENDING:
            return payout
        payout = payout.transition_to(PayoutRequest.PROCESSING, reason="test setup")
        if state == PayoutRequest.PROCESSING:
            return payout
        if state == PayoutRequest.COMPLETED:
            return payout.transition_to(PayoutRequest.COMPLETED, reason="test setup")
        return payout.transition_to(PayoutRequest.FAILED, reason="test setup")

    def test_illegal_state_transitions_raise(self):
        """
        Stripe principle P4 - Illegal payout transitions are hard model-layer errors.

        Every non-terminal shortcut, backward move, and terminal escape must raise.
        """
        illegal_transitions = [
            (PayoutRequest.PENDING, PayoutRequest.COMPLETED),
            (PayoutRequest.PENDING, PayoutRequest.FAILED),
            (PayoutRequest.PROCESSING, PayoutRequest.PENDING),
            (PayoutRequest.COMPLETED, PayoutRequest.PENDING),
            (PayoutRequest.COMPLETED, PayoutRequest.PROCESSING),
            (PayoutRequest.COMPLETED, PayoutRequest.FAILED),
            (PayoutRequest.FAILED, PayoutRequest.PENDING),
            (PayoutRequest.FAILED, PayoutRequest.PROCESSING),
            (PayoutRequest.FAILED, PayoutRequest.COMPLETED),
            (PayoutRequest.PROCESSING, PayoutRequest.PROCESSING),
        ]

        for current_state, next_state in illegal_transitions:
            with self.subTest(current_state=current_state, next_state=next_state):
                payout = self._payout_in_state(current_state)
                with self.assertRaises(InvalidStateTransition):
                    payout.transition_to(next_state, reason="illegal test transition")


class PayoutBalanceInvariantTests(TestCase):
    """Verify balances across the payout lifecycle."""

    def test_balance_invariant_at_every_lifecycle_stage(self):
        """
        Stripe principles P3 and P10 - Ledger is source of truth and refunds are atomic.

        API available balance must equal SUM(CREDIT)-SUM(DEBIT) after create, process,
        complete, and fail/refund lifecycle stages.
        """
        user, merchant, bank_account = create_merchant_fixture(amount_paise=10_000)
        client = authenticated_client(user)

        def assert_profile(expected_available, expected_held):
            profile = client.get("/api/v1/merchants/me/")
            self.assertEqual(profile.status_code, 200)
            self.assertEqual(profile.json()["available_balance_paise"], expected_available)
            self.assertEqual(profile.json()["held_balance_paise"], expected_held)
            self.assertEqual(profile.json()["available_balance_paise"], ledger_balance_for(merchant))
            self.assertEqual(profile.json()["available_balance_paise"], get_merchant_balance(merchant.id))

        assert_profile(expected_available=10_000, expected_held=0)

        with patch("payouts.views.process_payout.delay"):
            create_response = client.post(
                "/api/v1/payouts/",
                {"amount_paise": 6_000, "bank_account_id": str(bank_account.id)},
                format="json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
        self.assertEqual(create_response.status_code, 201)
        payout = PayoutRequest.objects.get(pk=create_response.json()["id"])
        assert_profile(expected_available=4_000, expected_held=6_000)

        payout = payout.transition_to(PayoutRequest.PROCESSING, reason="bank worker picked payout")
        assert_profile(expected_available=4_000, expected_held=6_000)

        payout.transition_to(PayoutRequest.COMPLETED, reason="bank settled payout")
        assert_profile(expected_available=4_000, expected_held=0)

        with patch("payouts.views.process_payout.delay"):
            failed_create_response = client.post(
                "/api/v1/payouts/",
                {"amount_paise": 3_000, "bank_account_id": str(bank_account.id)},
                format="json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
        self.assertEqual(failed_create_response.status_code, 201)
        failed_payout = PayoutRequest.objects.get(pk=failed_create_response.json()["id"])
        assert_profile(expected_available=1_000, expected_held=3_000)

        failed_payout = failed_payout.transition_to(PayoutRequest.PROCESSING, reason="bank worker picked payout")
        failed_payout.transition_to(PayoutRequest.FAILED, reason="bank rejected payout")
        assert_profile(expected_available=4_000, expected_held=0)


class PayoutConcurrencyTests(TransactionTestCase):
    """Verify row locks prevent concurrent payout overdraw."""

    reset_sequences = True

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_payout_overdraw(self):
        """
        Stripe principle P5 - Lock before you read.

        Two simultaneous payout requests for 6000 paise against a 10000 paise balance
        must produce exactly one hold and one insufficient_funds response.
        """
        user, merchant, bank_account = create_merchant_fixture(amount_paise=10_000)
        barrier = threading.Barrier(2, timeout=10)
        responses = []
        errors = []
        response_lock = threading.Lock()

        def post_payout(idempotency_key):
            # Each thread owns its own DB connection and client to avoid sharing request state.
            close_old_connections()
            thread_client = authenticated_client(user)
            try:
                barrier.wait()
                response = thread_client.post(
                    "/api/v1/payouts/",
                    {"amount_paise": 6_000, "bank_account_id": str(bank_account.id)},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=idempotency_key,
                )
                with response_lock:
                    responses.append(response)
            except Exception as exc:  # pragma: no cover - surfaced by assertion below.
                with response_lock:
                    errors.append(exc)
            finally:
                close_old_connections()

        with patch("payouts.views.process_payout.delay"):
            threads = [
                threading.Thread(target=post_payout, args=(str(uuid.uuid4()),)),
                threading.Thread(target=post_payout, args=(str(uuid.uuid4()),)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(response.status_code for response in responses), [201, 402])
        error_response = next(response for response in responses if response.status_code == 402)
        self.assertEqual(error_response.json()["error"]["code"], "insufficient_funds")
        self.assertEqual(LedgerEntry.objects.filter(merchant=merchant, entry_type=LedgerEntry.DEBIT).count(), 1)
        self.assertEqual(ledger_balance_for(merchant), 4_000)
        self.assertEqual(
            PayoutRequest.objects.filter(
                merchant=merchant,
                state__in=[PayoutRequest.PENDING, PayoutRequest.PROCESSING],
            ).count(),
            1,
        )
