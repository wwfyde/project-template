#!/usr/bin/env bash
set -euo pipefail

environment=${1:?Usage: scripts/deploy.sh test|production release-id}
release_id=${2:?Missing release ID (for example sha-<commit>-<run-id>)}
case "$environment" in
  test) default_target='test' ;;
  production) default_target=oracle ;;
  *) echo 'Environment must be test or production' >&2; exit 1 ;;
esac
[[ "$release_id" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || { echo 'Invalid release ID' >&2; exit 1; }
: "${API_IMAGE:?Set API_IMAGE to the immutable API image reference}"
: "${WEB_IMAGE:?Set WEB_IMAGE to the immutable web image reference}"
for image in "$API_IMAGE" "$WEB_IMAGE"; do
  [[ "$image" =~ ^[a-zA-Z0-9][a-zA-Z0-9./_:@-]+$ ]] || { echo 'Invalid image reference' >&2; exit 1; }
done
target=${DEPLOY_SSH_TARGET:-$default_target}
[[ "$target" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.@:-]*$ ]] || { echo 'Invalid SSH target' >&2; exit 1; }
if [[ -n "${HTTP_BIND:-}" ]]; then
  [[ "$HTTP_BIND" =~ ^[][0-9a-fA-F.:]+$ ]] || { echo 'HTTP_BIND must be an IP address' >&2; exit 1; }
fi
if [[ -n "${HTTP_PORT:-}" ]]; then
  if ! [[ "$HTTP_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$HTTP_PORT < 1 || 10#$HTTP_PORT > 65535 )); then
    echo 'Invalid HTTP_PORT' >&2; exit 1
  fi
fi
ssh_args=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes)
if [[ -n "${DEPLOY_SSH_CONFIG:-}" ]]; then ssh_args+=(-F "$DEPLOY_SSH_CONFIG"); fi
# Remote commands below quote only validated paths and identifiers.
# shellcheck disable=SC2029
ssh_remote() { ssh "${ssh_args[@]}" "$target" "$@"; }
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
deploy_path=${DEPLOY_PATH:-}
if [[ -z "$deploy_path" ]]; then
  # shellcheck disable=SC2016 # HOME belongs to the remote user.
  remote_home=$(ssh_remote 'printf "%s" "$HOME"')
  deploy_path="$remote_home/apps/project-template/$environment"
fi
[[ "$deploy_path" = /* && "$deploy_path" =~ ^[a-zA-Z0-9_./-]+$ ]] || { echo 'DEPLOY_PATH must be an absolute path without spaces' >&2; exit 1; }
release_path="$deploy_path/releases/$release_id"
ssh_remote "test -f '$deploy_path/.env' && docker compose version >/dev/null && command -v flock >/dev/null && command -v curl >/dev/null && umask 077 && mkdir -p '$deploy_path/releases' && mkdir '$release_path'"
cleanup() {
  local status=$?
  trap - EXIT
  ssh_remote "rm -rf -- '$release_path/.docker'" || true
  exit "$status"
}
trap cleanup EXIT
tar -C "$root" -czf - docker-compose.yaml deploy/apply.sh | ssh_remote "tar -xzf - -C '$release_path'"
{
  printf 'API_IMAGE=%s\nWEB_IMAGE=%s\n' "$API_IMAGE" "$WEB_IMAGE"
  if [[ -n "${HTTP_BIND:-}" ]]; then
    printf 'HTTP_BIND=%s\n' "$HTTP_BIND"
  fi
  if [[ -n "${HTTP_PORT:-}" ]]; then
    printf 'HTTP_PORT=%s\n' "$HTTP_PORT"
  fi
} | ssh_remote "umask 077; cat > '$release_path/images.env'"
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  : "${GHCR_USER:?Set GHCR_USER alongside GHCR_TOKEN}"
  [[ "$GHCR_USER" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 1
  printf '%s' "$GHCR_TOKEN" | ssh_remote "umask 077; mkdir -p '$release_path/.docker'; docker --config '$release_path/.docker' login ghcr.io --username '$GHCR_USER' --password-stdin >/dev/null"
fi
ssh_remote "bash '$release_path/deploy/apply.sh' '$deploy_path' '$release_id'"
