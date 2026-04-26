"""
config/urls.py

Routes admin and authentication endpoints for the Playto backend.

Key design decisions:
  - JWT token endpoints use Simple JWT's documented TokenObtainPairView/TokenRefreshView.
  - Business API endpoints are versioned under /api/v1/ for a stable client contract.
"""

from django.contrib import admin
from django.urls import path
from ledger.views import LedgerEntryListView
from merchants.views import BankAccountDetailView, BankAccountListCreateView, MerchantMeView, SignupView, MerchantSeedView
from payouts.views import PayoutDetailView, PayoutListCreateView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # Admin is enabled in Phase 1 so seeded money objects can be inspected locally.
    path("admin/", admin.site.urls),
    # Login returns {"refresh": "...", "access": "..."} using Simple JWT's stable views.
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    # Refresh exchanges a refresh token for a new access token without reusing passwords.
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Signup endpoint creates a user and merchant.
    path("api/v1/auth/signup/", SignupView.as_view(), name="auth_signup"),
    # Merchant profile exposes derived balances and identity for the dashboard.
    path("api/v1/merchants/me/", MerchantMeView.as_view(), name="merchant_me"),
    # Seed endpoint populates the merchant account with mock data for testing.
    path("api/v1/merchants/me/seed/", MerchantSeedView.as_view(), name="merchant_seed"),
    # Bank account list/create feeds the payout form destination dropdown.
    path("api/v1/bank-accounts/", BankAccountListCreateView.as_view(), name="bank_account_list_create"),
    # Bank account patch/delete is scoped by ownership inside the view.
    path("api/v1/bank-accounts/<uuid:account_id>/", BankAccountDetailView.as_view(), name="bank_account_detail"),
    # Payout list/create is the critical money-mutation API.
    path("api/v1/payouts/", PayoutListCreateView.as_view(), name="payout_list_create"),
    # Payout detail supports frontend polling for state changes.
    path("api/v1/payouts/<uuid:pk>/", PayoutDetailView.as_view(), name="payout_detail"),
    # Ledger feed is read-only and paginated by DRF settings.
    path("api/v1/ledger/", LedgerEntryListView.as_view(), name="ledger_list"),
]
