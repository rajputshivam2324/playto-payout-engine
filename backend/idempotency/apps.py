"""
idempotency/apps.py

Declares the idempotency Django application.
"""

from django.apps import AppConfig


class IdempotencyConfig(AppConfig):
    """Application configuration for idempotency key models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "idempotency"
