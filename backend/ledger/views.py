"""
ledger/views.py

Read-only ledger API endpoints.

Key design decisions:
  - Ledger entries are scoped to the authenticated merchant.
  - DRF pagination prevents unbounded ledger feed responses.
"""

from rest_framework.generics import ListAPIView

from ledger.models import LedgerEntry
from ledger.serializers import LedgerEntrySerializer
from merchants.auth import merchant_for_user


class LedgerEntryListView(ListAPIView):
    """Return paginated ledger entries for the authenticated merchant."""

    serializer_class = LedgerEntrySerializer

    def get_queryset(self):
        """
        Build the merchant-scoped ledger queryset.

        Returns:
            QuerySet of immutable ledger rows ordered newest first.
        """
        merchant = merchant_for_user(self.request.user)
        # Filtering by merchant prevents cross-merchant money history disclosure.
        return LedgerEntry.objects.filter(merchant=merchant).order_by("-created_at")
