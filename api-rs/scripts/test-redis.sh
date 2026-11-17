#!/usr/bin/env bash
# Each run owns one disposable container; no existing Redis service is modified.
set -euo pipefail

if [[ ${1:-} == --cleanup ]]; then
    redis_test_container=${2:?pass the container name printed by --prepare}
    redis_test_label=$(docker inspect --format '{{index .Config.Labels "project-template.redis-test"}}' "$redis_test_container")
    [[ $redis_test_label == disposable ]] || { echo "Not a Redis test fixture" >&2; exit 1; }
    docker rm -f "$redis_test_container"
    exit
fi

if [[ $# -gt 0 && ${1:-} != --prepare ]]; then
    echo "Usage: $0 [--prepare | --cleanup CONTAINER]" >&2
    exit 2
fi

redis_test_base=$(uv run --no-project python - <<'PY'
import random
import socket

for base in random.sample(range(20000, 39000, 10), 200):
    sockets = []
    try:
        for port in range(base, base + 7):
            listener = socket.socket()
            sockets.append(listener)
            listener.bind(('127.0.0.1', port))
        print(base)
        break
    except OSError:
        pass
    finally:
        for listener in sockets:
            listener.close()
else:
    raise SystemExit('No free port range for disposable Redis tests')
PY
)
redis_test_container="api-rs-redis-test-${redis_test_base}-$$"
redis_test_publish=()
for ((offset = 0; offset < 7; offset++)); do
    redis_test_port=$((redis_test_base + offset))
    redis_test_publish+=(-p "127.0.0.1:${redis_test_port}:${redis_test_port}")
done

cleanup() {
    docker rm -f "$redis_test_container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "$redis_test_container" \
    --label project-template.redis-test=disposable \
    "${redis_test_publish[@]}" \
    -e PORT_BASE="$redis_test_base" \
    redis:8.2.10-alpine sh -eu -c '
base=$PORT_BASE
password=api-rs-disposable-redis
sentinel_password=api-rs-disposable-sentinel
# One standalone instance, plus one primary and two replicas.
for offset in 0 1 2 3; do
    port=$((base + offset))
    mkdir -p "/tmp/redis-$port"
    set -- --port "$port" --bind 0.0.0.0 --protected-mode yes \
        --requirepass "$password" --save "" --appendonly no \
        --dir "/tmp/redis-$port" --daemonize yes \
        --pidfile "/tmp/redis-$port/redis.pid" --logfile "/tmp/redis-$port/redis.log"
    if [ "$offset" -ge 2 ]; then
        set -- "$@" --replicaof 127.0.0.1 "$((base + 1))" --masterauth "$password"
    fi
    redis-server "$@"
done
# Three Sentinels with quorum 2. They discover each other through Redis.
for offset in 4 5 6; do
    port=$((base + offset))
    cat > "/tmp/sentinel-$port.conf" <<EOF
port $port
bind 0.0.0.0
protected-mode yes
requirepass $sentinel_password
sentinel sentinel-pass $sentinel_password
daemonize yes
pidfile /tmp/sentinel-$port.pid
logfile /tmp/sentinel-$port.log
sentinel announce-ip 127.0.0.1
sentinel announce-port $port
sentinel monitor api-rs-test 127.0.0.1 $((base + 1)) 2
sentinel auth-pass api-rs-test $password
sentinel down-after-milliseconds api-rs-test 1000
sentinel failover-timeout api-rs-test 5000
sentinel parallel-syncs api-rs-test 1
EOF
    redis-server "/tmp/sentinel-$port.conf" --sentinel
done
for attempt in $(seq 1 40); do
    ready=true
    for offset in 2 3; do
        if ! redis-cli --no-auth-warning -a "$password" -p "$((base + offset))" INFO replication |
            tr -d "\r" | grep -q "^master_link_status:up$"; then
            ready=false
        fi
    done
    for offset in 4 5 6; do
        status=$(redis-cli --no-auth-warning -a "$sentinel_password" -p "$((base + offset))" \
            --raw SENTINEL MASTER api-rs-test | tr -d "\r")
        replicas=$(printf "%s\n" "$status" | awk "/^num-slaves$/ { getline; print }")
        sentinels=$(printf "%s\n" "$status" | awk "/^num-other-sentinels$/ { getline; print }")
        if [ "$replicas" != 2 ] || [ "$sentinels" != 2 ]; then
            ready=false
        fi
    done
    if [ "$ready" = true ]; then
        touch /tmp/ready
        exec tail -f /dev/null
    fi
    sleep 1
done
echo "Replicas or Sentinel quorum failed to become ready" >&2
exit 1
' >/dev/null

redis_test_ready=false
for ((attempt = 0; attempt < 45; attempt++)); do
    if docker exec "$redis_test_container" test -f /tmp/ready 2>/dev/null; then
        redis_test_ready=true
        break
    fi
    if [[ $(docker inspect --format '{{.State.Running}}' "$redis_test_container") != true ]]; then
        break
    fi
    sleep 1
done
if [[ $redis_test_ready != true ]]; then
    docker logs "$redis_test_container" >&2
    echo "Disposable Redis fixture did not become ready" >&2
    exit 1
fi

export API_RS_REDIS_TEST_DISPOSABLE=1
export API_RS_REDIS_TEST_BASE_PORT=$redis_test_base
if [[ ${1:-} == --prepare ]]; then
    trap - EXIT
    printf 'export API_RS_REDIS_TEST_DISPOSABLE=1\nexport API_RS_REDIS_TEST_BASE_PORT=%s\n' "$redis_test_base"
    printf '# Cleanup: %s --cleanup %s\n' "$0" "$redis_test_container"
    exit
fi

cd "$(dirname "$0")/../.."
cargo test -p api_rs --bin api_rs core::cache::tests:: --locked -- --ignored --test-threads=1
