# Redis 单机与哨兵的统一连接

项目固定 `redis = "=2.0.0-rc.3"`，对应官方提交 `fee227aa921fa8da7281721744d1985a332d4841`。只支持单机和哨兵；配置及业务调用示例见 [README](../README.md#redis-异步缓存)。

## 同一个业务对象

`CacheConnection::standalone(&RedisConfig)` 和 `CacheConnection::sentinel(&RedisConfig)` 都返回 `CacheConnection`。内部连接类型不对业务公开，`app.rs::run` 根据配置选择构造函数，随后统一放入 `AppState.cache`。克隆共享底层长连接，业务只使用 `AsyncCommands`、`Cmd::query_async` 或 pipeline，无需匹配部署模式或增加外层锁。[统一连接](../src/core/cache.rs)、[创建入口](../src/app.rs)

这种边界与 FastAPI Redis SDK 的 Sentinel 用法一致：启动时选择连接方式，业务依赖仍是标准异步 Redis 客户端，所有命令默认发送到主节点。[FastAPI Redis SDK 的 Sentinel 模式](https://redis.github.io/fastapi-redis-sdk/latest/guide/configuration/#sentinel-mode)

## 1 主 2 从 + 3 哨兵

三个哨兵部署在独立故障域，每个哨兵的 `sentinel monitor` 使用相同主节点名并设置 quorum 为 `2`。客户端配置三个哨兵地址和主节点名，不配置副本地址，不自行执行投票，也不启用读写分离。quorum 和故障转移授权由 Sentinel 服务端完成。[Redis Sentinel 官方部署说明](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/)

主节点读写是连接策略，不等于强一致保证；Redis 使用异步复制，故障转移仍可能丢失已确认但尚未复制的写入。应用无需为了三个哨兵增加三个业务连接对象。

## 重连保持在连接层

单机内部使用 `ConnectionManager`，自动恢复固定地址的连接。该版本管理器只接收普通 `redis::Client`，把第一次发现的主节点直接交给它，后续只能重连旧地址，不能替代哨兵发现。[ConnectionManager 官方源码](https://github.com/redis-rs/redis-rs/blob/fee227aa921fa8da7281721744d1985a332d4841/redis/src/aio/connection_manager.rs#L290-L420)

哨兵内部保留发现能力和共享的 `MultiplexedConnection`。I/O 错误（包括超时）、`READONLY` 或 `MASTERDOWN` 会使当前连接失效；下一次调用重新查询哨兵、校验主节点角色并建连。每个哨兵独立并发发现，取首个成功结果；整轮失败后最多重试 6 轮，退避从 100 毫秒增至最多 2 秒。换代标记保护新连接不被旧请求的错误清除，正常命令在锁外执行。[哨兵实现](../src/core/cache/sentinel.rs)、[官方客户端发现规范](https://redis.io/docs/latest/develop/reference/sentinel-clients/)

失败命令保持原错误，不自动重放；业务自行决定是否重试。v2 在底层可能以 `Value::ServerError` 返回服务端错误，连接层同时检查普通错误和嵌套响应，避免漏掉 pipeline / 事务中的切主信号。当前不定期检查主节点角色，成功读取本身不作为拓扑变化信号。

连接和响应超时默认 5 秒，可通过 `socket_connect_timeout` / `socket_timeout` 覆盖；哨兵发现、角色校验和最终建连共同受每轮连接超时约束。TCP keepalive 在空闲 60 秒后探测，间隔 15 秒。支持系统根证书、PEM CA 和 mTLS；哨兵与数据节点共用 TLS 配置，两端认证独立。证书验证必须启用。[连接配置](../src/core/cache/options.rs)

`REDIS=null` 禁用缓存，启用时初始化失败阻止启动。`max_connections` 仅保留配置兼容性，业务前缀、TTL、会话与限流规则不在连接层自动执行。真实服务测试通过 `bash api-rs/scripts/test-redis.sh` 创建临时单机及 1 主 2 从 + 3 哨兵，验证重连、切主和不重放后自动清理；该脚本不覆盖 TLS/mTLS。
