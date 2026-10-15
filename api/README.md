# API Redis 配置

项目默认使用 **FastAPI Redis SDK 0.9.0+**：业务路由直接从 `redis_fastapi` 导入 `AsyncRedisDep`，连接池由 SDK 的 `redis_lifespan` 创建和关闭。`RedisConfig` 继承 SDK 的 `RedisSettings`，使用其原生字段与校验。0.9.0 已正式提供 Sentinel 支持，见 [发布记录](https://github.com/redis/fastapi-redis-sdk/releases/tag/0.9.0) 与 [配置参考](https://redis.github.io/fastapi-redis-sdk/latest/api/configuration/#fields)。

目标 Redis 已部署且网络可达后，可修改配置并重启 API 切换以下三种模式，连接管理均由 SDK 完成。

| 模式 | `cluster` | `sentinel` | 连接目标 |
| --- | --- | --- | --- |
| 单机 | `false` | `false` | `host` / `port` 或 `url` |
| Sentinel 主从 | `false` | `true` | `sentinel_nodes` + `sentinel_master_name` |
| Cluster 分片 | `true` | `false` | `host` / `port` 或 `url`，作为入口节点 |

单机默认 `host="localhost"`、`port=6379`、`db=0`。Cluster 仅支持 DB 0；多键事务、Lua 等原子操作需要相关键处于同一个 hash slot。`cluster` 和 `sentinel` 不能同时启用。

SDK 0.9.0 的 Cluster 模式存在 `ssl=true` 参数转发问题。Cluster 使用 TLS 时，配置 `url="rediss://user:password@redis.example:6379/0"` 并保持 `ssl=false`，由 URL 启用 TLS；CA、客户端证书等选项可放在 URL 查询参数中。单机和 Sentinel 可以使用 `ssl=true`。

`AsyncRedisDep` 注入的对象本身就是 `redis-py` 异步客户端，需要原生命令时直接调用并复用同一个池。路由中不要关闭这个共享客户端；默认读取的字符串值是 `bytes`，需要文本时显式解码：

```python
from fastapi import APIRouter
from redis_fastapi import AsyncRedisDep

router = APIRouter()

@router.get("/cache/title")
async def read_title(redis: AsyncRedisDep) -> dict[str, str | None]:
    value = await redis.get("title")
    return {"title": value.decode("utf-8") if value is not None else None}
```

API 健康检查继续使用 `PING`。独立脚本也可按需直接使用 `redis.asyncio`，并自行通过 `async with redis.asyncio.Redis(...) as client:` 管理连接生命周期；API 内调用原生命令不需要另设后端开关。

## Sentinel 示例

将下列内容合并到运行目录的 `config.toml`，替换示例地址和密码：

```toml
[redis]
cluster = false
sentinel = true
sentinel_nodes = ["redis-a:26379", "redis-b", "redis-c:26379"]
sentinel_master_name = "mymaster"
sentinel_username = "default"
sentinel_password = "sentinel-password"
username = "default"
password = "redis-data-password"
db = 0
```

`sentinel_nodes` 是 `host[:port]` 字符串数组，省略端口时使用 `26379`。`sentinel_master_name` 默认 `mymaster`，必须与 Sentinel 的监控名称一致。`sentinel_username/password` 用于连接哨兵，`username/password` 用于连接 Redis 数据节点；未配置对应认证时可省略相应凭据。

哨兵模式忽略 `host/port`，禁止同时配置 `url`。客户端查询当前主节点后直接连接该数据节点，因此 API 必须能访问所有可能被提升为主节点的 Redis 地址。Redis 数据密码与 Sentinel 自身密码可以不同。[redis-py 连接说明](https://redis.io/docs/latest/develop/clients/redis-py/connect/)

相同配置也可以写入 `.env`；`REDIS_SENTINEL_NODES` 使用逗号分隔，SDK 0.9.0 不接受 JSON 数组字符串，TOML 中仍使用上面的字符串数组：

```dotenv
REDIS_CLUSTER=false
REDIS_SENTINEL=true
REDIS_SENTINEL_NODES=redis-a:26379,redis-b:26379,redis-c:26379
REDIS_SENTINEL_MASTER_NAME=mymaster
REDIS_SENTINEL_USERNAME=default
REDIS_SENTINEL_PASSWORD=sentinel-password
REDIS_USERNAME=default
REDIS_PASSWORD=redis-data-password
REDIS_DB=0
```

切入哨兵模式时，删除所有配置来源中的 `REDIS_URL` / `redis.url`。切回单机时设置 `REDIS_SENTINEL=false`、`REDIS_CLUSTER=false`，再填写 `REDIS_HOST` / `REDIS_PORT`；切入 Cluster 时设置 `REDIS_SENTINEL=false`、`REDIS_CLUSTER=true`、`REDIS_DB=0`，再填写入口地址。

## 配置优先级与生效

优先级为：**进程环境变量 > 运行目录 `.env` > TOML 配置 > 字段默认值**。TOML 按 `config.toml`、`config.dev.toml`、`config.staging.toml`、`config.prod.toml`、`config.local.toml`、`config.dev.local.toml`、`config.staging.local.toml`、`config.prod.local.toml` 的顺序合并，后面的同名顶层表整体覆盖前面的表（例如整个 `[redis]`）；当前不会根据 `APP_ENV` 自动过滤这些文件。不要在高优先级来源中残留旧模式配置。单机和 Cluster 中，`url` 内的连接参数优先于对应独立字段。

应用启动时，将按上述优先级解析的项目配置写入 SDK 配置，再进入 SDK lifespan。SDK 配置在同一进程内共用；修改后需要重启 API，不应在请求处理中修改配置。同一进程中的多个应用也共用这套 SDK 配置。

`AsyncRedisDep` 本身不读取 TOML。项目的完整路径是：`Settings` 读取 TOML → `settings.redis` → `configure_redis_sdk()` 写入 SDK 缓存配置 → `redis_lifespan(app)` 创建连接池 → 路由通过 `AsyncRedisDep` 取得该连接池的客户端。

这个顺序由 [应用 lifespan](src/api/core/lifespan.py) 保证，配置传递见 [configure_redis_sdk](src/api/core/cache.py)。只复制路由中的 `from redis_fastapi import AsyncRedisDep`，或只给一个新应用注册 SDK 自带的 lifespan，都不会自动接入本项目的 TOML。应使用 `api.main.create_app()`，或为新应用注册 `api.core.lifespan.lifespan`。

Compose 环境变量变化需要**重建容器**，例如在仓库根目录执行：

```bash
docker compose --env-file deploy/.env up -d --no-deps --force-recreate api
```

`docker compose restart api` 不会重新载入容器环境变量。当前根 Compose 仍会运行内置单机 Redis，并在 `environment` 中固定部分 Redis 字段；这些值会覆盖 `env_file` 的同名字段。连接外部 Redis 时还需检查最终 Compose 配置，相关部署约定见 [部署文档](../deploy/README.md)。

模式切换只改变 API 的连接方式，不会创建 Redis 集群或迁移数据；已有键、会话及 TTL 需要在切换目标之前单独处理。Sentinel 的“3+3”通常指 1 主 2 从加 3 个哨兵，Cluster 的“3 主 3 从”则是六个数据节点。
