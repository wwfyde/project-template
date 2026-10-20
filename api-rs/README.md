# api-rs

基于 Axum 0.8、SeaORM 2.0.4 stable 和 PostgreSQL 的 Rust API。需要 Rust 1.94 或更新版本；SeaORM 使用 SQLx 0.9，项目不再直接依赖旧版 SQLx。

## 启动

```sh
cd api-rs
cp config.example.toml config.local.toml
# 修改 config.local.toml 中的数据库连接、API key 和 JWT secret。
cargo run --bin api_rs -- --port 3000
```

监听端口优先级为 `--port` > `API_PORT` > `3000`。`API_PORT` 也可写入 `.env.local` 或 `.env`，例如：

```sh
API_PORT=8000 cargo run --bin api_rs
```

文档入口为 `/docs`，OpenAPI 为 `/api-docs/openapi.json`，健康检查为 `/health`。Swagger UI 使用 vendored 资源，构建时不再单独从 GitHub 下载前端资源。

配置优先级从低到高为 `config.toml`、`config.{APP_ENV}.toml`（仅在设置 APP_ENV 时加载）、`config.local.toml`、环境变量。环境变量采用双下划线分层，例如 `POSTGRES__PASSWORD`、`APP__API_KEY`、`APP__JWT_SECRET`。进程环境变量优先于 `.env.local`，后者优先于 `.env`。启动不需要 DEMO；API key 和 JWT secret 必填，没有默认 `admin` 密钥。

数据库表名使用单数，实体映射现有 `public` schema。服务不会自动创建或同步生产数据库结构；运行前须准备与实体一致的数据库表。连接池统一由 SeaORM 管理，收到 Ctrl+C / SIGTERM 后停止接收请求并关闭连接池。

`repositories` 按 `in_memory`、`sqlx`、`orm` 三种技术组织，每种技术都实现 user、student、todo，共九个仓储实现。`models` 只定义数据类型和 trait，仓储接口直接返回 `anyhow::Result<T>`；领域类型和接口由 `repositories` 根模块重新导出，具体实现从技术模块导入，例如 `repositories::orm::SeaOrmUserRepository`。旧的 `repositories::user/student/todo` 路径不再保留。错误分类和共享校验留在仓储层内部，保留底层错误来源；服务通过类型 downcast 判断已知错误，不匹配错误文本。两种数据库后端可复用同一个 PostgreSQL 连接池；目录、导入示例及契约测试见 [仓储说明](src/repositories/README.md)。

## SeaORM v2

- 使用 `#[sea_orm::model]` dense entity 格式；非空外键使用 `BelongsTo<Entity>`，集合关系使用 `HasMany<Entity>`。
- 关系数据属于宏生成的 `ModelEx`，普通 `Model` 仅含数据库列。
- 唯一列查询使用生成的 `find_by_email`，其他条件使用强类型 `COLUMN`。
- 创建时显式写入 UUID v7 与时间戳；通过 ActiveModel 仅修改可编辑字段，仓储更新使用单次 UPDATE RETURNING，保留创建时间。
- 删除 SQLx 0.8、RC 版本声明、旧 HasOne belongs-to 写法、重复配置入口和未使用的调试代码，不启用旧 serial 主键兼容选项。

参考：[2.0.4 发布记录](https://github.com/SeaQL/sea-orm/releases/tag/2.0.4)、[SeaORM 2.0 稳定版说明](https://www.sea-ql.org/blog/2026-07-27-sea-orm-2.0/)、[官方迁移指南](https://www.sea-ql.org/blog/2026-01-12-sea-orm-2.0/)。

## 接口变化

- 用户接口为 `GET/POST /api/users`、`GET /api/users/{id}` 和 `GET /api/users/me`；同时要求 `X-Api-Key` 和 Bearer JWT。已移除错误调用 item 处理器的用户 PUT/DELETE 路由，返回 405。
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
