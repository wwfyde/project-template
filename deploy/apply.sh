#!/usr/bin/env bash
# Runs on the deployment server. The caller only uploads this script and Compose.
set -euo pipefail

deploy_path=${1:?Missing deployment path}
release_id=${2:?Missing release ID}
[[ "$deploy_path" = /* && "$deploy_path" =~ ^[a-zA-Z0-9_./-]+$ ]] || exit 1
[[ "$release_id" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || exit 1
release_path="$deploy_path/releases/$release_id"
export DEPLOY_ENV_FILE="$deploy_path/.env"
# The saved server configuration and release file must win over shell profiles.
unset API_IMAGE WEB_IMAGE COMPOSE_PROJECT_NAME APP_ENV HTTP_BIND HTTP_PORT
unset POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD REDIS_PASSWORD
[[ -f "$DEPLOY_ENV_FILE" ]] || { echo 'Initialize the server with deploy/init-env.sh first' >&2; exit 1; }

if [[ -d "$release_path/.docker" ]]; then
  export DOCKER_CONFIG="$release_path/.docker"
fi
compose=(docker compose --env-file "$DEPLOY_ENV_FILE" --env-file "$release_path/images.env" -f "$release_path/docker-compose.yaml")
cleanup() {
  local status=$?
  trap - EXIT
  if (( status != 0 )); then
    "${compose[@]}" ps -a || true
    echo "Deployment failed; current still points to the last successful release. Inspect $release_path and restore deliberately; migrations are not automatically reversed." >&2
  fi
  rm -rf -- "$release_path/.docker"
  exit "$status"
}
trap cleanup EXIT

# Serializes manual and Actions deploys to this environment, including migrations.
exec 9>"$deploy_path/.deploy.lock"
flock -w 600 9

"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up -d --no-build --wait --wait-timeout 180 postgres redis
# Explicit run means migrations run on every attempt, even when reusing an image.
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --no-build --no-deps --wait --wait-timeout 180 api
"${compose[@]}" up -d --no-build --no-deps --wait --wait-timeout 120 web

published=$("${compose[@]}" port web 8080)
bind=${published%:*}
port=${published##*:}
case "$bind" in 0.0.0.0) bind=127.0.0.1 ;; '[::]') bind='[::1]' ;; esac
curl --fail --silent --show-error --max-time 15 "http://$bind:$port/healthz" >/dev/null
curl --fail --silent --show-error --max-time 15 "http://$bind:$port/api/health"
ln -sfn "releases/$release_id" "$deploy_path/current.next"
mv -Tf "$deploy_path/current.next" "$deploy_path/current"
echo "Deployment ready: $release_id"
