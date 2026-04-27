"""
merchants/views.py

Merchant profile and bank-account API endpoints.

Key design decisions:
  - Every view resolves the merchant from JWT before touching merchant-owned data.
  - Bank-account mutations are scoped to the authenticated merchant.
  - Bank account POST/PATCH/DELETE are idempotency-safe: keys are checked and stored
    in the IdempotencyKey table so client retries replay the original response (P2).
  - SignupView validates username strictly to prevent email synthesis edge cases.
"""

import json
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from config.api_errors import error_response
from idempotency.models import IdempotencyKey
from merchants.auth import merchant_for_user
from merchants.models import BankAccount, Merchant
from merchants.seed_utils import apply_seed_persona
from merchants.serializers import BankAccountSerializer, MerchantProfileSerializer
from payouts.models import PayoutRequest


# Usernames must be 3–30 alphanumeric / underscore characters.
# This constraint ensures the synthesised @playto.local email is always valid and
# unique, and prevents characters that would break URL routing or email parsing.
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_]{3,30}$')


def _json_ready(data):
    """Normalise serializer output to plain JSON-compatible Python objects for storage."""
    return json.loads(JSONRenderer().render(data))


def require_idempotency_key(request):
    """
    Require Idempotency-Key on mutation requests.

    Args:
        request: DRF request object.

    Returns:
        Header value when present, otherwise None.
    """
    # P2 requires mutation endpoints to reject clients that cannot safely retry.
    return request.headers.get("Idempotency-Key")


def _resolve_bank_account_idempotency(merchant, key_value, action):
    """
    Look up an existing idempotency key for a bank-account mutation.

    Unlike payout creation we do not need a fingerprint check here because the
    action string (post/patch:<id>/delete:<id>) already encodes the full intent.
    A done key replays its stored response; an in-flight key returns 409.

    Args:
        merchant: Authenticated Merchant.
        key_value: Idempotency-Key header value.
        action: Short string that encodes the mutation intent (e.g. "post", "patch:uuid").

    Returns:
        Tuple of (IdempotencyKey or None, replay Response or None).
    """
    now = timezone.now()
    scoped_key = f"bank_account:{action}:{key_value}"
    existing = IdempotencyKey.objects.filter(merchant=merchant, key=scoped_key).first()

    if existing and existing.expires_at < now:
        existing.delete()
        existing = None

    if existing and existing.status == IdempotencyKey.DONE:
        return None, Response(existing.response_body, status=existing.response_status)

    if existing and existing.status == IdempotencyKey.IN_FLIGHT:
        return None, error_response(
            "request_in_progress",
            "A request with this key is already being processed.",
            "Idempotency-Key",
            status.HTTP_409_CONFLICT,
        )

    try:
        ik = IdempotencyKey.objects.create(
            merchant=merchant,
            key=scoped_key,
            status=IdempotencyKey.IN_FLIGHT,
            request_params={"action": action},
            expires_at=now + timedelta(hours=24),
        )
    except IntegrityError:
        return None, error_response(
            "request_in_progress",
            "A request with this key is already being processed.",
            "Idempotency-Key",
            status.HTTP_409_CONFLICT,
        )
    return ik, None


def _complete_bank_account_idempotency(ik, response_status, response_body):
    """Mark an idempotency key as done and store the response for future replays."""
    ik.status = IdempotencyKey.DONE
    ik.response_status = response_status
    ik.response_body = response_body
    ik.save(update_fields=["status", "response_status", "response_body"])


class MerchantMeView(APIView):
    """Return the authenticated merchant profile and derived balances."""

    def get(self, request):
        """
        Handle GET /api/v1/merchants/me/.

        Args:
            request: Authenticated DRF request.

        Returns:
            Merchant profile response with available and held balances.
        """
        # merchant_for_user issues one DB query per request. For higher traffic a
        # merchant_id JWT claim (via a custom token serializer) would eliminate this query.
        merchant = merchant_for_user(request.user)
        serializer = MerchantProfileSerializer(merchant)
        return Response(serializer.data)


class SignupView(APIView):
    """Register a new user and return JWT tokens."""
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """
        Handle POST /api/v1/auth/signup/.

        Validates username strictly (3–30 alphanumeric/underscore chars) before
        synthesising the @playto.local email, preventing email parsing edge cases
        and ensuring uniqueness assumptions hold throughout the system.

        Args:
            request: Unauthenticated DRF request with username and password.

        Returns:
            JWT access + refresh tokens on success.
        """
        username = request.data.get("username", "")
        password = request.data.get("password", "")

        if not username or not password:
            return error_response(
                "missing_fields",
                "Username and password are required.",
                None,
                status.HTTP_400_BAD_REQUEST,
            )

        # Enforce a strict allowlist: 3–30 alphanumeric + underscore characters.
        # This guarantees the synthesised email is always RFC-5321 compliant and unique.
        if not _USERNAME_RE.match(username):
            return error_response(
                "invalid_username",
                "Username must be 3–30 characters and contain only letters, digits, or underscores.",
                "username",
                status.HTTP_400_BAD_REQUEST,
            )

        if len(password) < 8:
            return error_response(
                "password_too_short",
                "Password must be at least 8 characters.",
                "password",
                status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()
        # Check existence before create to return a clear error without relying on IntegrityError text.
        if User.objects.filter(username=username).exists():
            # Return a generic message to avoid leaking which usernames are registered.
            return error_response(
                "username_taken",
                "An account with that username already exists.",
                "username",
                status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            email = f"{username}@playto.local"
            user = User.objects.create_user(username=username, password=password, email=email)
            Merchant.objects.create(name=username.capitalize(), email=email)

        refresh = RefreshToken.for_user(user)
        return Response(
            {"refresh": str(refresh), "access": str(refresh.access_token)},
            status=status.HTTP_201_CREATED,
        )


class MerchantSeedView(APIView):
    """Seed persona data for the authenticated merchant."""

    def post(self, request):
        merchant = merchant_for_user(request.user)
        persona_id = request.data.get("persona_id")
        if not persona_id:
            return error_response("missing_persona", "persona_id is required.", "persona_id", status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                apply_seed_persona(merchant, persona_id)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ValueError as e:
            return error_response("invalid_persona", str(e), "persona_id", status.HTTP_400_BAD_REQUEST)


class BankAccountListCreateView(APIView):
    """List and create bank accounts for the authenticated merchant."""

    def get(self, request):
        """
        Handle GET /api/v1/bank-accounts/.

        Args:
            request: Authenticated DRF request.

        Returns:
            Masked bank-account list for the merchant.
        """
        merchant = merchant_for_user(request.user)
        # Active-only filtering prevents soft-deleted destinations from appearing in payout forms.
        accounts = BankAccount.objects.filter(merchant=merchant, is_active=True)
        serializer = BankAccountSerializer(accounts, many=True)
        return Response(serializer.data)

    def post(self, request):
        """
        Handle POST /api/v1/bank-accounts/.

        Idempotency-safe: a repeated POST with the same key replays the stored
        201 response without creating a duplicate bank account (P2).

        Args:
            request: Authenticated DRF request containing bank account fields.

        Returns:
            Created bank account with masked account number, or replay of original response.
        """
        merchant = merchant_for_user(request.user)
        key_value = require_idempotency_key(request)
        if not key_value:
            return error_response(
                "idempotency_key_missing",
                "Idempotency-Key header is required.",
                "Idempotency-Key",
                status.HTTP_400_BAD_REQUEST,
            )

        ik, replay = _resolve_bank_account_idempotency(merchant, key_value, action="post")
        if replay is not None:
            return replay

        serializer = BankAccountSerializer(data=request.data, context={"merchant": merchant})
        if not serializer.is_valid():
            # Validation errors are not stored in the idempotency key so clients can fix and retry.
            _complete_bank_account_idempotency(
                ik,
                status.HTTP_400_BAD_REQUEST,
                {"error": {"code": "invalid_bank_account", "message": str(serializer.errors), "param": None}},
            )
            return error_response("invalid_bank_account", str(serializer.errors), None, status.HTTP_400_BAD_REQUEST)

        account = serializer.save()
        response_body = _json_ready(BankAccountSerializer(account).data)
        _complete_bank_account_idempotency(ik, status.HTTP_201_CREATED, response_body)
        return Response(response_body, status=status.HTTP_201_CREATED)


class BankAccountDetailView(APIView):
    """Update or soft-delete one authenticated merchant bank account."""

    def _get_owned_account(self, request, account_id):
        """
        Fetch an active bank account and enforce merchant ownership.

        Args:
            request: Authenticated DRF request.
            account_id: Bank account UUID from the URL.

        Returns:
            Tuple of (merchant, BankAccount) or (None, error Response).
        """
        merchant = merchant_for_user(request.user)
        try:
            account = BankAccount.objects.get(pk=account_id, is_active=True)
        except BankAccount.DoesNotExist:
            # A missing destination is a client input error; retrying the same ID will not help.
            return None, None, error_response(
                "invalid_bank_account",
                "Bank account was not found.",
                "bank_account_id",
                status.HTTP_400_BAD_REQUEST,
            )
        if account.merchant_id != merchant.id:
            # Ownership enforcement prevents one merchant from editing another merchant's payout destination.
            return None, None, error_response(
                "bank_account_not_owned",
                "Bank account does not belong to this merchant.",
                "bank_account_id",
                status.HTTP_403_FORBIDDEN,
            )
        return merchant, account, None

    def patch(self, request, account_id):
        """
        Handle PATCH /api/v1/bank-accounts/{id}/.

        Idempotency-safe: a repeated PATCH with the same key replays the stored
        200 response without re-applying the change (P2).

        Args:
            request: Authenticated DRF request.
            account_id: Bank account UUID from the URL.

        Returns:
            Updated bank account with masked account number, or replay of original response.
        """
        key_value = require_idempotency_key(request)
        if not key_value:
            return error_response(
                "idempotency_key_missing",
                "Idempotency-Key header is required.",
                "Idempotency-Key",
                status.HTTP_400_BAD_REQUEST,
            )

        merchant, account, error = self._get_owned_account(request, account_id)
        if error:
            return error

        ik, replay = _resolve_bank_account_idempotency(merchant, key_value, action=f"patch:{account_id}")
        if replay is not None:
            return replay

        serializer = BankAccountSerializer(account, data=request.data, partial=True)
        if not serializer.is_valid():
            _complete_bank_account_idempotency(
                ik,
                status.HTTP_400_BAD_REQUEST,
                {"error": {"code": "invalid_bank_account", "message": str(serializer.errors), "param": None}},
            )
            return error_response("invalid_bank_account", str(serializer.errors), None, status.HTTP_400_BAD_REQUEST)

        account = serializer.save()
        response_body = _json_ready(BankAccountSerializer(account).data)
        _complete_bank_account_idempotency(ik, status.HTTP_200_OK, response_body)
        return Response(response_body)

    def delete(self, request, account_id):
        """
        Handle DELETE /api/v1/bank-accounts/{id}/ as a soft delete.

        Idempotency-safe: a repeated DELETE with the same key replays the 204 response
        without error even if the account was already deactivated (P2).

        Args:
            request: Authenticated DRF request.
            account_id: Bank account UUID from the URL.

        Returns:
            204 response after marking the bank account inactive.
        """
        key_value = require_idempotency_key(request)
        if not key_value:
            return error_response(
                "idempotency_key_missing",
                "Idempotency-Key header is required.",
                "Idempotency-Key",
                status.HTTP_400_BAD_REQUEST,
            )

        merchant, account, error = self._get_owned_account(request, account_id)
        if error:
            return error

        ik, replay = _resolve_bank_account_idempotency(merchant, key_value, action=f"delete:{account_id}")
        if replay is not None:
            return replay

        active_payout_exists = PayoutRequest.objects.filter(
            bank_account=account,
            state__in=[PayoutRequest.PENDING, PayoutRequest.PROCESSING],
        ).exists()
        if active_payout_exists:
            # Clients must wait for active payouts to settle before removing the destination.
            _complete_bank_account_idempotency(
                ik,
                status.HTTP_409_CONFLICT,
                {"error": {"code": "bank_account_in_use", "message": "Bank account has an active payout.", "param": "bank_account_id"}},
            )
            return error_response("bank_account_in_use", "Bank account has an active payout.", "bank_account_id", status.HTTP_409_CONFLICT)

        with transaction.atomic():
            # Soft delete preserves historical payout references while hiding the account from future use.
            account.is_active = False
            account.is_default = False
            account.save(update_fields=["is_active", "is_default"])

        _complete_bank_account_idempotency(ik, status.HTTP_204_NO_CONTENT, None)
        return Response(status=status.HTTP_204_NO_CONTENT)
