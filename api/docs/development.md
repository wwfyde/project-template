# 开发与扩展指南

本文说明如何在现有结构中增加功能，以及如何验证没有破坏业务边界。运行环境和启动步骤见 [操作手册](operations.md)，文件职责见 [架构](architecture.md)。

## 1. 动手前应先确定什么？

为一项功能写下可验证的输入、输出和边界，再决定放置位置：

| 问题 | 本项目中常见的回答 |
| --- | --- |
| 谁在操作？ | 服务端已验证的 `AuthUser`；不要从请求体建立可信身份 |
| 操作哪个空间？ | 当前 session 的 `account_id`，且成员关系与账户状态有效 |
| 数据属于谁？ | 当前资源同时属于 account 和 user；共享资源必须另行定义规则 |
| 成功意味着什么？ | 数据已提交、外部动作已完成或任务已接受，三者需要明确区分 |
| 哪些步骤会失败？ | 参数校验、唯一约束、数据库、Redis、外部认证、模型、流断开 |
| 哪些动作允许重试？ | 读取与写入分别判断；凭据变更、工具副作用不能默认重复执行 |
| 是否影响兼容？ | HTTP 字段、旧 session、迁移状态、配置来源及前端类型 |

涉及新产品规则时，先更新 [业务流程](business-flows.md)；涉及难以逆转的设计选择时，记录 [ADR](decisions/README.md)。

## 2. 新增一个受保护的 HTTP 能力，代码放在哪里？

建议沿现有技术分层落地：

1. 在 `schemas/` 定义输入与公开输出。拒绝不支持的可写字段，明确是否允许 `null`，避免直接序列化凭据 ORM。
2. 在 `repositories/` 实现持久查询与事务；涉及外部服务时在 `services/` 或相应现有 adapter 中封装协议差异。
3. 在 `dependencies/` 复用身份、仓库和授权依赖。业务处理之前完成资源访问检查。
4. 在 `routes/` 定义 HTTP 路由，映射可公开的错误，并在 [路由组装入口](../src/api/routes/__init__.py) 注册。
5. 根据影响补充测试，并同步接口、数据和业务文档。

当前 `authorize_resource()` 只识别路径中的 `conversation_id` 与 `session_id`，分别检查 `conversation`、`agent_session` 归属。新增 `document_id` 等资源不会自动获得这套检查；需要显式增加对应规则或独立授权依赖。

仅添加 `CurrentUserDep` 只能证明请求来自有效用户，不能证明用户可以访问任意资源 ID。列表也必须先按权限过滤，再分页或限制条数。

参考：[dependencies/auth.py](../src/api/dependencies/auth.py)、[routes/agents.py](../src/api/routes/agents.py)、[资源授权测试](../tests/test_auth_ownership.py)。

## 3. 新增或修改数据库模型，应同步什么？

### 模型与命名

- 表名使用单数，如 `account_member`。业务实体名称与登录提供方概念保持一致。
- 使用共同的 [`Base`](../src/api/models/base.py)，并确保新模型会通过 [`models/__init__.py`](../src/api/models/__init__.py) 等实际导入路径进入 metadata。
- 明确 PK、FK、唯一约束、索引、NULL、应用默认值和数据库默认值。`default=` 与 `server_default=` 的执行位置不同。
- 删除规则需要逐个外键审查；不能从“账户是资源容器”直接推断删除用户不会影响任何资源。
- `structure` 只描述 `personal/workspace`；角色、计费套餐和登录方式分别建模。

### 迁移

新增 Alembic revision，保留已有历史 revision。生成候选迁移后核对表重命名、字段映射、回填、约束、锁和回滚条件；不能把自动生成的 drop/create 当成无损重命名。

在已经配置好的开发数据库上，从 `api/` 执行以下命令会连接该数据库并生成候选脚本：

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

提交迁移前至少回答：

- 空数据库可否沿历史迁移升级？
- 旧数据的空值、重复或不一致归属如何处理？
- Python 模型变更前后，已有应用进程是否还能写入？
- 有数据时能否降级？不能表达的新状态是否明确阻止降级？
- `_account_legacy_scope` 等迁移保留数据是否被错误当成废弃表删除？

账户迁移的验证方式可参考 [test_account_migration.py](../tests/test_account_migration.py)。它使用临时数据库/随机 schema 验证回填、拒绝不安全转换、受限回滚及 metadata 一致性；不依赖清空业务库。

## 4. 新增一种 OAuth 登录渠道，扩展点是什么？

[`OAuthProvider`](../src/api/services/auth_providers/base.py) 约定两个方法：

- `build_authorize_url(state, nonce, code_verifier, interactive=False)`：构造授权地址；`interactive` 用于绑定/重新认证场景的交互要求。
- `authenticate(code, nonce, code_verifier)`：验证上游响应，返回应用的 `ProviderIdentity`。

实施顺序：

1. 在 [`core/auth_config.py`](../src/api/core/auth_config.py) 增加强类型配置、合法值校验和 `ready` 判定。
2. 在 `services/auth_providers/` 实现 provider；把供应商特有 subject 映射为稳定标识，而不是用可变昵称或未经验证的邮箱合并用户。
3. 在 [`PROVIDER_REGISTRY`](../src/api/services/auth_providers/__init__.py) 注册工厂、方式及可用性函数。
4. 加入部署配置和 `auth.providers` 后，由现有公共登录路由使用；无需为每个渠道复制本地用户注册和 session 建立逻辑。
5. 同时测试登录、绑定和重新认证，确认错误不会泄漏上游响应或令牌。

当前配置仍要求列表包含 Google，但是否可登录取决于启用状态与凭据。`phone` 是未实现的 OTP 预留位；把它设为 enabled 不会获得短信能力。

最低验证场景：错误 state、重放、错误 nonce、subject 冲突、供应商失败、同邮箱不同用户、源 session 失效、绑定与重新认证不能跳入自动注册路径。

参考：[provider 测试](../tests/test_auth_providers.py)、[HTTP 登录测试](../tests/test_auth_routes.py)、[账户流程测试](../tests/test_account_routes.py)。

## 5. 新增 Agent backend 或业务工具，哪些协议不能改变？

新增 backend 应实现 [`AgentBackend`](../src/api/agents/contracts.py) 的 `name`、`validate()`、`stream()`、`aclose()`，在 [`runtime.py`](../src/api/agents/runtime.py) 或应用组装处注册。

需要保持的契约：

- 创建 session 时校验配置，每次开始 turn 时再次检查本地模型配置与工具注册有效性；这不包含向上游确认模型访问权限。
- stream 可以产生进度，随后必须恰好返回一次 `result` 并结束；结果的 state 必须属于该 backend。
- 关闭生成器应停止执行并回收 SDK 资源。不能让客户端断开后留下无主执行。
- 继续执行状态是内部 `BackendState`，带 backend 与版本；不通过 HTTP 直接暴露。
- 当前 OpenAI adapter 使用本地 history 续接，不同时叠加上游 conversation ID、previous response ID 或 SDK session。
- 默认组装没有业务工具。工具由服务器注册，客户端只能选择已注册名称，不能提交可执行代码。

`AgentTool.invoke` 还应自行验证具体参数和业务授权。当前 `ToolContext` 只包含 `session_id` / `turn_id`，并不自动提供可信 account/user；工具若需要访问用户业务数据，应先设计显式授权上下文或可信查询流程。

工具带有写入外部系统的副作用时，需要另外设计幂等性与审计。turn 互斥和 lease 不保证外部动作只执行一次。

示例与现有接入方式见 [Agents 专项文档](../agents.md)。关键测试见 [backend](../tests/test_agent_backend.py)、[service](../tests/test_agent_runtime.py)、[store](../tests/test_agent_store.py) 与 [HTTP/SSE](../tests/test_agents.py)。

## 6. 应如何组织验证？

依据改动选择有意义的测试，避免只复制实现细节。

| 改动 | 应验证的行为 |
| --- | --- |
| Schema / 配置 | 正常输入、边界、未知字段、敏感输入是否回显 |
| 数据模型 / 仓库 | 唯一性、外键、隔离、事务回滚、版本变更 |
| 登录 / 安全操作 | CSRF、会话期限、撤权、并发变更、渠道冲突 |
| 资源 API | 跨用户、跨 account、缺少归属映射、列表过滤先于分页 |
| Agent backend / service | 正常完成、失败、超时、取消、结果协议、lease |
| 迁移 | 有旧数据的升级、约束一致性、受限降级、真实 PostgreSQL 行为 |
| 文档 | 源码事实、链接目标、示例路径、命令目录与前提 |

在仓库根目录运行 API 测试：

```bash
uv run --no-sync pytest api/tests -q
```

`--no-sync` 假定当前环境已经安装对应依赖。首次准备环境的步骤见 [操作手册](operations.md)。

外部服务验证使用专用变量 `TEST_AUTH_REDIS_URL` 与 `TEST_ACCOUNT_POSTGRES_DSN`；未设置时相应用例跳过。内存/SQLite 测试不能代替 Redis 生命周期或 PostgreSQL 并发验收，跳过不能报告为通过。

前端契约发生变化时，在 `web/` 使用其实际 scripts：

```bash
pnpm run check-types
pnpm test
```

Python 优先使用 `uv` / `uvx`，JavaScript/TypeScript 使用 `pnpm` / `pnpx`。格式和风格以当前文件及仓库约定为准。

## 7. 日志、异常和敏感数据怎样处理？

模块使用 `logging.getLogger(__name__)`，复用应用统一 handler。日志中的 `otel.event.name` 表达业务事件，用户/account 的可信上下文由请求认证后绑定。

对外错误只输出明确可公开的信息；密码、Cookie、OAuth code、上游 token、完整配置和 provider 原始异常不写入普通日志或响应。当前账户/认证/Agent 的错误结构并未完全统一，新增端点要选择明确契约，并写入 [接口参考](api-reference.md)。

排查所需的 Request-ID、trace/span 和兼容 Tenant-ID 的含义见 [配置参考](configuration.md) 与 [操作手册](operations.md)。

## 8. 一次改动应更新哪些文档？

| 变化 | 同步文档 |
| --- | --- |
| 目录职责、组件依赖、运行边界 | `architecture.md`；重大取舍补 ADR |
| 表、字段、关系、约束、回填或删除规则 | `data-schema.md`、`operations.md` |
| 登录、授权、流程、并发、失败语义 | `business-flows.md` |
| 路径、请求响应、Header、错误 | `api-reference.md` 与前端类型 |
| 默认值、配置来源、环境差异 | `configuration.md`、示例配置 |
| 启动、迁移、部署、排错命令 | `operations.md` |

完成的判据应包括：实现符合明确的业务规则、必要检查通过、文档可以带读者找到代码和验证方式。对尚未实现的扩展，保留问题和边界，不写成已具备的能力。
