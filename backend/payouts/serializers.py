"""
payouts/serializers.py

Serializers for payout creation and payout responses.

Key design decisions:
  - Creation input is deliberately narrow: amount_paise and bank_account_id only.
  - Response output is stable and exposes integer paise amounts.
"""

from rest_framework import serializers

from payouts.models import PayoutRequest


class PayoutCreateSerializer(serializers.Serializer):
    """Validate payout creation input."""

    amount_paise = serializers.IntegerField()
    bank_account_id = serializers.UUIDField()

    def validate_amount_paise(self, value):
        """
        Validate payout amount boundaries.

        Args:
            value: Requested payout amount in paise.

        Returns:
            Validated integer amount in paise.
        """
        if value <= 0:
            raise serializers.ValidationError("amount_paise must be positive.")
        if value > 10_000_000:
            raise serializers.ValidationError("amount_paise exceeds the maximum allowed payout.")
        return value


class PayoutSerializer(serializers.ModelSerializer):
    """Serialize payout request state for API clients."""

    bank_account_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = PayoutRequest
        fields = (
            "id",
            "amount_paise",
            "state",
            "bank_account_id",
            "attempt_count",
            "failure_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
