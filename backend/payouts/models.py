"""
payouts/models.py

Defines payout requests and their state machine.

Key design decisions:
  - PayoutRequest state transitions are encoded at the model layer (P4).
  - Money is stored in positive integer paise, never floats or decimals (P9).
  - Failure refunds are created in the same transaction as the failed transition (P10).
"""

import uuid

from django.db import models, transaction
from django.utils import timezone


class InvalidStateTransition(RuntimeError):
    """Raised when code attempts a state transition outside the payout state machine."""


class PayoutRequest(models.Model):
    """Represents a merchant request to move held INR to a bank account."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    STATE_CHOICES = (
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    )

    LEGAL_TRANSITIONS = {
        PENDING: {PROCESSING},
        PROCESSING: {COMPLETED, FAILED},
        COMPLETED: set(),
        FAILED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID keeps payout IDs unguessable for API clients.
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="payouts")  # PROTECT preserves payout audit history if merchant data changes.
    bank_account = models.ForeignKey("merchants.BankAccount", on_delete=models.PROTECT, related_name="payouts")  # PROTECT keeps historical payout destinations inspectable.
    amount_paise = models.PositiveBigIntegerField()  # PositiveBigIntegerField stores payout money in integer paise only.
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=PENDING)  # Choices encode the finite payout lifecycle.
    idempotency_key = models.CharField(max_length=255, db_index=True)  # Indexed key links payout creation to Stripe-style replay protection.
    attempt_count = models.IntegerField(default=0)  # Integer tracks worker retries and stuck-payout promotion.
    failure_reason = models.CharField(max_length=255, null=True, blank=True)  # Nullable reason records why a bank settlement failed.
    created_at = models.DateTimeField(auto_now_add=True)  # Creation time is part of the stable API response contract.
    updated_at = models.DateTimeField(auto_now=True)  # auto_now is the heartbeat used by stuck-payout detection.

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Merchant/state index supports dashboard lists and stuck payout scans.
            models.Index(fields=["merchant", "state"], name="payout_merchant_state_idx"),
            # updated_at index lets workers find stale processing payouts efficiently.
            models.Index(fields=["state", "updated_at"], name="payout_state_updated_idx"),
        ]
        constraints = [
            # Payout requests must hold a strictly positive paise amount. (P9)
            models.CheckConstraint(condition=models.Q(amount_paise__gt=0), name="payout_amount_paise_positive"),
        ]

    def transition_to(self, new_state, reason=None):
        """
        Move this payout through its legal state machine.

        Args:
            new_state: Target state, one of pending/processing/completed/failed.
            reason: Optional audit reason, especially for failed payouts.

        Returns:
            The refreshed PayoutRequest after the state change is committed.

        Raises:
            InvalidStateTransition: The requested move is not legal from current state.
        """
        from ledger.models import LedgerEntry

        with transaction.atomic():
            # Lock the payout row so two workers cannot transition the same payout at once.
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            allowed_states = self.LEGAL_TRANSITIONS[locked.state]
            if new_state not in allowed_states:
                # Illegal transitions are hard errors so callers cannot silently skip states.
                raise InvalidStateTransition(f"Cannot transition payout {locked.id} from {locked.state} to {new_state}.")

            previous_state = locked.state
            locked.state = new_state
            locked.updated_at = timezone.now()
            if reason:
                # Reasons are stored with transitions so operators can debug without a debugger.
                locked.failure_reason = reason
            locked.save(update_fields=["state", "updated_at", "failure_reason"])

            if previous_state == self.PROCESSING and new_state == self.FAILED:
                # Refund CREDIT is in the same transaction as the failed state transition.
                # If either write fails, both roll back, so funds cannot be stranded. (P10)
                LedgerEntry.objects.create(
                    merchant=locked.merchant,
                    entry_type=LedgerEntry.CREDIT,
                    amount_paise=locked.amount_paise,
                    reference_id=str(locked.id),
                    description=f"Payout refund after failure - {reason or 'unspecified failure'}",
                )

            self.state = locked.state
            self.updated_at = locked.updated_at
            self.failure_reason = locked.failure_reason
            return locked

    def __str__(self):
        """Return a compact admin label showing amount and state."""
        return f"{self.amount_paise} paise payout ({self.state})"
