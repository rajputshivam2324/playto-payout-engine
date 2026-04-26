"""
config/wsgi.py

Exposes the WSGI callable for Django runserver and production web workers.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

application = get_wsgi_application()
