#!/bin/sh
set -e

echo "Running migrations..."
python manage.py migrate

echo "Seeding merchants..."
python manage.py seed_merchants || true

echo "Starting Celery worker in background..."
celery -A config worker -l info &

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2
