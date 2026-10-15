set dotenv-load

# 启动后端；--port/-p 优先于 API_PORT。
[arg("port", long, short="p")]
[working-directory('api')]
api $port=env_var_or_default("API_PORT", "8000"):
    @case "$port" in ''|*[!0-9]*) echo 'API_PORT 必须是 1–65535 的整数' >&2; exit 1;; esac; [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { echo 'API_PORT 必须是 1–65535 的整数' >&2; exit 1; }
    uv run uvicorn api.main:app --reload --port {{ port }}

[working-directory('api-rs')]
api-rs:

# 启动前端；--port/-p 优先于 WEB_PORT，端口占用时直接报错。
[arg("port", long, short="p")]
web $port=env_var_or_default("WEB_PORT", "5173"):
    @case "$port" in ''|*[!0-9]*) echo 'WEB_PORT 必须是 1–65535 的整数' >&2; exit 1;; esac; [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { echo 'WEB_PORT 必须是 1–65535 的整数' >&2; exit 1; }
    WEB_PORT="$port" pnpm --filter web run dev --port {{ port }} --strictPort

# 同时启动前后端；Ctrl+C 或任一服务退出时关闭本次启动的所有子进程。
[arg("api_port", long="api-port")]
[arg("web_port", long="web-port")]
run $web_port=env_var_or_default("WEB_PORT", "5173") $api_port=env_var_or_default("API_PORT", "8000"):
    WEB_PORT="$web_port" API_PORT="$api_port" pnpm exec node scripts/run-dev.mjs
