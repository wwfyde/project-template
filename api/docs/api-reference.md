# API 参考

本文以当前 [路由注册](../src/api/routes/__init__.py) 和 [应用入口](../src/api/main.py) 为准，解释端点用途、认证边界与主要契约。
完整字段、类型、别名、长度限制以运行实例的 `/openapi.json` 和源码 schema 为准；业务约束补充见 [业务流程](business-flows.md)。
运行实例需要配置与基础服务，不应把下列请求片段当作无需环境即可执行的演示。

## 1. 服务入口与认证约定

业务 API 前缀为 `/api`。本文表格列出完整路径，`{...}` 是路径参数。
除明确公开或 Header API Key 示例外，业务端点使用浏览器 Cookie 对应的 Redis 会话；没有用户 Bearer Token 登录协议。
`account_id` 表示当前账户；响应中的 `tenant_id` 是相同值的兼容字段。

| 标记 | 认证含义 | 写请求要求 |
| --- | --- | --- |
| 公开 | 不要求已登录用户 | 仍可能需要 Redis 或其他依赖 |
| 会话 | 有效 Redis 会话 + 用户/身份有效 + auth_version 匹配 + 账户可访问 | `X-CSRF-Token`；如有 `Origin`，必须等于配置的前端地址 |
| 资源 | 会话认证，再校验资源属于当前 user 和 account | 同上；其他用户的资源统一返回 `404` |
| API Key | 仅适用于明确挂载的 Header 认证教学接口 | 配置的专用头，默认 `X-Api-Key`；不要求 Cookie 或 CSRF |

`GET`、`HEAD`、`OPTIONS` 不要求 CSRF。需 CSRF 的请求必须提供恰好一个匹配 token。
token 来自登录响应或 `GET /api/auth/session`；重新认证、绑定、改密和解绑非当前身份后会轮换，应重新读取会话。
API Key 不产生用户身份，不能代替 Cookie 访问 account、conversations 或 agents。

### 请求头能表达什么？

| 头 | 语义 |
| --- | --- |
| `Cookie` | 浏览器会话凭证；Cookie 名称和属性由 Redis 会话配置决定 |
| `X-CSRF-Token` | 与当前会话对应的写操作防伪 token |
| `X-Requested-With: XMLHttpRequest` | 密码登录的必要来源策略，不是身份凭证 |
| `Origin` | 密码登录和会话写请求中如有提供，必须精确匹配 `auth.frontend_url` |
| `Request-ID` | 默认请求关联头；合法单值可采用，否则生成新值，不参与授权 |
| `User-ID` | 默认用户身份断言；提供时必须与服务端认证结果一致 |
| `Tenant-ID` | 默认账户身份断言，兼容旧命名；提供时必须等于当前 `account_id` |
| `Account-ID` | 账户断言；不能用于选择或切换账户 |
| `User-Code` | 仅创建 conversation/Agent session 的兼容断言；不可冒用其他用户 |
| `traceparent` / `tracestate` | 链路关联信息，不是身份或权限证明 |

请求关联头及身份头的名称可配置；`Account-ID` 是认证依赖显式检查的兼容断言。
默认响应可暴露已验证的 `User-ID`、`Tenant-ID` 和 `Request-ID`；不保证输出 `Account-ID`。
认证相关响应禁用缓存；其他已认证资源响应也设置私有、不可缓存策略。
详见 [请求上下文实现](../src/api/core/request_context.py) 和 [认证依赖](../src/api/dependencies/auth.py)。

## 2. 基础与运行状态

| 方法与路径 | 认证 | 主要输出 / 状态 |
| --- | --- | --- |
| `GET /api/health` | 公开 | `status`、Redis ping、PostgreSQL 连接状态、版本；都可用为 `200`，任一不可用为 `503` |
| `GET /api/hello` | 公开 | 固定示例 `message` 与 `data`，`200` |
| `GET /api/config` | 会话；仅非 prod 挂载 | 配置投影，`200`；用途为开发诊断 |
| `GET /api/files/{path}` | 未声明用户/资源授权依赖 | `settings.data_dir` 的静态文件；不存在为 `404` |
| `GET /openapi.json` | 公开 | 当前应用 OpenAPI；生产环境未在应用构造中关闭该入口 |
| `GET /docs`、`GET /redoc` | 公开；仅非 prod | 交互式接口文档 |

`/api/files` 是静态目录挂载，不适用 conversation 的 `resource_owner` 规则。
文件上传、文件所有者校验和私有文件下载不是该挂载已经提供的能力；不要把私有材料存放到公开静态路径后假设它受到用户登录保护。
部署与配置详见 [运维说明](operations.md)。

## 3. 登录与退出

| 方法与路径 | 认证 | 关键输入 | 成功结果 |
| --- | --- | --- | --- |
| `GET /api/auth/session` | 公开，可读取现有会话 | Cookie 可选 | `200 AuthSessionResponse` |
| `POST /api/auth/password/login` | 公开；密码登录策略 | `username`、`password`；必须有 `X-Requested-With` | `200 AuthSessionResponse`，轮换 Cookie |
| `GET /api/auth/oauth/{provider_id}/start` | 公开 | provider；可选 `return_to`，默认 `/` | `303` 跳转 provider |
| `GET /api/auth/oauth/{provider_id}/callback` | OAuth 浏览器绑定 | `state`；`code` 或钉钉 `authCode`；可选 `error` | 通常 `303` 跳回前端 |
| `POST /api/auth/logout` | 可选会话 | 若当前会话非空，仍需 CSRF | `204`，撤销当前会话 |

`AuthSessionResponse` 包含 `authenticated`、`user`、`providers`、`csrf_token`。
未认证时 `user` 和 `csrf_token` 为 `null`；provider 列表含 `enabled`、`implemented`、`method`、可选 `start_path`。
`AuthUser` 包含稳定用户 ID、当前 provider、个人资料、`account_id` 和兼容字段 `tenant_id`。
`authenticated=false` 是正常的会话探测结果；存储故障则返回 `503`。

OAuth 还保留 `/api/auth/{provider_id}/start`、`/api/auth/{provider_id}/callback` 兼容别名，未出现在 OpenAPI。
新客户端使用带 `/oauth/` 的规范路径。回调由 provider/浏览器流程驱动，不应手工拼造 state 或授权码。

常见失败：`400` state/回调输入错误，`401` 密码登录失败，`403` 来源策略或禁止注册，`429` 限流，`503` provider/认证存储不可用。
OAuth 授权拒绝/验证失败也可能通过 `303` 携带前端错误 query 表达。
无公开 `/register`、`/forgot-password`、短信 OTP 登录或全设备退出接口。

源码：[auth schema](../src/api/schemas/auth.py)、[OAuth 路由](../src/api/routes/auth.py)、[密码路由](../src/api/routes/password.py)。

## 4. 当前用户与账户安全

下列端点都要求会话认证；所有写操作要求 CSRF。
名称 `/account` 包含“当前账户视图”和“当前用户凭证管理”，不代表凭证属于 workspace。

| 方法与路径 | 关键输入 | 成功结果 / 附加条件 |
| --- | --- | --- |
| `GET /api/account` | 无 | `200 AccountRead`：account、user、identities、providers、reauthentication |
| `PATCH /api/account/profile` | `display_name` 或 `avatar_url`，至少一项 | `200 AccountRead`；更新用户资料，头像可设为 `null` |
| `POST /api/account/identities/{provider_id}/start` | OAuth provider | `200 {authorization_url}`；需近期认证，provider 尚未绑定 |
| `POST /api/account/reauth/oauth/{provider_id}/start` | 已绑定 OAuth provider | `200 {authorization_url}`；去该 provider 重新验证 |
| `POST /api/account/reauth/password` | `password` | `200 AuthSessionResponse`；已绑定密码方式，轮换会话 |
| `PUT /api/account/password` | `password`；首次需 `username`；已有密码需 `current_password` | `200 {requires_login:false}`；需近期认证 |
| `DELETE /api/account/identities/{identity_id}` | 身份记录 ID | `200 {requires_login}`；需近期认证且保留可用登录方式 |

`account.structure` 为 `personal` 或 `workspace`；这些接口不修改 structure。
`identities[].enabled/current/can_unlink` 是界面提示，服务端实际修改时仍重新验证。
`reauthentication` 返回 `required` 与 `expires_in`。
解绑当前登录方式时 `requires_login=true`；前端应进入登录流程。
账户 OAuth 回调复用 `/api/auth/oauth/{provider_id}/callback`，通过服务端保存的 `intent` 识别绑定或重新验证。

常见结构化错误为 `{"detail":{"code":"...","message":"..."}}`：

| 状态 | 典型 code | 客户端处理 |
| --- | --- | --- |
| `400` | `current_password_required`、`invalid_current_password` | 补充/修正当前密码 |
| `401` | `session_changed`、`account_unavailable` | 重新探测会话或登录 |
| `403` | `reauthentication_required`、`reauthentication_failed`、`identity_not_linked` | 验证已绑定登录方式或修正操作 |
| `404` | `identity_not_linked` | 刷新账户身份列表 |
| `409` | `account_changed`、`identity_conflict`、`provider_already_linked`、`last_login_method`、`username_conflict` | 刷新状态并处理冲突，不能盲目重试 |
| `422` | `invalid_username`、`invalid_password`、`username_required`、`username_immutable` | 修正字段 |
| `503` | `provider_unavailable` 或认证存储失败 | 检查依赖；凭证写入可能已提交，必要时重新登录 |

普通身份认证/CSRF错误的 `detail` 也可能是字符串，不应假设所有错误都是统一对象。
安全字段验证错误会去掉输入回显，避免响应包含密码。
源码：[账户 schema](../src/api/schemas/account.py)、[账户路由](../src/api/routes/account.py)。

## 5. 对话和消息

所有端点要求会话；包含 `conversation_id` 的端点还要求资源归属。列表按当前用户和账户过滤。

| 方法与路径 | 关键输入 | 成功结果 |
| --- | --- | --- |
| `GET /api/conversations` | `limit=50`，范围 1–100；`include_archived=false` | `200 ConversationRead[]`，更新时间倒序 |
| `POST /api/conversations` | 可选 title、endpoint、model、mode、is_pinned、meta | `201 ConversationRead`；mode 默认 `agent` |
| `GET /api/conversations/{conversation_id}` | ID | `200 ConversationDetail`，包含 messages |
| `PATCH /api/conversations/{conversation_id}` | 需更新的 title、endpoint、model、mode、is_archived、is_pinned、meta | `200 ConversationRead` |
| `DELETE /api/conversations/{conversation_id}` | ID | `204` |
| `GET /api/conversations/{conversation_id}/messages` | ID | `200 MessageRead[]` |
| `POST /api/conversations/{conversation_id}/messages` | 必填 role；可选 content、text、messageId、parentMessageId 等 | `201 MessageRead` |

`role` 为 `system/user/assistant/tool`；`mode` 为 `agent/image`。
请求 schema 的 `content` 接受字符串、对象、对象数组或 `null`；但当前 PostgreSQL 列为 `Text`、路由未转换，对象/数组写入尚未对齐。字符串是当前持久化类型匹配的路径。
存储消息不会自动调用模型。
消息输入支持部分 camelCase 别名，输出也存在混合字段命名，应以 OpenAPI 的请求与响应 schema 分别建模。
消息体中的 `conversationId` 不决定目标；路径参数决定实际 conversation。
若创建对话时提供 `user_id`，必须等于当前用户；新客户端通常无需传它。

主要错误：认证 `401`、CSRF或所有者断言 `403`、资源不可访问 `404`、字段验证 `422`。
数据库约束、事务与归属记录的一致性边界见 [数据模型](data-schema.md) 和 [业务流程](business-flows.md)。
源码：[对话 schema](../src/api/schemas/conversation.py)、[对话路由](../src/api/routes/conversations.py)。

## 6. Agent 会话、turn 与流式响应

所有 Agent 端点要求会话；包含 `session_id` 的端点要求该 Agent session 的资源归属。
这里的 `session` 是 Agent 对话运行状态，与登录会话不同。

| 方法与路径 | 关键输入 | 成功结果 |
| --- | --- | --- |
| `GET /api/agents/backends` | 无 | `200 {default, available}` |
| `POST /api/agents/sessions` | 可选 backend、agent 配置 | `201 AgentSession` |
| `GET /api/agents/sessions/{session_id}` | ID | `200 AgentSession` |
| `DELETE /api/agents/sessions/{session_id}` | ID | `204`；运行中不能删除 |
| `POST /api/agents/sessions/{session_id}/turns` | `input`，可选 `stream=false` | `200 AgentTurn` 或 SSE |
| `GET /api/agents/sessions/{session_id}/turns` | `limit=50`，范围 1–100 | `200 AgentTurn[]`，创建时间与 ID 倒序 |
| `GET /api/agents/sessions/{session_id}/turns/{turn_id}` | session 与 turn ID | `200 AgentTurn` |

`agent` 包含 name、instructions、model、tools、max_steps；tools 只接受服务端已注册的工具名称。
`AgentTurn.status` 为 `running/completed/failed/cancelled`，结果包含 output、items、usage、error 和时间。
backend 续接状态不在 HTTP 返回中。当前没有 session 列表、修改 agent 配置或独立取消 turn 的接口。

流式请求仍使用 POST 和 JSON 请求体；需要可发送 Cookie、CSRF 与请求体的流读取方式，不能直接用仅发 GET 的浏览器 `EventSource` 调用。
SSE 一条事件的格式为：

```text
id: <turn_id>:<sequence>
event: <event_type>
data: <AgentEvent 的 JSON>

```

事件类型：`turn.started`、`output_text.delta`、`item.completed`、`agent.updated`、`turn.completed`、`turn.failed`。
序号在单次执行中递增；事件 ID 不代表服务器支持重放，当前不实现 `Last-Event-ID` 续传。
发送响应头前的验证失败使用正常 HTTP 错误，例如 `404`、`409 session_busy`、`503 backend_unavailable`。
开始执行后的失败写入 turn：非流式可能为 `200 + status=failed`，流式为 `turn.failed`；持久化故障也可能中断响应。
流断开后可查询 turn 终态；没有 `turn.cancelled` SSE 事件，取消行为见 [业务流程](business-flows.md)。

源码：[应用契约](../src/api/agents/contracts.py)、[Agent 路由](../src/api/routes/agents.py)。

## 7. 哪些接口只是开发教学？哪些代码没有挂载？

Header 示例 `/api/examples/auth-header/ping`（GET）与 `/api/examples/auth-header/echo`（POST，body 为 `message`）只检查配置的 API Key，不依赖用户会话。
它们在非 prod 可访问；prod 返回 `404`。未启用 Header 认证为 `503`，凭证缺失/错误为 `401` 并带 `WWW-Authenticate: ApiKey`。

其余 `/api/examples` 路由统一要求用户会话及写请求 CSRF；生产环境禁止访问。
依赖解析可能先返回 `401`，已通过认证后才执行环境拒绝 `404`，因此“开发专用”不等于“匿名可访问”。

| 路径（均加 `/api/examples`） | 方法 | 教学内容 / 额外要求 |
| --- | --- | --- |
| `/misc` | GET | 杂项示例 |
| `/otel/trace`、`/otel/propagation` | GET | trace 演示、传播头；trace 的 `fail=true` 演示失败 |
| `/cache/demo` | GET | Redis 直接访问 |
| `/cache/conversations/{conversation_id}` | GET、PATCH | Cache-aside 读取、改名；PostgreSQL 与资源授权 |
| `/cache/conversations/batch` | POST | 批量读取；校验每个 conversation 的归属 |
| `/cache/conversations/{conversation_id}/hot` | GET | 热点缓存；PostgreSQL 与资源授权 |
| `/cache/rate-limit/{subject}` | POST | Lua 原子限流 |
| `/cache/structures/{demo_id}` | POST | Redis 数据结构与事务 |
| `/cache/sdk/cache` | GET、DELETE | SDK 响应缓存读取/失效 |
| `/cache/sdk/cache/refresh` | POST | SDK 响应缓存刷新 |
| `/cache/sdk/cache-backend/conversations/{conversation_id}` | GET、DELETE | SDK 模型缓存；资源授权 |
| `/cache/sdk/rate-limit` | GET | SDK 限流 |
| `/cache/sdk/session`、`/cache/sdk/session/required`、`/cache/sdk/session/rotate` | 源码有 GET/PUT/DELETE/POST | 主应用主动阻止整个 session 示例路径，已认证请求仍为 `404` |

SDK session 示例在主应用中被拦截，以免教学代码旋转或撤销真实登录会话。
部分端点依赖真实 Redis/PostgreSQL，需按 [开发指南](development.md) 准备环境；它们不是隔离的内存 mock。
`routes/editor.py` 当前为空且没有被注册；工具模块、SDK samples、仓储方法也不会自动成为 HTTP 端点。
workspace 创建/切换/邀请、用户注册/找回密码、独立图片生成等不能从源码文件名推断出已存在 API。

新增端点时先定义认证、资源归属、成功/失败语义与是否进入 OpenAPI，再同步本文；层间职责见 [架构设计](architecture.md)。
