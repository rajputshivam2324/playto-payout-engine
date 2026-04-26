"""
workers/apps.py

Declares the workers Django application.
"""

from django.apps import AppConfig


class WorkersConfig(AppConfig):
    """Application configuration for background worker code."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "workers"
