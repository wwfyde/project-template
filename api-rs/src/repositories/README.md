# Repositories

仓储实现按技术组织为 `in_memory`、`sqlx`、`orm` 三个目录。每个目录实现 user、student、todo 三个领域接口，共九个实现；调用方使用领域模型和 `anyhow::Result<T>`，不依赖 ORM entity 或 SQLx row。

| 领域接口 | 内存实现 | SeaORM 2 实现 | SQLx 0.9 实现 |
| --- | --- | --- | --- |
| `UserRepository` | `InMemoryUserRepository` | `SeaOrmUserRepository` | `SqlxUserRepository` |
| `StudentRepository` | `InMemoryStudentRepository` | `SeaOrmStudentRepository` | `SqlxStudentRepository` |
| `TodoRepository` | `InMemoryTodoRepository` | `SeaOrmTodoRepository` | `SqlxTodoRepository` |

## 目录与边界

```text
src/
├── models/
│   ├── user.rs              # User / UserId / UserQuery / UserPage / UserSort / UserRepository
│   ├── student.rs           # NewStudent / Student / StudentRepository
│   └── todo.rs              # Todo / TodoRepository
└── repositories/
    ├── mod.rs               # 导出技术模块及领域模型、接口
    ├── error.rs             # crate 内部错误分类标记，不作为 trait 返回类型
    ├── in_memory/
    │   ├── mod.rs           # 导出三个 InMemory*Repository
    │   ├── user.rs
    │   ├── student.rs
    │   └── todo.rs
    ├── sqlx/
    │   ├── mod.rs           # 导出三个 Sqlx*Repository，统一 SQLx 错误映射
    │   ├── user.rs
    │   ├── student.rs
    │   └── todo.rs
    ├── orm/
    │   ├── mod.rs           # 导出三个 SeaOrm*Repository，统一 SeaORM 错误映射
    │   ├── user.rs
    │   ├── student.rs
    │   └── todo.rs
    ├── tests.rs             # 共用仓储契约测试
    └── README.md
```

`models` 只定义数据类型和 trait，仓储方法直接返回 `anyhow::Result<T>`，不定义仓储错误类型或数据库校验逻辑。`repositories` 根模块重新导出用户、学生、待办的领域模型与 trait，以及 `UserQuery`、`UserPage`、`UserSort`；具体实现从 `repositories::in_memory`、`repositories::sqlx`、`repositories::orm` 导入。旧的 `repositories::user`、`repositories::student`、`repositories::todo` 路径已删除，不保留兼容别名。

`repositories/error.rs` 中的 `RepositoryError` 是 `pub(crate)` 的内部分类标记，只有 `NotFound`、`Conflict`、`InvalidInput`，不出现在 trait 签名中，也不作为公开 API 导出。后端将已知驱动错误通过 `anyhow::Error::context(marker)` 添加分类并保留原始来源；未知错误直接通过 anyhow 传播，没有额外的 `Database` 包装。应用服务使用 `downcast_ref::<RepositoryError>()` 判断分类，不匹配错误文本。

这种组织适合在基础设施层集中维护同一后端的连接和错误映射。代价是同一业务的仓储变更需要检查三个技术目录，因此使用共同契约验证行为一致。trait 仍按业务领域划分，应用服务只依赖 trait，具体实现由组装入口选择；这次调整仅限仓储基础设施，不将整个项目改为技术优先。

## 公共行为

- 三组接口均有 `find_all`、`find_by_id`、`update`、`delete_by_id`。user 新增记录使用 `insert`，已移除旧 `create` 名称；student / todo 保留 `create`。user 另有 `find_many`、`find_by_email`、`save`、`search` 和 `exists_by_id`。`exists_by_id` 返回 `anyhow::Result<bool>`，trait 提供复用 `find_by_id` 的默认实现，当前三个用户仓储均覆盖为存在性检查，避免加载完整用户。
- `find_all` 按 ID 升序返回；查询不到单条记录返回 `Ok(None)`，更新或删除不存在的记录返回包含 `NotFound` 标记的 anyhow 错误。
- 唯一键冲突标记为 `Conflict`；无效仓储输入标记为 `InvalidInput`。数据库错误映射分别位于 `orm/mod.rs` 和 `sqlx/mod.rs`，保留底层错误来源。
- `update` 更新所有可编辑字段，`Option::None` 表示清空该字段，在数据库中写入 SQL NULL；不会修改 ID 或 `created_at`。user / todo 的 `updated_at` 由调用方提供。
- user 插入需要调用方提供 `UserId(Uuid)` 和时间戳。领域模型的 email 仍为 Option，但数据库列非空，`insert`、`update` 和 `save` 缺失 email 都会产生 `InvalidInput` 标记；该校验由 `repositories` 内部的私有共享 helper 实现，三个后端共用。内存实现同样检查重复 ID 和 email。
- student 创建使用 `NewStudent { name, age }`，由仓储生成 ID，并在返回的 `Student` 中提供该 ID；数据库实现使用自增主键，内存实现自行分配。
- todo 与现有数据库实体一致：UUID 主键、`completed: Option<bool>`、`created_at` / `updated_at` 均为 UTC 时间。创建时由调用方提供 UUID 和时间戳，不使用整数 ID 兼容转换。

数据库表使用现有 `public."user"`、`public.student`、`public.todo`，均为单数。仓储只负责数据访问，不自动创建或迁移业务表。

## 用户批量查询、保存与搜索

`UserRepository` 用显式方法定义业务能力。组合筛选通过普通 Rust 类型 `UserQuery` 表达，结果使用 `UserPage`；`search` 本身就是查询入口，无需再暴露一个 query builder 接口。SeaORM 的 `Select`、SQLx 的 `QueryBuilder` 和字符串字段 DSL 均留在仓储实现内部，不进入 `models` 或调用方接口。当前没有调用需求的泛型 `count`、`delete_many`、`query` 方法不预先加入 trait。

### 批量读取与原子保存

`find_many(&[UserId])` 最多接受 1000 个输入 ID，校验发生在去重之前。空输入返回空列表；重复 ID 只返回一次，缺失 ID 跳过，结果按 ID 升序排列，不保留输入顺序。

`insert(&User)` 只插入新记录，重复主键或 email 返回 `Conflict`。`save(&User)` 明确表示按主键原子 upsert：不存在则插入，已存在则保留原来的 `created_at`，完整替换 email、username、hashed_password、is_active、is_superuser、updated_at。可空字段的 `None` 会清空原值；另一个 ID 已占用 email 时仍返回 `Conflict`。时间戳由调用方提供，仓储不会自动刷新 `updated_at`。数据库实现使用 `INSERT ... ON CONFLICT (id) DO UPDATE`，内存实现在单个写锁内完成检查和写入。

这里的 `save` 与 SeaORM `ActiveModel::save` 的语义不同。后者根据主键的 `ActiveValue` 选择操作：`NotSet` 插入，`Set` 或 `Unchanged` 更新；它不会通过查询数据库存在性决定 upsert，给一个不存在的 UUID 设置 `Set` 也会走更新。本项目使用显式冲突处理实现仓储的保存契约。参考：[SeaORM Save](https://www.sea-ql.org/SeaORM/docs/basic-crud/save/)、[SeaORM Insert / On Conflict](https://www.sea-ql.org/SeaORM/docs/basic-crud/insert/)。

### 组合查询与分页

`search(&UserQuery)` 返回 `UserPage { items, total, page, page_size }`，其中 `total` 是筛选后、分页前的记录数。查询条件如下：

| 字段 | 行为 |
| --- | --- |
| `keyword: Option<String>` | 去除首尾空白并转小写，按字面量子串匹配 username 或 email；空字符串或纯空白关闭该条件。`%`、`_` 等字符没有通配符含义。 |
| `is_active: Option<bool>` | `None` 不筛选；`Some(true)` / `Some(false)` 仅匹配对应布尔值，均不匹配 NULL。 |
| `is_superuser: Option<bool>` | 与 is_active 相同，所有启用的筛选条件用 AND 组合。 |
| `page: u64` | 从 1 开始，默认 1。 |
| `page_size: u64` | 允许 1..=100，默认 20。 |
| `sort: UserSort` | `IdAsc`（默认）、`IdDesc`、`CreatedAtAsc`、`CreatedAtDesc`。按创建时间排序时，再按同方向 ID 排序，保证唯一顺序。 |

仓储拒绝无效页码、页大小，以及计算溢出或超过 `i64::MAX` 的 offset，返回带 `InvalidInput` 标记的错误。合法页码超出结果范围时，`items` 为空，`total` 仍是匹配总数。SQLx 在实现内部用 `QueryBuilder` 组合固定 SQL 片段、通过 `push_bind` 绑定筛选值；排序片段由 `UserSort` 枚举选择。参考：[SQLx QueryBuilder](https://docs.rs/sqlx/0.9.0/sqlx/struct.QueryBuilder.html)。

关键词在 Rust 中做 trim / lowercase 标准化，PostgreSQL 列值的 `LOWER` 按数据库 locale / collation 规则转换；内存实现使用 Rust `to_lowercase` 模拟，SQLite 默认内置 `lower` 仅处理 ASCII。因此非 ASCII 字符的大小写匹配不保证三个后端完全一致；需要统一国际化搜索语义时，应明确规则并在真实 PostgreSQL 环境验证。参考：[PostgreSQL 字符串函数](https://www.postgresql.org/docs/current/functions-string.html)、[SQLite lower](https://www.sqlite.org/lang_corefunc.html#lower)。

一次 PostgreSQL `search` 的 count 和 items 查询放在同一个 `REPEATABLE READ`、`READ ONLY` 事务中，二者使用同一快照；内存实现从单次读锁取得筛选快照。这个保证仅限单次调用，翻到下一页会开启新的查询，期间发生的新增、删除或排序字段变化仍可能使跨页结果重复或遗漏。参考：[PostgreSQL Repeatable Read](https://www.postgresql.org/docs/current/transaction-iso.html#XACT-REPEATABLE-READ)。

当前使用 offset 分页，适用于有界的常规列表。数据库仍需计算被 offset 跳过的记录，深分页可能代价较高；出现明确的大数据量连续翻页需求后，再设计游标分页。参考：[PostgreSQL LIMIT / OFFSET](https://www.postgresql.org/docs/current/queries-limit.html)。

### 使用示例

下面的函数可在 crate 内直接调用，`repo` 可以是三个后端中的任意一个实现：

```rust
use anyhow::Result;
use chrono::Utc;
use crate::repositories::{User, UserPage, UserQuery, UserRepository, UserSort};

async fn save_and_search_users(
    repo: &dyn UserRepository,
    mut user: User,
) -> Result<UserPage> {
    // user 已包含调用方生成的 ID、非空 email 和时间戳。
    // 只允许新增的流程使用 repo.insert(&user).await?。
    user.username = Some("Alice".into());
    user.is_active = Some(true);
    user.is_superuser = Some(false);
    user.updated_at = Some(Utc::now());
    let saved = repo.save(&user).await?;

    // 去重后最多返回一个用户；空输入同样合法。
    let found = repo.find_many(&[saved.id.clone(), saved.id.clone()]).await?;
    assert!(found.len() <= 1);

    repo.search(&UserQuery {
        keyword: Some("  ALICE  ".into()),
        is_active: Some(true),
        is_superuser: Some(false),
        sort: UserSort::CreatedAtDesc,
        ..UserQuery::default()
    }).await
}
```

## 连接与使用

SeaORM 实现接收 `Arc<DatabaseConnection>`；SQLx 实现接收可轻量克隆的 `PgPool`。应用已经使用 PostgreSQL SeaORM 连接时，可以复用底层连接池：

```rust
use std::sync::Arc;
use crate::repositories::{NewStudent, StudentRepository, UserRepository};
use crate::repositories::orm::SeaOrmUserRepository;
use crate::repositories::sqlx::SqlxStudentRepository;

// db: Arc<sea_orm::DatabaseConnection>，必须是 PostgreSQL 连接。
let users: Arc<dyn UserRepository> = Arc::new(SeaOrmUserRepository::new(db.clone()));
let students: Arc<dyn StudentRepository> = Arc::new(SqlxStudentRepository::new(
    db.get_postgres_connection_pool().clone(),
));
let student = students.create(&NewStudent {
    name: "Alice".into(),
    age: 20,
}).await?;
```

内存实现可通过 `Default` 创建，不需要数据库连接：

```rust
use std::sync::Arc;
use crate::repositories::{StudentRepository, TodoRepository, UserRepository};
use crate::repositories::in_memory::{
    InMemoryStudentRepository, InMemoryTodoRepository, InMemoryUserRepository,
};

let users: Arc<dyn UserRepository> = Arc::new(InMemoryUserRepository::default());
let students: Arc<dyn StudentRepository> = Arc::new(InMemoryStudentRepository::default());
let todos: Arc<dyn TodoRepository> = Arc::new(InMemoryTodoRepository::default());
```

也可以使用 `sqlx::postgres::PgPoolOptions` 创建独立池。现有 HTTP 用户处理器默认仍使用 SeaORM；`UserService` 接收 `Arc<dyn UserRepository>`，可注入任一种实现，无需修改业务逻辑。当前未增加 student / todo HTTP 路由。

SQLx 使用参数绑定、显式列和 `RETURNING`；不使用需要构建时连接数据库的 `query!` 宏。SeaORM 使用 ActiveModel 更新，省去更新前的查询。参考：[SQLx 参数绑定](https://docs.rs/sqlx/0.9.0/sqlx/fn.query.html)、[SeaORM PostgreSQL 连接池](https://docs.rs/sea-orm/2.0.4/sea_orm/struct.DatabaseConnection.html#method.get_postgres_connection_pool)。

## 测试

从工作区根目录执行：

```sh
cargo test -p api_rs --locked repositories::
```

默认运行真实 SQLite 内存库上的三组 SeaORM 契约测试、三组内存仓储契约测试，以及行转换测试。内存 student / todo 实现与 user 一样接受共同 CRUD 契约验证；目录调整不改变 `repositories::` 测试筛选方式。

PostgreSQL 测试 `repositories::tests::postgres_repository_contracts` 默认忽略，显式提供一个**空的、可丢弃的测试数据库**后运行：

```sh
docker run --rm --detach --name api-rs-repository-test \
  --tmpfs /var/lib/postgresql:rw \
  -e POSTGRES_PASSWORD=repository-test-only \
  -e POSTGRES_DB=api_rs_repository_tests \
  -p 127.0.0.1:15432:5432 postgres:18-alpine

docker exec api-rs-repository-test pg_isready -U postgres -d api_rs_repository_tests

# 确认上一步报告 accepting connections 后运行。
API_RS_TEST_DATABASE_URL='postgresql://postgres:repository-test-only@127.0.0.1:15432/api_rs_repository_tests' \
  cargo test -p api_rs --locked repositories::tests::postgres_repository_contracts -- --ignored

docker stop api-rs-repository-test
```

PostgreSQL 测试创建这三个表，对 SeaORM / SQLx 的六个数据库实现执行相同的 CRUD 契约，并验证同一连接池下 SQLx 写入的数据可以由 SeaORM 读取和删除。契约覆盖 nullable 字段、排序、特殊字符绑定、唯一键冲突、未找到记录、自增 ID 和创建时间不可修改。若表已存在，测试会在建表阶段失败；重跑应使用新的临时数据库。
