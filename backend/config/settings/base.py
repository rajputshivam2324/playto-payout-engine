"""
config/settings/base.py

Defines shared Django settings for the Playto payout engine.

Key design decisions:
  - DRF is configured with JWT authentication because Phase 1 must expose token login.
  - Application modules are registered explicitly so migrations cover every money model.
  - Money safety lives in models and transactions, not in mutable settings.
"""

from datetime import timedelta
import os
from pathlib import Path


# BASE_DIR points at backend/, where manage.py and the app packages live.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECRET_KEY is environment-driven outside local development because it signs JWTs.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "playto-local-dev-secret-key-for-phase-one")

# DEBUG defaults to False here; local.py opts in for development.
DEBUG = False

# Hosts are environment-driven so production can be locked down without code changes.
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


INSTALLED_APPS = [
    # Django core apps provide admin, users, sessions, and static files.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps expose API primitives and JWT token views.
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # Playto apps are registered explicitly so all model migrations are discovered.
    "merchants",
    "ledger",
    "payouts",
    "idempotency",
    "workers",
]

MIDDLEWARE = [
    # CORS middleware must run before CommonMiddleware so browser preflights are handled.
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

# UTC keeps ledger and payout timestamps comparable across workers and API clients.
TIME_ZONE = "UTC"

USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Django auth models still use BigAutoField; Playto money models use explicit UUIDs.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# Extend the default CORS headers to include Idempotency-Key, which mutation
# endpoints require on every POST/PATCH/DELETE (P2).
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key")

REST_FRAMEWORK = {
    # Simple JWT documents JWTAuthentication as the DRF authentication hook.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # Phase 2 will add authenticated API views; defaulting to auth avoids accidental leaks.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    # All raised DRF exceptions are normalized to the public Stripe-style error shape.
    "EXCEPTION_HANDLER": "config.api_errors.playto_exception_handler",
    # Ledger feeds use page-number pagination so clients can poll without unbounded payloads.
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

SIMPLE_JWT = {
    # Short access tokens limit blast radius if a merchant token leaks.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    # Refresh tokens are long enough for a dashboard session without constant login.
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

# Celery reads these through namespace="CELERY". Redis is the required broker (spec line 78).
# The memory:// broker cannot communicate between separate worker and beat processes, so
# Redis is the correct default even for local development.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# Late ACK means a worker crash returns the task to the broker instead of silently losing payout work.
CELERY_TASK_ACKS_LATE = True

# Beat owns periodic maintenance; run a single beat scheduler so duplicate schedules do not fan out tasks.
CELERY_BEAT_SCHEDULE = {
    # Runs every 30 seconds so simulated bank hangs are retried or failed promptly.
    "retry-stuck-payouts": {
        "task": "workers.tasks.retry_stuck_payouts",
        "schedule": 30.0,
    },
    # Runs hourly to keep the idempotency table lean after the 24-hour replay window.
    "purge-expired-idempotency-keys": {
        "task": "workers.tasks.purge_expired_idempotency_keys",
        "schedule": 3600.0,
    },
}
