#!/usr/bin/env bash
# Container entrypoint: apply migrations, then start the API.
#
# Schema is created by `alembic upgrade head` here — NOT by the app calling
# create_all. This is the "schema via migration, not auto-create" rule. If the
# DB is fresh, upgrade creates the table; if it's already current, it's a
# no-op. Running it on every boot is safe and idempotent.
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Starting API..."
# exec so uvicorn becomes PID 1 and receives Docker's stop signals directly
# (clean shutdown, no zombie bash wrapper).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
