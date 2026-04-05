#!/bin/bash

set -o errexit
set -o pipefail
set -o nounset

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:=config.settings.production}"
export DATABASE_URL="${DATABASE_URL:=sqlite:////tmp/build.db}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:=dummy-secret}"
export TURNSTILE_SITEKEY="${TURNSTILE_SITEKEY:=dummy}"
export TURNSTILE_SECRET="${TURNSTILE_SECRET:=dummy}"
export QN_API_KEY="${QN_API_KEY:=dummy}"
export QN_STREAM_KEY="${QN_STREAM_KEY:=dummy}"
APP_HOME="${APP_HOME:=/app}"

mkdir -p /tmp "${APP_HOME}/staticfiles"

python /app/manage.py collectstatic --noinput
python /app/manage.py compilemessages

rm -f /tmp/build.db
