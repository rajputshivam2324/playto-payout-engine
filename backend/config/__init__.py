"""
config/__init__.py

Marks the Django project configuration package as importable.
"""

# Importing the Celery app here follows Celery's Django integration pattern so
# shared_task decorators bind to this project app when Django starts.
from .celery import app as celery_app

__all__ = ("celery_app",)
