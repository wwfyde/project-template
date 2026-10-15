#!/usr/bin/env bash
set -euo pipefail

environment=${1:?Usage: init-env.sh test|production [absolute-deploy-path]}
case "$environment" in test|production) ;; *) echo 'Environment must be test or production' >&2; exit 1 ;; esac
deploy_path=${2:-"$HOME/apps/project-template/$environment"}
[[ "$deploy_path" = /* && "$deploy_path" =~ ^[a-zA-Z0-9_./-]+$ ]] || { echo 'Use an absolute path without spaces' >&2; exit 1; }
command -v openssl >/dev/null
umask 077
mkdir -p "$deploy_path"
if [[ -e "$deploy_path/.env" ]]; then
  echo "Existing configuration preserved: $deploy_path/.env"
  exit 0
fi
# noclobber prevents concurrent initializations from replacing database passwords.
set -o noclobber
cat > "$deploy_path/.env" <<EOF
COMPOSE_PROJECT_NAME=project-template-$environment
APP_ENV=prod
HTTP_BIND=127.0.0.1
HTTP_PORT=18080
POSTGRES_USER=app
POSTGRES_DB=app
POSTGRES_PASSWORD=$(openssl rand -hex 32)
REDIS_PASSWORD=$(openssl rand -hex 32)
EOF
echo "Created configuration: $deploy_path/.env"
