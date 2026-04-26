"""
payouts/admin.py

Registers payout requests for local state inspection.
"""

from django.contrib import admin

from payouts.models import PayoutRequest


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    """Admin list for payout lifecycle records."""

    list_display = ("id", "merchant", "amount_paise", "state", "attempt_count", "created_at", "updated_at")
    list_filter = ("state", "created_at", "updated_at")
    search_fields = ("merchant__email", "idempotency_key", "failure_reason")
    readonly_fields = ("id", "created_at", "updated_at")

# Register your models here.
