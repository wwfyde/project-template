---
description: Rust API 的用户、租户、账户、文件、资产、文档和知识模型、关系与持久化边界。
---

# 数据模型

`api-rs` 以用户表示登录身份、租户表示组织与计费归属、账户表示资源管理与隔离边界。在账户内，统一文件载体支撑资产、文档和可追溯知识索引，各对象保留自己的身份与生命周期。

本页描述领域模型及持久化映射。用户、租户、账户和两层成员关系已有持久化及应用用例，`item` 已接入账户隔离；文件、资产、文档和知识领域尚未接入 SeaORM 实体、文件存储、向量服务或 CRUD 路由，这些领域的拟议表名不代表数据库已经创建或执行相应约束。API schema 由 `utoipa` 从代码生成，通过服务现有的 `/docs` 与 `/api-docs/openapi.json` 查看，本页不重复维护 API 参数或响应参考。

## 领域边界与代码组织

| 位置 | 职责 |
| --- | --- |
| `api-rs/src/models/tenant.rs` | 个人／组织租户与租户成员快照 |
| `api-rs/src/models/account.rs` | 个人／Workspace 账户、成员角色和已验证的账户上下文 |
| `api-rs/src/models/account_repository.rs` | 注册、账户访问和成员变更的应用持久化端口 |
| `api-rs/src/services/account.rs` | 账户应用用例及错误边界 |
| `api-rs/src/repositories/orm/account.rs` 与 `account/` | SeaORM 事务、成员授权和并发变更约束 |
| `api-rs/src/services/auth_extractor.rs` | 身份验证、请求账户选择与 `AccountContext` |
| `api-rs/src/models/shared.rs` | 领域共用标识、校验与错误 |
| `api-rs/src/models/file.rs` | 文件身份、内容分类、格式、大小、哈希及存储定位 |
| `api-rs/src/models/asset.rs` | 资产业务身份及带作用的文件关联 |
| `api-rs/src/models/document.rs` | 文档身份、正文与不可变修订 |
| `api-rs/src/models/knowledge.rs` 与 `knowledge/` | 知识领域入口及子模块：知识库、来源快照、收录、索引状态与来源定位 |
| `api-rs/src/schemas/` | 对外 DTO、领域对象转换及 `utoipa::ToSchema` |
| `api-rs/src/entities/` | 已实现的 SeaORM 数据库映射，与领域对象分别组织 |

领域实体通过构造函数和行为方法维护约束。持久化对象、HTTP 输入输出和领域对象分别承担自己的职责；新增 DTO 不意味着相应 HTTP 用例已经提供。

知识领域由 `knowledge.rs` 统一导出类型：`knowledge/base.rs` 定义知识库，`source.rs` 定义来源快照，`index.rs` 定义收录及索引生命周期，`chunk.rs` 定义片段、定位和引用。内部拆分不改变调用方使用的 `models::knowledge` 路径。

`lib.rs` 导出 `entities`、`models` 与 `schemas`，便于调用及独立验证；服务入口沿用现有模块组织。`entities` 继续提供已有数据库映射，本次未增加内容领域的表。`schemas/content.rs` 汇总内容领域及来源引用的 schema，由 `ContentSchemas` modifier 接入现有 `AllApi`；它只声明已有 DTO 的组件，不生成尚未实现的 CRUD 路径。文件 DTO 不暴露内部存储的 backend、bucket 或 key。

`design` 与 `creative` 暂不建立独立聚合。可编辑设计工程需要画布、图层、组件等行为后，再扩展设计领域；广告创意需要投放、渠道和变体等行为后，再扩展广告领域。现有 `resource` 目录及分类草稿不承担这些新增领域对象的通用父类职责。

## 用户实体

`user` 由 `entities/user.rs` 映射至 PostgreSQL `public` schema，SeaORM、SQLx 和内存仓储实现同一用户仓储契约。

| 字段 | 数据库类型与约束 | 含义 |
| --- | --- | --- |
| `id` | UUID，主键 | 稳定用户身份，业务关系引用此键 |
| `uid` | BIGINT，identity、非空、唯一且大于零 | 创建时分配的数字身份，更新时保留 |
| `email` | VARCHAR，非空、唯一 | 邮箱；领域写入类型虽允许 `None`，仓储会拒绝 |
| `username` | VARCHAR，可空、唯一 | 精确值唯一，区分大小写，允许多个 `NULL` |
| `nickname` | VARCHAR，可空 | 展示昵称，不要求唯一 |
| `locale` | VARCHAR，非空，默认 `zh-CN` | CHECK 限定 `zh-CN`、`en-US`、`ja-JP` |
| `hashed_password` | VARCHAR，可空 | 密码散列，不进入用户响应 |
| `is_active` / `is_superuser` | BOOLEAN，可空 | 当前身份状态；创建接口默认启用且非超级用户 |
| `created_at` / `updated_at` | 带时区时间戳，后者可空 | 创建与更新时间 |

`User` 表示已经保存的用户，包含必填 `Uid`；`UserWrite` 表示写入参数，不包含 UID。`insert` 和按 UUID 新建的 `save` 分配 UID，`update` 和已有记录的 `save` 保留 UID 与创建时间。编辑现有用户通过 `UserWrite::from(&user)` 投影出可写字段。

数据库 UID 读取采用可失败的 `i64 → Uid` 转换，拒绝非正数；语言值也必须能解析为领域 `Locale`，不会将非法存储值悄悄替换为默认语言。内存仓储在同一写锁中检查唯一性和分配递增 UID，删除后不复用编号。

`nickname` 与 `locale` 已进入插入、更新、upsert 和读取链路。用户名唯一性与检索时的大小写转换是两种规则：唯一约束允许 `Alice` 和 `alice`，关键词搜索可以同时匹配它们。当前数据结构以重建后的表为准，不保留旧昵称字段兼容逻辑。

## 租户、账户与两层成员

`Tenant` 是计费归属单元，类别为 `personal` 或 `organization`；`Account` 是资源隔离单元，类别为 `personal` 或 `workspace`。Workspace 是 Account 的一种类别，不再建立与 Account 平行的身份或表。

```text
User ── tenant_member ── Tenant（计费归属）
                           │
                           └── Account（资源边界）── item / 文件 / 资产 / 文档 / 知识
User ── account_member ─────────┘

个人租户 → 本人的 personal account
组织租户 → 一个或多个 workspace account
```

同一用户可以属于多个组织，并加入各组织中的不同账户。用户表不保存单一的 `tenant_id` 或 `account_id`，参与范围由两种成员关系表达。租户所有者或管理员不会仅凭组织角色自动获得所有 Workspace 的资源访问权。

这个职责划分参考 OpenAI 公开文档中组织承接用量归属、项目用于隔离工作和访问范围的做法；这里定义的是本系统模型，不代表 OpenAI 内部数据库结构。[OpenAI 组织与项目说明](https://developers.openai.com/api/docs/guides/production-best-practices#setting-up-your-organization)

### 默认注册与持久化表

正常注册通过 `AccountService` 和 `AccountRepository::register_user`，在一个事务内创建用户、个人租户、个人账户及两条 `owner` 成员关系。任何一步失败都会整体回滚。`UserRepository` 仍是基础身份存储端口，单独向用户表插入记录不会自动补齐这些业务容器。

| 表 | 核心字段 | 数据库保证 |
| --- | --- | --- |
| `tenant` | `id`、`name`、`kind`、`personal_user_id`、`is_active`、`created_at` | UUID 主键；名字非空白；类别与个人归属组合 CHECK；`personal_user_id` 可空且唯一、FK 到 user |
| `account` | `id`、`tenant_id`、`name`、`kind`、`personal_user_id`、`is_active`、`created_at` | UUID 主键；非空 tenant FK；类别与个人归属组合 CHECK；`personal_user_id` 可空且唯一、FK 到 user |
| `tenant_member` | `tenant_id`、`user_id`、`role`、`created_at` | `(tenant_id, user_id)` 复合主键；两条 FK；角色 CHECK |
| `account_member` | `account_id`、`user_id`、`role`、`created_at` | `(account_id, user_id)` 复合主键；两条 FK；角色 CHECK |

个人租户和个人账户必须填写 `personal_user_id`；组织租户和 Workspace 必须为空。两张表分别保证同一用户至多有一个个人租户和一个个人账户。租户与账户均默认启用。

个人账户只能置于同一用户的个人租户内；Workspace 只能置于组织租户内。跨表类别和归属一致性由领域工厂、仓储变更逻辑及读取授权共同验证。数据库行内 CHECK 不会检查父租户类别，也不会保证每个账户成员都同时是租户成员。

账户到租户、个人归属到用户的外键使用 `RESTRICT`，避免直接删除父身份后留下资源容器；成员关系到用户和所属容器的外键使用 `CASCADE`。这些物理删除行为与成员移除用例不同：移除成员不删除账户、租户或资源。

实体同步创建表结构，不等于为既有用户补齐个人租户和账户。当前按可重建的数据库结构实现，没有旧用户归属回填；正常注册入口才保证默认个人空间存在。

### 成员与权限

两层成员均使用 `owner/admin/member`，但角色只对当前租户或账户有效：

| 角色 | 成员管理规则 |
| --- | --- |
| `owner` | 可管理成员角色；移除或降级自身也必须满足至少保留另一位 owner |
| `admin` | 可添加、修改或移除普通 member；不能操作 owner/admin 或将成员提升为管理角色 |
| `member` | 不可管理成员；账户成员可使用该账户内的资源 |

组织的 owner/admin 可以创建 Workspace，创建者成为新账户 owner。向 Workspace 添加用户前，目标用户必须已经属于同一组织。个人租户和个人账户不提供共享成员变更。

删除或降级最后一个 owner 会被拒绝。删除组织成员前，还会检查其是否为任一 Workspace 的唯一 owner；必须先转移对应 Workspace 的所有权。租户 admin 只能级联撤销普通账户 member：如果目标在任一 Workspace 中担任 admin 或 owner，则需要租户 owner 处理，同时仍受最后 owner 规则约束。成功移除组织成员时，会一并清除该用户在组织内各账户的成员关系，不会删除账户内容。

这些跨行规则通过事务与锁控制，而不是仅靠角色字段的 CHECK。租户成员关系、账户成员关系、用户启用状态以及租户／账户启用状态都参与访问判断。

### 每次请求的账户上下文

JWT 的 `sub` 使用稳定的用户 UUID，账户与角色不会作为长期可信权限固化到 JWT。`X-Account-Id` 在每次资源请求中选择账户；省略时明确选择当前用户的个人账户，不任意选择某条 Workspace 成员关系。重复或无效的账户选择头会被拒绝。

`AccountContext` 根据当前持久化成员关系解析 `AccountAccess { user_id, account_id, tenant_id, role }`。`tenant_id` 从所选账户的归属解析，客户端不能为同一资源请求另行指定计费租户。即使同属一个组织，也仍需拥有具体账户的成员关系才能访问该账户。

`item` 的列表、单条读取、更新和删除都包含 `account_id` 条件；跨账户 ID 不会绕过过滤。创建时的账户 ID 和 `owner_id` 从已验证上下文取得，后者只记录创建者。请求体不接受客户端指定账户或创建者，更新不改变这些归属字段。用户列表和按 ID 查询也限定为当前所选账户的成员；当前用户身份查询仍表示登录者自己。

当前计费能力只建立归属关系：资源属于账户，账户映射到账单归属租户。用量采集、账单计算、扣费与支付渠道尚未实现。未来计量事件应使用服务端解析出的租户归属，不信任前端提交的付款方标识。

## 分类与归属

| 维度 | 含义 | 示例 |
| --- | --- | --- |
| `media_kind` | 文件内容大类 | `image`、`document`、`audio`、`video` |
| `mime_type` | 文件具体格式 | `image/png`、`application/pdf` |
| 业务对象 | 内容的业务身份 | 资产、文档、知识库 |
| `kind` | 对象所在领域内的细分类 | Logo 资产、规范文档 |
| 文件关联的 `role` | 文件在某个资产中的作用 | 原稿、预览、缩略图、蒙版 |
| 知识库收录关系 | 来源加入哪些知识库 | 同一来源加入多个知识库 |

一份《品牌规范.pdf》可以同时是文档类文件、品牌规范资产、某份文档的修订内容和知识库来源。文件不包含互斥的 `asset/document/knowledge` 库归属枚举。

`AccountId` 表示资源归属边界。跨对象建立关系时必须满足账户一致；账户一致并不等于操作者已被授权。账户成员、角色与请求上下文已由账户应用链路落实；未来文件和知识检索用例接入时仍须复用这些授权判断，不能只比较两个来源的账户 ID。

领域 ID 使用不同的 UUID 包装类型，区分文件、资产、文档、修订等身份；这些类型本身不查询数据库，也不保证所指对象存在。账户有效性、全局主键唯一性和引用存在性仍需持久化层保证。

## 文件与资产

文件 ID 对应不可变字节内容。替换内容产生新文件，资产或文档修订引用明确的文件 ID。原稿、预览、缩略图和导出内容都可以由统一文件服务保存，展示时根据业务关联区分。

| 对象 | 字段 | 领域约束 |
| --- | --- | --- |
| `File` | `id`、`account_id`、`metadata`、`storage`、`created_at` | 表示已经完成的文件；没有替换字节的方法 |
| `FileMetadata` | `filename`、`media_kind`、`mime_type`、`byte_size`、`sha256` | 文件名非空白且不含控制字符；MIME 为不带参数的 `type/subtype`；SHA-256 为 64 位十六进制 |
| `StorageLocation` | `backend`、`bucket`、`key` | 均非空白，是内部定位而非公开下载 URL |
| `Asset` | `id`、`account_id`、`title`、`kind`、`files`、`created_at` | 标题非空白；文件关联由资产行为方法维护 |
| `AssetFile` | `file_id`、`role` | 同一资产内 `(file_id, role)` 唯一 |

MIME 与哈希统一保存为小写，文件名保留原文；空文件合法。领域对象校验哈希格式，真实文件大小、内容类型和哈希是否匹配实际字节，需要文件接收流程核实。`media_kind` 由调用者明确提供，当前没有从 MIME 自动推断或核验内容大类。

`MediaKind` 包括 `image/document/audio/video/archive/data/other`；`AssetKind` 包括 `logo/photo/illustration/template/brand_guideline/design/other`；`AssetFileRole` 包括 `original/preview/thumbnail/export/mask/reference`。

资产拥有独立名称与业务分类，通过文件关联表示一组文件及其作用。移除文件关联只改变资产的组成，不删除被其他对象引用的文件。

`attach_file` 拒绝跨账户或重复的文件作用关联；同一文件可以在同一资产中承担多个作用，也可以被同账户的多个资产引用。`detach_file` 只移除指定作用的关联，未找到时返回错误。失败的重命名、关联或移除不会部分修改资产。

文件哈希用于校验和存储去重依据，不代表跨账户身份或权限相同。将来如需对象存储层去重，可以独立引入存储对象，保留各账户的文件记录。

## 文档与修订

文档具有稳定 ID，修订保存确定版本的内容。在线正文可以直接作为修订内容，上传文件也可以承载修订；原生文档无需先生成一个上传文件。导出 PDF 等操作可在应用层生成新的文件引用。

| 对象 | 字段 | 领域约束 |
| --- | --- | --- |
| `Document` | `id`、`account_id`、`title`、`kind`、`current_revision_id`、`revision_no`、`created_at`、`updated_at` | 标题非空白；初始无当前修订、版本号为零 |
| `DocumentRevision` | `id`、`document_id`、`account_id`、`revision_no`、`title`、`content`、`source_file_id`、`created_at` | 版本从一开始递增；保存创建修订时的标题、正文和原件引用 |
| `DocumentContent` | `Markdown { text }` / `RichText { body }` / `File { file_id }` | 一份修订只有一种权威正文 |

`DocumentKind` 包括 `note/specification/guide/report/other`。Markdown 正文不能是空白；富文本必须是非空 JSON 对象，编辑器节点结构的完整校验由编辑器及应用用例负责。文件正文通过 `revise_file` 建立，并校验文件账户；Markdown 和富文本也可以保留同账户的可选原文件引用。

`rename` 与创建修订均不允许时间早于当前更新时间。创建新修订时检查版本号溢出、当前修订 ID 重复和来源账户；验证失败不推进版本或替换当前修订。聚合不加载全部历史，历史修订 ID 的全局唯一性仍由仓储和数据库主键保证。

文档修改产生新修订，历史修订保持不变。新修订与文档当前版本指针应在持久化时原子提交；并发编辑需要仓储提供版本比较或锁，单个内存对象的校验不能替代数据库并发控制。

## 知识来源、索引与引用

知识来源固定指向一份文件或某个文档修订。同一来源可被多个知识库收录；每条收录关系独立维护索引进度及是否被移除。

| 对象 | 字段 | 领域约束 |
| --- | --- | --- |
| `KnowledgeBase` | `id`、`account_id`、`name`、`created_at` | 名称非空白 |
| `KnowledgeSource` | `id`、`account_id`、`title`、`origin`、`original_file_id`、`created_at` | 来源及标题快照固定；来源对象必须属于同一账户 |
| `SourceOrigin` | `File { file_id }` / `DocumentRevision { document_id, revision_id }` | 枚举保证来源类型排他，文档引用必须固定修订 |
| `KnowledgeBaseSource` | `knowledge_base_id`、`source_id`、`account_id`、`index_status`、`index_version`、`active_attempt`、`last_error`、`enrolled_at`、`removed_at` | 知识库与来源同账户；索引状态和移除状态分别表达；保存当前索引配方标识 |
| `KnowledgeChunk` | `id`、`account_id`、`source_id`、`ordinal`、`text`、`locator`、`index_version` | 正文、索引版本非空白；来源账户由来源对象确定；定位合法 |
| `SourceCitation` | `chunk_id`、`source_id`、`title`、`origin`、`original_file_id`、`locator` | 由片段与匹配的来源解析得到 |

文件来源的 `original_file_id` 指向该文件；文档修订来源沿用修订的 `source_file_id`，原生文档可以没有原文件。文档后续改名或发布新修订，不改变已经建立的知识来源及引用。

```text
文件 / 文档修订
    ↓
知识来源快照
    ↓
解析正文、OCR 或转写
    ↓
知识片段 + 来源位置
    ↓
向量索引

回答引用 → 知识片段 → 来源快照 → 原文件 / 文档修订
```

嵌入向量用于寻找相关内容，原文与来源定位用于展示证据。原文件链接应在访问时根据稳定 ID 和权限生成，临时签名 URL 不作为来源身份。

`SourceLocator` 使用明确的位置类型，区分位置单位：

| 类型 | 字段及约束 |
| --- | --- |
| `WholeSource` | 只能定位到整份来源 |
| `PdfPage` | `page` 从一开始 |
| `TextRange` | `start/end` 是从零开始的 Unicode 字符半开区间，要求 `start < end` |
| `DocumentBlock` | `block_id` 非空白 |
| `ImageRegion` | `x/y/width/height` 是左上角为原点的归一化坐标；值有限、宽高为正且区域完全位于 `[0, 1]` 内 |
| `TimeRange` | `start_ms/end_ms` 是毫秒半开区间，要求 `start_ms < end_ms` |

当前校验位置结构及数值范围，不读取实际源内容验证页数、字符长度或时间长度，也不自动核验定位类型与媒体格式是否匹配。解析器必须提供可靠的原文映射；没有定位依据时，使用 `WholeSource`，不应声称已定位到具体页码。

`KnowledgeChunk::citation` 检查账户及来源 ID，再返回包含来源版本、原文件和位置的引用。该方法没有执行检索或下载授权；它保证传入来源与片段引用的身份一致。

### 收录与索引生命周期

新收录的索引状态为 `queued`，`index_version` 为空。`start_indexing(index_version)` 只允许从 `queued` 或 `failed` 开始；配方标识必须非空白。开始后保存配方标识，进入 `processing` 并生成新的 UUID `IndexAttempt`。成功或失败回报必须携带当前尝试标识，分别转为 `ready` 或 `failed`，保留该配方标识；错误信息不能是空白。

`queue_reindex` 将有效收录置为 `queued`，并清空索引配方与活动任务标识。`remove` 记录不早于收录时间的 `removed_at`，同时清空配方并废弃活动任务标识；已移除收录不再接受开始、完成、失败或重建操作。`is_searchable` 要求未移除且状态为 `ready`，因此移除后的历史索引状态即使仍是 `ready`，也不会被视为可检索。

`accepts_chunk` 在可检索状态下进一步检查片段的账户、来源 ID 和 `index_version`。重建为新配方后，保留的旧配方片段不会被当前收录接受；调用方仍须单独校验操作者权限。

这些规则保护当前领域实例。落库时仍须对收录状态、配方与任务标识做原子条件更新，避免多个工作进程绕过失效检查。任务标识与 `index_version` 含义不同：前者区分执行尝试，后者标识解析器、分块和嵌入模型的配方；当前仅要求配方标识非空白，完整配置与实际索引发布属于后续索引服务。

### 托管与自管索引

自行管理分块和向量时，保留片段正文、来源定位及索引配置版本，向量后端保存可重建的检索索引。更换解析器、分块策略或嵌入模型时，不混用不同索引版本。

使用 OpenAI Vector Stores 时，可由服务处理分块、嵌入与索引；本地仍保留领域来源和供应商标识映射。若上传的是 OCR 或转写生成的文本，还需要将供应商文件映射回原图或音视频。供应商 ID 不替代本地领域 ID。参考 [OpenAI Retrieval](https://developers.openai.com/api/docs/guides/retrieval)。

OpenAI File Search 的文件引用包含文件标识与文件名，但引用标注的 `index` 不能作为原 PDF 页码；精确来源定位应由解析与映射流程提供。参考 [OpenAI File Search](https://developers.openai.com/api/docs/guides/tools-file-search)。

## 拟议的关系表映射

数据库表名使用单数。以下是领域落库时的命名与职责，当前不新增这些表。

| 表 | 职责 | 主要关系 |
| --- | --- | --- |
| `file` | 不可变文件身份与文件元数据 | 属于账户 |
| `asset` | 资产业务身份 | 属于账户 |
| `asset_file` | 资产与文件的带作用关联 | 资产 ↔ 文件 |
| `document` | 文档身份及当前修订 | 属于账户，指向当前修订 |
| `document_revision` | 不可变文档版本 | 属于文档，可引用来源文件 |
| `knowledge_base` | 知识库容器 | 属于账户 |
| `knowledge_source` | 固定文件或文档版本的来源快照 | 引用文件或文档修订 |
| `knowledge_base_source` | 收录及索引状态 | 知识库 ↔ 来源 |
| `knowledge_chunk` | 片段正文与原文定位 | 属于来源及索引版本 |

持久化实现应保证文档修订号唯一、收录关系唯一、文件关联唯一，以及跨账户关系的一致性。来源的文件引用与文档修订引用须排他，不能出现两个都为空或同时存在的状态。具体外键、唯一键和检查约束在引入 ORM 实体及迁移时实现并验证。

`File`、`DocumentRevision`、`KnowledgeSource` 采用仅插入的持久化语义；已被引用的知识片段同样不覆盖。仓储不得通过 upsert 或通用 save 在相同 ID 下替换历史内容、来源或版本。文档新增修订时，插入修订和更新当前版本指针必须在同一事务中完成，并用预期版本号做乐观锁检查；冲突时整体回滚，避免产生未被文档接受的修订或覆盖他人的当前版本。

## 删除与访问边界

从资产或知识库移除内容只移除对应关系。物理删除文件前，应用服务必须检查资产、文档修订、知识来源以及正在运行的任务是否仍引用它。原文与索引同步删除、保留策略和垃圾回收尚未实现。

检索结果进入模型上下文前，应过滤未授权、已删除、已移除或无效版本的内容；不能只在用户点击原文件链接时鉴权。索引清理可以异步进行，但撤权与移除状态必须被检索路径及时遵守。

## 实现边界

用户、租户、账户与两层成员已具备领域、持久化和应用访问链路，item 已接入真实账户隔离。账户持久化当前使用 SeaORM；它不因用户基础仓储还提供 memory/SQLx 实现而自动具备另外两种实现。

文件、资产、文档和知识领域目前交付领域规则及 API schema。后续接入顺序建议为仓储与数据库约束、文件存储适配、应用用例、HTTP 路由、异步解析与索引、检索授权和引用展示。计费后续另行接入计量和支付流程。

实现仓储时保留领域规则，同时通过事务与数据库约束处理跨实例并发；接入外部服务时维持本地稳定身份和供应商映射。数据模型文档继续解释这些关系与边界，API 参考继续由 `utoipa` 生成。
