#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python manage.py migrate --noinput
python manage.py bootstrap_admin
exec gunicorn backend.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --access-logfile - --error-logfile -
