# 用户与账号

本项目以 `user` 和 `account` 为核心，区分登录的人、资源所属空间、登录身份和个人展示资料。数据库表名使用单数。

设计参考：[User 与 Account 的职责分析](https://share.gemini.google/6WBV0EEEGuSz)，采用其中个人与团队空间共用 Account 的模型。

## Language

**User（用户）**：全局稳定的自然人及认证主体，对应 `user` 表。增加或移除登录身份不会改变 `user_id`；用户通过成员关系参与一个或多个账户。
_Avoid_: 用 Profile 表示用户主体。

**Account（账户）**：资源归属与隔离容器，对应 `account` 表。`structure` 默认为 `personal`，也支持 `workspace`。每个新用户在注册事务中获得一个独立的个人账户；团队空间是另一个账户，不覆盖个人账户。
_Avoid_: 用 Account 表示 OAuth 身份或密码凭据，或用套餐名表示账户结构。

**AccountMember（账户成员）**：`account_member` 连接用户和账户，支持一人多个空间、一个 workspace 多个成员，角色为 `owner`、`admin`、`member`。个人账户仅其所属用户可访问。
_Avoid_: 只凭客户端传来的 `account_id` 授予权限。

**Identity（登录身份）**：某个身份提供方已验证、且绑定到一个用户的登录身份，对应 `user_identity`。一个外部身份不能同时属于多个用户；本地密码单独存于 `password_credential`。
_Avoid_: 将邮箱相同视为同一个 Identity，或把新登录方式当成新的 User。

**Profile（个人资料）**：用户的显示名称、头像等展示信息，不承担登录凭据或权限证明的作用。
_Avoid_: 将密码、账户成员关系或登录身份绑定归入 Profile。

**资源归属**：`resource_owner` 记录 `account_id` 与 `user_id`。当前 conversation 和 agent session 即使处于同一 workspace，也仍按用户私有；成员角色不隐含读取其他成员聊天的权限。

**账户上下文**：Redis session 使用 `account_id`，每次请求校验成员关系和账户状态。响应 `tenant_id` 与追踪头 `Tenant-ID` 暂作兼容别名，其值就是当前 `account_id`，不再表示用户固定归属的租户。

## 组织方式

`api/src/api` 沿用技术分层：`routes` 承接 HTTP，`schemas` 定义数据契约，`models` 定义 ORM，`repositories` 处理数据库事务，`services` 适配 OAuth，`dependencies` 组合请求依赖，`core` 提供配置与会话安全，`cli` 提供管理命令。account/auth 的代码分布在这些层中。

**账号绑定**：将经过验证的登录身份关联到当前用户。已被其他用户占用的身份属于冲突，不自动合并两个用户及其资源。
_Avoid_: 将账号绑定与账号合并混用。
