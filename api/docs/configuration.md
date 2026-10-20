# 配置参考

本页区分代码默认值、示例值和部署覆盖值。字段及校验以 [Settings](../src/api/core/config.py) 为准，操作步骤见 [operations.md](operations.md)。
认证配置见 [auth_config.py](../src/api/core/auth_config.py)，观测配置见 [telemetry_config.py](../src/api/core/telemetry_config.py)。

## 1. 配置从哪里读取

`get_settings()` 使用进程内缓存，模块导入时创建全局 `settings`。
优先级由高到低：

1. 显式传给 `Settings(...)` 的参数，主要供测试或代码构造。
2. 进程环境变量。
3. 工作目录中的 dotenv 文件。
4. 工作目录中的 TOML 文件。
5. 模型字段默认值。

`file_secret_settings` 没有加入当前来源列表，因此不会自动从 secret 目录读取字段。
部署 secret 需要通过既有环境变量或受保护的配置文件注入。
配置更改后重启进程；不要在请求处理中修改共享 `settings` 或 Redis SDK 的配置。

dotenv 文件按以下顺序读取，后面的同名变量覆盖前面的：

```text
.env → .env.dev → .env.staging → .env.prod
     → .env.local → .env.dev.local → .env.staging.local → .env.prod.local
```

TOML 文件的顺序：

```text
config.toml → config.dev.toml → config.staging.toml → config.prod.toml
            → config.local.toml → config.dev.local.toml
            → config.staging.local.toml → config.prod.local.toml
```

当前不会根据 `APP_ENV` 筛选文件；即使 `APP_ENV=dev`，存在的 `config.prod.local.toml` 仍会参与加载。
后读入 TOML 的同名顶层表整体覆盖先前表，而非逐个深层字段叠加。
例如晚文件只写 `[auth.password] enabled=true`，也会替换先前文件整个 `auth` 表；未重新提供的其他字段回到默认值或由更高优先级来源补齐。

`extra` 是独立的 `ExtraSettings`，当前只读取 `config/extra.toml`，不能推断它采用主配置的环境变量优先级。
所有相对文件路径以工作目录为基准；常规运行统一使用 `api/`。
`project_dir` 指向 API 包目录，默认 `base_dir` 是工作目录，`data_dir`、`temp_dir`、`static_dir` 从默认工作目录派生。
单独覆盖 `base_dir` 不会自动重新计算其他路径，需显式配置实际要改变的目录。

## 2. 环境变量映射

嵌套分隔符为 `_`，最多展开一层：先识别完整顶层字段前缀，再将余下部分作为其直接子字段名，子字段名内的下划线保留。

| 配置字段 | 环境变量写法 |
| --- | --- |
| `app.env` | `APP_ENV=prod` |
| `postgres.pool_size` | `POSTGRES_POOL_SIZE=30` |
| `redis.session_idle_ttl` | `REDIS_SESSION_IDLE_TTL=1800` |
| `auth.providers` | `AUTH_PROVIDERS='["google","password","dingtalk","phone"]'` |
| `auth.google` | `AUTH_GOOGLE='{"enabled":true,"client_id":"...","client_secret":"...","redirect_uri":"https://app.example.com/api/auth/oauth/google/callback"}'` |
| `auth.password` | `AUTH_PASSWORD='{"enabled":true}'` |
| `providers.openai` | `PROVIDERS_OPENAI='{"base_url":"https://api.openai.com/v1","api_key":"...","model":"..."}'` |
| `request_context.accept_request_id` | `REQUEST_CONTEXT_ACCEPT_REQUEST_ID=false` |

`AUTH_GOOGLE_CLIENT_ID` 不会映射为 `auth.google.client_id`，使用上表的渠道 JSON。
顶层名称本身含 `_` 也会按完整字段名识别，因此 `REQUEST_CONTEXT_ACCEPT_REQUEST_ID` 可以正常映射。
完整对象也可通过 `AUTH`、`PROVIDERS`、`POSTGRES`、`REQUEST_CONTEXT` 等 JSON 环境变量传入。
Redis Sentinel 是特殊字段：`REDIS_SENTINEL_NODES=redis-a:26379,redis-b:26379` 使用逗号分隔；TOML 使用字符串数组。

顶层 `Settings` 忽略未知字段，不代表这些字段具有功能。
例如示例文件的 `cloud_provider`、`object_storage_provider`、`model_providers` 不是当前 `Settings` 声明的选择开关。
`auth`、`agents` 等严格模型会拒绝未知字段；新增设置应先定义模型、消费路径与验证。

## 3. 应用与目录

| 字段 | 代码默认值 | 影响 |
| --- | --- | --- |
| `app.name` | `api` | 配置中的应用名称 |
| `app.env` | `dev` | `dev/prod/local`；控制文档、示例与生产认证校验 |
| `app.debug` | `true` | 配置值；不能据此推断所有组件都开启调试 |
| `app.port` | `8000` | `uv run api` 的监听端口 |
| `app.log_level` | `INFO` | 应用日志初始级别 |
| `repo_type` | `in-memory` | 部分业务存储选择，见下节 |
| `httpx_timeout` | `60` | 被相应 HTTP/agent 适配器采用的超时秒数 |
| `proxy_url` | `None` | 使用该配置的外部 HTTP 客户端代理 |
| `data_dir` | 工作目录下 `data/` | 本地文件存储与 `/api/files` 挂载 |

`config.example.toml` 把 `app.name` 设为 `Kayn API`、`httpx_timeout` 设为 180，并提供本地代理；这些都是示例覆盖。
`just api` 和 `uv run dev` 有各自端口语义，不统一受 `app.port` 控制，见 [operations.md](operations.md)。
`APP_ENV=prod` 关闭 `/docs`、`/redoc`，当前不会关闭 `/openapi.json`。
`api_prefix` 虽在配置中声明，主应用路由实际挂载为 `/api`，不能靠它改 API 前缀。

## 4. PostgreSQL 与业务存储

`postgres.host/port/username/password/database` 必填，没有可用的代码默认数据库或凭据；`pool_size` 默认为 30。
DSN 由 `URL.create("postgresql+psycopg", ...)` 生成并处理密码编码，不需要手工拼接。
`postgres_dsn` 包含真实密码，不能直接写入日志或诊断输出。

| 连接层 | 使用配置与生命周期 |
| --- | --- |
| 运行时 SQLAlchemy | [core/db.py](../src/api/core/db.py) 创建异步 engine，`pool_size`、`max_overflow=60`、`pool_recycle=3600`、`pool_pre_ping=true`；lifespan 关闭 engine |
| Alembic | [alembic/env.py](../alembic/env.py) 使用同一 DSN 单独建 engine，`NullPool`，迁移结束关闭 |

`PostgresDep` 和 `AsyncSessionLocal` 共享运行时 engine，不是各自独立的数据库配置。
认证仓库和资源归属始终使用 PostgreSQL；`repo_type` 不会把它们切换为内存实现。
Conversations 在 `repo_type=postgres` 时持久化，否则当前路由走内存分支；Agents 只接受 `in-memory` 或 `postgres`。
虽然配置枚举还允许 `mongodb/mysql/redis`，当前没有对应 Agents store，使用时返回 `unsupported_store`。
新部署需要持久化业务数据时显式设置 `REPO_TYPE=postgres`，也要执行迁移。
数据所有权、约束与迁移边界见 [data-schema.md](data-schema.md)。

## 5. Redis 与 session

项目 `RedisConfig` 继承安装的 `redis_fastapi.RedisSettings`，仅覆盖 session Cookie 名称和失败策略等项目默认值。
嵌套 `RedisConfig` 不自行重读环境：主 `Settings` 先解析，随后 [configure_redis_sdk()](../src/api/core/cache.py) 将结果写入 SDK 缓存配置。
SDK lifespan 管理应用级连接池；同一进程多个 app 共用 SDK 配置。

| 字段 | 当前代码/安装 SDK 默认值 | 说明 |
| --- | --- | --- |
| `host/port/db` | `localhost/6379/0` | 单机默认目标 |
| `url` | `None` | 单机、Cluster 时优先于独立连接字段 |
| `cluster/sentinel` | `false/false` | 两者互斥 |
| `session_cookie_name` | `project_template_session` | 项目覆盖 SDK 名称 |
| `session_cookie_https_only` | `true` | 示例 TOML 为本地 HTTP 显式改为 false |
| `session_cookie_same_site/path` | `lax` / `/` | 应用只接受 lax 与 `/` 或 `/api` |
| `session_idle_ttl` | `1800` 秒 | 空闲期限 |
| `session_absolute_ttl` | `28800` 秒 | 绝对期限 |
| `session_fail_closed` | `true` | 项目覆盖；Redis 故障不能当作认证成功 |

会话 TTL 在当前应用必须为正数，即使 SDK 通用配置允许零值也不能用于本应用。
安全操作轮换 session 时保留应用 payload 中的 `login_expires_at`，不会因此延长原始登录绝对期限。
session key 前缀组合为 `{auth.session_key_prefix}:{app.env}:sessions`；修改前缀、环境或目标 Redis 会改变会话命名空间。
Cookie 只携带随机 session ID；完整认证和 CSRF 行为见 [business-flows.md](business-flows.md)。

| 模式 | 必要配置 |
| --- | --- |
| 单机 | `cluster=false`、`sentinel=false`，配置 URL 或 host/port |
| Cluster | `cluster=true`、`sentinel=false`、`db=0`，入口节点必须能访问集群其他节点 |
| Sentinel | `sentinel=true`、`cluster=false`、`sentinel_nodes` 与 master 名称，移除 `url` |

数据节点凭据使用 `username/password`；Sentinel 自身使用 `sentinel_username/sentinel_password`。
切换模式不会创建集群或迁移已有键。更多连接、TLS、缓存字段沿用 SDK；本项目的配置测试见 [test_config.py](../tests/test_config.py)。

## 6. 用户认证与渠道

`auth.providers` 默认依次为 `google/password/dingtalk/phone`，它控制可选来源和展示顺序，不能重复或包含未注册渠道，必须保留 `google`。
“在列表中”“配置 enabled”“实际 ready”是不同条件：OAuth ready 需要 enabled 且 client ID、secret 非空。
API 返回渠道摘要中的 `enabled` 是已实现且 ready 的结果，不等于配置文件原始布尔值。

| 字段/渠道 | 默认值 | 行为 |
| --- | --- | --- |
| `google.enabled`、`dingtalk.enabled` | `true` | 无凭据仍不可登录 |
| `password.enabled` | `false` | 示例 TOML 显式开启；没有默认用户 |
| `phone.enabled` | `false` | 当前未实现，改 true 会被拒绝 |
| `allow_signup` | `true` | OAuth 新身份可创建用户；false 不禁止 CLI 创建用户 |
| `frontend_url` | `http://localhost:5173` | 必须是完整 origin，不包含子路径 |
| `oauth_state_ttl_seconds` | `600` | OAuth state 一次性有效期 |
| `reauth_max_age_seconds` | `300` | 敏感账号操作要求的近期验证窗口 |
| `session_key_prefix` | `project-template:auth` | session/state 等认证数据命名空间基础 |

生产有效登录渠道要求 HTTPS 前端及 OAuth callback；应用还单独要求 Secure Cookie。
Google scope 必须包含 `openid`；回调 URI 必须为合法 HTTP(S) URL，配置可通过不等于供应商已登记或网络可达。
密码限流默认用户名 10 次/300 秒、客户端 IP 50 次/300 秒，成功和失败都会计数。
IP 来自 ASGI 客户端地址；反向代理可信设置由服务器部署处理。

`default_tenant_id` 仅为兼容旧配置接受，默认 `"default"`，已不决定注册数据归属。
每个新用户创建独立 `structure=personal` 账户；`workspace` 是领域模型能力，不是更改默认 tenant 配置即可启用的页面功能。
旧 `auth.dingtalk.frontend_url` 会迁移到共享 `auth.frontend_url`，显式共享值优先；旧 `session_secret` 被忽略。

Header API Key 独立配置于 `auth.header`，默认关闭，Header 名为 `X-Api-Key`，`keys=[]`。
可设置最多 16 个密钥，每个 32–512 个可见 ASCII 字符，便于轮换；Header 名不能与身份、Cookie、CSRF、追踪头冲突。
它只作用于声明 Header 认证依赖的路由，不产生用户身份，也不能替代普通用户接口的 session。
接口边界见 [api-reference.md](api-reference.md)。

## 7. Agents、模型与文件

`agents.default_backend="openai-agents"`，`run_timeout_seconds=120`，`tracing_enabled=false`。
当前 [runtime.py](../src/api/agents/runtime.py) 仅在 `providers.openai` 存在时注册 OpenAI Agents backend；仅改 backend 名称不会安装其他实现。
模型配置复用 `providers.openai` 的 `base_url/api_key/model`，业务会话 store 复用 `repo_type`。
Agents SDK tracing 与应用 OTel 是独立链路，需要分别配置。

`providers` 默认没有任何供应商配置；`LLMConfig` 要求 `base_url`、`api_key`，其余模型字段按功能使用。
别名包括 `qwen → dashscope`、`ark → volcengine`、`gemini → google`；示例模型 ID 不代表当前账号可调用或服务端必然支持。
`oss` 默认 `None`；其 `prefix` 默认 `tmp`，兼容旧 `path_prefix`。
[core/storage.py](../src/api/core/storage.py) 的 `upload_image()` 当前写本地 `data_dir` 并返回 `/api/files/...`，不会仅因填写 OSS 配置自动切换实现。
`data_dir` 被静态服务挂载，不能把需要账号权限校验的私密文件当作普通公开文件写入。

## 8. 请求上下文与可观测性

`request_context` 默认开启，头名为 `Request-ID/User-ID/Tenant-ID`，默认接受合法外部请求 ID、回传已认证身份、记录请求完成日志。
`Tenant-ID` 当前承载 `account_id`；入站身份头只是与 session 的一致性断言，不能切换账号。
字段与校验见 [request_context.py](../src/api/core/request_context.py)。

OTel 默认 `enabled=false`、`sdk_disabled=false`；实际启用条件是前者 true 且后者 false。
协议只支持 `http/protobuf`，默认 collector 为 `http://localhost:4318`，各信号默认附加 `/v1/traces`、`/v1/metrics`、`/v1/logs`。
可单独覆盖三个 signal endpoint；认证使用 `exporter_otlp_headers`，不能把凭据放进 URL。
traces/metrics/logs、FastAPI、Postgres 子开关默认开启，但受总开关约束。
默认采样 `parentbased_traceidratio`，比例 1.0；metric interval 60000 ms；日志导出级别 INFO。
`/api/health` 默认从 FastAPI 遥测排除；Redis SDK 的两个 OTel 开关也会与应用总开关相与。
资源属性、collector 配置与查询方法见 [可观测性部署说明](../../deploy/observability/README.md)。

新增配置时同步模型、实际消费逻辑、示例、测试与本页；原则见 [development.md](development.md) 和 [architecture.md](architecture.md)。
返回 [文档导航](README.md)。
