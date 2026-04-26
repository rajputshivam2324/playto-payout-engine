FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt gunicorn

COPY . /app/

ENV DJANGO_SETTINGS_MODULE=config.settings.local
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
