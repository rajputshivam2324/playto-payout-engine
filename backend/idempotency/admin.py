"""
idempotency/admin.py

Registers idempotency keys for replay debugging.
"""

from django.contrib import admin

from idempotency.models import IdempotencyKey


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    """Admin list for merchant-scoped idempotency records."""

    list_display = ("id", "merchant", "key", "status", "response_status", "created_at", "expires_at")
    list_filter = ("status", "expires_at")
    search_fields = ("merchant__email", "key")
    readonly_fields = ("id", "created_at")

# Register your models here.
