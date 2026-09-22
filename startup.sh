#!/bin/sh
set -eu
# Schema initialization and bootstrap are explicit deployment steps, never public HTTP routes.
exec gunicorn 'web:create_app()' --bind 0.0.0.0:8000 --workers 2 --threads 4 --timeout 90 --access-logfile /dev/null --error-logfile -
