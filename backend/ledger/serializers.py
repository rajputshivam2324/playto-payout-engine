"""
ledger/serializers.py

Serializes immutable ledger entries.

Key design decisions:
  - Ledger rows are read-only API resources.
  - Amounts remain integer paise all the way to the client.
  - payout_state is derived at read time so immutable descriptions are enriched
    with the current payout lifecycle state.
"""

from rest_framework import serializers

from ledger.models import LedgerEntry
from payouts.models import PayoutRequest


class LedgerEntrySerializer(serializers.ModelSerializer):
    """Serialize one immutable ledger entry."""

    payout_state = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = ("id", "entry_type", "amount_paise", "reference_id", "description", "payout_state", "created_at")
        read_only_fields = fields

    def get_payout_state(self, obj):
        """
        Resolve the current payout state for DEBIT hold entries.

        Args:
            obj: LedgerEntry instance.

        Returns:
            Payout state string ('pending', 'processing', 'completed', 'failed')
            or None for non-payout entries like seed credits.
        """
        if obj.entry_type != LedgerEntry.DEBIT:
            return None
        try:
            payout = PayoutRequest.objects.only("state").get(pk=obj.reference_id)
            return payout.state
        except (PayoutRequest.DoesNotExist, ValueError):
            # reference_id may not be a valid payout UUID (e.g. seed data).
            return None
