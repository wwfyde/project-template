# API 文档索引

这套文档解释 API 的设计、业务规则和使用方式。内容以当前工作区代码为准；“已实现”“兼容行为”“尚未实现”分别说明，不能把扩展建议当成现成接口。

适用范围是 `api/` Python 服务，不包含 `api-rs/` 的实现。数据库表名统一使用单数。术语约定见仓库 [CONTEXT.md](../../CONTEXT.md)。

## 推荐的文档组织

目前采用平铺的专题文件，只有设计决策单独分目录。这样可以直接按文件名查找，也避免初期就出现很多只有一篇文档的子目录。

```text
api/
├── README.md                     # 项目入口与既有接入说明
├── agents.md                     # 既有 Agents 专项说明
└── docs/
    ├── README.md                 # 阅读路线、问题清单、维护约定
    ├── architecture.md           # 系统边界、技术分层、依赖和取舍
    ├── data-schema.md            # 实体、表结构、约束、存储与迁移
    ├── business-flows.md         # 业务流程、不变量、失败和并发
    ├── api-reference.md          # HTTP 契约、认证要求、错误与示例
    ├── ai-image-tools.md         # 图片工具 HTTP 参数、统一结果与 OSS 配置
    ├── ai-image-models-reference.md # 独立端点、请求模型与工具直调维护
    ├── configuration.md          # 配置来源、优先级、默认值与限制
    ├── operations.md             # 启动、迁移、验证和故障处理
    ├── development.md            # 新增功能、扩展渠道、测试和文档维护
    └── decisions/
        ├── README.md             # ADR 索引与写作模板
        └── 0001-user-account.md  # User / Account 分离与技术分层
```

这里把四种阅读目的分开：架构与业务文档解释“为什么”；操作手册说明“怎么做”；参考文档回答“准确是什么”；设计决策记录“为什么在当时选了这个方案”。

## 从哪里开始读？

| 你的任务 | 推荐顺序 |
| --- | --- |
| 第一次接手项目 | [架构](architecture.md) → [数据模型](data-schema.md) → [业务流程](business-flows.md) |
| 本地启动或部署 | [配置参考](configuration.md) → [操作手册](operations.md) |
| 对接前端或其他客户端 | [接口参考](api-reference.md) → [认证与账户流程](business-flows.md) |
| 接入图片编辑或模型提供商 | [图片编辑 API](image-editing.md) → [配置示例](../config.example.toml) |
| 调用图片工具或切换渠道 | [AI 图片工具 API](ai-image-tools.md) → [图片工具调用参考](ai-image-models-reference.md) → [配置示例](../config.example.toml) |
| 新增模型、接口或外部渠道 | [开发指南](development.md) → 对应专题 → [设计决策](decisions/README.md) |
| 排查登录、权限、数据问题 | [操作手册](operations.md) → [业务流程](business-flows.md) → [数据模型](data-schema.md) |
| 理解为什么不用一个 account/auth 目录 | [架构](architecture.md) → [ADR 0001](decisions/0001-user-account.md) |
| 研究 Agent 执行与 SDK 适配 | [业务流程](business-flows.md) → [既有 Agents 文档](../agents.md) → [源码](../src/api/agents/) |

## 每篇文档应回答哪些问题？

下列问题既是当前文档的内容边界，也是以后改代码时的检查清单。

| 文档 | 应持续回答的问题 |
| --- | --- |
| `architecture.md` | 服务解决什么问题？系统边界在哪里？每个技术层负责什么？依赖如何组装？请求经过哪些组件？哪些模块尚未遵循统一分层？哪些外部服务不可缺少？ |
| `data-schema.md` | User、Account、Identity 分别是什么？实体是一对多还是多对多？哪些规则由数据库保证，哪些由应用保证？数据属于谁？删除会级联到哪里？如何迁移已有数据？ |
| `business-flows.md` | 操作由谁发起？执行前必须满足什么条件？哪些步骤必须同事务？失败时留下什么状态？并发如何处理？重试是否安全？完成的判据是什么？ |
| `api-reference.md` | 方法和路径是什么？需要哪种认证？输入输出及分页是什么？哪些 Header 必需？错误状态和错误码如何区分？流式响应发生错误怎么办？ |
| `configuration.md` | 配置从哪里读取？同名值谁覆盖谁？默认值与示例值是否不同？哪些配置组合不支持？是否需要重启？哪些字段只是兼容保留？ |
| `operations.md` | 如何首次启动、创建用户、验证依赖和登录？如何升级与回滚？故障从哪里开始定位？哪些操作会改变数据或使会话失效？ |
| `development.md` | 新逻辑放在哪一层？如何新增模型、OAuth 渠道或 Agent backend？需要哪些测试？如何避免泄漏 SDK 类型或敏感字段？哪些文档需要同步？ |
| `decisions/` | 面临什么约束？考虑过哪些方案？选择了什么？代价是什么？什么变化会触发重新评估？ |

## 当前需要明确的能力边界

- `user` 是全局用户，`account` 是资源空间，`account_member` 连接二者；新用户默认获得独立的 `personal` 账户。
- `workspace` 已有存储模型、仓库方法和成员校验；尚无完整邀请、成员管理、工作空间切换及角色权限 API。
- 同一个 workspace 内的 conversation 和 agent session 仍按用户隔离。角色字段不意味着成员可以查看其他人的私人内容。
- 登录、凭据和资源归属依赖 PostgreSQL；登录会话、OAuth state 和密码限流依赖 Redis。`repo_type=in-memory` 不会免除这两项依赖。
- `agents/` 仍采用既有模块组织；部分 conversation 路由仍直接访问存储。技术分层是当前组织约定，不是已经由工具强制执行的完整依赖规则。
- 文件静态挂载、示例接口及开发配置接口的访问边界各不相同，不能用“整个 `/api` 都受登录保护”概括。

## 推荐接下来补写的问题

以下是尚未形成完整产品契约的议题。等对应功能有需求或实现时再建立专题，不预先创建空文档。

| 优先级与建议文件 | 在实现前必须回答的问题 |
| --- | --- |
| P0：`workspace-access.md` | 谁可创建 workspace？如何邀请、接受和撤销成员？owner 能否退出或转移？如何切换账户并轮换 session？并发撤权如何生效？私人和共享资源的边界是什么？ |
| P0：`data-lifecycle.md` | 用户、个人账户、workspace 分别如何停用或删除？哪些外键会阻止删除，哪些会级联？资源导出、保留、匿名化与清理策略是什么？ |
| P0：`file-access.md` | 哪些文件允许公开？私有上传如何绑定 account？下载使用登录校验还是限时 URL？临时文件何时清理？当前静态目录如何划分？ |
| P1：`reliability.md` | 资源与归属跨事务失败如何补偿？数据库成功但 Redis 轮换失败如何提示？哪些写入需要幂等键？如何识别与修复孤立资源？ |
| P1：`backup-recovery.md` | PostgreSQL、Redis、文件分别如何备份？恢复到不同时间点是否一致？可接受的数据丢失时间和恢复时间是多少？如何演练恢复？ |
| P1：`agent-execution.md` | 当前请求内执行何时需要改为任务队列？进程重启后如何处理运行中的 turn？工具副作用如何去重？是否需要任务取消、事件重放或断点续传？ |
| P1：`observability.md` | 用户遇到故障时提供哪个标识？指标与告警阈值是什么？日志保留多久？如何在不记录提示词、令牌等敏感内容的情况下定位问题？ |
| P2：`api-evolution.md` | 何时移除 `tenant_id` 兼容输出？接口如何版本化？错误格式、分页和兼容窗口如何统一？客户端如何得知弃用？ |
| P2：`capacity.md` | 连接池、并发 turn、模型调用与文件处理的容量上限是多少？如何压测？扩容瓶颈和配额归属在哪里？ |

P0 表示相关功能进入生产前应先明确的设计问题，不表示当前已经存在这些功能。

## 文档如何保持可信？

1. 文档中写“当前”时，应有对应源码、Schema、迁移或测试支持；没有实现的内容标为“建议”或“待设计”。
2. 流程文档负责讲规则，参考文档负责列契约，操作文档负责给步骤。相同细节使用链接，避免多处复制后相互矛盾。
3. `models` 描述目标 ORM，Alembic 描述建库与演进历史，线上结构取决于实际 migration revision；三者不能直接画等号。
4. HTTP 字段以实际挂载路由及其 OpenAPI 为准。`/docs` 的环境限制不等于 `/openapi.json` 被关闭。
5. 每个操作命令说明执行目录、前提、预期结果和写入影响；示例中不放真实密钥、真实 Cookie 或完整生产连接串。
6. 改动代码时一并更新对应专题；关键设计变化补 ADR。测试数量和第三方“最新版本”不作为长期文档事实。
7. 文档内源码链接使用相对路径，以便在本地与代码托管平台阅读。新增文件后检查链接和章节引用。

既有 [API README](../README.md)、[Agents 文档](../agents.md) 与 [部署文档](../../deploy/README.md) 继续保留；本目录提供统一阅读入口与设计解释。
