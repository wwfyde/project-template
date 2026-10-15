#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu host; never replace or upgrade an existing runtime.
# https://docs.docker.com/engine/install/ubuntu/
set -euo pipefail

fail() {
  echo "$*" >&2
  exit 1
}

as_root() {
  if (( EUID == 0 )); then
    "$@"
  else
    sudo -n "$@"
  fi
}

[[ -r /etc/os-release ]] || fail 'Cannot identify this host: /etc/os-release is missing.'
# shellcheck source=/dev/null
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || fail 'This installer supports Ubuntu only, not derivative distributions.'
codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
case "${VERSION_ID:-}:$codename" in
  22.04:jammy|24.04:noble|26.04:resolute) ;;
  *) fail "Unsupported Ubuntu release: ${VERSION_ID:-unknown} ($codename). Check Docker's supported releases first." ;;
esac

if command -v docker >/dev/null; then
  docker compose version >/dev/null 2>&1 || fail 'Docker already exists but Compose is unavailable. Repair the existing installation manually.'
  docker buildx version >/dev/null 2>&1 || fail 'Docker already exists but Buildx is unavailable. Repair the existing installation manually.'
  if ! docker info >/dev/null 2>&1; then
    as_root docker info >/dev/null 2>&1 || fail 'Docker already exists but its daemon is unavailable. Check its service and permissions manually.'
    echo 'Docker is healthy with root access. Check docker group membership and reconnect SSH for unprivileged use.'
  fi
  docker --version
  docker compose version
  docker buildx version
  echo 'Existing Docker installation preserved; no packages or group membership changed.'
  exit 0
fi

architecture=$(dpkg --print-architecture)
case "$architecture" in
  amd64|arm64|armhf|s390x|ppc64el) ;;
  *) fail "Unsupported Docker architecture: $architecture" ;;
esac
command -v systemctl >/dev/null || fail 'This installer requires an Ubuntu host running systemd.'
[[ -d /run/systemd/system ]] || fail 'systemd is not running. Use a full Ubuntu server, not a build container.'

conflicts=()
for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; do
  package_status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)
  if [[ "$package_status" == 'install ok installed' ]]; then
    conflicts+=("$package")
  fi
done
(( ${#conflicts[@]} == 0 )) || fail "Existing runtime packages found: ${conflicts[*]}. Nothing was removed. Review and resolve the existing installation manually."
if command -v snap >/dev/null && snap list docker >/dev/null 2>&1; then
  fail 'A Docker snap installation exists. Review it manually before installing Docker CE.'
fi

deploy_user=${SUDO_USER:-$(id -un)}
id "$deploy_user" >/dev/null || fail "Unknown invoking user: $deploy_user"
as_root true || fail 'Installation requires root or passwordless sudo. Run this script through sudo after reviewing it.'

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/docker.sources" <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF

# Reuse only this exact source definition; never replace a custom repository.
shopt -s nullglob
for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [[ -f "$source_file" ]] || continue
  if grep -q 'download\.docker\.com' "$source_file"; then
    if [[ "$source_file" != /etc/apt/sources.list.d/docker.sources ]] || ! cmp -s "$source_file" "$work_dir/docker.sources"; then
      fail "An existing Docker apt source needs manual review: $source_file"
    fi
  fi
done
if [[ -e /etc/apt/sources.list.d/docker.sources ]]; then
  cmp -s /etc/apt/sources.list.d/docker.sources "$work_dir/docker.sources" || fail 'Existing docker.sources differs; it will not be overwritten.'
fi

install_packages() {
  local plan
  plan=$(as_root env LC_ALL=C apt-get --simulate --no-install-recommends --no-remove --no-upgrade install "$@")
  if grep -Eq '^Inst [^ ]+ \[' <<< "$plan"; then
    printf '%s\n' "$plan" >&2
    fail 'This installation would upgrade existing packages. Review those upgrades separately before retrying.'
  fi
  as_root env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends --no-remove --no-upgrade "$@"
}

as_root apt-get update
install_packages ca-certificates curl
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://download.docker.com/linux/ubuntu/gpg -o "$work_dir/docker.asc"
as_root install -m 0755 -d /etc/apt/keyrings
as_root install -m 0644 "$work_dir/docker.asc" /etc/apt/keyrings/docker.asc
as_root install -m 0644 "$work_dir/docker.sources" /etc/apt/sources.list.d/docker.sources
as_root apt-get update
install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
as_root systemctl enable --now docker.service
as_root docker info >/dev/null
docker compose version
docker buildx version

if [[ "$deploy_user" != root ]]; then
  as_root groupadd --force docker
  as_root usermod -aG docker "$deploy_user"
  echo "Docker is ready. Added $deploy_user to the docker group; reconnect SSH to activate membership."
else
  echo 'Docker is ready. Invoked directly as root; no non-root account was added to the docker group.'
fi
