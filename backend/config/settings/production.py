"""
config/settings/production.py
Production settings for Render free tier deployment.
"""
import os
from .base import *  # noqa: F403,F401

DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"]  # hard crash if missing — intentional

# Hard crash if the hostname is not configured — falling back to "*" would accept any
# Host header and silently expose the API to host-header injection attacks.
_render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if not _render_hostname:
    raise RuntimeError(
        "RENDER_EXTERNAL_HOSTNAME environment variable is required in production. "
        "Set it to the public hostname (e.g. myapp.onrender.com)."
    )
ALLOWED_HOSTS = [_render_hostname]

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "OPTIONS": {"sslmode": "require"},
        "CONN_MAX_AGE": 60,
    }
}

CELERY_BROKER_URL = os.environ["CELERY_BROKER_URL"]
CELERY_RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

MIDDLEWARE = ["whitenoise.middleware.WhiteNoiseMiddleware"] + MIDDLEWARE  # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
