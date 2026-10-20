# 0001. 分离 User 与 Account，保留 account/auth 技术分层

状态：已实施；按当前代码补录。

## 背景与约束

系统需要支持同一个人使用多种登录方式，并为个人使用与后续团队空间提供共同的资源隔离模型。旧实现的用户包含单一 `tenant_id`，新用户可共享默认 tenant；认证表使用 `auth_` 前缀，account 主要表示资料和安全设置页面。

如果直接把旧默认 tenant 转成一个 personal account，会把本来独立的用户空间并在一起。如果把 Account 定义成 OAuth 凭据，又难以用同一术语表示个人或团队资源容器。

代码组织沿用 `routes / schemas / models / core` 等技术层，不要求把账户和认证整体集中在纵向业务目录。已有 Redis session、密码、OAuth、资源访问控制及未提交功能需要保持其安全语义。

## 决策

1. `user` 是全局用户及认证主体，`account` 是资源空间；通过 `account_member` 多对多关联。
2. `account.structure` 默认 `personal`，允许 `workspace`。账户结构不承担角色、登录渠道或商业套餐的含义。
3. 新用户、登录身份/凭据、独立个人账户与 owner 成员关系在同一数据库事务内创建。
4. `user_identity` 保留供应商 subject 映射，`password_credential` 保留本地密码哈希。增加或删除登录方式不改变 user ID。
5. 资源归属通过 `resource_owner(account_id, user_id)` 检查。当前 conversation 与 agent session 继续按用户私有；workspace 不是自动共享开关。
6. session 与 OAuth attempt 使用 `account_id`；需要用户身份的请求检查成员关系和账户状态。旧 tenant 命名仅保留于兼容输入输出、追踪、弃用配置及迁移备份，不再决定新用户归属。
7. account/auth 实现分布到技术层。`AccountRepository` 管空间，现有 `AccountStore` 位于 `user_security.py`，管理全局用户资料与登录方式。

## 考虑过的方案

| 方案 | 收益 | 未采用或限制的原因 |
| --- | --- | --- |
| 用户只持有一个 account/tenant 外键 | 初始查询较简单 | 不适合一人多个空间，切换空间与成员管理受限 |
| 个人数据挂 user，团队数据另挂 workspace | 个人使用容易起步 | 每个业务模块都需要区分两种归属路径 |
| Account 表示 OAuth 登录凭据 | 与某些认证库术语接近 | 与本项目资源账户含义冲突；身份与资源容器仍需分开 |
| 所有旧 default tenant 合成一个账户 | 回填步骤较少 | 会错误合并独立用户空间 |
| account/auth 整体放入独立业务目录 | 业务文件集中 | 与当前项目选择的技术分层不一致，也不能自动解决跨层依赖 |

## 结果与代价

个人与团队共用一种账户实体；认证身份不依赖当前空间。数据库约束保证结构取值、个人账户所属用户唯一及成员记录唯一；应用进一步限制 personal 仅所属用户可访问。

代价是每次认证需要查询用户、账户及成员关系，注册需要创建多条记录。ORM 关系、数据迁移和 session 格式需要同步更新。

本次不实现 workspace 切换、邀请、owner 转移、完整角色权限或计费。角色存储不意味着这些操作已经受角色策略管理。

当前删除策略也不等于完整产品注销流程：个人账户的用户外键使用 `RESTRICT`，成员和资源映射上的其他外键包含 `CASCADE`。删除与资产保留需要单独设计，见 [数据模型](../data-schema.md)。

## 迁移与验证

迁移 `e28b47a1d902` 重命名旧认证表，为每个用户回填独立 UUID personal account 和 owner membership，并按已核实的原用户归属填充 `resource_owner.account_id`。

旧资源与用户的 tenant 不一致时拒绝升级。`_account_legacy_scope` 保留旧 tenant 映射以支持回滚。新增 workspace、资源重新归属或其他旧模型不能表达的状态会阻止降级。

升级和降级递增 `auth_version`。旧 tenant-only session 不作为账户上下文继续使用，部署后用户需要重新登录。旧 `auth.default_tenant_id` 配置可被读取，但不再决定新用户归属。

验证涵盖个人账户分离、注册事务回滚、workspace 内按用户隔离、成员移除或账户禁用、OAuth/密码安全变更、受限迁移回滚及 PostgreSQL 并发行为。

## 重新评估条件

- 产品需要共享资源或细粒度角色权限，而不仅是账户成员资格。
- 增加 workspace 切换、邀请、个人空间迁移、用户注销或 owner 转移。
- 成员查询成为可测量的性能瓶颈，需要带撤销语义的缓存或新的上下文模型。
- 要统一资源和归属写入，避免当前跨事务孤立记录。
- API 进入兼容弃用阶段，需要移除 `tenant_id` 输出或替换旧追踪字段。

## 依据

- [架构](../architecture.md)、[业务流程](../business-flows.md)、[数据模型](../data-schema.md)
- [Account 模型](../../src/api/models/account.py)、[成员模型](../../src/api/models/account_member.py)
- [账户仓库](../../src/api/repositories/account.py)、[用户与资源仓库](../../src/api/repositories/user.py)
- [认证依赖](../../src/api/dependencies/auth.py)、[会话建立](../../src/api/core/auth_session.py)
- [迁移](../../alembic/versions/e28b47a1d902_user_accounts.py)、[迁移测试](../../tests/test_account_migration.py)、[资源隔离测试](../../tests/test_auth_users.py)
