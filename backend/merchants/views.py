"""
merchants/views.py

Merchant profile and bank-account API endpoints.

Key design decisions:
  - Every view resolves the merchant from JWT before touching merchant-owned data.
  - Bank-account mutations are scoped to the authenticated merchant.
"""

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api_errors import error_response
from merchants.auth import merchant_for_user
from merchants.models import BankAccount, Merchant
from merchants.serializers import BankAccountSerializer, MerchantProfileSerializer
from payouts.models import PayoutRequest
from merchants.seed_utils import apply_seed_persona
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken


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
        merchant = merchant_for_user(request.user)
        serializer = MerchantProfileSerializer(merchant)
        return Response(serializer.data)


class SignupView(APIView):
    """Register a new user and return JWT tokens."""
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return error_response("missing_fields", "Username and password are required.", None, status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            return error_response("username_taken", "Username is already taken.", "username", status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            email = f"{username}@playto.local"
            user = User.objects.create_user(username=username, password=password, email=email)
            merchant = Merchant.objects.create(name=username.capitalize(), email=email)

        refresh = RefreshToken.for_user(user)
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }, status=status.HTTP_201_CREATED)


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

        Args:
            request: Authenticated DRF request containing bank account fields.

        Returns:
            Created bank account with masked account number.
        """
        merchant = merchant_for_user(request.user)
        if not require_idempotency_key(request):
            # Missing keys are rejected so clients learn to make mutation retries safe.
            return error_response("idempotency_key_missing", "Idempotency-Key header is required.", "Idempotency-Key", status.HTTP_400_BAD_REQUEST)

        serializer = BankAccountSerializer(data=request.data, context={"merchant": merchant})
        if not serializer.is_valid():
            # Serializer errors are collapsed to the stable API error envelope.
            return error_response("invalid_bank_account", str(serializer.errors), None, status.HTTP_400_BAD_REQUEST)
        account = serializer.save()
        return Response(BankAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class BankAccountDetailView(APIView):
    """Update or soft-delete one authenticated merchant bank account."""

    def _get_owned_account(self, request, account_id):
        """
        Fetch an active bank account and enforce merchant ownership.

        Args:
            request: Authenticated DRF request.
            account_id: Bank account UUID from the URL.

        Returns:
            BankAccount owned by the current merchant, or an error Response.
        """
        merchant = merchant_for_user(request.user)
        try:
            account = BankAccount.objects.get(pk=account_id, is_active=True)
        except BankAccount.DoesNotExist:
            # A missing destination is a client input error; retrying the same ID will not help.
            return None, error_response("invalid_bank_account", "Bank account was not found.", "bank_account_id", status.HTTP_400_BAD_REQUEST)
        if account.merchant_id != merchant.id:
            # Ownership enforcement prevents one merchant from editing another merchant's payout destination.
            return None, error_response("bank_account_not_owned", "Bank account does not belong to this merchant.", "bank_account_id", status.HTTP_403_FORBIDDEN)
        return account, None

    def patch(self, request, account_id):
        """
        Handle PATCH /api/v1/bank-accounts/{id}/.

        Args:
            request: Authenticated DRF request.
            account_id: Bank account UUID from the URL.

        Returns:
            Updated bank account with masked account number.
        """
        if not require_idempotency_key(request):
            # Missing keys are rejected so PATCH retries cannot accidentally double-apply intent.
            return error_response("idempotency_key_missing", "Idempotency-Key header is required.", "Idempotency-Key", status.HTTP_400_BAD_REQUEST)
        account, error = self._get_owned_account(request, account_id)
        if error:
            return error

        serializer = BankAccountSerializer(account, data=request.data, partial=True)
        if not serializer.is_valid():
            # Invalid bank account edits should be corrected by the client before retrying.
            return error_response("invalid_bank_account", str(serializer.errors), None, status.HTTP_400_BAD_REQUEST)
        account = serializer.save()
        return Response(BankAccountSerializer(account).data)

    def delete(self, request, account_id):
        """
        Handle DELETE /api/v1/bank-accounts/{id}/ as a soft delete.

        Args:
            request: Authenticated DRF request.
            account_id: Bank account UUID from the URL.

        Returns:
            204 response after marking the bank account inactive.
        """
        if not require_idempotency_key(request):
            # Missing keys are rejected so delete retries have an explicit retry key.
            return error_response("idempotency_key_missing", "Idempotency-Key header is required.", "Idempotency-Key", status.HTTP_400_BAD_REQUEST)
        account, error = self._get_owned_account(request, account_id)
        if error:
            return error

        active_payout_exists = PayoutRequest.objects.filter(
            bank_account=account,
            state__in=[PayoutRequest.PENDING, PayoutRequest.PROCESSING],
        ).exists()
        if active_payout_exists:
            # Clients must wait for active payouts to settle before removing the destination.
            return error_response("bank_account_in_use", "Bank account has an active payout.", "bank_account_id", status.HTTP_409_CONFLICT)

        with transaction.atomic():
            # Soft delete preserves historical payout references while hiding the account from future use.
            account.is_active = False
            account.is_default = False
            account.save(update_fields=["is_active", "is_default"])
        return Response(status=status.HTTP_204_NO_CONTENT)
