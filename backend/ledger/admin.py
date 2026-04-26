"""
ledger/admin.py

Registers immutable ledger entries for local audit inspection.
"""

from django.contrib import admin

from ledger.models import LedgerEntry


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Read-only admin list for append-only money rows."""

    list_display = ("id", "merchant", "entry_type", "amount_paise", "reference_id", "created_at")
    list_filter = ("entry_type", "created_at")
    search_fields = ("merchant__email", "reference_id", "description")
    readonly_fields = ("id", "merchant", "entry_type", "amount_paise", "reference_id", "description", "created_at")

    def has_change_permission(self, request, obj=None):
        """Disable admin edits because ledger rows are append-only."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable admin deletes because ledger rows are append-only."""
        return False

# Register your models here.
