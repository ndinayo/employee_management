#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python manage.py migrate --noinput
# Read-only report of accounts sharing an email; adds the unique email index once there are none.
if ! python manage.py check_duplicate_emails; then
    echo "WARNING: python manage.py check_duplicate_emails failed; see the error above. Starting the server anyway." >&2
fi
# Idempotent. A seeding problem (for example a missing PLATFORM_ADMIN_PASSWORD on a
# fresh database) is reported in the logs but must not keep the site from starting.
if ! python manage.py seed; then
    echo "WARNING: python manage.py seed failed; see the error above. Starting the server anyway." >&2
fi
python manage.py bootstrap_admin
exec gunicorn backend.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --access-logfile - --error-logfile -
