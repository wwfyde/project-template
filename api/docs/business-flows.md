# 业务流程与不变量

本文回答“一个请求如何改变用户、账户和业务资源”，描述当前代码已经实现的行为。
`user` 是使用系统的人，`account` 是资源归属上下文；`account.structure` 为 `personal` 或 `workspace`。
字段、约束和表关系见 [数据模型](data-schema.md)，职责划分见 [架构设计](architecture.md)，调用方式见 [API 参考](api-reference.md)。

## 1. 首次 OAuth 登录会创建什么？再次登录会合并资料吗？

**输入与前提**：已配置且启用的 OAuth provider、浏览器会话，以及可选的站内返回路径。
目前具体 OAuth 适配器为 Google 和钉钉；能力以 `/api/auth/session` 返回的 provider 列表为准。

1. `/auth/oauth/{provider_id}/start` 生成随机 `state`、`nonce` 和 PKCE verifier。
2. Redis 保存带过期时间的授权尝试；浏览器会话保存随机标识，尝试中只保存其摘要。
3. 回调以 Redis `GETDEL` 一次性消费尝试，验证 provider 与浏览器绑定，再向 provider 验证授权码。
4. 登录解析只使用 `(provider, subject)` 查找 `user_identity`，不使用邮箱、手机号或显示名合并用户。
5. 找到身份时复用原 `user`；新身份且允许注册时，在同一数据库事务中创建 `user`、个人 `account`、`account_member` 和 `user_identity`。
6. 登录成功统一建立 Redis 会话并跳回经过清理的站内路径。

首次创建时复制 provider 的显示名、头像、邮箱和手机号。
再次登录直接返回已有用户，不把 provider 资料自动覆盖到用户自定义资料上。
同一人在两个 provider 上分别首次登录，可能产生两个独立用户；合并邮箱并非当前功能，应通过已登录状态下的显式绑定建立第二种登录方式。

**失败与不变量**：

- 过期、已消费或浏览器不匹配的 `state` 返回 `400`；授权拒绝、provider 验证失败通常重定向到带错误代码的登录页。
- 关闭注册后，已有身份仍可登录，新身份返回 `403`；停用用户不能登录。
- 并发首次登录由 provider/subject 唯一约束决定获胜事务；失败事务回滚新用户、账户和成员，再读取获胜记录。
- OAuth `link` 和 `reauth` 回调走独立路径，不进入普通注册/登录解析，不创建或切换本地用户。

源码：[登录路由](../src/api/routes/auth.py)、[用户仓储](../src/api/repositories/user.py)、[账户仓储](../src/api/repositories/account.py)。

## 2. 为什么每个用户都有个人账户？workspace 已支持到哪一步？

**默认创建**：用户创建事务调用 `create_personal_account()`，分配独立的账户 ID，设置 `structure="personal"`、`personal_user_id=user.id`，加入一条角色为 `owner` 的成员记录。
`user.id` 与 `account.id` 独立生成，不应在业务代码中互相替代。
OAuth 新用户和通过密码仓储创建的用户都走这个规则。

**账户访问前提**：

- 用户必须仍是 `account_member` 中的成员，账户必须启用。
- `personal` 账户还要求 `personal_user_id` 与当前用户相同；错误添加的其他成员不能借此访问他人的个人账户。
- `workspace` 账户允许其成员进入账户上下文；目前验证的是成员资格，没有按 `owner/admin/member` 实现分级业务操作策略。

普通登录选择个人账户；已有会话中的 `account_id` 在每次认证时重新验证。
删除成员或停用账户会使后续请求无法通过账户检查。
`AccountRepository` 已提供 `create_workspace()`、`list_for_user()` 和 `get()`，但尚无对外的账户列表、workspace 创建、切换、邀请或成员管理 HTTP 接口。
因此，模型可承载 workspace，不代表已有完整团队产品流程。

**资源不变量**：当前资源授权同时要求 `resource_owner.user_id` 和 `resource_owner.account_id` 匹配。
即使两人属于同一个 workspace，也不能读取彼此的 conversation 或 agent session。
若未来要共享资源，需要明确新增授权规则，不能只移除现有用户过滤。

源码：[账户访问条件](../src/api/repositories/account.py)、[资源归属查询](../src/api/repositories/user.py)。

## 3. 密码登录与 OAuth 登录有什么共同点和区别？

**输入与前提**：`username`、`password`；密码 provider 已启用；请求携带唯一的 `X-Requested-With: XMLHttpRequest`。
提供 `Origin` 时必须与配置的前端地址一致；`Sec-Fetch-Site: cross-site` 被拒绝。
此入口没有匿名密码注册接口，用户创建与管理员重置方式见 [运维说明](operations.md)。

1. 用户名按 ASCII、去首尾空格、小写规则规范化。
2. Redis 分别按实际连接客户端地址和规范化用户名计数；不是把二者拼成一个桶，也不直接信任调用方 `X-Forwarded-For`。
3. 同时查找用户、密码凭证和匹配的 password 身份；密码哈希验证在工作线程中执行。
4. 验证后按 `User` → `PasswordCredential` 的顺序加锁，再检查用户状态、`auth_version`、用户名及哈希快照。
5. 成功后与 OAuth 一样调用 `establish_user_session()`，轮换会话 ID 和 CSRF token，默认进入个人账户。

旧密码与并发重置后的新版本不能组合成有效登录。
哈希算法需要升级时可在登录成功后更新哈希，但不因此改变用户身份。
不存在、停用、用户名无效或密码错误统一表现为登录失败，不暴露账户是否存在。

**失败**：凭证错误为 `401`；登录来源策略不符为 `403`；限流为 `429` 并返回 `Retry-After`；认证存储或 provider 不可用为 `503`。
Redis 故障不会绕过限流或降级成匿名成功。

源码：[密码入口](../src/api/routes/password.py)、[限流依赖](../src/api/dependencies/password.py)、[密码仓储](../src/api/repositories/password.py)。

## 4. 已经有 Cookie，为什么还可能被要求重新登录？

有效 Cookie 只是认证的第一步。每次需要用户身份的请求还会检查：

1. Redis 会话可用且有效，`login_expires_at` 未到期。
2. 会话包含 `user_id`、`account_id`、provider；该 provider 当前仍启用。
3. 对应身份仍存在、用户仍启用，数据库 `auth_version` 与会话相同。
4. 当前账户仍可访问；可选身份头与服务端验证出的用户/账户完全一致。

`GET /auth/session` 对无效或匿名登录返回 `authenticated=false`；受保护接口返回 `401`。
会话存储故障返回 `503`，不会假装用户只是退出登录。
已有会话与数据库不是两个可独立信任的身份源。

写操作还需要 CSRF token；`Origin` 存在时也要校验。
退出登录撤销当前 Redis 会话，不增加 `auth_version`，不代表登出所有设备。

源码：[认证依赖](../src/api/dependencies/auth.py)、[会话配置和建立](../src/api/core/auth_session.py)。

## 5. 修改资料、绑定身份和重新验证为什么分开？

`PATCH /account/profile` 更新的是当前 **user 的显示名/头像**，即跨账户共用的个人资料。
它不修改 `account.name`、`account.structure`、邮箱或手机号。
资料编辑要求有效会话和 CSRF，但不要求近期认证，也不增加 `auth_version`。

敏感操作需要近期认证：绑定新身份、设置/修改密码、解绑身份。
是否“近期”由 `authenticated_at` 与 `reauth_max_age_seconds` 决定，可从账户读取结果的 `reauthentication` 查看剩余秒数。

| 操作 | 所需证明 | 对近期认证的影响 | 对绝对登录期限的影响 |
| --- | --- | --- | --- |
| 普通 OAuth/密码登录 | 验证登录凭证 | 记录新的认证时间 | 建立新的登录期限 |
| 密码/OAuth reauth | 验证已绑定登录方式 | 更新认证时间 | 保留原期限 |
| 绑定新 OAuth 身份 | 近期认证 + 目标 provider 证明 | 保留原认证时间 | 保留原期限 |
| 修改密码、解绑非当前身份 | 近期认证；更改已有密码另需旧密码 | 保留原认证时间 | 保留原期限 |

**绑定流程**：

1. 已登录用户发起 POST；检查近期认证，并拒绝同一 provider 重复绑定。
2. 授权尝试额外绑定 `user_id`、`account_id`、`auth_version`、当前 provider 和会话 ID 摘要。
3. OAuth 回调先检查原会话，再验证目标身份；外部往返结束后再次检查原会话仍存在且未过期。
4. 锁住用户行，检查版本、账户访问资格和全局身份冲突，新增身份并增加 `auth_version`。
5. 轮换当前会话，保留原登录 provider、认证时间、账户和绝对期限。

**不变量**：新 provider 证明“你控制目标身份”，不证明“你有权修改原用户”。
目标身份已属于其他用户时返回冲突；绑定不会合并用户或移动资源。
绑定前后的近期认证和原会话检查都必须成立。

源码：[账户路由](../src/api/routes/account.py)、[OAuth 账户流程](../src/api/services/account_oauth.py)。

## 6. reauth、修改密码、解绑怎样使旧会话失效？

**reauth** 只能使用当前用户已绑定的登录方式。
密码验证还会核对验证后的用户 ID 与版本；OAuth 要求返回的 provider/subject 正是本用户的既有身份。
成功会轮换当前会话和 CSRF token，并把 provider 更新为此次验证方式；不增加 `auth_version`。
客户端应重新读取 `/auth/session` 获取最新 token。

**设置或修改密码**：

- 第一次添加密码必须提供符合规则的 `username`，同时创建 password 身份与密码凭证。
- 已有用户名不可修改；更改密码必须提交正确的 `current_password`，即使近期已经通过其他方式 reauth。
- 新密码要求 12–1024 个字符，UTF-8 编码最多 4096 字节；用户名为 3–64 个允许的 ASCII 字符。
- 昂贵的哈希工作不持有数据库行锁；写入时重新锁定并验证快照，避免覆盖并发修改。

**解绑**：

- 至少保留一种当前启用且实际可用的登录方式，不能仅数身份记录数量。
- 删除 password 身份同时删除密码凭证。
- 解绑当前登录 provider 后撤销当前会话，响应 `requires_login=true`。
- 解绑其他身份后轮换当前会话，响应 `requires_login=false`。

绑定、密码变更、解绑都会在数据库中增加 `user.auth_version`。
其他设备的旧会话在后续请求检查时失效，不需要逐一查找 Redis 会话；管理员密码重置同样增加版本。

**事务边界**：数据库凭证修改与 Redis 会话轮换不是分布式事务。
凭证已提交后，如果原会话失效或 Redis 写失败，请求仍可能失败；不要假设失败响应意味着密码没有改动。
原版本会话不能继续认证，用户应使用变更后的可用凭证重新登录。
长时间验证不会复活已退出或超过 `login_expires_at` 的会话。

源码：[安全仓储](../src/api/repositories/user_security.py)、[近期认证和活跃会话检查](../src/api/core/account_security.py)。

## 7. 对话和消息的创建、读取与删除依据什么授权？

**前提**：会话认证成功，写操作通过 CSRF，当前账户仍可访问。
所有对话路由共用 `authorize_resource`；带 `conversation_id` 的请求先检查资源归属。
不存在和不属于当前用户/账户的资源都表现为 `404`，避免暴露他人资源。

**创建与读取**：

1. 创建时用户 ID 来自已认证会话；请求体 `user_id` 或兼容头 `User-Code` 如有提供，只能与当前用户一致。
2. 创建 conversation；默认标题为“新对话”，随后为当前用户和账户写入 `resource_owner`。
3. 列表先获取可访问资源 ID，再按更新时间倒序查询；默认排除归档记录，并携带最新消息。
4. 详情返回 conversation 与按创建时间、ID 排序的消息；消息请求中的 conversation 路径参数决定实际目标。
5. 当标题仍为“新对话”且新增 `user` 消息时，从文本或首个文本块提取首行前 120 个字符作为标题。

保存消息只是存储操作，允许 schema 定义的角色，不自动调用模型，也不自动创建 Agent turn。
`mode="agent"`/`"image"` 是对话分类，不意味着在此路由执行对应生成流程。
修改对话可更新标题、模型、endpoint、mode、归档、置顶和 meta；归档不会删除消息。
消息 schema 虽接受结构化 `content`，当前 PostgreSQL `Message.content` 仍为 `Text`，且路由直接赋值；对象/数组的持久化路径尚未对齐，不能据此宣称已支持端到端结构化消息写入。

**当前一致性边界**：

- PostgreSQL conversation 提交后才调用另一个仓储事务写归属；中间失败可能留下没有归属记录的 conversation。
- 内存模式也先写内存，再写 PostgreSQL 归属；它不是无数据库运行模式。
- 删除 conversation 会删除其消息，但此路由没有同步删除通用 `resource_owner` 记录。
- 当前没有针对上述跨存储边界的自动补偿或孤儿清理任务；新增业务应明确是否需要共享事务或补偿。

源码：[对话路由](../src/api/routes/conversations.py)、[消息模型](../src/api/models/conversation.py)。

## 8. Agent 会话和 turn 如何执行？失败是否污染后续上下文？

**输入与前提**：创建 Agent session 时给出可选 backend 和 agent 配置；执行 turn 时给出非空 `input` 与 `stream`。
会话和 turn 属于独立的 Agent 模型，不等同于 conversation/message。
运行时只注册已配置的 backend，客户端只能选择服务端注册的工具名称。

1. 创建 session 前，backend 校验模型、工具和步数等配置；保存 session 后再单独写 `resource_owner`。
2. 执行前重新验证 backend 配置和工具可用性，再原子占用 session，写入 `running` turn。
3. session 同时只允许一个未过期的执行租约；租约时长为执行超时配置加 30 秒，用于取消与收尾。
4. backend 接收上一次成功的内部 continuation state，逐步返回文本、条目和最终结果。
5. 成功将 turn 标记为 `completed`，原子保存结果与 continuation，并释放租约。
6. 超时或执行错误标记为 `failed`；取消标记为 `cancelled`。两者保留上次成功的 continuation。

运行中的 session 不能被另一个 turn 占用，也不能删除，返回 `409 session_busy`。
进程异常遗留的租约不会由后台定时器立即修复；下一次抢占时，过期旧 turn 才会被标记为 `failed/lease_expired`。
提交最终结果必须仍持有相同的 `active_turn_id`，旧执行不能覆盖新执行结果。
内部 continuation 不经 HTTP 返回。

**SSE 与取消边界**：

- `stream=false` 消费同一执行流程后返回最终 turn；执行失败可能是 HTTP `200` 携带 `status="failed"`，客户端必须读取业务状态。
- `stream=true` 在发送响应头前完成验证与租约占用；后续以 `turn.started`、增量事件及 `turn.completed`/`turn.failed` 通知。
- 流断开会关闭生成器与 backend 迭代器，并尝试持久化取消状态；尚未开始消费的 turn 也有清理路径。
- 没有独立取消 HTTP 接口，也没有 SSE 历史事件持久化、`Last-Event-ID` 重放或断线续传协议。
- 无法保证断线客户端收到终态事件；应通过 turn 查询确认。进程强杀或存储故障仍可能留待租约恢复。
- “取消”不等于撤销已经完成的外部工具副作用；需要工具自己定义幂等与补偿。

源码：[Agent 编排](../src/api/agents/service.py)、[存储与租约](../src/api/agents/store.py)、[SSE 路由](../src/api/routes/agents.py)。

## 9. 后续业务设计优先回答哪些问题？

- workspace 的创建、邀请、切换、退出和最后一个 owner 规则是什么？角色与权限如何对应？
- 哪些资源保持个人私有，哪些允许 workspace 共享？资源迁移是否改变所有者？
- conversation 与 Agent session 是否关联，模型结果由谁写入消息，如何防止重复提交？
- 资源创建与归属记录是否需要同事务？删除后的归属记录、失败记录由谁清理？
- 账号合并、邮箱变更、找回密码、全设备退出是否进入产品范围？
- 长任务是否需要后台执行、显式取消、幂等键、SSE 重放或任务恢复？

这些是待决策问题，不是已经实现的功能。设计变更应同步修改本文、[数据模型](data-schema.md) 与对应测试；验证入口见 [开发指南](development.md)。
