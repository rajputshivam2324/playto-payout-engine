"""
payouts/views.py

Payout request API endpoints.

Key design decisions:
  - Payout creation follows the numbered Phase 2 flow from the build prompt.
  - Idempotency stores full serialized responses for byte-perfect replays.
  - Merchant rows are locked before balance reads and ledger DEBIT creation.
"""

import json
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api_errors import error_body, error_response
from idempotency.models import IdempotencyKey
from ledger.models import LedgerEntry, get_merchant_balance
from merchants.auth import merchant_for_user
from merchants.models import BankAccount, Merchant
from payouts.models import PayoutRequest
from payouts.serializers import PayoutCreateSerializer, PayoutSerializer
from workers.tasks import process_payout


logger = logging.getLogger(__name__)


def json_ready(data):
    """
    Convert DRF serializer data into plain JSON-compatible Python objects.

    Args:
        data: Serializer data or ordinary dict.

    Returns:
        Dict/list that can be stored in JSONField and replayed.
    """
    # Rendering and loading normalizes ReturnDict, UUIDs, and datetimes exactly as the API emits them.
    return json.loads(JSONRenderer().render(data))


def request_fingerprint(validated_data):
    """
    Build the idempotency request fingerprint.

    Args:
        validated_data: Validated payout creation input.

    Returns:
        Dict containing fields that define payout intent.
    """
    # The fingerprint stores amount_paise and bank_account_id so a reused key for a different payout is rejected.
    return {
        "amount_paise": validated_data["amount_paise"],
        "bank_account_id": str(validated_data["bank_account_id"]),
    }


def rupees_from_paise(amount_paise):
    """
    Format paise as a rupee string for client-facing errors.

    Args:
        amount_paise: Integer money amount in paise (may be negative for error messages).

    Returns:
        Rupee string with two decimal places, with leading minus sign if negative.
    """
    # Use divmod on the absolute value so Python's floor-division behaviour for
    # negative numbers does not produce an incorrect sign on the fractional part.
    # e.g. -50 // 100 == -1 in Python, giving "₹-1.50" instead of "-₹0.50". (P9)
    sign = "-" if amount_paise < 0 else ""
    whole, fractional = divmod(abs(amount_paise), 100)
    return f"{sign}₹{whole:,}.{fractional:02d}"


class PayoutListCreateView(APIView):
    """Create payouts and list existing payouts for the authenticated merchant."""

    def get(self, request):
        """
        Handle GET /api/v1/payouts/.

        Args:
            request: Authenticated DRF request.

        Returns:
            Payout list ordered by newest first.
        """
        merchant = merchant_for_user(request.user)
        # Merchant filtering prevents one merchant from seeing another merchant's payout states.
        payouts = PayoutRequest.objects.filter(merchant=merchant).order_by("-created_at")
        serializer = PayoutSerializer(payouts, many=True)
        return Response(serializer.data)

    def post(self, request):
        """
        Handle POST /api/v1/payouts/.

        Args:
            request: Authenticated DRF request with amount_paise and bank_account_id.

        Returns:
            Created payout or replayed idempotency response.
        """
        # Step 1: Authenticate merchant from JWT.
        merchant = merchant_for_user(request.user)

        # Step 2: Parse and validate request body (amount_paise, bank_account_id).
        # Validation logic lives entirely in PayoutCreateSerializer; views must not re-inspect
        # raw request data to infer error codes — that duplicates and can contradict the serializer.
        serializer = PayoutCreateSerializer(data=request.data)
        if not serializer.is_valid():
            if "amount_paise" in serializer.errors:
                # The serializer raises distinct messages for non-positive and over-maximum amounts.
                # Map those messages to stable error codes without re-parsing the raw value.
                error_message = serializer.errors["amount_paise"][0]
                if "exceeds" in str(error_message):
                    code, message = "amount_exceeds_maximum", "amount_paise exceeds the maximum allowed payout."
                else:
                    code, message = "amount_must_be_positive", "amount_paise must be positive."
                return error_response(code, message, "amount_paise", status.HTTP_400_BAD_REQUEST)
            # Clients should send a valid UUID bank_account_id before retrying.
            return error_response("invalid_bank_account", "bank_account_id must be a valid UUID.", "bank_account_id", status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        # Step 3: Read Idempotency-Key header; reject with 400 if missing.
        idempotency_key_value = request.headers.get("Idempotency-Key")
        if not idempotency_key_value:
            # Missing keys are rejected so clients learn to retry payout creation safely.
            return error_response("idempotency_key_missing", "Idempotency-Key header is required.", "Idempotency-Key", status.HTTP_400_BAD_REQUEST)

        fingerprint = request_fingerprint(validated_data)

        # Step 4: Check IdempotencyKey table and handle replay/in-flight/expired/new cases.
        idempotency_key, replay_response = self._prepare_idempotency_key(merchant, idempotency_key_value, fingerprint)
        if replay_response is not None:
            return replay_response

        response_status, response_body = self._create_payout_response(merchant, validated_data, idempotency_key_value)

        # Step 8: Update IdempotencyKey: store response body + status=done.
        idempotency_key.status = IdempotencyKey.DONE
        idempotency_key.response_status = response_status
        idempotency_key.response_body = response_body
        idempotency_key.save(update_fields=["status", "response_status", "response_body"])

        # Step 9: Return 201 or the structured error response generated during payout creation.
        return Response(response_body, status=response_status)

    def _prepare_idempotency_key(self, merchant, key_value, fingerprint):
        """
        Resolve or create an idempotency key for payout creation.

        Args:
            merchant: Authenticated Merchant.
            key_value: Idempotency-Key header value.
            fingerprint: Request parameter fingerprint.

        Returns:
            Tuple of (IdempotencyKey or None, replay Response or None).
        """
        now = timezone.now()
        existing = IdempotencyKey.objects.filter(merchant=merchant, key=key_value).first()

        if existing and existing.expires_at < now:
            # Case D: Expired keys are deleted so the client may reuse a key after 24 hours.
            existing.delete()
            existing = None

        if existing and existing.status == IdempotencyKey.DONE:
            if existing.request_params != fingerprint:
                # Parameter mismatch tells clients they reused a key for a different payout intent.
                return None, error_response(
                    "idempotency_key_conflict",
                    "This idempotency key was used with different request parameters.",
                    "Idempotency-Key",
                    status.HTTP_409_CONFLICT,
                )
            # Case B: Completed keys replay the stored status/body and do not enqueue work again.
            logger.info("idempotency replay: key=%s merchant=%s", key_value, merchant.id)
            return None, Response(existing.response_body, status=existing.response_status)

        if existing and existing.status == IdempotencyKey.IN_FLIGHT:
            # Case C: In-flight keys tell clients to retry after the first request finishes.
            return None, error_response(
                "request_in_progress",
                "A request with this key is already being processed.",
                "Idempotency-Key",
                status.HTTP_409_CONFLICT,
            )

        try:
            # Case A: New keys are created in_flight with the request fingerprint for conflict detection.
            idempotency_key = IdempotencyKey.objects.create(
                merchant=merchant,
                key=key_value,
                status=IdempotencyKey.IN_FLIGHT,
                request_params=fingerprint,
                expires_at=now + timedelta(hours=24),
            )
        except IntegrityError:
            # Concurrent creators converge on the unique (merchant, key) row and ask the client to retry.
            return None, error_response(
                "request_in_progress",
                "A request with this key is already being processed.",
                "Idempotency-Key",
                status.HTTP_409_CONFLICT,
            )
        return idempotency_key, None

    def _create_payout_response(self, merchant, validated_data, idempotency_key_value):
        """
        Create a payout and ledger hold, or return a structured error body.

        Args:
            merchant: Authenticated Merchant.
            validated_data: Validated amount and bank account UUID.
            idempotency_key_value: Idempotency-Key header value.

        Returns:
            Tuple of response status code and JSON-compatible response body.
        """
        amount_paise = validated_data["amount_paise"]
        bank_account_id = validated_data["bank_account_id"]

        try:
            bank_account = BankAccount.objects.get(pk=bank_account_id, is_active=True)
        except BankAccount.DoesNotExist:
            # Invalid IDs should be fixed by the client; retrying unchanged will fail the same way.
            return status.HTTP_400_BAD_REQUEST, error_body("invalid_bank_account", "Bank account was not found.", "bank_account_id")
        if bank_account.merchant_id != merchant.id:
            # Ownership check prevents a merchant from referencing another merchant's bank account as a payout destination.
            return status.HTTP_403_FORBIDDEN, error_body("bank_account_not_owned", "Bank account does not belong to this merchant.", "bank_account_id")

        with transaction.atomic():
            # Step 5a: SELECT FOR UPDATE on merchant row.
            # This PostgreSQL row lock blocks concurrent payout creations for the same merchant until commit,
            # preventing two requests from both passing the balance check on the same stale funds. (P5)
            locked_merchant = Merchant.objects.select_for_update().get(pk=merchant.pk)

            # Step 5b: Compute available balance via DB aggregate.
            # The aggregate runs in the locked transaction so the balance reflects prior committed holds. (P3, P5)
            ledger_balance = get_merchant_balance(locked_merchant.id)

            # Step 5c: Pending/processing payouts are already represented by DEBIT ledger holds.
            # held_balance remains a dashboard metric, but subtracting it here would reserve the same funds twice. (P3)
            available_for_new_payout = ledger_balance

            # Step 5d: If amount > available, rollback by returning before writes.
            if amount_paise > available_for_new_payout:
                message = (
                    f"Available balance of {rupees_from_paise(max(available_for_new_payout, 0))} "
                    f"is less than requested {rupees_from_paise(amount_paise)}"
                )
                # The client should lower the amount or wait for funds before retrying.
                return status.HTTP_402_PAYMENT_REQUIRED, error_body("insufficient_funds", message, "amount_paise")

            # Step 5e: Create PayoutRequest in pending state.
            payout = PayoutRequest.objects.create(
                merchant=locked_merchant,
                bank_account=bank_account,
                amount_paise=amount_paise,
                idempotency_key=idempotency_key_value,
            )

            # Step 5f: Create DEBIT LedgerEntry as the hold in the same transaction as the payout.
            # If either write fails, both roll back, so there is no orphan debit or unfunded payout. (P1, P3)
            LedgerEntry.objects.create(
                merchant=locked_merchant,
                entry_type=LedgerEntry.DEBIT,
                amount_paise=amount_paise,
                reference_id=str(payout.id),
                description=f"Payout hold to ******{bank_account.account_number_last4}",
            )

            # Precompute the Step 7 response before commit so serializer bugs roll back the money hold.
            response_body = json_ready(PayoutSerializer(payout).data)

        # Step 6: Enqueue process_payout.delay(payout_id) to Celery after the DB commit.
        # Local settings run tasks eagerly; Phase 3 replaces this placeholder with settlement logic.
        process_payout.delay(str(payout.id))

        # Step 7: Serialize response for stable API output and idempotency storage.
        # The body was precomputed inside the transaction so money writes roll back if serialization fails.
        return status.HTTP_201_CREATED, response_body


class PayoutDetailView(RetrieveAPIView):
    """Return one payout belonging to the authenticated merchant."""

    serializer_class = PayoutSerializer

    def get_queryset(self):
        """
        Build the merchant-scoped payout queryset.

        Returns:
            QuerySet of payouts owned by the current merchant.
        """
        merchant = merchant_for_user(self.request.user)
        # Filtering by merchant makes another merchant's payout ID behave as not found.
        return PayoutRequest.objects.filter(merchant=merchant)

    def get(self, request, *args, **kwargs):
        """
        Handle GET /api/v1/payouts/{id}/.

        Args:
            request: Authenticated DRF request.
            *args: Positional URL args.
            **kwargs: Keyword URL args containing payout id.

        Returns:
            Single payout detail or structured 404 error.
        """
        try:
            return super().get(request, *args, **kwargs)
        except Http404:
            # Missing or cross-merchant payouts should be treated as a stable not-found response.
            return error_response("payout_not_found", "Payout was not found.", "id", status.HTTP_404_NOT_FOUND)
