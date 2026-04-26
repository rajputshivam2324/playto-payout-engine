"""
ledger/apps.py

Declares the ledger Django application.
"""

from django.apps import AppConfig


class LedgerConfig(AppConfig):
    """Application configuration for immutable ledger models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "ledger"
