"""
merchants/serializers.py

Serializers for merchant profiles and bank accounts.

Key design decisions:
  - Bank account responses never expose raw account_number.
  - Profile balance fields are integers in paise, matching backend money storage.
"""

from django.db import transaction
from rest_framework import serializers

from ledger.models import get_held_balance, get_merchant_balance
from merchants.models import BankAccount, Merchant


class BankAccountSerializer(serializers.ModelSerializer):
    """Serialize bank accounts with masked account numbers only."""

    account_number = serializers.CharField(write_only=True, required=False)
    account_number_masked = serializers.SerializerMethodField()

    class Meta:
        model = BankAccount
        fields = (
            "id",
            "account_holder",
            "account_number",
            "account_number_masked",
            "ifsc_code",
            "is_default",
            "created_at",
        )
        read_only_fields = ("id", "account_number_masked", "created_at")

    def get_account_number_masked(self, obj):
        """
        Return a masked account number for API responses.

        Args:
            obj: BankAccount being serialized.

        Returns:
            Masked string containing only the last four digits.
        """
        # Full account numbers are stored for payout execution but never sent over
        # the wire; exposing only last four digits limits accidental credential leaks.
        return f"******{obj.account_number_last4}"

    def validate_ifsc_code(self, value):
        """
        Normalize and validate IFSC length.

        Args:
            value: Incoming IFSC code.

        Returns:
            Uppercase IFSC code.
        """
        normalized = value.upper()
        if len(normalized) != 11:
            raise serializers.ValidationError("IFSC code must be 11 characters.")
        return normalized

    def validate(self, attrs):
        """
        Validate create versus patch field rules.

        Args:
            attrs: Serializer attributes after field validation.

        Returns:
            Validated attributes.
        """
        if self.instance is None and "account_number" not in attrs:
            raise serializers.ValidationError({"account_number": "This field is required."})
        if self.instance is not None:
            illegal_fields = set(attrs) - {"account_holder", "is_default"}
            if illegal_fields:
                # Existing payout destinations cannot have account or routing identity rewritten.
                raise serializers.ValidationError({field: "This field cannot be updated." for field in illegal_fields})
        return attrs

    def create(self, validated_data):
        """
        Create a bank account for the request merchant.

        Args:
            validated_data: Validated bank account fields.

        Returns:
            Created BankAccount instance.
        """
        merchant = self.context["merchant"]
        with transaction.atomic():
            if validated_data.get("is_default"):
                # Clearing the previous default inside the transaction preserves the DB singleton invariant.
                BankAccount.objects.filter(merchant=merchant, is_default=True).update(is_default=False)
            return BankAccount.objects.create(merchant=merchant, **validated_data)

    def update(self, instance, validated_data):
        """
        Update editable bank account fields.

        Args:
            instance: Existing BankAccount owned by the merchant.
            validated_data: Validated partial update fields.

        Returns:
            Updated BankAccount instance.
        """
        with transaction.atomic():
            if validated_data.get("is_default"):
                # The old default must be cleared before this row is saved to avoid violating the partial unique index.
                BankAccount.objects.filter(merchant=instance.merchant, is_default=True).exclude(pk=instance.pk).update(is_default=False)
            for field in ("account_holder", "is_default"):
                if field in validated_data:
                    setattr(instance, field, validated_data[field])
            instance.save(update_fields=["account_holder", "is_default"])
            return instance


class MerchantProfileSerializer(serializers.ModelSerializer):
    """Serialize the authenticated merchant profile and derived balances."""

    available_balance_paise = serializers.SerializerMethodField()
    held_balance_paise = serializers.SerializerMethodField()
    has_seeded_data = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = ("id", "name", "email", "created_at", "available_balance_paise", "held_balance_paise", "has_seeded_data")

    def get_available_balance_paise(self, obj):
        """
        Return balance derived from immutable ledger rows.

        Args:
            obj: Merchant being serialized.

        Returns:
            Integer available balance in paise.
        """
        # API availability is the ledger invariant: SUM(CREDIT) - SUM(DEBIT). (P3)
        return get_merchant_balance(obj.id)

    def get_held_balance_paise(self, obj):
        """
        Return funds currently tied to pending or processing payouts.

        Args:
            obj: Merchant being serialized.

        Returns:
            Integer held balance in paise.
        """
        return get_held_balance(obj.id)

    def get_has_seeded_data(self, obj):
        """
        Check if the merchant has seeded data (we use BankAccount as a heuristic).
        """
        return BankAccount.objects.filter(merchant=obj).exists()
