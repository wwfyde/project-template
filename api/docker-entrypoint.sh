#!/usr/bin/env sh
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic -c /app/alembic.ini upgrade head
fi

exec "$@"
