"""
config/settings/local.py

Local development settings.

Key design decisions:
  - PostgreSQL is required even locally because SELECT FOR UPDATE (P5) is the core
    correctness primitive. SQLite silently ignores select_for_update(), making all
    locking non-functional and allowing double-spend race conditions.
  - Redis is the local Celery broker so beat and worker processes communicate across
    processes exactly as they will in production.
  - Celery tasks are queued by default so API requests do not run random settlement inline.
"""

import os

from .base import *  # noqa: F403,F401


DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# PostgreSQL is required because payout correctness depends on row-level locking.
# SELECT FOR UPDATE is silently ignored on SQLite, which would allow two concurrent
# payout requests to both pass the balance check and create a double-spend. (P5)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "playto"),
        "USER": os.environ.get("POSTGRES_USER", "playto"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "playto"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# Redis is the local Celery broker so stuck-payout beat tasks and process_payout workers
# communicate across separate processes, matching production behaviour.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# Keep payout settlement out of the request path; tests can opt into eager mode explicitly.
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False").lower() == "true"
