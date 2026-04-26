"""
workers/tests.py

Phase 4 worker heartbeat, retry, and cleanup tests.

Key design decisions:
  - Worker tests call task run methods directly so no external broker is required.
  - Stuck payout setup writes updated_at with queryset.update(), matching production heartbeat repair.
  - Refund assertions compare ledger balance before and after failure.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from idempotency.models import IdempotencyKey
from ledger.models import LedgerEntry, get_held_balance, get_merchant_balance
from merchants.models import BankAccount, Merchant
from payouts.models import PayoutRequest
from workers.tasks import process_payout, purge_expired_idempotency_keys, retry_stuck_payouts


def create_processing_payout(amount_paise=3_000, attempt_count=0):
    """
    Create a processing payout with a matching DEBIT hold.

    Args:
        amount_paise: Payout amount in integer paise.
        attempt_count: Existing worker retry count.

    Returns:
        Tuple of (merchant, payout).
    """
    User = get_user_model()
    email = f"worker-{uuid.uuid4()}@example.com"
    User.objects.create_user(username=email, email=email, password="playto-test")
    merchant = Merchant.objects.create(name="Worker Merchant", email=email)
    bank_account = BankAccount.objects.create(
        merchant=merchant,
        account_number="50100098765432",
        ifsc_code="HDFC0001234",
        account_holder="Worker Merchant",
        is_default=True,
    )
    # Opening CREDIT gives the payout real funds to hold.
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.CREDIT,
        amount_paise=10_000,
        reference_id="WORKER-SEED",
        description="Worker test opening credit",
    )
    payout = PayoutRequest.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=amount_paise,
        idempotency_key=str(uuid.uuid4()),
        attempt_count=attempt_count,
    )
    # The DEBIT is the payout hold; failure must create a matching CREDIT refund. (P3, P10)
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.DEBIT,
        amount_paise=amount_paise,
        reference_id=str(payout.id),
        description="Worker test payout hold",
    )
    payout = payout.transition_to(PayoutRequest.PROCESSING, reason="worker test setup")
    return merchant, payout


class WorkerHeartbeatTests(TransactionTestCase):
    """Verify retry_stuck_payouts uses updated_at as a heartbeat."""

    def test_retry_stuck_payouts_reenqueues_with_exponential_backoff(self):
        """
        Stripe principles P7 and P8 - Stuck payouts are detected by heartbeat and rechecked under lock.

        A processing payout untouched for more than 30 seconds should increment attempt_count,
        refresh updated_at, and enqueue process_payout with countdown = 2 ** attempt_count.
        """
        _, payout = create_processing_payout(attempt_count=0)
        stale_time = timezone.now() - timedelta(seconds=45)
        # Queryset.update bypasses auto_now so the test can simulate an old worker heartbeat.
        PayoutRequest.objects.filter(pk=payout.pk).update(updated_at=stale_time)

        with patch("workers.tasks.process_payout.apply_async") as apply_async:
            result = retry_stuck_payouts.run()

        payout.refresh_from_db()
        self.assertEqual(result["retried"], 1)
        self.assertEqual(payout.state, PayoutRequest.PROCESSING)
        self.assertEqual(payout.attempt_count, 1)
        self.assertGreater(payout.updated_at, stale_time)
        apply_async.assert_called_once_with(args=[str(payout.id)], countdown=2)

    def test_retry_stuck_payouts_fails_and_refunds_after_retry_limit(self):
        """
        Stripe principle P10 - Retry exhaustion fails and refunds in one atomic transition.

        A stuck payout at attempt_count >= 3 should become failed and return the DEBIT hold
        with a CREDIT ledger entry in the same model-layer transition.
        """
        merchant, payout = create_processing_payout(amount_paise=3_000, attempt_count=3)
        stale_time = timezone.now() - timedelta(seconds=45)
        PayoutRequest.objects.filter(pk=payout.pk).update(updated_at=stale_time)
        self.assertEqual(get_merchant_balance(merchant.id), 7_000)
        self.assertEqual(get_held_balance(merchant.id), 3_000)

        with patch("workers.tasks.process_payout.apply_async") as apply_async:
            result = retry_stuck_payouts.run()

        payout.refresh_from_db()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(payout.state, PayoutRequest.FAILED)
        self.assertEqual(payout.failure_reason, "stuck_payout_retry_limit_exceeded")
        self.assertEqual(get_merchant_balance(merchant.id), 10_000)
        self.assertEqual(get_held_balance(merchant.id), 0)
        self.assertEqual(
            LedgerEntry.objects.filter(
                merchant=merchant,
                entry_type=LedgerEntry.CREDIT,
                reference_id=str(payout.id),
            ).count(),
            1,
        )
        apply_async.assert_not_called()


class IdempotencyCleanupTests(TestCase):
    """Verify periodic idempotency-key cleanup."""

    def test_purge_expired_idempotency_keys_deletes_only_expired_rows(self):
        """
        Stripe principle P2 - Idempotency replay rows expire after their safety window.

        The cleanup task should remove expired keys while leaving active replay keys intact.
        """
        merchant = Merchant.objects.create(name="Cleanup Merchant", email="cleanup@example.com")
        expired = IdempotencyKey.objects.create(
            merchant=merchant,
            key="expired-key",
            status=IdempotencyKey.DONE,
            request_params={"amount_paise": 1_000, "bank_account_id": str(uuid.uuid4())},
            response_status=201,
            response_body={"id": str(uuid.uuid4())},
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        active = IdempotencyKey.objects.create(
            merchant=merchant,
            key="active-key",
            status=IdempotencyKey.DONE,
            request_params={"amount_paise": 2_000, "bank_account_id": str(uuid.uuid4())},
            response_status=201,
            response_body={"id": str(uuid.uuid4())},
            expires_at=timezone.now() + timedelta(hours=1),
        )

        deleted = purge_expired_idempotency_keys.run()

        self.assertEqual(deleted, 1)
        self.assertFalse(IdempotencyKey.objects.filter(pk=expired.pk).exists())
        self.assertTrue(IdempotencyKey.objects.filter(pk=active.pk).exists())


class WorkerIdempotencyTests(TransactionTestCase):
    """Verify workers exit cleanly on already-settled payouts (Part C of spec Test 5)."""

    def test_process_payout_on_completed_payout_is_noop(self):
        """
        Stripe principle P8 - Background workers are suspects.

        Calling process_payout on a payout that is already in a terminal state
        ('completed') must not raise an exception, change the payout state,
        or create any new ledger entries.

        This verifies that duplicate worker delivery (e.g. Celery at-least-once)
        is harmless. The worker must detect the stale state at entry and exit cleanly.
        """
        merchant, payout = create_processing_payout(amount_paise=3_000, attempt_count=0)

        # Move to completed through the legal state machine path
        payout.transition_to(PayoutRequest.COMPLETED, reason="test settlement")
        payout.refresh_from_db()

        # Snapshot ledger state before the duplicate worker call
        ledger_count_before = LedgerEntry.objects.filter(merchant=merchant).count()
        balance_before = get_merchant_balance(merchant.id)

        # Calling process_payout on a completed payout must not raise
        process_payout.run(str(payout.id))

        payout.refresh_from_db()
        # State must remain completed — the worker did not revert or re-process
        self.assertEqual(payout.state, PayoutRequest.COMPLETED)  # catches: worker re-opened a settled payout
        # No new ledger entries should exist — no accidental double-debit or phantom credit
        self.assertEqual(
            LedgerEntry.objects.filter(merchant=merchant).count(),
            ledger_count_before,
        )  # catches: duplicate worker created extra ledger rows
        # Balance must be unchanged
        self.assertEqual(
            get_merchant_balance(merchant.id),
            balance_before,
        )  # catches: worker modified money state on a settled payout

    def test_process_payout_on_failed_payout_is_noop(self):
        """
        Stripe principle P8 - Duplicate delivery on a failed payout is also safe.

        A payout in 'failed' state (which already has a refund CREDIT) must not
        receive additional refund credits or state changes from a stale worker.
        """
        merchant, payout = create_processing_payout(amount_paise=3_000, attempt_count=0)

        # Fail the payout — this creates the refund CREDIT inside transition_to (P10)
        payout.transition_to(PayoutRequest.FAILED, reason="test bank rejection")
        payout.refresh_from_db()

        ledger_count_before = LedgerEntry.objects.filter(merchant=merchant).count()
        balance_before = get_merchant_balance(merchant.id)

        # Duplicate worker delivery on a failed payout
        process_payout.run(str(payout.id))

        payout.refresh_from_db()
        self.assertEqual(payout.state, PayoutRequest.FAILED)  # catches: worker revived a failed payout
        self.assertEqual(
            LedgerEntry.objects.filter(merchant=merchant).count(),
            ledger_count_before,
        )  # catches: duplicate refund CREDIT created
        self.assertEqual(
            get_merchant_balance(merchant.id),
            balance_before,
        )  # catches: double-refund inflated balance

