# 数据模型与存储参考

本页回答“每个概念存在哪里、数据库保证什么、应用还需要保证什么”。内容对应当前模型和 Alembic 迁移；它描述代码定义，不代表某个运行环境已经执行到最新迁移。先读 [architecture.md](architecture.md) 理解技术分层，再使用本页查字段、约束和迁移边界。

## 为什么以 `user` 和 `account` 为核心？

- `user` 表示全局自然人身份。同一人可以使用多个登录渠道，也可以参与多个账户。
- `account` 表示资源归属容器。`structure` 描述参与结构，默认 `personal`，也支持 `workspace`。
- `account_member` 连接人和账户，保存成员角色。登录凭证属于人，资源归属包含账户。
- `user_identity` 保存登录渠道身份；`password_credential` 保存本地密码凭证；`resource_owner` 保存现有业务资源的归属映射。

所有表使用单数形式。账户类型字段使用 `structure`，登录渠道使用 `provider`，两者不能混用。`account` 不是 OAuth 账号，`user_identity` 也不是资源容器。

| 关系 | 数据库表达 | 业务含义 |
| --- | --- | --- |
| 人 → 个人账户 | `account.personal_user_id` 可空 FK + UNIQUE + CHECK | 每人至多一个个人账户；个人账户必须指向一个人 |
| 人 ↔ 账户 | `account_member` 复合主键 | 一人可参与多个账户，一个 workspace 可有多名成员 |
| 人 → 登录身份 | `user_identity.user_id` FK | 多渠道身份指向稳定的用户 ID |
| 人 → 密码凭证 | `password_credential.user_id` PK + FK | 每人至多一份本地密码凭证 |
| 人 / 账户 → 资源归属 | `resource_owner.user_id/account_id` FK | 同时保留创建者与账户范围 |

## 字段表中的默认值和类型怎样理解？

以下六张核心表以当前 ORM 和迁移到 `e28b47a1d902` 后的数据库为准：

- `String(n)` 对应有长度上限的字符串，`String` 表示未指定长度；核心身份 ID 使用 `String(36)`，不是数据库原生 UUID 类型。
- “可空”表示数据库允许 `NULL`，不表示 HTTP 请求一定接受缺省或空值。
- “ORM”默认值由 SQLAlchemy 写入时提供；“DB”默认值由数据库提供。直接执行 SQL 不会获得只有 ORM 的默认值。
- `DateTime(timezone=True)` 在 PostgreSQL 中为带时区时间戳。`created_at` 的 `now()` 是数据库默认值。
- 核心 ID 由仓储调用 `uuid4()` 后转为字符串；字段本身没有 UUID 生成默认值，也没有 UUID 格式 CHECK。
- PK 为主键，FK 为外键；下面列出的索引均为非唯一索引，除非明确写出 UNIQUE。

### `user` 保存哪些人的信息？

来源：[models/user.py](../src/api/models/user.py)。

| 字段 | SQLAlchemy 类型 | 可空 | 默认值 | 约束 / 含义 |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | 否 | 无 | PK；稳定用户 ID |
| `display_name` | `String(255)` | 否 | 无 | 展示名称 |
| `avatar_url` | `String(2048)` | 是 | 无 | 头像地址 |
| `email` | `String(320)` | 是 | 无 | 联系资料，无 UNIQUE |
| `phone` | `String(32)` | 是 | 无 | 联系资料，无 UNIQUE |
| `is_active` | `Boolean` | 否 | ORM `True` | 是否允许使用用户身份；无 DB 默认 |
| `auth_version` | `Integer` | 否 | ORM `1` | 会话失效版本；无 DB 默认和正数 CHECK |
| `created_at` | `DateTime(timezone=True)` | 否 | DB `now()` | 创建时间 |

`personal_account` 是 ORM 关系属性，不是 `user` 的列；它通过 `account.personal_user_id` 加载个人账户。资料中的邮箱和手机号不作为跨渠道自动合并用户的依据，登录身份以 `provider + subject` 匹配。

### `account` 如何区分个人账户和工作空间？

来源：[models/account.py](../src/api/models/account.py)。

| 字段 | SQLAlchemy 类型 | 可空 | 默认值 | 约束 / 含义 |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | 否 | 无 | PK；账户范围 ID |
| `name` | `String(255)` | 是 | 无 | 账户名称；新建个人账户未设置名称 |
| `structure` | `String(20)` | 否 | ORM / DB `personal` | CHECK 限定 `personal`、`workspace` |
| `personal_user_id` | `String(36)` | 是 | 无 | FK → `user.id`，删除 `RESTRICT`；UNIQUE |
| `is_active` | `Boolean` | 否 | ORM / DB `True` | 账户是否可用 |
| `created_at` | `DateTime(timezone=True)` | 否 | DB `now()` | 创建时间 |

数据库约束：

- `ck_account_structure`：只允许 `personal` 或 `workspace`。
- `ck_account_personal_user`：个人账户必须填写 `personal_user_id`；workspace 必须为 `NULL`。
- `uq_account_personal_user_id`：一个用户至多对应一个个人账户，多个 workspace 的 `NULL` 不冲突。

`name` 非空和长度为 1–255 的业务校验发生在 `AccountRepository.create_workspace()`，不是数据库 CHECK。新建个人账户的 `name` 为 `NULL`；旧数据迁移时会把原用户的 `display_name` 复制为账户名。

### `account_member` 的角色是不是完整权限系统？

来源：[models/account_member.py](../src/api/models/account_member.py)、[repositories/account.py](../src/api/repositories/account.py)。

| 字段 | SQLAlchemy 类型 | 可空 | 默认值 | 约束 / 含义 |
| --- | --- | --- | --- | --- |
| `account_id` | `String(36)` | 否 | 无 | 复合 PK；FK → `account.id`，`CASCADE` |
| `user_id` | `String(36)` | 否 | 无 | 复合 PK；FK → `user.id`，`CASCADE`；索引 |
| `role` | `String(20)` | 否 | ORM / DB `member` | CHECK：`owner`、`admin`、`member` |
| `created_at` | `DateTime(timezone=True)` | 否 | DB `now()` | 加入时间 |

复合主键保证同一个人不能重复加入同一个账户。`ck_account_member_role` 保证角色值合法，但数据库没有保证“至少一个 owner”“只有一个 owner”或“个人账户只有自己的 owner 成员”。

当前仓储在创建用户时，同一事务内创建个人账户和 `owner` 成员；`create_workspace()` 也创建操作者的 `owner` 成员。账户访问查询要求账户有效且成员关系存在，并对个人账户额外验证 `personal_user_id`。因此，即使直接向个人账户插入其他成员，也不会通过当前账户访问查询。

这些角色目前是模型基础，尚无完整的成员邀请、角色变更与按角色分配权限的 RBAC 工作流。也没有数据库约束保证每个用户一定拥有个人账户；这由正常的用户创建流程保证。

### `user_identity` 如何连接多个登录渠道？

来源：[models/user_identity.py](../src/api/models/user_identity.py)、[repositories/user.py](../src/api/repositories/user.py)。

| 字段 | SQLAlchemy 类型 | 可空 | 默认值 | 约束 / 含义 |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | 否 | 无 | PK；身份记录 ID |
| `user_id` | `String(36)` | 否 | 无 | FK → `user.id`，`CASCADE`；索引 |
| `provider` | `String(80)` | 否 | 无 | 渠道标识，例如 `google`、`password` |
| `subject` | `String(255)` | 否 | 无 | 渠道内稳定身份标识 |

`uq_user_identity_provider_subject` 对 `(provider, subject)` 全局唯一，因此同一外部身份不能绑定给两个人。数据库没有 `(user_id, provider)` 唯一约束，也没有 provider 枚举 CHECK；绑定规则和已启用渠道由应用处理。

密码登录也有一条 `provider="password"` 的身份，其 `subject` 为规范化用户名。身份绑定、解绑和凭证变更时的并发锁及版本校验见 [repositories/user_security.py](../src/api/repositories/user_security.py)。

### `password_credential` 为什么单独保存？

来源：[models/password_credential.py](../src/api/models/password_credential.py)、[repositories/password.py](../src/api/repositories/password.py)。

| 字段 | SQLAlchemy 类型 | 可空 | 默认值 | 约束 / 含义 |
| --- | --- | --- | --- | --- |
| `user_id` | `String(36)` | 否 | 无 | PK；FK → `user.id`，`CASCADE` |
| `username` | `String(64)` | 否 | 无 | UNIQUE `uq_password_credential_username` |
| `hashed_password` | `String(255)` | 否 | 无 | 密码哈希，不保存明文密码 |

用户名先经过 ASCII 检查、首尾空白移除及小写化，再验证为 3–64 位允许字符。数据库 UNIQUE 针对实际存入的字符串，不负责这些规范化规则。

`password_credential.username` 与 `user_identity(provider="password").subject` 的一致性由仓储事务维护，两个字段之间没有数据库 FK。密码验证支持 Argon2 和既有 bcrypt 哈希；算法升级、当前密码验证及 `auth_version` 更新均属于应用逻辑。

### `resource_owner` 是否等同于业务表外键？

来源：[models/resource_owner.py](../src/api/models/resource_owner.py)。

| 字段 | SQLAlchemy 类型 | 可空 | 默认值 | 约束 / 含义 |
| --- | --- | --- | --- | --- |
| `resource_type` | `String(32)` | 否 | 无 | 复合 PK；当前接入 `conversation`、`agent_session` |
| `resource_id` | `String` | 否 | 无 | 复合 PK；业务资源 ID |
| `user_id` | `String(36)` | 否 | 无 | FK → `user.id`，`CASCADE`；索引 |
| `account_id` | `String(36)` | 否 | 无 | FK → `account.id`，`CASCADE`；索引 |

复合主键 `(resource_type, resource_id)` 为一个资源记录一组归属。`resource_type` 没有枚举 CHECK，`resource_id` 没有指向具体业务表的 FK。映射可以引用并不存在的业务资源；反过来，业务资源也可能没有映射。

当前 `owns()` / `owned_ids()` 同时要求：

1. 资源类型与请求相符。
2. `resource_owner.user_id` 等于当前用户。
3. `account_id` 等于当前会话中的可访问账户。

因此 workspace 成员资格不会自动获得其他成员创建的资源；当前授权仍是“同创建者 + 同账户”。消息通过所属 conversation 授权，Agent turn 通过所属 agent session 授权，无需单独创建归属记录。

原有 `conversation.user_id`、`message.user_id`、`image.user_id` 不带指向 `user` 的 FK，也不是当前统一资源授权依据。不能仅凭这些字段把历史资源归属到某个新账户；没有归属映射的历史资源保持不可访问。

## 其他业务数据有哪些表，哪些已经接入？

来源：[models/conversation.py](../src/api/models/conversation.py)、[models/image.py](../src/api/models/image.py)、[models/agent_session.py](../src/api/models/agent_session.py)。

| 表 / 定义 | 关键数据与约束 | 当前接入状态 |
| --- | --- | --- |
| `conversation` | 字符串 PK；标题、模型、模式、创建者、归档/置顶标记、`meta` 与时间戳 | 有 ORM、初始迁移和增删改查路由；`repo_type=postgres` 时落库 |
| `message` | 字符串 PK；`conversation_id` 非空 FK，`CASCADE`；`user_id` 为非空 UUID；消息内容、角色、状态与时间戳 | 有 ORM、初始迁移和 conversation 下的消息路由 |
| `openai_response` | provider 响应 ID 作 PK；conversation FK `CASCADE`，可空 message FK `SET NULL`；完整原始 JSONB 与结构化属性 | 有 ORM、初始迁移、`from_api_response()` 转换及测试；当前 Agent 运行链路不自动写此表 |
| `response_item` | 字符串 PK；response FK `CASCADE`；`(response_id, output_index)` UNIQUE；完整 item JSONB | 有 ORM、初始迁移及 `from_api_item()`；跟随响应建模，未接入当前 Agent 持久化链路 |
| `image` | UUID PK；文件信息、尺寸、对象存储定位、JSONB 扩展；`storage_key` 唯一，`sha256` 唯一索引，二者可空 | 有 ORM、初始迁移；当前图片工具使用对象存储返回结果，没有写入该 ORM 的业务路径 |
| `project` | 仅 UUID PK，ORM / DB UUIDv7 默认 | 定义在 conversation 模块，导入模块时注册 metadata；有初始迁移，尚无项目业务 CRUD |
| `agent_session` | 字符串 PK；非空 `document` JSONB；可空 `active_turn_id`、`lease_expires_at` | 有 ORM、迁移，`PostgresSessionStore` 实际使用 |
| `agent_turn` | 字符串 PK；非空 session FK `CASCADE`、JSONB 文档、创建时间；`(session_id, created_at, id)` 索引 | 有 ORM、迁移，用于持久化运行结果和历史 |
| `Agent` / 预定 `agent` | 另一个包含名称、API key hash、claim 等字段的类定义 | [models/agent.py](../src/api/models/agent.py) 未由模型入口导入，没有迁移或当前运行链路接入；不属于已部署表契约 |
| `ClaudeMessage`、`MessageBlock` | 抽象 ORM 类 | `__abstract__ = True`，不创建表 |

注意当前类型并未全面统一：核心 `user.id` 为字符串，`message.user_id` 为 UUID，conversation 和 image 的 `user_id` 为文本。消息路由会把认证用户 ID 转为 UUID。新增业务外键时应先明确字段类型和迁移方案。

`parent_message_id`、`previous_response_id`、`openai_conversation_id` 和 `agent_session.active_turn_id` 都没有 FK。代码中的关联含义不能当作数据库参照完整性保证。`message.role` 的 Python 类型别名也不是数据库枚举约束。

`openai_response.response_metadata` 是 ORM 属性名，实际 SQL 列名为 `metadata`。`message` 同时定义 `message` JSONB、`content` Text 和 `text` Text；当前消息路由写入 `content` / `text`，没有把请求统一转换成 `message` JSONB。

这里存在已知的请求与存储类型差异：[MessageCreate](../src/api/schemas/conversation.py) 的 `content` 接受字符串、字典列表、字典或 `None`，但 [create_message()](../src/api/routes/conversations.py) 在 PostgreSQL 路径将 `payload.content` 原样赋给 Text 列，既不做 JSON 序列化，也不写入 JSONB 列。内存路径能保留结构化内容，不代表 PostgreSQL 路径也已支持；后者的结构化消息持久化需要另行统一请求、列类型与迁移。

### Agent 的 JSON 文档和普通会话有什么区别？

[agents/contracts.py](../src/api/agents/contracts.py) 定义文档结构，[agents/store.py](../src/api/agents/store.py) 负责原子读写：

- `agent_session.document` 保存 `SessionRecord`：公开 session、后端 continuation `state` 和租约信息。
- `agent_turn.document` 保存 `AgentTurn`：输入、输出、`items`、usage、错误、运行状态与时间；状态值为 `running/completed/failed/cancelled`。
- PostgreSQL 使用 JSONB，其他方言使用 JSON。文档内部字段由 Pydantic 校验，数据库没有对应状态 CHECK。
- `active_turn_id` 和 `lease_expires_at` 另存为列。读取时这些列覆盖 JSON 中相应值；写入时同时更新。
- 开始、完成和删除操作锁定 session 行；完成时校验当前 turn，结果与 continuation 一起提交，防止过期工作者覆盖后来者。

Agent session 与 conversation 是两条独立存储链路，当前没有外键或自动同步。`repo_type=in-memory` 时，这两类业务对象保存在进程内；用户、账户与归属仓储仍使用 PostgreSQL，不能把该配置理解成整个服务无需数据库。

## 删除一条记录会影响哪些数据？

| 删除目标 | 实际数据库行为 | 应用层边界 |
| --- | --- | --- |
| `user` | 若仍被个人账户引用，`RESTRICT` 拒绝删除；允许删除后，其 identity、credential、membership、resource_owner 按 FK 级联删除 | 没有自动删除全部业务内容的用户注销流程 |
| `account` | 级联删除 member 与 resource_owner；不会删除 user | 业务资源没有到 account 的 FK，不会随账户删除 |
| `conversation` | 级联删除 message、openai_response，后者再删除 response_item | 当前 DELETE 是硬删除；虽然有 `deleted_at` 字段，路由未实现软删除 |
| `message` | 保留对应 openai_response，将其 `message_id` 置空 | conversation 仍保留 |
| `agent_session` | 级联删除 agent_turn | 有未过期运行租约时，store 拒绝删除 |
| 任意业务资源 | 不会自动删除 `resource_owner` | 当前 conversation / agent session 删除路由未清理归属映射 |

创建 conversation 或 agent session 时，先提交业务资源，再调用归属仓储建立映射，这两步不是跨表单一事务。第二步失败可能留下不可访问的资源。当前没有通用孤儿清理任务；若未来增加删除、迁移或补偿逻辑，必须同时考虑业务记录与归属映射。

## Redis 保存什么，为什么不画进 SQL 表关系？

登录 session 是浏览器认证状态，Agent session 是业务运行状态，两者不使用同一存储模型。

| Redis 数据 | 关键内容 / 生命周期 | 实现来源 |
| --- | --- | --- |
| 登录 session | `user_id`、`account_id`、`provider`、`auth_version`、CSRF token、认证时间及绝对到期时间；由 SDK 管理空闲 / 绝对 TTL 与轮换 | [core/auth_session.py](../src/api/core/auth_session.py) |
| OAuth attempt | provider、浏览器摘要、nonce、PKCE verifier、返回路径；绑定 / 再认证时还包含用户、账户和会话上下文 | [schemas/auth.py](../src/api/schemas/auth.py)、[routes/auth.py](../src/api/routes/auth.py) |
| 密码登录限流 | 按身份摘要 / 地址摘要计数，带 TTL | [dependencies/password.py](../src/api/dependencies/password.py) |

登录 session 的 SDK key 前缀为 `{auth.session_key_prefix}:{app.env}:sessions`；OAuth key 为同一配置前缀加 `:oauth:{SHA256(state)}`，默认 TTL 为 600 秒，callback 使用 `GETDEL` 一次性消费。它们都不是 SQL 表，不能通过 Alembic 恢复。

PostgreSQL 中的 `auth_version` 是认证有效性依据；session 里的值需要与用户当前版本一致。数据库升级后旧 session 即使尚未到 Redis TTL，也可能立即失效。

## 迁移如何保留旧数据，什么时候不能回滚？

当前迁移链：

| Revision | 作用 |
| --- | --- |
| `56f837de55b5` | 创建 conversation、message、openai_response、response_item、image、project |
| `8d50b113df31` | 创建 agent_session、agent_turn |
| `c36f109ab672` | 创建旧 auth_user、auth_identity、auth_resource_owner |
| `da72e4b18c09` | 创建旧 auth_password_credential |
| `e28b47a1d902` | 改为 user / account 模型，回填个人账户、成员和资源账户范围 |

[最新迁移](../alembic/versions/e28b47a1d902_user_accounts.py) 会：

1. 检查旧归属记录的 user 存在，且原 `tenant_id` 与该 user 一致；不一致则在数据变更前拒绝升级。
2. 重命名四张 `auth_*` 表，调整相关唯一约束和索引名称。
3. 为每位旧用户生成独立个人账户和 owner 成员。即使旧用户共享相同 tenant，也不会被合并进同一账户。
4. 为已有 resource_owner 回填 `account_id`，再设为非空并创建 FK；删除 user 与 resource_owner 的 `tenant_id`。
5. 把原用户和 tenant 对应关系保存到迁移专用表 `_account_legacy_scope`，并递增所有用户的 `auth_version`。

`_account_legacy_scope` 只有 `user_id` PK 和非空 `tenant_id`，无 ORM 模型、无 FK；它不是业务表，也不表示新的账户体系仍使用 tenant。[alembic/env.py](../alembic/env.py) 明确排除它的自动差异处理，以保留回滚信息。

升级和降级都需要在线连接，不支持这一步的 `--sql` 离线生成。PostgreSQL 迁移会对相关表加排他锁，使验证、快照与回填一致；应在部署安排中考虑写入阻塞。

降级前会检查旧模型能否表示现状。出现 workspace、额外成员或非 owner 成员、缺少个人账户或 owner、资源创建者与个人账户不一致、账户停用，或非 NULL 的账户名称不同于用户显示名时，拒绝降级。需要先导出或调整这些状态，不能期待自动丢弃它们。

可降级时，旧用户恢复 `_account_legacy_scope` 中的 tenant；升级后新增用户使用其个人账户 ID 作为旧 tenant。随后删除新账户表和备份表、恢复旧命名，并再次递增 `auth_version`。业务资源表本身不在该迁移中改写。

当前核心六表的字段和约束与迁移有一致性测试。初始迁移保留旧历史命名，必须读完整迁移链才能得到现状；不能依据单个初始文件推断最终 schema。`default_tenant_id` 配置仍被接受但已弃用，新用户不会据此获得共享账户。

## 本页应持续回答哪些问题？

- 新字段的业务含义、可空性、默认值和唯一性分别是什么？哪些规则由 DB 保证，哪些只在应用执行？
- 新资源是个人私有还是 workspace 共享？授权依赖创建者、成员关系还是具体角色？
- 新增 FK 的 ID 类型是否一致？删除采用 RESTRICT、CASCADE、SET NULL 还是软删除？
- 业务记录与归属映射能否原子提交？失败后谁负责补偿和清理？
- JSON 文档变更是否需要兼容旧数据？后端 continuation 的版本如何升级？
- 迁移是否需要 backfill、锁表、重新登录？旧版本能否表达新增的数据状态？
- 模型是否已注册 metadata、具备迁移并被业务链路使用？仅有类定义不能代表已实现。

验证依据可查 [test_account_models.py](../tests/test_account_models.py)（约束与删除）、[test_account_migration.py](../tests/test_account_migration.py)（回填、回滚、schema 一致性）、[test_account_postgres_integration.py](../tests/test_account_postgres_integration.py)（真实数据库并发）、[test_auth_ownership.py](../tests/test_auth_ownership.py)（双重范围与历史资源）、[test_agent_store.py](../tests/test_agent_store.py)（租约、原子提交、级联删除）和 [test_conversation_models.py](../tests/test_conversation_models.py)（provider 响应转换）。测试文件的存在不表示所有运行环境已执行这些测试。
