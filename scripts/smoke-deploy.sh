#!/usr/bin/env bash
set -euo pipefail

# Run only against a disposable, uniquely named Compose project. API_IMAGE and
# WEB_IMAGE may reference locally built images or published registry digests.
: "${API_IMAGE:?Set API_IMAGE to the image to test}"
: "${WEB_IMAGE:?Set WEB_IMAGE to the image to test}"

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
smoke_dir=$(mktemp -d "${RUNNER_TEMP:-/tmp}/project-template-smoke.XXXXXX")
COMPOSE_PROJECT_NAME="project-template-smoke-$(basename "$smoke_dir" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]')"
export COMPOSE_PROJECT_NAME
export DEPLOY_ENV_FILE="$smoke_dir/.env"
export HTTP_BIND=127.0.0.1
# Ask Docker for an unused loopback port instead of claiming the server's port.
export HTTP_PORT=0

compose=(docker compose --env-file "$DEPLOY_ENV_FILE" -f "$repo_root/docker-compose.yaml")
cleanup() {
  status=$?
  trap - EXIT
  if [[ $status -ne 0 && -f "$DEPLOY_ENV_FILE" ]]; then
    "${compose[@]}" logs --no-color --tail 100 || true
  fi
  if [[ -f "$DEPLOY_ENV_FILE" ]]; then
    "${compose[@]}" down --volumes --remove-orphans || true
  fi
  rm -rf -- "$smoke_dir"
  exit "$status"
}
trap cleanup EXIT

bash deploy/init-env.sh test "$smoke_dir"
"${compose[@]}" config --quiet
"${compose[@]}" up --detach --no-build --wait --wait-timeout 240 web

http_address=$("${compose[@]}" port web 8080)
[[ "$http_address" =~ ^127\.0\.0\.1:[0-9]+$ ]] || { echo "Unexpected HTTP binding: $http_address" >&2; exit 1; }
curl --fail --silent --show-error --max-time 15 "http://$http_address/healthz" >/dev/null
curl --fail --silent --show-error --max-time 15 "http://$http_address/api/health"
curl --fail --silent --show-error --max-time 15 "http://$http_address/" > "$smoke_dir/index.html"
grep -qi '<!doctype html' "$smoke_dir/index.html"
"${compose[@]}" exec -T web nginx -t
for path in /api/does-not-exist /api/config /assets/does-not-exist.js; do
  status=$(curl --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code}' "http://$http_address$path")
  [[ "$status" == 404 ]] || { echo "Expected 404 at $path, got $status" >&2; exit 1; }
done

# A ready database alone does not prove that the one-shot migration succeeded.
# These variables must expand inside the Postgres container.
# shellcheck disable=SC2016
"${compose[@]}" exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"' \
  > "$smoke_dir/migration-version"
[[ -s "$smoke_dir/migration-version" ]] || { echo 'No Alembic revision found' >&2; exit 1; }

# Verify the app really writes to Postgres and survives API replacement.
curl --fail --silent --show-error --max-time 15 \
  -H 'Content-Type: application/json' -d '{"title":"Compose deployment smoke"}' \
  "http://$http_address/api/conversations" > "$smoke_dir/conversation.json"
# shellcheck disable=SC2016 # Credentials expand inside the Postgres container.
"${compose[@]}" exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM conversation"' \
  > "$smoke_dir/conversation-count"
[[ $(cat "$smoke_dir/conversation-count") == 1 ]] || { echo 'Conversation was not persisted in Postgres' >&2; exit 1; }
"${compose[@]}" up -d --no-build --no-deps --force-recreate --wait --wait-timeout 120 api
# Nginx caches the old Docker DNS record for at most ten seconds.
curl --fail --silent --show-error --max-time 15 --retry 10 --retry-all-errors --retry-delay 2 \
  "http://$http_address/api/conversations" > "$smoke_dir/conversations.json"
grep -q 'Compose deployment smoke' "$smoke_dir/conversations.json"
echo 'Compose smoke test passed: migrations, Postgres persistence, Redis, API replacement, and web.'
