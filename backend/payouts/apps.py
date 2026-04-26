"""
payouts/apps.py

Declares the payouts Django application.
"""

from django.apps import AppConfig


class PayoutsConfig(AppConfig):
    """Application configuration for payout state-machine models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "payouts"
