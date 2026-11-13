# api-rs

基于 Axum 0.8、SeaORM 2.0.4 stable 和 PostgreSQL 的 Rust API。需要 Rust 1.94 或更新版本；SeaORM 使用 SQLx 0.9，项目不再直接依赖旧版 SQLx。

## 启动

```sh
cd api-rs
cp config.example.toml config.local.toml
# 修改 config.local.toml 中的数据库连接、API key 和 JWT secret。
cargo run --bin api_rs -- --port 3000
```

监听端口优先级为 `--port` > 进程环境变量 `API_PORT` > 合并后的 `app.port`（默认 `8000`）。推荐通过 `APP_PORT` 或 TOML 的 `[app].port` 配置；dotenv 中的旧 `API_PORT` 仍作为兼容输入，例如：

```sh
API_PORT=8000 cargo run --bin api_rs
```

文档入口为 `/docs`，OpenAPI 为 `/api-docs/openapi.json`，健康检查为 `/health`。Swagger UI 使用 vendored 资源，构建时不再单独从 GitHub 下载前端资源。

配置通过 `config + serde` 加载，字段及默认值与 Python `Settings` 对齐。优先级从低到高为字段默认值、TOML、dotenv、进程环境变量。相对文件路径以启动工作目录为基准，建议在 `api-rs/` 中运行。

单字段默认值通过 `Settings::from_config()` 中的 `set_default()` 集中设置，嵌套类型保留各自的 `Default` 实现。常规使用 `load_config()`；代码构造 `config::Config` 时，通过 `Settings::from_config(config)` 应用相同默认值和校验，直接调用 `try_deserialize::<Settings>()` 不会补齐这些加载器默认值。

TOML 依次读取 `config.toml`、`config.dev.toml`、`config.staging.toml`、`config.prod.toml`、`config.local.toml`、`config.dev.local.toml`、`config.staging.local.toml`、`config.prod.local.toml`。后读文件的同名顶层表整体替换前表，与 Python 行为一致。dotenv 采用相同后缀顺序，从 `.env` 到 `.env.prod.local`，后读变量覆盖先读变量。所有文件均可省略，`APP_ENV` 不筛选文件。

环境变量支持 Python 的单下划线形式，例如 `APP_PORT`、`POSTGRES_POOL_SIZE`、`REQUEST_CONTEXT_ACCEPT_REQUEST_ID`；识别完整顶层字段后只展开一层。更深的对象使用 JSON，例如 `PROVIDERS_OPENAI='{"base_url":"https://api.openai.com/v1","api_key":"...","model":"..."}'`。原 Rust 的双下划线形式仍可用，例如 `POSTGRES__PASSWORD`、`APP__API_KEY`、`PROVIDERS__OPENAI__MODEL`。

`repo_type` 位于顶层，默认 `memory`，枚举还包括 `postgres/mongodb/mysql/redis`；该字段的可接受值不代表 Rust 已提供相应存储实现。PostgreSQL 的 `host/port/username/password/db` 必填，`db` 兼容 `database`，`pool_size` 默认 `30`。当前 Rust 服务仍连接 PostgreSQL；API key、JWT secret 和 token 有效天数通过兼容字段 `app.api_key/app.jwt_secret/app.access_token_expire_days` 提供，启动时校验，没有默认认证密钥。

`redis` 省略时使用默认配置，显式 JSON `null`（例如 `REDIS=null`）表示禁用；TOML 不支持 `null`。`oss/nacos/api_prefix/proxy_url` 与各 LLM 供应商均可省略。供应商别名为 `qwen → dashscope`、`ark → volcengine`、`gemini → google`；每个已配置供应商必须提供 `base_url/api_key/model`。`models` 接受完整的字符串列表或模型对象列表，不接受二者混合。独立 `extra` 配置只从 `config/extra.toml` 读取。

Rust 加载器明确支持 `REDIS=null` 禁用和 `TOOLS` 环境变量的 JSON 解码；这两项是对 Python 环境变量解析行为的扩展。普通字符串配置和密钥保留原文，包括空串、数字字符串及字面值 `null`。

数据库表名使用单数，实体映射 `public` schema。服务连接 PostgreSQL 后、监听 HTTP 前执行 entity-first 结构同步；同步失败会阻止服务启动。连接池统一由 SeaORM 管理，最大连接数取 `postgres.pool_size`，收到 Ctrl+C / SIGTERM 后停止接收请求并关闭连接池。

`repositories` 按 `memory`、`sqlx`、`orm` 三种技术组织，每种技术都实现 user、student、todo，共九个仓储实现。仓储接口直接返回 `anyhow::Result<T>`；领域类型和接口由 `repositories` 根模块重新导出，具体实现从技术模块导入，例如 `repositories::orm::SeaOrmUserRepository`。用户写入采用不含自增 UID 的 `UserWrite`，保存后返回完整 `User`。错误分类和共享校验留在仓储层内部，保留底层错误来源；服务通过类型 downcast 判断已知错误，不匹配错误文本。两种数据库后端可复用同一个 PostgreSQL 连接池；目录、导入示例及契约测试见 [仓储说明](src/repositories/README.md)。

## SeaORM v2

### Entity-first 自动同步

独立函数 `core::db::sync_schema(&db).await?` 使用 SeaORM 2 的 `schema-sync`，在一个事务内同步已注册的 11 个业务实体：缺失的表、列、外键会自动创建，唯一键按实体声明对齐。`alembic_version` 等迁移元数据不参与同步。新增实体时，在该函数中追加 `.register(entities::新模块::Entity)`。

`user.id` 保留 UUID 主键；`uid` 为正数 `BIGINT` 自增身份并独立唯一，`username` 也有唯一约束。用户名按精确值比较，允许多个 `NULL`。昵称统一使用可空的 `nickname`；`locale` 非空、默认 `zh-CN`，允许 `zh-CN/en-US/ja-JP`。当前以清库重建后的结构为准，不保留旧昵称字段的迁移或回填逻辑。

同步不会自动删除列、重命名列或修改已有列的类型；这些变更以及需要定制回填的非空字段仍应使用显式迁移。当前启动流程只调用 entity-first 同步，不执行下面的版本迁移。

在空的、可丢弃的 PostgreSQL 数据库验证首次建表、重复同步和用户字段约束：

```sh
API_RS_SCHEMA_TEST_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/api_rs_schema_test' \
  cargo test -p api_rs --bin api_rs core::db::tests::entity_first_schema_sync -- --ignored
```

### 显式数据库迁移

保留的版本迁移将基础用户表补齐为当前用户字段与约束；它不负责旧字段兼容。空库启动优先使用 entity-first，已经完成同步的表不需要再执行该迁移。迁移入口使用 SeaORM CLI 的 `DATABASE_URL`（或 `-u` 参数），不读取应用的 TOML 配置。在工作区根目录运行：

```sh
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DATABASE'
cargo run -p api_rs --bin migration -- status
cargo run -p api_rs --bin migration -- up
# 回滚最近一次迁移（会删除该迁移新增字段中的数据）
cargo run -p api_rs --bin migration -- down -n 1
```

`m20261111_090526_modify_table` 要求已存在包含 `id/email/username` 的基础 `public."user"` 表，补充 `uid`、`nickname`、`locale` 及对应约束。用户名已重复时，添加唯一约束会失败，不会自动替用户改名。迁移版本由 `seaql_migrations` 记录，与 entity-first 同步独立。

迁移回归测试需要空的、可丢弃的 PostgreSQL 数据库，独立于应用数据库配置：

```sh
API_RS_MIGRATION_TEST_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/api_rs_migration_test' \
  cargo test -p api_rs --test user_migration -- --ignored
```

### 实体与查询

- 使用 `#[sea_orm::model]` dense entity 格式；非空外键使用 `BelongsTo<Entity>`，集合关系使用 `HasMany<Entity>`。
- 关系数据属于宏生成的 `ModelEx`，普通 `Model` 仅含数据库列。
- 唯一列查询使用生成的 `find_by_email`，其他条件使用强类型 `COLUMN`。
- 创建时显式写入 UUID v7 与时间戳；通过 ActiveModel 仅修改可编辑字段，仓储更新使用单次 UPDATE RETURNING，保留创建时间。
- 删除 SQLx 0.8、RC 版本声明、旧 HasOne belongs-to 写法、重复配置入口和未使用的调试代码，不启用旧 serial 主键兼容选项。

参考：[2.0.4 发布记录](https://github.com/SeaQL/sea-orm/releases/tag/2.0.4)、[SeaORM 2.0 稳定版说明](https://www.sea-ql.org/blog/2026-07-27-sea-orm-2.0/)、[官方迁移指南](https://www.sea-ql.org/blog/2026-01-12-sea-orm-2.0/)。

## 初始化与创建用户

启动服务后，使用配置中的 `app.api_key`（或 `APP_API_KEY` 环境变量）调用 `POST /api/users`。首次初始化和后续新建用户使用同一个接口，只需 `X-Api-Key`，无需 JWT。接口返回 `201`；缺少或错误的 API key 返回 `401`，重复邮箱返回 `409`。

```sh
API_KEY='替换为服务配置中的 API key'
curl --fail-with-body http://localhost:8000/api/users \
  -H "X-Api-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"replace-with-your-password","email":"alice@example.com"}'
```

服务自动生成 UUID `id` 和自增 `uid`，密码通过 bcrypt 加密后保存，响应不包含密码。创建的用户默认启用，`is_superuser=false`；省略昵称和语言时，分别使用 `nickname=NULL` 与 `locale=zh-CN`。这两个字段会持久化并随用户信息返回；UID 不接受客户端指定。API key 是允许创建用户的服务凭据，应由受信任的调用方保管。

随后通过用户名和密码登录获取 JWT：

```sh
curl --fail-with-body http://localhost:8000/api/auth/token \
  --data-urlencode 'username=alice' \
  --data-urlencode 'password=replace-with-your-password'
```

把响应中的 `access_token` 用于用户查询接口，同时提供 API key：

```sh
TOKEN='替换为 access_token'
curl --fail-with-body http://localhost:8000/api/users/me \
  -H "X-Api-Key: $API_KEY" \
  -H "Authorization: Bearer $TOKEN"
```

## 接口变化

- `POST /api/users` 仅要求 `X-Api-Key`；重复邮箱或用户名返回 `409`。`GET /api/users`、`GET /api/users/{id}` 和 `GET /api/users/me` 同时要求 `X-Api-Key` 和 Bearer JWT。已移除错误调用 item 处理器的用户 PUT/DELETE 路由，返回 405。
- `POST /api/auth/token` 接收 URL encoded username/password，响应的 `expires_in` 是有效秒数。未启用的用户不能登录；内部数据库错误返回 500，不回传错误详情。
- item 接口要求 `X-Api-Key`。POST 和 PUT 使用独立输入 DTO，必填 `title`、`config`、`owner_id`；`description`、`description2` 可空。客户端不再提交 `id`、`created_at`、`updated_at`，未知字段返回 422。
- PUT 完整替换可编辑字段，省略或传 null 的描述字段会清空；服务维护 ID、创建时间和更新时间。

```json
{
  "title": "示例",
  "description": null,
  "description2": "补充说明",
  "config": { "enabled": true },
  "owner_id": "019a0123-4567-7890-abcd-0123456789ab"
}
```

## 验证

在工作区根目录运行：

```sh
cargo fmt -p api_rs -- --check
cargo check -p api_rs --all-targets --locked
cargo test -p api_rs --all-targets --locked
cargo clippy -p api_rs --all-targets --locked -- -D warnings
```

默认回归测试无需本地配置、PostgreSQL 或 Redis：三组 SeaORM 仓储契约使用真实内存 SQLite，三组内存仓储运行相同的 CRUD 契约；HTTP 测试直接调用 Axum Router，覆盖登录与当前用户、item CRUD、JWT、OpenAPI 和 CORS。SQLite 仅作为测试依赖；生产使用 PostgreSQL。SQLx / SeaORM 六个数据库实现另有可显式运行的真实 PostgreSQL 公共契约测试，测试名仍为 `repositories::tests::postgres_repository_contracts`，运行方式见仓储说明。

## 架构

文件、资产、文档和知识库的领域对象按上下文组织在 `src/models/`，接口表示位于 `src/schemas/`。领域实体通过构造和行为方法保护不变量，不依赖 ORM 或 HTTP；库入口导出 `models`、`schemas` 和现有 `entities` 供调用及独立验证，服务入口沿用现有模块组织。

对象关系、版本与来源追溯、索引生命周期及拟议单数表映射见[数据模型文档](../docs/data-model.md)，业务用语见[术语表](GLOSSARY.md)。这些新对象目前提供领域规则和 `utoipa` schema，尚未新增文件、资产、文档或知识库的 HTTP CRUD、仓储实现及数据库表；schema 已纳入现有 `/docs` 和 `/api-docs/openapi.json`，接口说明由代码生成。

- DDD+分层架构

  - 领域层（Domain Layer）

    - 领域模型（Entities）：表示业务对象和概念，包含业务逻辑和规则。
    - 领域服务（Domain Services）：封装复杂的业务逻辑，通常涉及多个实体。
    - 仓储接口（Repositories）：定义数据访问接口，隐藏数据存储细节。

  - 应用层（Application Layer）

    - 应用服务（Application Services）：协调领域对象以完成特定的用例，处理事务管理。
    - DTO（Data Transfer Objects）：用于在应用层和表示层之间传输数据。

  - 表示层（Presentation Layer）

    - 控制器（Controllers）：处理用户请求，调用应用服务，并返回响应。
    - 视图模型（View Models）：用于表示层的数据结构，适合前端展示。

  - 基础设施层（Infrastructure Layer）

    - 数据库访问实现（Database Access Implementations）：具体的仓储实现，负责与数据库交互。
    - 外部服务集成（External Service Integrations）：与外部系统或服务的集成代码。
    - 通用工具和库（Common Utilities and Libraries）：提供跨层使用的通用功能。
