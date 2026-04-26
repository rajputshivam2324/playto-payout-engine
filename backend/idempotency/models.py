"""
idempotency/models.py

Defines storage for Stripe-style idempotency keys.

Key design decisions:
  - Keys are scoped to merchants with a database unique constraint (P2).
  - Full response bodies are stored for byte-perfect API replays.
  - Expiry is indexed because cleanup and stale-key handling need fast lookups.
"""

from datetime import timedelta
import uuid

from django.db import models
from django.utils import timezone


def default_expires_at():
    """Return the default 24-hour idempotency expiry timestamp."""
    return timezone.now() + timedelta(hours=24)


class IdempotencyKey(models.Model):
    """Stores one merchant-scoped mutation key and its replay response."""

    IN_FLIGHT = "in_flight"
    DONE = "done"

    STATUS_CHOICES = (
        (IN_FLIGHT, "In flight"),
        (DONE, "Done"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID avoids sequential internal key-row IDs.
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.CASCADE, related_name="idempotency_keys")  # FK scopes keys so merchants can reuse the same client UUID independently.
    key = models.CharField(max_length=255)  # CharField stores caller-provided idempotency keys exactly as sent.
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=IN_FLIGHT)  # Choices model in-flight versus replayable completed requests.
    request_params = models.JSONField()  # JSON stores the original request fingerprint for conflict detection.
    response_status = models.IntegerField(null=True, blank=True)  # Nullable until the first request finishes and status becomes done.
    response_body = models.JSONField(null=True, blank=True)  # JSON preserves the response body for byte-perfect replays.
    created_at = models.DateTimeField(auto_now_add=True)  # Creation time supports audit and expiry reasoning.
    expires_at = models.DateTimeField(default=default_expires_at)  # Default expiry limits replay storage to the Stripe-style 24-hour window.

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Merchant/key uniqueness makes concurrent duplicate mutation requests converge.
            models.UniqueConstraint(fields=["merchant", "key"], name="unique_idempotency_key_per_merchant"),
        ]
        indexes = [
            # Expiry index makes hourly cleanup cheap even as completed keys accumulate.
            models.Index(fields=["expires_at"], name="idempotency_expires_idx"),
        ]

    def __str__(self):
        """Return the merchant-scoped key and status for admin screens."""
        return f"{self.merchant_id}:{self.key} ({self.status})"
