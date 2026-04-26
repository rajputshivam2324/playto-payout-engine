"""
merchants/models.py

Defines the Merchant and BankAccount models.

Key design decisions:
  - Merchant has no balance column; balance is derived from immutable ledger rows (P3).
  - BankAccount stores the full account number but serializers must only expose masking.
  - One default bank account per merchant is enforced by a partial unique constraint.
"""

import uuid

from django.db import models
from django.db.models import Q


class Merchant(models.Model):
    """Represents a Playto merchant that can receive INR payouts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID prevents guessable merchant identifiers in URLs and logs.
    name = models.CharField(max_length=255)  # CharField keeps merchant display names indexed and bounded.
    email = models.EmailField(unique=True)  # EmailField validates merchant login identity and is unique for JWT lookup.
    created_at = models.DateTimeField(auto_now_add=True)  # auto_now_add records when the merchant entered the payout system.

    class Meta:
        ordering = ["name"]

    def __str__(self):
        """Return the merchant's human-readable name for admin screens."""
        return f"{self.name} <{self.email}>"


class BankAccount(models.Model):
    """Stores a merchant-owned INR destination bank account."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID avoids exposing sequential bank account IDs.
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="bank_accounts")  # FK scopes every bank account to exactly one merchant.
    account_number = models.CharField(max_length=32)  # CharField preserves leading zeroes and avoids numeric overflow for account numbers.
    ifsc_code = models.CharField(max_length=11)  # IFSC is an 11-character routing code, so a bounded CharField matches the domain.
    account_holder = models.CharField(max_length=255)  # CharField stores the beneficiary name shown in masked payout choices.
    is_default = models.BooleanField(default=False)  # Boolean marks the merchant's preferred payout destination.
    is_active = models.BooleanField(default=True)  # Soft-delete flag keeps historical payout references intact.
    created_at = models.DateTimeField(auto_now_add=True)  # Timestamp supports stable API ordering and audit inspection.

    class Meta:
        ordering = ["-is_default", "created_at"]
        constraints = [
            # Partial unique constraint: at most one default destination per merchant.
            models.UniqueConstraint(
                fields=["merchant"],
                condition=Q(is_default=True),
                name="unique_default_bank_account_per_merchant",
            )
        ]

    @property
    def account_number_last4(self):
        """Return the last four digits used for masked account display."""
        return self.account_number[-4:]

    def __str__(self):
        """Return a masked destination label for admin screens."""
        return f"{self.account_holder} - ******{self.account_number_last4}"
