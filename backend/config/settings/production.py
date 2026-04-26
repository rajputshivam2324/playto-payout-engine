"""
config/settings/production.py

Production settings for the Playto payout engine.

Key design decisions:
  - PostgreSQL is required in production because payout correctness depends on row locks.
  - Database credentials are read from environment variables to match Railway-style deploys.
"""

import os

from .base import *  # noqa: F403,F401


DEBUG = False

DATABASES = {
    "default": {
        # PostgreSQL is the production database because SELECT FOR UPDATE semantics matter.
        "ENGINE": "django.db.backends.postgresql",
        # Each setting is environment-backed so secrets never land in source control.
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
