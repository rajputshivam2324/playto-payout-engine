"""
merchants/apps.py

Declares the merchants Django application.
"""

from django.apps import AppConfig


class MerchantsConfig(AppConfig):
    """Application configuration for merchant models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "merchants"
