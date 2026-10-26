# 运行与运维说明

本页说明如何准备、启动、检查和维护当前 API。设计边界见 [architecture.md](architecture.md)，表与迁移见 [data-schema.md](data-schema.md)，业务规则见 [business-flows.md](business-flows.md)。
这些命令是操作步骤，不表示目标环境已经执行或验证过。

## 1. 运行前提与工作目录

根目录和 API 包均要求 Python `>=3.14`，API 是根 `uv` workspace 的成员。
从仓库根目录安装 API 依赖：

```bash
uv sync --locked --package api
```

完整前端开发环境另需 `pnpm install --frozen-lockfile`；端口协同入口由根 [justfile](../../justfile) 管理。
依赖版本以 [api/pyproject.toml](../pyproject.toml) 与根 [uv.lock](../../uv.lock) 为准。

运行 API 时使用 `api/` 作为工作目录，或使用 `uv run --directory api ...`。
配置文件相对于工作目录读取，`data/`、`temp/` 等默认路径也从工作目录派生。
因此，在根目录直接运行模块与在 `api/` 运行可能读到不同配置、写入不同目录。
根 `.env` 主要用于开发端口；API 的文件配置放在 `api/`，具体加载规则见 [configuration.md](configuration.md)。

本地完整应用需要可用的 PostgreSQL 与 Redis。
仓库 Compose 使用 PostgreSQL 18、Redis 8.2，迁移中存在 `uuidv7()`，Redis session 依赖当前 SDK 所用命令。
使用其他服务版本前，应在隔离环境验证迁移与 session 集成测试。
`repo_type=in-memory` 只改变部分业务存储；认证、资源归属和健康检查仍使用 PostgreSQL，不能据此省略数据库。

## 2. 准备本地配置

在已创建的本地数据库和 Redis 上使用专用开发账户；以下地址、用户名和密码都是待替换示例。
将所需内容合并到未跟踪的 `api/config.local.toml`，不要覆盖已有配置：

```toml
repo_type = "postgres"

[app]
env = "dev"
debug = true

[postgres]
host = "127.0.0.1"
port = 5432
username = "app"
password = "replace-with-local-password"
database = "app"

[redis]
host = "127.0.0.1"
port = 6379
db = 0
session_cookie_https_only = false
# 如果本地 Redis 启用了认证，在这里配置 password。

[auth]
frontend_url = "http://localhost:5173"

[auth.password]
enabled = true
```

模型、OAuth 和对象存储凭据只在使用对应功能时补充，字段见 [config.example.toml](../config.example.toml)。
示例文件含占位凭据、代理和模型名，不能不加检查地作为已就绪配置。
多个 TOML 文件的同名顶层表整体覆盖；只在更晚文件写 `[redis]` 的一个字段，会丢失前一文件该表的其他显式字段。

## 3. 迁移与创建登录用户

以下命令会连接并修改配置指定的数据库；先确认运行目录、目标实例、数据库名和备份策略。
应用启动不自动建表，首次启动与新增迁移后均需执行迁移：

```bash
# 从仓库根目录执行；current 查询目标库，upgrade 会写入目标库。
uv run --directory api alembic current
uv run --directory api alembic upgrade head
uv run --directory api alembic current
```

准备好数据库后创建本地用户。密码通过终端隐藏输入，避免进入 shell 历史：

```bash
uv run --directory api python -m api.cli.auth create-user alice --display-name Alice
uv run --directory api python -m api.cli.auth set-password alice
```

第一条命令创建 `user`、个人 `account`、owner 成员关系和密码身份；没有默认账号或公开密码注册接口。
第二条是独立的重设密码操作，不是首次创建后的必需步骤；它递增 `auth_version`，使已有登录失效。
用户名规范化为小写，长度 3–64；新密码 12–1024 字符且不超过 4096 UTF-8 字节。
启用密码入口还需要 `password` 在 `auth.providers` 中，且 `auth.password.enabled=true`。

## 4. 启动入口及端口

| 入口 | 执行位置 | 行为 |
| --- | --- | --- |
| `just run` | 根目录 | 同时启动前后端，默认前端 5173、API 8000 |
| `just api --port 9036` | 根目录 | 在 `api/` 启动 Uvicorn，支持 reload |
| `uv run api` | `api/` | 使用 `settings.app.port`，监听 `0.0.0.0` |
| `uv run dev` | `api/` | 现有快捷脚本固定监听 `127.0.0.1:8023`，支持 reload |

`just` 的端口参数优先于 `API_PORT` / `WEB_PORT`，根 `.env` 为开发脚本提供默认值。
`app.port` 不会覆盖 `just api` 显式传给 Uvicorn 的 `--port`。
修改本地前端端口时同步修改 `auth.frontend_url`；OAuth callback 也需与实际地址和供应商登记值一致。
`just run` 不会启动数据库、Redis，也不会执行 Alembic。

## 5. 启动后的检查

在已经启动的本地 API 上执行只读请求：

```bash
curl --fail http://localhost:8000/api/health
curl --fail http://localhost:8000/api/auth/session
```

`/api/health` 分别执行 Redis `PING` 与 PostgreSQL `SELECT 1`，每项最多等待 3 秒。
两者成功才返回 200；任一失败返回 503，并显示 `redis.pong`、`postgres.connected`。
它没有验证表版本、模型调用、OAuth 回调或数据正确性；`/api/hello` 也不能代替依赖健康检查。
匿名调用 `/api/auth/session` 正常返回 `authenticated=false`，同时可观察后端提供的渠道列表。

| 路径 | 可用条件 |
| --- | --- |
| `/docs`、`/redoc` | `app.env != "prod"`；是 API 根路径，不带 `/api` |
| `/openapi.json` | 当前 FastAPI 工厂未禁用；生产只关闭了 docs/redoc 页面 |
| `/api/config` | 非生产且已经登录 |
| `/api/examples/...` | 仅 dev/local；认证要求随示例类别不同 |

当前前端代理主要处理 `/api`；查看 `/docs` 时应直接使用 API 地址或专门配置代理。
`GET /api/config` 不等于完整配置诊断：它会排除部分字段且仅输出显式设置字段，不要将返回体作为可公开信息传播。

## 6. 登录联调

浏览器访问前端 origin，由同源 `/api` 代理访问后端。
HTTP 本地开发设置 `redis.session_cookie_https_only=false`；生产必须使用 HTTPS 与 Secure Cookie。
`localhost` 与 `127.0.0.1` 的 Cookie 作用域不同，应始终使用同一主机名。
`SameSite` 必须为 `lax`，Cookie path 必须是 `/` 或 `/api`。

密码登录 `POST /api/auth/password/login` 需要 `X-Requested-With: XMLHttpRequest`。
浏览器传来的 `Origin` 必须与 `auth.frontend_url` 完全相同；登录成功返回 session 信息及 `csrf_token`。
后续受保护的写操作携带当前 `X-CSRF-Token`；轮换 session 后重新读取 token。
Google/钉钉登录需要真实有效的凭据和登记回调，离线测试不能证明外部授权可用。
绑定、解绑、密码变更和重新验证规则见 [business-flows.md](business-flows.md)；请求契约见 [api-reference.md](api-reference.md)。

## 7. 验证命令

常规测试从根目录执行。依赖已安装时使用 `--no-sync`，避免测试过程中隐式同步环境：

```bash
uv run --no-sync pytest api/tests -q
```

常规测试通过临时配置与测试替身隔离服务；真实服务用例在未提供专用测试 URL 时跳过。
运行集成测试前，仅将下面的变量指向可清理的专用测试实例，不要使用业务数据库或生产 Redis：

```bash
# 在当前 shell 已配置专用测试地址后，按需执行对应组。
TEST_AUTH_REDIS_URL="$TEST_AUTH_REDIS_URL" \
  uv run --no-sync pytest api/tests/test_auth_redis_integration.py -q
TEST_ACCOUNT_POSTGRES_DSN="$TEST_ACCOUNT_POSTGRES_DSN" \
  uv run --no-sync pytest api/tests/test_account_migration.py api/tests/test_account_postgres_integration.py -q
```

Redis 集成测试使用随机前缀；PostgreSQL 用例使用临时 schema，执行真实迁移与锁竞争并清理。
测试范围与新增用例指导见 [development.md](development.md)。
Compose 冒烟和部署测试入口见 [部署说明](../../deploy/README.md)，它们与普通离线测试的资源使用不同。

## 8. 升级与受限回滚

发布前保存数据库备份、配置和前一版镜像 digest，并在隔离环境演练。
部署流程先等数据库和 Redis 就绪，再执行一次性迁移，随后更新 API、Web 和检查 HTTP。
修改 Compose 环境变量后需要重建对应容器，单纯 `docker compose restart` 不会载入新的环境变量。
实际发布命令、备份命令和卷位置以 [部署说明](../../deploy/README.md) 为入口。

用户/账户迁移 `e28b47a1d902` 需要在线数据库连接，不能用 `alembic upgrade --sql` 生成完整离线脚本。
迁移检查旧资源与用户 tenant 的一致性，回填每人独立的 personal 账户，并保留 `_account_legacy_scope` 用于旧范围恢复。
升级后旧 session 失效，需要重新登录；不能删除迁移备份表后仍假定可以完整降级。
出现 workspace、共享成员、资源迁移或旧模型无法表达的账户专属状态时，降级会拒绝执行。
不要把 `alembic downgrade -1` 当作通用回滚方案；先确认旧代码、数据状态与 revision 的兼容性，再决定兼容修复或恢复备份。

## 9. 故障定位

图片 API 的422错误先查同一 Request-ID 下的 ERROR 事件 `http.request.validation_failed`。`json_invalid` 表示 JSON 语法错误，日志会指出行、列及字符偏移；其他类型通过 `validation.error_locations` 定位字段，例如 `body.prompt` 或 `query.provider`。不要仅凭 INFO access log 中的状态码判断缺了哪个参数。

先记录发生时间、接口、HTTP 状态与 `Request-ID`，再根据下表检查；不复制 Cookie、密码、OAuth code 或完整配置到日志。

AI 图片工具采用 `200 + success=false` 表达工具失败。GPT 调用失败时，先用本地 Request-ID 查找 `image.request.failed` 日志，再查看 `data.diagnostics` 的 `upstream_host/status/upstream_request_id/error_code/error_param/error_message`。渠道配置名不保证直连官方主机；不要只根据 `provider=openai` 或异常类名归因。上游未返回的字段无法从旧日志恢复；诊断日志不会自动重试模型调用。

| 现象 | 优先检查 |
| --- | --- |
| 401 | Cookie 是否发送、session 是否过期、用户/账户是否启用、成员关系、渠道是否可用、`auth_version` 是否变化 |
| 403 | CSRF 与 Origin、密码登录请求头、近期验证窗口、传入身份头是否与 session 一致 |
| 404 | 路径/环境是否正确；资源是否属于当前 `(account_id, user_id)`，是否缺少 `resource_owner` |
| 409 | 用户名/身份冲突、安全操作竞争、业务执行状态；读取具体 `detail.code`，核实当前状态后处理 |
| 429 | 密码尝试次数与 `Retry-After`，代理可信设置是否导致大量用户共用同一客户端 IP |
| 503 | Redis/session、PostgreSQL、渠道配置或 agent backend 是否可用；同时看响应错误信息与服务日志 |

Redis：核对最终配置的 URL、模式、认证、TLS 与服务版本；单机 URL 会覆盖独立连接字段，Sentinel 不能保留 URL。
不要通过清空 Redis 处理连接错误；清空 session 会使用户掉线，也可能影响业务缓存。
PostgreSQL：核对主机/库名/用户、连接池压力、Alembic revision；`health` 成功但业务报缺表时优先检查迁移。
账号变更可能已经提交 PostgreSQL，随后 Redis 轮换失败返回 503；恢复后重新登录并读取状态，不自动重放安全变更。

OTel：确认 `otel.enabled=true` 且 `sdk_disabled=false`，然后检查各信号开关、采样、collector 地址、网络与接收端。
`sampled` 或 `recording` 只能说明本地 span 状态，不能证明 collector 已收到数据。
API 默认向 collector 主动发送 HTTP/protobuf；collector、Tempo/Loki/Prometheus 查询与排查见 [可观测性部署说明](../../deploy/observability/README.md)。

返回 [文档导航](README.md)。
