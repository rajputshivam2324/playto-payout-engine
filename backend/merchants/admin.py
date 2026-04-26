"""
merchants/admin.py

Registers merchant-owned objects for local audit inspection.
"""

from django.contrib import admin

from merchants.models import BankAccount, Merchant


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    """Admin list view for merchants."""

    list_display = ("id", "name", "email", "created_at")
    search_fields = ("name", "email")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    """Admin list view that never displays full account numbers."""

    list_display = ("id", "merchant", "account_holder", "masked_account_number", "ifsc_code", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("account_holder", "ifsc_code", "merchant__email")

    def masked_account_number(self, obj):
        """Return a masked bank account number for admin list safety."""
        # Even in admin lists, only the last four digits should be casually visible.
        return f"******{obj.account_number_last4}"

# Register your models here.
