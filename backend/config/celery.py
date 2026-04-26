"""
config/celery.py

Defines the Celery application used by Playto workers.

Key design decisions:
  - Configuration is loaded from Django settings with the CELERY_ namespace.
  - Tasks are autodiscovered from installed apps so workers/tasks.py is picked up.
"""

import os

from celery import Celery


# Set the default settings module before constructing the Celery app.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# The app name is stable because Railway worker commands will reference it later.
app = Celery("playto")

# namespace="CELERY" means settings like CELERY_BROKER_URL map to Celery broker_url.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscovery loads tasks.py from every Django app without manual imports.
app.autodiscover_tasks()
