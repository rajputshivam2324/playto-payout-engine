"""
ledger/models.py

Defines immutable ledger entries for merchant balances.

Key design decisions:
  - LedgerEntry is append-only and has no updated_at field (P3).
  - Money is stored as positive paise in a 64-bit integer field (P9).
  - Balance is derived by aggregating CREDIT and DEBIT rows, never by mutating a balance.
"""

import uuid

from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone


class ImmutableLedgerEntryError(RuntimeError):
    """Raised when code tries to mutate or delete a ledger entry."""


class ImmutableQuerySet(models.QuerySet):
    """
    QuerySet that rejects bulk deletes and updates on ledger entries.

    Django's admin "delete selected" action calls QuerySet.delete(), which bypasses
    the instance-level delete() override. This QuerySet closes that gap so no code
    path — ORM, admin, or shell — can remove or overwrite ledger history.
    """

    def delete(self):
        # Bulk delete would silently remove money history without calling instance .delete().
        raise ImmutableLedgerEntryError("Ledger entries are append-only and cannot be deleted.")

    def update(self, **kwargs):
        # Bulk update would rewrite money rows without the instance .save() guard.
        raise ImmutableLedgerEntryError("Ledger entries are append-only and cannot be updated.")


class ImmutableLedgerManager(models.Manager):
    """Custom manager that returns an ImmutableQuerySet for all LedgerEntry queries."""

    def get_queryset(self):
        return ImmutableQuerySet(self.model, using=self._db)


class LedgerEntry(models.Model):
    """Append-only money movement row used as the source of truth."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"

    ENTRY_TYPE_CHOICES = (
        (CREDIT, "Credit"),
        (DEBIT, "Debit"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID avoids sequential money-row identifiers.
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="ledger_entries")  # PROTECT prevents deleting merchants with money history.
    entry_type = models.CharField(max_length=6, choices=ENTRY_TYPE_CHOICES)  # Choices make CREDIT/DEBIT the only valid ledger directions.
    amount_paise = models.PositiveBigIntegerField()  # PositiveBigIntegerField stores paise as an integer and rejects negative money.
    reference_id = models.CharField(max_length=64)  # CharField supports payout UUIDs and seed references without foreign-key coupling.
    description = models.CharField(max_length=255)  # Bounded text records why this immutable money movement exists.
    created_at = models.DateTimeField(default=timezone.now, editable=False)  # Default timestamp is set once and can be seeded without later updates.

    # ImmutableLedgerManager replaces the default manager so QuerySet.delete() and
    # QuerySet.update() raise ImmutableLedgerEntryError, closing the Django admin
    # bulk-action bypass that the instance-level .delete() override cannot cover.
    objects = ImmutableLedgerManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Merchant/time index keeps ledger feeds and balance audits efficient.
            models.Index(fields=["merchant", "-created_at"], name="ledger_merchant_created_idx"),
            # Reference index lets payout-related DEBIT/CREDIT rows be found quickly.
            models.Index(fields=["reference_id"], name="ledger_reference_idx"),
        ]
        constraints = [
            # Money movements must be strictly positive; direction is represented by entry_type.
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="ledger_amount_paise_positive"),
        ]

    def save(self, *args, **kwargs):
        """Create a ledger entry and reject updates to preserve append-only history."""
        if not self._state.adding and self.pk:
            # Updating money rows would rewrite history and break derived-balance audits.
            raise ImmutableLedgerEntryError("Ledger entries are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Reject deletes so money history is never removed."""
        # Deleting a ledger row would make historical balances impossible to reconstruct.
        raise ImmutableLedgerEntryError("Ledger entries are append-only and cannot be deleted.")

    def __str__(self):
        """Return a compact admin label with direction and amount."""
        return f"{self.entry_type} {self.amount_paise} paise"


def get_merchant_balance(merchant_id):
    """
    Derive a merchant balance from immutable ledger rows.

    Args:
        merchant_id: UUID identifying the merchant whose ledger should be aggregated.

    Returns:
        Integer balance in paise, computed as credits minus debits.
    """
    # DB-level aggregate avoids Python summing over stale fetched rows. (P3)
    result = LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        credits=Sum("amount_paise", filter=Q(entry_type=LedgerEntry.CREDIT)),
        debits=Sum("amount_paise", filter=Q(entry_type=LedgerEntry.DEBIT)),
    )
    # None means no rows for that direction, which is safely treated as zero paise.
    return (result["credits"] or 0) - (result["debits"] or 0)


def get_held_balance(merchant_id):
    """
    Derive the amount currently held by pending or processing payouts.

    Args:
        merchant_id: UUID identifying the merchant whose held payouts should be summed.

    Returns:
        Integer held balance in paise.
    """
    from payouts.models import PayoutRequest

    # Held funds are computed with one DB aggregate, not by iterating payout rows in Python.
    result = PayoutRequest.objects.filter(
        merchant_id=merchant_id,
        state__in=[PayoutRequest.PENDING, PayoutRequest.PROCESSING],
    ).aggregate(held=Sum("amount_paise"))
    return result["held"] or 0
