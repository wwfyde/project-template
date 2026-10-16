# API 用户与认证

认证从 `fs-agent` 的 provider / session / 登录门禁结构移植，保留钉钉，新增 Google OIDC，并从 `fastapi-template-production` 接入用户名密码和 Header API Key 的依赖组织。所有用户登录统一使用 Redis session；Header API Key 仅用于指定服务接口。手机号只保留注册表与配置扩展位，不提供短信或验证码接口。Google 必须出现在 `auth.providers` 中；是否可登录还取决于 `enabled` 和客户端凭据。渠道列表及排序由后端控制。

Google、钉钉默认 `enabled=true`，配置 `client_id`、`client_secret` 和平台登记的回调地址后，登录页自动展示相应入口；未填写凭据的渠道不可用，可用 `enabled=false` 显式关闭。兼容旧 `[auth.dingtalk] frontend_url`（迁移到共享 `auth.frontend_url`，显式共享值优先），旧 `session_secret` 被忽略，不用于 Redis session。旧回调 `/api/auth/dingtalk/callback` 和 `/api/auth/dingtalk/start` 仍可使用，新配置推荐 `/api/auth/oauth/dingtalk/...`。

## 启用登录

1. 准备 PostgreSQL 和 Redis ≥ 7.4（Compose 使用 Redis 8.2）。在 `api/` 运行 `uv run alembic upgrade head`，认证迁移依次为 `c36f109ab672`、`da72e4b18c09`（密码凭据）；应用启动不自动改表。
2. 参考 `config.example.toml` 的 `[auth]`、`[auth.google]`、`[redis]` 和 `[request_context]`。在 Google Cloud 创建 Web OAuth 客户端，并将准确的回调地址加入授权重定向 URI，例如 `https://app.example.com/api/auth/oauth/google/callback`。
3. 设置 Google `client_id` / `client_secret`、`redirect_uri` 和 `auth.frontend_url`。本地 HTTP 开发需要 `redis.session_cookie_https_only=false`；生产必须使用 HTTPS 和 Secure Cookie。Cookie 固定要求 `SameSite=lax`，路径为 `/` 或 `/api`，覆盖 OAuth 回调及业务接口。
4. Web 使用同源 `/api`；本地 Vite 和部署反向代理均转发 API。`frontend_url` 必须是浏览器访问的准确 origin，含端口，不含子路径。浏览器须能把同一 Cookie 发给回调和 API，请勿混用 `localhost` / `127.0.0.1`。当前采用同源部署，不提供跨站 Cookie/CORS 登录模式。

配置优先级和 TOML 表覆盖规则见下文。环境变量嵌套只拆分一次，因此渠道对象使用 JSON，不使用 `AUTH_GOOGLE_CLIENT_ID`：

```dotenv
AUTH_PROVIDERS='["google","password","dingtalk","phone"]'
AUTH_FRONTEND_URL=https://app.example.com
AUTH_GOOGLE='{"enabled":true,"client_id":"your-client-id","client_secret":"your-secret","redirect_uri":"https://app.example.com/api/auth/oauth/google/callback"}'
AUTH_DEFAULT_TENANT_ID=default
AUTH_ALLOW_SIGNUP=true
AUTH_SESSION_KEY_PREFIX=project-template:auth
REDIS_SESSION_COOKIE_NAME=project_template_session
REDIS_SESSION_COOKIE_HTTPS_ONLY=true
REDIS_SESSION_IDLE_TTL=1800
REDIS_SESSION_ABSOLUTE_TTL=28800
```

凭据留在部署环境或未跟踪的本地配置中。Google 无凭据时该渠道不可用；不会提供开发假登录。`AUTH_ALLOW_SIGNUP=false` 只允许已有外部 OAuth 身份登录，不影响命令行创建本地账号。

## 用户名密码登录

在 `auth.providers` 中加入 `password`，设置 `[auth.password] enabled=true`（环境变量为 `AUTH_PASSWORD='{"enabled":true}'`）。默认配置关闭密码渠道，示例 TOML 显式开启。Google 渠道仍须保留在来源列表，但可在未配置 Google 凭据时先使用密码登录。

在 `api/` 目录创建账号或重设密码，密码通过隐藏输入读取，不放在命令行、配置文件或日志里：

```bash
uv run alembic upgrade head
uv run python -m api.auth.manage create-user alice --display-name Alice
# 可用 --tenant-id 指定服务端分配的租户，否则使用 auth.default_tenant_id。
uv run python -m api.auth.manage set-password alice
```

用户名不区分大小写，去除首尾空白后须为 3–64 个 ASCII 字母、数字或 `_.@-`，数据库唯一约束防止重复。新密码为 12–1024 个字符，最多 4096 UTF-8 字节。没有默认账号、公开注册或自动超级用户。`auth_password_credential` 关联本地用户，并与 `auth_identity(provider=password)` 同事务建立；不会按同邮箱自动合并已有 OAuth 用户。

新密码使用 Argon2；兼容来源项目的 bcrypt 哈希，校验成功后升级为 Argon2。bcrypt 输入超过 72 UTF-8 字节会拒绝，避免旧版本的截断行为。密码计算在线程池执行；登录验证后复核密码哈希与认证版本，防止并发重设密码时用旧凭据创建新版本 session。重设密码递增用户 `auth_version`，使该用户现有登录会话失效。

`POST /api/auth/password/login` 接受 JSON `{"username":"alice","password":"..."}`，成功返回与 `/auth/session` 一样的用户及 CSRF 信息，并设置/轮换 Cookie。来源项目的 JWT 签发接口不移植；这里不返回 Bearer token。请求必须带 `X-Requested-With: XMLHttpRequest`，浏览器带来的 `Origin` 必须与 `frontend_url` 一致，阻止登录 CSRF；命令行调用同样设置此头。错误用户名、错误密码、停用用户统一返回 401，校验错误不回显密码。

密码尝试默认按用户名每 300 秒 10 次、客户端 IP 每 300 秒 50 次限制，成功和失败都计数，Redis Lua 原子维护计数和 TTL。通过 `rate_limit_attempts`、`ip_rate_limit_attempts`、`rate_limit_window_seconds` 配置；超限返回 429 和 `Retry-After`，Redis 故障返回 503。IP 使用 ASGI 的客户端地址，不自行信任 `X-Forwarded-For`；部署反向代理时须正确配置 Uvicorn 的可信代理。

## 指定 API 的 Header 认证

配置独立的 `[auth.header]` 或 JSON 环境变量：

```toml
[auth.header]
enabled = true
name = "X-Api-Key"
keys = ["replace-with-at-least-32-random-ASCII-characters"]
```

实际密钥应随机生成并存放在部署 secret 中，支持同时配置多个有效密钥以便轮换。默认关闭且没有演示密钥；禁用/未配置返回 503，缺失、错误或重复 Header 返回 401。密钥常量时间比较，不回显、不记录。Header 名不能与 Cookie、CSRF、身份或追踪头冲突；原来的 `api_key_header="fastapi"` 默认值已移除。

`api.core.deps` 提供统一依赖入口：`CurrentUserDep` / `get_current_user` / `get_current_active_user` 使用已登录、有效且启用的用户 session；`HeaderAuthDep` / `verify_header_token` 仅验证服务调用凭据。Header API Key 不会产生用户身份，不能绕过普通用户接口的 session、CSRF 和资源归属检查。

```python
from fastapi import APIRouter, Depends
from api.core.deps import HeaderAuthDep, verify_header_token

router = APIRouter()

@router.get("/service-ping", dependencies=[Depends(verify_header_token)])
async def service_ping() -> dict[str, bool]:
    return {"ok": True}

@router.post("/service-call")
async def service_call(principal: HeaderAuthDep) -> dict[str, str]:
    return {"authentication": principal.scheme}
```

新增教学接口为 `GET /api/examples/auth-header/ping`、`POST /api/examples/auth-header/echo`（JSON `{"message":"hello"}`）。在 dev/local 配置密钥后，通过 `X-Api-Key` 调用即可，无需 session Cookie 或 CSRF；即使携带旧 Cookie，也不会读取 Redis session。这两个示例独立挂载，生产环境返回 404。原有会话数据示例继续执行用户及归属校验。其他新增的纯 Header 路由可按 `configure_auth_sessions()` 的明确路径范围排除 session 加载；不要把需要用户身份的路由加入排除范围。

密码哈希参考 [FastAPI 官方说明](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) 和 [pwdlib API](https://frankie567.github.io/pwdlib/reference/pwdlib/)。

## 身份、租户与会话边界

`auth_user` 保存稳定的本地 UUID、单一 `tenant_id` 和账号状态；`auth_identity` 以 `(provider, subject)` 唯一映射外部身份。Google `sub`、钉钉 `unionId` 用来识别账号，同邮箱不会自动合并。首次注册由服务端 `default_tenant_id` 分配租户，后续更改该默认值不会迁移已有用户。当前不提供租户切换、成员管理、管理员角色或账号合并接口；新增这些功能须验证成员关系并轮换会话。

浏览器 Cookie 只保存随机 session ID。会话由 **fastapi-redis-sdk** 的单个 `SessionMiddleware`、`SessionStore.rotate/revoke` 管理；Redis 只保留本地用户 ID、租户 ID、渠道、认证版本、CSRF token 等必要状态，不保存 Google/钉钉令牌。OAuth state 存 Redis，绑定浏览器会话，带过期时间，并通过 `GETDEL` 原子消费。Google 额外验证签名、issuer、audience、有效期、nonce、azp，并使用 PKCE S256。

每次认证请求回查用户和渠道状态。禁用账号、移除/禁用渠道、改变用户租户或增加 `auth_version` 都使旧 session 不再通过。Redis 故障返回 503，不降级为已登录；默认 `session_fail_closed=true`。退出仅在服务端成功撤销后清 Cookie，前端不会把退出失败伪装为成功。原项目的自定义 session 格式不兼容，迁移后需重新登录；此改动不复制来源项目的数据库或凭据。

`/agents`、`/conversations` 使用 `auth_resource_owner` 校验当前用户及租户归属，包括消息、turn、SSE、删除和列表分页。创建记录后才由服务端写入归属，不允许客户端自行认领。旧资源没有归属映射时默认不可访问；已有部署应核实历史所有者后单独补齐映射，不能按首次访问自动认领。资源与归属跨事务写入失败时可能产生不可访问的孤立记录，接口不会返回成功。

## API 与追踪

| 接口 | 用途 |
| --- | --- |
| `GET /api/auth/session` | 当前用户、渠道配置、已登录会话的 `csrf_token`；匿名返回 `authenticated=false` |
| `POST /api/auth/password/login` | 验证用户名密码并建立/轮换同一套 Redis session |
| `GET /api/auth/oauth/{provider}/start?return_to=/...` | Google / 钉钉授权跳转；只接受站内返回路径 |
| `GET /api/auth/oauth/{provider}/callback` | 一次性 state 校验、交换凭据、创建用户映射和轮换 session |
| `POST /api/auth/logout` | 撤销当前会话；需 `X-CSRF-Token` |

受保护的 POST/PATCH/PUT/DELETE 必须携带当前 session 返回的 `X-CSRF-Token`。如请求带 `Origin`，须与 `frontend_url` 完全一致。用户和认证响应不缓存。

默认每个请求生成/回传 `Request-ID`，也可接受长度 ≤128 的合法外部 ID；重复或非法值会重新生成。`request_context.accept_request_id=false` 可强制服务端生成。`User-ID` / `Tenant-ID` 仅在认证成功后回传；请求中的这两个字段是可选一致性断言，不是凭据，不一致返回 403。客户端 `User-Code` / 请求体 `user_id` 不能替换登录身份。

启用现有 OTel 配置后，标准 `traceparent` / `tracestate` 延续当前 span，span 带 `request.id`、`user.id`、`tenant.id`。应用日志和请求完成日志自动带 `request_id`、`user_id`、`tenant_id`、trace/span ID；不记录 Cookie、OAuth code、token 或完整查询串。关闭 OTel 时只传播合法入站 trace context，并用 `incoming_trace_id` 明确标记，不伪造本地 span。访问日志中的外部 Request-ID 仅用于排查，不用于授权。

需要调用内部下游服务时使用 `api.core.request_context.outbound_context_headers()` 传播可信 ID 和 W3C 链路头。不要把这些身份字段发给无关第三方。可用 `[request_context]` 配置头名、是否接受外部 Request-ID、是否回传身份头、请求完成日志和总开关。

新增渠道时，在 `api/auth/providers/` 实现 `OAuthProvider`（或另建 OTP 协议）、添加强类型配置并注册到 `PROVIDER_REGISTRY`。业务路由和本地用户映射保持 provider 无关。手机号当前 `implemented=false`；配置 `enabled=true` 会被拒绝，未来接入短信发送、限流、验证码原子消费后再开放。

## 验证

```bash
# 仓库根目录：离线业务测试使用真实 SDK、中间件与 SQLite 事务。
uv run --no-sync pytest api/tests -q
# 可选：专用 Redis 服务上的真实 TTL、轮换、撤销验证，只使用随机测试前缀。
TEST_AUTH_REDIS_URL=redis://127.0.0.1:16389/0 uv run --no-sync pytest api/tests/test_auth_redis_integration.py -q
```

Google/钉钉端到端外部授权仍需部署环境的真实凭据和已登记回调地址。主应用关闭 SDK 的匿名偏好/session 管理教学路由，避免示例轮换绕过真实登录的绝对期限；其余访问会话数据的缓存示例也检查资源归属，批量请求逐项检查。独立测试应用可以注册隔离的示例 session，不得在主应用叠加两个 SessionMiddleware。

# API Redis 配置

项目默认使用 **FastAPI Redis SDK 0.9.0+**：业务路由直接从 `redis_fastapi` 导入 `AsyncRedisDep`，连接池由 SDK 的 `redis_lifespan` 创建和关闭。`RedisConfig` 继承 SDK 的 `RedisSettings`，使用其原生字段与校验。0.9.0 已正式提供 Sentinel 支持，见 [发布记录](https://github.com/redis/fastapi-redis-sdk/releases/tag/0.9.0) 与 [配置参考](https://redis.github.io/fastapi-redis-sdk/latest/api/configuration/#fields)。

目标 Redis 已部署且网络可达后，可修改配置并重启 API 切换以下三种模式，连接管理均由 SDK 完成。

| 模式 | `cluster` | `sentinel` | 连接目标 |
| --- | --- | --- | --- |
| 单机 | `false` | `false` | `host` / `port` 或 `url` |
| Sentinel 主从 | `false` | `true` | `sentinel_nodes` + `sentinel_master_name` |
| Cluster 分片 | `true` | `false` | `host` / `port` 或 `url`，作为入口节点 |

单机默认 `host="localhost"`、`port=6379`、`db=0`。Cluster 仅支持 DB 0；多键事务、Lua 等原子操作需要相关键处于同一个 hash slot。`cluster` 和 `sentinel` 不能同时启用。

SDK 0.9.0 的 Cluster 模式存在 `ssl=true` 参数转发问题。Cluster 使用 TLS 时，配置 `url="rediss://user:password@redis.example:6379/0"` 并保持 `ssl=false`，由 URL 启用 TLS；CA、客户端证书等选项可放在 URL 查询参数中。单机和 Sentinel 可以使用 `ssl=true`。

`AsyncRedisDep` 注入的对象本身就是 `redis-py` 异步客户端，需要原生命令时直接调用并复用同一个池。路由中不要关闭这个共享客户端；默认读取的字符串值是 `bytes`，需要文本时显式解码：

```python
from fastapi import APIRouter
from redis_fastapi import AsyncRedisDep

router = APIRouter()

@router.get("/cache/title")
async def read_title(redis: AsyncRedisDep) -> dict[str, str | None]:
    value = await redis.get("title")
    return {"title": value.decode("utf-8") if value is not None else None}
```

API 健康检查继续使用 `PING`。独立脚本也可按需直接使用 `redis.asyncio`，并自行通过 `async with redis.asyncio.Redis(...) as client:` 管理连接生命周期；API 内调用原生命令不需要另设后端开关。

## Sentinel 示例

将下列内容合并到运行目录的 `config.toml`，替换示例地址和密码：

```toml
[redis]
cluster = false
sentinel = true
sentinel_nodes = ["redis-a:26379", "redis-b", "redis-c:26379"]
sentinel_master_name = "mymaster"
sentinel_username = "default"
sentinel_password = "sentinel-password"
username = "default"
password = "redis-data-password"
db = 0
```

`sentinel_nodes` 是 `host[:port]` 字符串数组，省略端口时使用 `26379`。`sentinel_master_name` 默认 `mymaster`，必须与 Sentinel 的监控名称一致。`sentinel_username/password` 用于连接哨兵，`username/password` 用于连接 Redis 数据节点；未配置对应认证时可省略相应凭据。

哨兵模式忽略 `host/port`，禁止同时配置 `url`。客户端查询当前主节点后直接连接该数据节点，因此 API 必须能访问所有可能被提升为主节点的 Redis 地址。Redis 数据密码与 Sentinel 自身密码可以不同。[redis-py 连接说明](https://redis.io/docs/latest/develop/clients/redis-py/connect/)

相同配置也可以写入 `.env`；`REDIS_SENTINEL_NODES` 使用逗号分隔，SDK 0.9.0 不接受 JSON 数组字符串，TOML 中仍使用上面的字符串数组：

```dotenv
REDIS_CLUSTER=false
REDIS_SENTINEL=true
REDIS_SENTINEL_NODES=redis-a:26379,redis-b:26379,redis-c:26379
REDIS_SENTINEL_MASTER_NAME=mymaster
REDIS_SENTINEL_USERNAME=default
REDIS_SENTINEL_PASSWORD=sentinel-password
REDIS_USERNAME=default
REDIS_PASSWORD=redis-data-password
REDIS_DB=0
```

切入哨兵模式时，删除所有配置来源中的 `REDIS_URL` / `redis.url`。切回单机时设置 `REDIS_SENTINEL=false`、`REDIS_CLUSTER=false`，再填写 `REDIS_HOST` / `REDIS_PORT`；切入 Cluster 时设置 `REDIS_SENTINEL=false`、`REDIS_CLUSTER=true`、`REDIS_DB=0`，再填写入口地址。

## 配置优先级与生效

优先级为：**进程环境变量 > 运行目录 `.env` > TOML 配置 > 字段默认值**。TOML 按 `config.toml`、`config.dev.toml`、`config.staging.toml`、`config.prod.toml`、`config.local.toml`、`config.dev.local.toml`、`config.staging.local.toml`、`config.prod.local.toml` 的顺序合并，后面的同名顶层表整体覆盖前面的表（例如整个 `[redis]`）；当前不会根据 `APP_ENV` 自动过滤这些文件。不要在高优先级来源中残留旧模式配置。单机和 Cluster 中，`url` 内的连接参数优先于对应独立字段。

应用启动时，将按上述优先级解析的项目配置写入 SDK 配置，再进入 SDK lifespan。SDK 配置在同一进程内共用；修改后需要重启 API，不应在请求处理中修改配置。同一进程中的多个应用也共用这套 SDK 配置。

`AsyncRedisDep` 本身不读取 TOML。项目的完整路径是：`Settings` 读取 TOML → `settings.redis` → `configure_redis_sdk()` 写入 SDK 缓存配置 → `redis_lifespan(app)` 创建连接池 → 路由通过 `AsyncRedisDep` 取得该连接池的客户端。

这个顺序由 [应用 lifespan](src/api/core/lifespan.py) 保证，配置传递见 [configure_redis_sdk](src/api/core/cache.py)。只复制路由中的 `from redis_fastapi import AsyncRedisDep`，或只给一个新应用注册 SDK 自带的 lifespan，都不会自动接入本项目的 TOML。应使用 `api.main.create_app()`，或为新应用注册 `api.core.lifespan.lifespan`。

Compose 环境变量变化需要**重建容器**，例如在仓库根目录执行：

```bash
docker compose --env-file deploy/.env up -d --no-deps --force-recreate api
```

`docker compose restart api` 不会重新载入容器环境变量。当前根 Compose 仍会运行内置单机 Redis，并在 `environment` 中固定部分 Redis 字段；这些值会覆盖 `env_file` 的同名字段。连接外部 Redis 时还需检查最终 Compose 配置，相关部署约定见 [部署文档](../deploy/README.md)。

模式切换只改变 API 的连接方式，不会创建 Redis 集群或迁移数据；已有键、会话及 TTL 需要在切换目标之前单独处理。Sentinel 的“3+3”通常指 1 主 2 从加 3 个哨兵，Cluster 的“3 主 3 从”则是六个数据节点。

## 业务日志

统一配置由 `setup_logging()` 和 `setup_telemetry()` 管理。Endpoint/service 只声明模块 logger，无需从 `__init__.py` 导入全局对象，也不要重复添加 handler：

```python
import logging

logger = logging.getLogger(__name__)

logger.info(
    "订单创建成功 order_id=%s",
    order_id,
    extra={"otel.event.name": "order.created", "order.id": order_id},
)
```

消息供人工阅读，`extra` 保留可检索业务字段和数值类型。控制台输出时间、级别、模块位置、trace/span ID 与业务字段；OTLP 使用原生日志结构，Loki 中无需再对消息执行 `| json`。异常在负责处理的一层使用 `logger.exception("订单创建失败", extra={"otel.event.name": "order.create_failed"})`，保留完整堆栈；避免各层重复记录，也不要加入请求体、令牌或完整配置。

开启 `OTEL_ENABLED=true` 后默认导出 `INFO` 及以上日志，`OTEL_LOGS_ENABLED=false` 只关闭日志导出，`OTEL_LOGS_LEVEL` 设置远端最低级别；源 logger 自身的级别仍会先过滤日志。终端和 `docker logs` 的文本输出继续保留。本机与 Docker 都向 Alloy 主动推送，采集端配置、Docker 去重和 Grafana 查询见 [日志接入与验证](../deploy/observability/README.md#alloy-与-loki-日志接入)。

## OTel 追踪与日志示例

[routes/examples/otel.py](src/api/routes/examples/otel.py) 演示业务父子 span、属性与事件、异常记录、日志关联和追踪头传播，接口仅在 `APP_ENV=dev/local` 可用。复用应用已有的 SDK 和 HTTP 自动埋点；路由不创建 provider 或 exporter，也不访问数据库或 Redis。

在 API 配置中启用以下选项，将 collector 地址替换为实际可达地址，再重启 API（应用启动仍需原有数据库和 Redis 配置）：

```dotenv
OTEL_ENABLED=true
OTEL_TRACES_ENABLED=true
OTEL_LOGS_ENABLED=true
OTEL_LOGS_LEVEL=INFO
OTEL_FASTAPI_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
```

```bash
# 成功链路：HTTP SERVER span → examples.otel.trace → examples.otel.work。
curl http://localhost:8000/api/examples/otel/trace
# 返回 503，业务父子 span 均记录异常并标记 ERROR。
curl -i 'http://localhost:8000/api/examples/otel/trace?fail=true'
# 继承上游 trace，并展示由当前 span 生成的出站追踪头；不实际发起请求。
curl http://localhost:8000/api/examples/otel/propagation \
  -H 'traceparent: 00-12345678901234567890123456789012-1234567890123456-01'
```

响应的 `trace.trace_id` 可用于 Tempo 查询，`trace.span_id` 对应业务 span；业务日志由现有过滤器附加相同标识。`sampled` / `recording` 不代表导出已成功。未开启 SDK 时示例仍可执行，没有有效上下文的 ID 返回 `null`；未采样的上下文仍可携带有效 ID。完整配置和查询步骤见 [OTel 接入与验证](../deploy/observability/README.md)，手动埋点 API 见 [OpenTelemetry Python 文档](https://opentelemetry.io/docs/languages/python/instrumentation/)。

## Agents API

`/api/agents` 提供会话、turn、执行历史和 SSE 输出，首个执行后端使用 `openai-agents`。应用自有 `AgentBackend` / `SessionStore` 协议隔离 SDK、存储和 HTTP，可注册其他 agent backend。配置、调用示例、扩展方式及执行边界见 [Agents 层](agents.md)。
