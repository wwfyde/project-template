"""Redis + PostgreSQL 教学示例：从缓存旁路到并发、批量和原子操作。

阅读顺序
========
1. ``read_conversation``：GET → 未命中查询数据库 → SET EX（Cache-Aside）。
2. ``rename_conversation``：数据库事务提交成功 → DEL，让下一次读重建缓存。
3. ``read_conversations``：pipeline 批量读 → SQL IN 批量回源 → pipeline 回填。
4. ``read_hot_conversation``：SET NX EX 抑制热点重建，Lua 校验锁持有者。
5. ``check_rate_limit``：Lua 原子计数 + TTL，实现固定时长窗口限流。
6. ``use_data_structures``：Hash / Set / List / Sorted Set，以及 MULTI/EXEC。
7. ``read_sdk_response`` / refresh / evict：SDK 响应缓存及限流依赖的组合。
8. ``read_sdk_model``：CacheBackendDep 配合 PostgreSQL/Pydantic。
9. ``sdk_rate_limited``：SDK rate_limit 依赖、429、故障策略与响应头。
10. ``read_sdk_session`` 等：匿名偏好会话、Cookie、有效性检查、轮换与退出。

运行前提与试用
==============
- 使用 ``fastapi-redis-sdk`` 的 ``redis_fastapi.AsyncRedisDep`` 和项目的
  ``api.deps.PostgresDep``；Redis 连接池由 SDK lifespan 管理，应用已通过
  ``FastAPIRedis(app).lifespan()`` 注册。路由里不要创建/关闭共享客户端，不要使用
  ``async with redis``。pipeline 是请求私有的，可以用 async with。
- SDK 使用自身的 REDIS_* 环境变量/.env 配置，不会自动使用项目自定义的
  ``api.core.cache.get_redis_client()`` 或其 ``settings.redis_dsn``。
- 数据库示例使用已有的 ``conversation`` 表，不自动建表；先配置 PostgreSQL、
  执行项目迁移并设置 ``REPO_TYPE=postgres``。这些示例不使用会话路由的内存数据。
- 当前路由挂载后前缀为 ``/api/examples/cache``。在 dev/local 环境启动 API，
  可在 /docs 操作；生产环境请求返回 404。示例没有接入登录/租户权限，仅供本地教学。
- 先通过 ``POST /api/conversations`` 创建会话（请求体如 {"title":"Redis 入门"}），
  记下返回的 UUID，替换下列命令中的 <id>；服务端口按实际配置替换：

  curl http://localhost:8000/api/examples/cache/conversations/<id> -i
  # 连续读两次：X-Cache 通常由 MISS 变为 HIT。
  curl -X PATCH http://localhost:8000/api/examples/cache/conversations/<id> \
      -H 'Content-Type: application/json' -d '{"title":"提交后失效"}' -i
  curl -X POST http://localhost:8000/api/examples/cache/conversations/batch \
      -H 'Content-Type: application/json' -d '{"ids":["<id>"]}'
  curl http://localhost:8000/api/examples/cache/conversations/<id>/hot -i
  curl -X POST http://localhost:8000/api/examples/cache/rate-limit/demo -i
  curl -X POST http://localhost:8000/api/examples/cache/structures/<id>

设计约定
========
- 数据库是事实来源，Redis 保存可重建的投影。只缓存展示所需字段，不缓存整个 ORM
  对象、密码、令牌或任意 pickle；JSON + Pydantic 使结构可检查、可演进。
- 本例使用 Cache-Aside，由应用决定何时读写缓存。Write-Through 要把写数据库与
  写缓存封装进统一写路径，但仍要处理双写失败；Write-Behind 先写缓存再异步落库，
  涉及丢数据、重试和顺序问题，不适合作为普通业务默认方案，也不在本例实现。
- key 包含项目/环境/用途/版本；修改序列化结构时升级 v1。多租户接入时还要加入
  可信 tenant_id，先鉴权再查缓存，不能把请求中自报的 user_id 当成权限证明。
  当前只按会话 ID 缓存，故不得直接复制为生产私有数据接口。
- 数据 TTL 为 300~360 秒；不存在的记录缓存 JSON null 30~35 秒，减少穿透。
  Redis 返回 None 是未命中，JSON null 是已命中的“不存在”，不能用 truthiness
  混淆。数据库异常不属于“不存在”，绝不写入负缓存；新建同 ID 也需主动失效。
- TTL 抖动分散过期时刻，不能防单个热点击穿；热点锁减少同时回源，不能替代容量
  规划。缓存雪崩还需数据库限流、并发隔离、熔断和按业务允许的旧值兜底。
- 可选缓存的 Redis 错误/超时记录日志并降级到数据库；数据库错误正常向上抛出。
  限流/Redis 数据结构示例依赖 Redis 的语义，故 Redis 不可用返回 503。
  示例每段 Redis I/O 有 300ms 预算；生产应根据延迟目标配置连接超时、命令超时、
  有界重试和池大小。超时不代表命令没执行，INCR/列表追加等不得无脑重试。
- AsyncSession 是有状态的事务对象，不要在 asyncio.gather 中共享同一个 session；
  本例用一次 SQL IN 消除批量读取的 N+1。缓存命中不会执行 SQL。

一致性：务必理解的边界
====================
- 先提交 DB 再删缓存：提交失败时保留旧缓存；删缓存失败时 DB 可能已经成功，
  本例通过日志和 X-Cache-Invalidated 暴露失败，依靠 TTL 最终淘汰旧值。
  所有新增、修改、删除、软删除入口都必须失效同一投影；现有 /api/conversations
  及其他 SQL 写入尚未接入本示例失效逻辑，经那些入口写入可能读到 TTL 内的旧值。
- “读旧 DB → 写请求提交并 DEL → 读请求把旧值 SET 回去”仍可能发生；缓存重建锁
  不会让 DB 与 Redis 成为一个事务，普通读、批量读和外部写入口也不共享该锁。
  TTL 约束的是每次回填后的寿命，不是从 DB 提交起算的严格陈旧时间上界。
- 需要可靠失效时，在同一 DB 事务写业务数据与 outbox 事件，由独立 worker 重试
  删除/更新缓存；消费者要幂等。CDC 也是选择。仅使用 BackgroundTasks、进程内
  sleep 后“双删”或发布 Pub/Sub，都不能保证崩溃后补偿，也不能消除全部读写竞态。
  乱序更新需要单调版本检查；强一致读直接走数据库。余额/库存约束与幂等键放 DB。
- 锁采用随机 token + 租约 TTL + compare-and-delete，避免旧持有者删掉新锁；
  回填时也校验 token。租约到期、主从切换仍可能出现多个执行者，所以本例的锁
  只优化缓存回源，不用于支付、唯一执行或跨系统互斥。需要时使用 DB 锁/约束及
  fencing token（由被保护资源验证的单调令牌），不能只延长锁 TTL。

其他常见用法与运维
==================
- Session/验证码：通常 String/Hash + TTL；一次性消费可用 GETDEL（Redis 6.2+），
  需要“验证正确才删除”时用短 Lua 原子比较和删除，另外限制尝试次数。
- 幂等：SET NX EX 只能作短期去重提示；涉及落库的幂等必须在 DB 使用唯一约束，
  持久化请求摘要、状态和结果，并在一个事务内完成，避免“占位成功但业务未提交”。
- 队列：List 的简单 POP 缺少确认/重领。可靠消费可考虑 Streams 的 XREADGROUP /
  XACK / XAUTOCLAIM，并由 DB 唯一键去重；ACK 应在业务提交之后。Streams 本身不
  提供跨数据库的 exactly-once，也不自动解决 Redis 持久化/故障转移的数据丢失。
  Pub/Sub 适合允许丢失的即时通知，离线订阅者不会补收，不适合作唯一失效渠道。
- 扫描：运维用 SCAN/scan_iter(match=前缀, count=200)，不用 KEYS * 或 FLUSHDB。
  COUNT 是提示而非上限，SCAN 可能重复且不是一致性快照；Cluster 要确认扫描了
  所有主节点。大 value 可用 UNLINK 异步释放内存，批量处理也要限制每批大小。
- Cluster：相关 Lua/事务 key 需要同一 hash slot，本例用 {conversation:<id>}
  或 {structures:<id>} hash tag；不同 ID 保持分散。不要为整个应用固定一个 tag。
  跨槽批读使用 pipeline 的逐键 GET，不能直接把任意 ID 交给 MGET。
  SDK 按配置注入单机/Sentinel 的 Redis 或分片模式的 RedisCluster；切换时仍需
  配置对应模式，不能只把单机地址替换为 Cluster 节点地址。
- 生产监测命中率、回源 QPS、P95/P99、缓存错误、失效失败、锁竞争、内存与淘汰；
  设置 maxmemory/淘汰策略、ACL/TLS，避免大 key/无限集合。缓存数据与会话、锁、
  队列等状态最好按可靠性需求隔离部署；Redis DB 编号不是安全或资源隔离边界。

SDK 原生用法：/api/examples/cache/sdk
====================================
- 下半部分基于已安装的 fastapi-redis-sdk 0.9.0。cache / cache_put / cache_evict /
  rate_limit / valid_session 都是 Depends 工厂，不是 @cache 函数装饰器；当前包
  的限流函数名是 rate_limit，不是 rate_limiter。Session 通过 SessionDep 注入。
- main.py 在已有 .lifespan().caching() 后调用 configure_sdk_examples(app)，
  仅 dev/local 注册 .rate_limiting().sessions()。注册顺序让会话先加载，限流头在
  HTTP 缓存捕获层之外生成。全局自动限流在这份教学配置中跳过，仅显式路由依赖
  消耗额度；Session middleware 只处理 /sdk/session 及其子路径。
- SDK 默认 TTL 可能是 0（不过期），因此示例总是显式设置正 TTL。SDK 的网络预算
  由其配置负责，不自动使用上半部分的 REDIS_BUDGET_SECONDS；按部署设置
  REDIS_SOCKET_CONNECT_TIMEOUT、REDIS_SOCKET_TIMEOUT 和 REDIS_MAX_CONNECTIONS。
- cache() 缓存成功 HTTP 响应，命中时跳过 endpoint 及后续依赖。因此开发环境检查、
  认证/授权、限流必须排在 cache 前；不能只在 endpoint 内鉴权。private=True 仅
  影响 HTTP Cache-Control，不会隔离 Redis 中的用户数据。Session 个性化页面还要
  正确使用 vary_on_session=True 与可靠身份来源；本例只缓存与用户无关的时间样本。
- 默认 key 包含路径和查询参数，不自动包含身份、请求体或任意请求头。本例 HTTP
  样本没有变化参数，用同一个 key_builder 让 GET、POST refresh、DELETE 操作相同
  key；真实接口须把所有影响结果的参数、租户、语言/版本等纳入 key。
- cache_put 总会执行 endpoint，再尝试存响应；cache_evict 在 endpoint 成功后尝试
  失效。遇到 Redis 错误 SDK 会记录日志并降级，不保证一定刷新/删除成功。DB 写入
  必须在 endpoint 返回前提交，不能把提交推迟到依赖清理阶段；需要可靠失效时仍用
  outbox/CDC。不要裸用 cache_evict()：省略 key_builder 和 group 会扩大清理范围。
- HTTP 缓存条目与 CacheBackend 的业务 JSON 是两种格式，不能共用同一个完整 key。
  CacheBackendDep 默认 JsonCoder，模型请 model_dump(mode="json") 后存、取出后
  model_validate；也可在自定义 Depends 里构造带 pydantic_model_coder 的 CacheBackend。
  SDK 对象缓存是独立投影，其他写入口同样需要失效它；本例提供单独 DELETE 演示。
- Session 只存匿名 theme/language，Cookie 只携随机 ID，不回显 ID。首次 GET 不创建
  空会话；PUT 的修改由 middleware 在响应开始前保存。中间件写入失败默认返回500，
  endpoint 内 try/except 无法捕获该阶段，也不会撤回已提交的数据库事务。
- 示例 Cookie 使用 SDK 配置的名称、HttpOnly、SameSite=lax 和仅 Session 路径，
  为本地 HTTP 设 Secure=False；生产应使用 HTTPS/Secure、独立 Cookie 名及正确的
  CSRF/鉴权机制。Path 是浏览器发送范围，不是访问控制；不从客户端接收 user_id。
  不要在本地配置 __Host-/__Secure- 前缀 Cookie 名，这些前缀要求 HTTPS 等属性。
- Session 空闲期限 300 秒、绝对期限 1800 秒；读取默认刷新空闲期限，不重置绝对
  期限。valid_session 只检查会话存在且有效，匿名会话也可通过，它不是登录校验。
  默认 REDIS_SESSION_FAIL_CLOSED=false 时，加载故障交由本例门禁返回503；若显式
  启用该配置，中间件会提前抛 SessionStoreError，默认返回500，需要另设中间件错误处理。
  rotate 撤销旧 ID 并产生新 ID，也重置绝对期限；生产应在完成认证/权限变化后使用，
  不应允许匿名请求借轮换无限延长认证会话。这里的手动轮换仅用于观察匿名偏好。
  SDK 可通过 principal_keys 自动检测真实身份变化；嵌套 dict 修改需重新顶层赋值。

试用顺序（第一次可不依赖 PostgreSQL）::

  curl -i http://localhost:8000/api/examples/cache/sdk/cache
  # 再读 nonce 不变；缓存命中仍消耗限流额度。GET 每 IP 每窗口 5 次，超额 429。
  curl -i -X POST http://localhost:8000/api/examples/cache/sdk/cache/refresh
  curl -i -X DELETE http://localhost:8000/api/examples/cache/sdk/cache
  curl -i http://localhost:8000/api/examples/cache/sdk/rate-limit
  curl -i -c /tmp/redis-example.cookies -X PUT \
      http://localhost:8000/api/examples/cache/sdk/session \
      -H 'Content-Type: application/json' -d '{"theme":"dark","language":"zh"}'
  curl -i -b /tmp/redis-example.cookies http://localhost:8000/api/examples/cache/sdk/session
  curl -i -b /tmp/redis-example.cookies -c /tmp/redis-example.cookies -X POST \
      http://localhost:8000/api/examples/cache/sdk/session/rotate
  curl -i -b /tmp/redis-example.cookies -c /tmp/redis-example.cookies -X DELETE \
      http://localhost:8000/api/examples/cache/sdk/session

官方参考（原生命令与 SDK 示例可对照阅读）
================================================
- SDK 缓存：https://redis.github.io/fastapi-redis-sdk/latest/guide/caching/
- SDK 限流：https://redis.github.io/fastapi-redis-sdk/latest/guide/rate-limiting/
- SDK 会话：https://redis.github.io/fastapi-redis-sdk/latest/guide/sessions/
- Cache-Aside：https://redis.io/docs/latest/develop/use-cases/cache-aside/redis-py/
- 异步客户端/连接池：https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html
- SET 的 EX/NX：https://redis.io/docs/latest/commands/set/
- 锁与租约：https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/
- Pipeline：https://redis.io/docs/latest/develop/using-commands/pipelining/
- Redis 事务：https://redis.io/docs/latest/develop/using-commands/transactions/
- Lua 原子执行：https://redis.io/docs/latest/develop/programmability/eval-intro/
- INCR/限流：https://redis.io/docs/latest/commands/incr/
- Cluster hash tags：https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags
- 数据结构：https://redis.io/docs/latest/develop/data-types/
- Streams：https://redis.io/docs/latest/develop/data-types/streams/
- Pub/Sub：https://redis.io/docs/latest/develop/pubsub/
- 超时/重试/监控：https://redis.io/docs/latest/develop/clients/redis-py/produsage/
- SQLAlchemy asyncio：https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
"""

import asyncio
import logging
import math
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Path,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from redis.asyncio.cluster import RedisCluster
from redis.exceptions import RedisError
from redis_fastapi import (
    AsyncRedisDep,
    CacheBackendDep,
    CookieSpec,
    FastAPIRedis,
    SessionDep,
    SessionStoreDep,
    SessionStoreError,
    build_cookie,
    cache,
    cache_evict,
    cache_put,
    rate_limit,
    valid_session,
)
from redis_fastapi import RateLimitResult as SDKRateLimitResult
from redis_fastapi.deps import SessionStateDep
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.deps import PostgresDep
from api.models.conversation import Conversation

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
CACHE_JITTER_SECONDS = 60
NEGATIVE_TTL_SECONDS = 30
REDIS_BUDGET_SECONDS = 0.3
LOCK_TTL_SECONDS = 5
RATE_LIMIT = 5
RATE_WINDOW_MS = 60_000


async def _require_example_environment() -> None:
    """教学接口有读写行为，生产环境不可访问；这不是完整的鉴权实现。"""
    if settings.app.env == "prod":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


async def _require_postgres() -> None:
    if settings.repo_type != "postgres":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "数据库教学示例需要 REPO_TYPE=postgres，并完成 conversation 表迁移",
        )


cache_router = APIRouter(
    prefix="/cache",
    tags=["Redis 教学"],
    dependencies=[Depends(_require_example_environment)],
)


class ConversationSnapshot(BaseModel):
    """只缓存投影字段；不触发 ORM relationship 的隐式 SQL/延迟加载。"""

    id: str
    title: str
    is_archived: bool
    updated_at: datetime | None


class RenameConversation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=240)


class ConversationBatch(BaseModel):
    # 限制批量大小，防止大 pipeline / SQL IN 占用过多连接、内存和响应时间。
    ids: list[UUID] = Field(min_length=1, max_length=50)


class RateLimitResult(BaseModel):
    allowed: bool
    count: int
    remaining: int
    reset_after_ms: int


class DataStructuresResult(BaseModel):
    profile: dict[str, str]
    tags: list[str]
    recent: list[str]
    leaderboard: list[tuple[str, float]]
    ttl_seconds: int


def _prefix() -> str:
    # 使用固定命名空间，不允许客户端提供任意 Redis key。
    return f"project-template:{settings.app.env}:examples:cache:v1"


def _conversation_key(conversation_id: str) -> str:
    # 花括号中的内容决定 Cluster slot；data 与 data:lock 会落到同一槽。
    return f"{_prefix()}:{{conversation:{conversation_id}}}:data"


def _cache_ttl(snapshot: ConversationSnapshot | None) -> int:
    if snapshot is None:
        return NEGATIVE_TTL_SECONDS + secrets.randbelow(6)
    return CACHE_TTL_SECONDS + secrets.randbelow(CACHE_JITTER_SECONDS + 1)


def _serialize(snapshot: ConversationSnapshot | None) -> str:
    # datetime 转成 ISO 8601；不要 str(ORM 对象) 或 pickle.loads(缓存内容)。
    return "null" if snapshot is None else snapshot.model_dump_json()


def _deserialize(
    raw: str | bytes | None, conversation_id: str
) -> tuple[bool, ConversationSnapshot | None]:
    if raw is None:
        return False, None
    if raw in ("null", b"null"):
        return True, None
    try:
        snapshot = ConversationSnapshot.model_validate_json(raw)
        if snapshot.id == conversation_id:
            return True, snapshot
    except ValidationError:
        pass
    # 缓存损坏/旧结构视作 miss；不记录原始内容，也不盲删可能已被别的请求更新的 key。
    logger.warning("Redis example: invalid cached conversation, treating as a miss")
    return False, None


def _log_redis_failure(operation: str, error: Exception) -> None:
    # 生产可补充结构化指标；不要把连接密码、用户数据或完整异常文本写进日志。
    logger.warning("Redis example %s failed: %s", operation, type(error).__name__)


async def _read_cache(
    redis: Redis | RedisCluster, conversation_id: str
) -> tuple[bool, ConversationSnapshot | None]:
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            raw = await redis.get(_conversation_key(conversation_id))
        # SDK 默认返回 bytes；同时兼容启用 decode_responses 后的 str。
        return _deserialize(raw, conversation_id)
    except (RedisError, TimeoutError, UnicodeDecodeError) as error:
        _log_redis_failure("GET", error)
        return False, None


async def _write_cache(
    redis: Redis | RedisCluster,
    conversation_id: str,
    snapshot: ConversationSnapshot | None,
) -> None:
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            # SET 与 TTL 必须同一条命令，避免 SET 成功而 EXPIRE 没执行的永久 key。
            await redis.set(
                _conversation_key(conversation_id),
                _serialize(snapshot),
                ex=_cache_ttl(snapshot),
            )
    except (RedisError, TimeoutError) as error:
        _log_redis_failure("SET", error)


async def _invalidate_cache(redis: Redis | RedisCluster, conversation_id: str) -> bool:
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            await redis.delete(_conversation_key(conversation_id))
        # DEL 返回 0 只是 key 不存在，也算成功；删除本身是幂等操作。
        return True
    except (RedisError, TimeoutError) as error:
        _log_redis_failure("invalidation after DB commit", error)
        return False


async def _load_snapshot(
    db: AsyncSession, conversation_id: str
) -> ConversationSnapshot | None:
    # 用参数绑定，不拼 SQL；只读主库/满足一致性要求的副本，防止回填复制延迟中的旧值。
    result = await db.execute(
        select(
            Conversation.id,
            Conversation.title,
            Conversation.is_archived,
            Conversation.updated_at,
        ).where(Conversation.id == conversation_id, Conversation.deleted_at.is_(None))
    )
    row = result.mappings().one_or_none()
    return ConversationSnapshot.model_validate(row) if row is not None else None


def _found(snapshot: ConversationSnapshot | None, source: str) -> ConversationSnapshot:
    if snapshot is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Conversation not found",
            headers={"X-Cache": source},
        )
    return snapshot


@cache_router.get("/demo")
async def get_demo(cache: AsyncRedisDep) -> str | bytes | None:
    await cache.set("a", "张三", 300)
    return await cache.get("a")


@cache_router.get(
    "/conversations/{conversation_id}",
    dependencies=[Depends(_require_postgres)],
    summary="1. Cache-Aside：缓存旁路、TTL 抖动与空值缓存",
)
async def read_conversation(
    conversation_id: UUID, redis: AsyncRedisDep, db: PostgresDep, response: Response
) -> ConversationSnapshot:
    """首次 MISS 查询 PostgreSQL；后续 HIT 不执行 SQL。

    Redis 读取或回填失败不影响数据库返回。不存在返回 404 并短暂缓存；SQL 错误直接
    抛出，不把故障伪装成 404。X-Cache=MISS 包括 Redis 不可用后回源的情况。
    普通版本适合非热点数据；它不对并发 miss 做合并，请对照 /hot 版本。
    """
    identifier = str(conversation_id)
    hit, snapshot = await _read_cache(redis, identifier)
    if not hit:
        snapshot = await _load_snapshot(db, identifier)
        await _write_cache(redis, identifier, snapshot)
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    return _found(snapshot, response.headers["X-Cache"])


@cache_router.patch(
    "/conversations/{conversation_id}",
    dependencies=[Depends(_require_postgres)],
    summary="2. 更新数据库：事务提交成功后失效缓存",
)
async def rename_conversation(
    conversation_id: UUID,
    payload: RenameConversation,
    redis: AsyncRedisDep,
    db: PostgresDep,
    response: Response,
) -> ConversationSnapshot:
    """真实修改已有会话标题，请使用测试数据。

    begin 上下文正常退出才提交，异常则回滚；不要在 commit 前删除或更新 Redis。
    UPDATE RETURNING 在同一语句拿到投影，避免提交后 refresh 失败导致跳过失效。
    数据库提交后，即使 Redis DEL 失败也返回已提交的结果，避免诱导重复业务写入；
    X-Cache-Invalidated=false 表示需要补偿。本教学实现没有持久化补偿 worker。
    删除记录、新建同 ID、软删除的失效时机相同，列表/聚合投影需另外失效。
    """
    identifier = str(conversation_id)
    async with db.begin():
        result = await db.execute(
            update(Conversation)
            .where(Conversation.id == identifier, Conversation.deleted_at.is_(None))
            .values(title=payload.title)
            .returning(
                Conversation.id,
                Conversation.title,
                Conversation.is_archived,
                Conversation.updated_at,
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        snapshot = ConversationSnapshot.model_validate(row)

    invalidated = await _invalidate_cache(redis, identifier)
    response.headers["X-Cache-Invalidated"] = str(invalidated).lower()
    return snapshot


@cache_router.post(
    "/conversations/batch",
    dependencies=[Depends(_require_postgres)],
    summary="3. 批量读取：pipeline + 一次 SQL IN，避免 N+1",
)
async def read_conversations(
    payload: ConversationBatch, redis: AsyncRedisDep, db: PostgresDep
) -> dict[str, ConversationSnapshot | None]:
    """最多 50 个 ID；结果以 ID 为键，重复 ID 去重，找不到的记录为 null。

    transaction=False 只减少网络往返，不保证这一批命令作为整体原子执行；不同 key
    可能来自不同时间点，因此结果不是跨记录一致性快照。独立 GET 可跨 Cluster 槽。
    排队调用 pipe.get/set 时不 await，最后 await execute；不跨请求共享 pipeline。
    """
    identifiers = list(dict.fromkeys(str(item) for item in payload.ids))
    cached = [None] * len(identifiers)
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            async with redis.pipeline(transaction=False) as pipe:
                for identifier in identifiers:
                    pipe.get(_conversation_key(identifier))
                cached = await pipe.execute()
    except (RedisError, TimeoutError, UnicodeDecodeError) as error:
        # 一批命令失败时可全部回源；大规模应用也可以精细识别每个命令的错误。
        _log_redis_failure("batch GET", error)

    snapshots: dict[str, ConversationSnapshot | None] = {}
    missing: list[str] = []
    for identifier, raw in zip(identifiers, cached, strict=True):
        hit, snapshot = _deserialize(raw, identifier)
        snapshots[identifier] = snapshot
        if not hit:
            missing.append(identifier)
    if not missing:
        return snapshots

    result = await db.execute(
        select(
            Conversation.id,
            Conversation.title,
            Conversation.is_archived,
            Conversation.updated_at,
        ).where(Conversation.id.in_(missing), Conversation.deleted_at.is_(None))
    )
    for row in result.mappings():
        snapshot = ConversationSnapshot.model_validate(row)
        snapshots[snapshot.id] = snapshot

    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            async with redis.pipeline(transaction=False) as pipe:
                for identifier in missing:
                    snapshot = snapshots[identifier]
                    pipe.set(
                        _conversation_key(identifier),
                        _serialize(snapshot),
                        ex=_cache_ttl(snapshot),
                    )
                await pipe.execute()
    except (RedisError, TimeoutError) as error:
        _log_redis_failure("batch SET", error)
    return snapshots


# Lua 在 Redis 内原子执行，脚本要短小且有界；不能在脚本里查 PostgreSQL。
# 所有 key 通过 KEYS 传入，数据通过 ARGV 传入，不做字符串拼接以免注入。
_RELEASE_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_FILL_IF_LOCK_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
    return 1
end
return 0
"""


@cache_router.get(
    "/conversations/{conversation_id}/hot",
    dependencies=[Depends(_require_postgres)],
    summary="4. 热点重建：带租约的锁、二次检查、受保护回填",
)
async def read_hot_conversation(
    conversation_id: UUID, redis: AsyncRedisDep, db: PostgresDep, response: Response
) -> ConversationSnapshot:
    """只让锁持有者回源；竞争者短暂等待缓存，否则返回可重试的 503。

    SET key token NX EX 同时完成占位与过期；不能拆成 SETNX + EXPIRE。
    Redis 故障时选择直接查数据库且不回填，是可用性优先的降级，需要另设数据库
    并发上限。锁竞争时则不全部回源。两种情况的策略有意不同。
    回填检查 token 可阻止已丢失租约的旧请求覆盖新值，但不提供 DB 强一致性。
    """
    identifier = str(conversation_id)
    key = _conversation_key(identifier)
    lock_key = f"{key}:lock"
    hit, snapshot = await _read_cache(redis, identifier)
    if hit:
        response.headers["X-Cache"] = "HIT"
        return _found(snapshot, "HIT")

    token = secrets.token_hex(16)
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            acquired = await redis.set(lock_key, token, nx=True, ex=LOCK_TTL_SECONDS)
    except (RedisError, TimeoutError) as error:
        _log_redis_failure("acquire rebuild lock", error)
        # 超时后 SET 可能已经执行，未知归属的锁等租约过期，不尝试无条件 DEL。
        response.headers["X-Cache"] = "BYPASS"
        return _found(await _load_snapshot(db, identifier), "BYPASS")

    if not acquired:
        for _ in range(3):
            await asyncio.sleep(0.05)
            hit, snapshot = await _read_cache(redis, identifier)
            if hit:
                response.headers["X-Cache"] = "HIT-AFTER-WAIT"
                return _found(snapshot, "HIT-AFTER-WAIT")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "缓存正在重建，请稍后重试",
            headers={"Retry-After": "1"},
        )

    try:
        # 等待/获取锁期间前一个请求可能已完成回填，必须 double-check。
        hit, snapshot = await _read_cache(redis, identifier)
        if hit:
            response.headers["X-Cache"] = "HIT"
            return _found(snapshot, "HIT")
        snapshot = await _load_snapshot(db, identifier)
        try:
            async with asyncio.timeout(REDIS_BUDGET_SECONDS):
                stored = await redis.eval(
                    _FILL_IF_LOCK_OWNER,
                    2,
                    lock_key,
                    key,
                    token,
                    _serialize(snapshot),
                    _cache_ttl(snapshot),
                )
            if not stored:
                logger.warning("Redis example: rebuild lease expired; skipped fill")
        except (RedisError, TimeoutError) as error:
            _log_redis_failure("guarded cache fill", error)
        response.headers["X-Cache"] = "MISS"
        return _found(snapshot, "MISS")
    finally:
        # DB 异常和 404 也释放锁；取消/崩溃时 finally 不保证完成，TTL 是最后兜底。
        # GET 再 DEL 两个客户端命令存在竞态，必须在一个原子脚本内校验并删除。
        try:
            async with asyncio.timeout(REDIS_BUDGET_SECONDS):
                await redis.eval(_RELEASE_LOCK, 1, lock_key, token)
        except (RedisError, TimeoutError) as error:
            _log_redis_failure("release rebuild lock", error)


_RATE_LIMIT_SCRIPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
local ttl = redis.call('PTTL', KEYS[1])
if ttl == -1 then
    return {0, count, ttl}
end
if count >= tonumber(ARGV[1]) then
    return {0, count, ttl}
end
count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return {1, count, redis.call('PTTL', KEYS[1])}
"""


@cache_router.post(
    "/rate-limit/{subject}", summary="5. 原子限流：INCR 与 PEXPIRE 放进同一个 Lua"
)
async def check_rate_limit(
    subject: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,64}$")],
    redis: AsyncRedisDep,
    response: Response,
) -> RateLimitResult:
    """同一 subject 从首次允许请求起 60 秒内最多允许 5 次，超额返回 429。

    此 POST 每次获准请求消耗一次配额，便于重复试验。生产应把此逻辑放在昂贵的
    数据库查询前，subject 从已认证身份取得，不能让客户端换路径绕过限流。
    窗口内后续请求不续期，拒绝的请求不继续 INCR。窗口边缘仍可能突发近 2 倍配额；
    需要更平滑的策略时用滑动窗口/令牌桶。它不是永久计费计数器。
    Redis 故障选择 fail-closed（503），明确区别于可选缓存的 fail-open。
    """
    key = f"{_prefix()}:rate-limit:{subject}"
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            allowed, count, ttl = await redis.eval(
                _RATE_LIMIT_SCRIPT, 1, key, RATE_LIMIT, RATE_WINDOW_MS
            )
    except (RedisError, TimeoutError) as error:
        _log_redis_failure("rate limit", error)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "限流服务暂不可用"
        ) from error

    # 若 key 被运维误写成无过期状态，拒绝继续使用损坏的限流状态并提示检查。
    if ttl < 0:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "限流 key 缺少 TTL")
    remaining = max(0, RATE_LIMIT - count)
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "请求过于频繁",
            headers={
                "Retry-After": str(max(1, math.ceil(ttl / 1000))),
                "X-RateLimit-Limit": str(RATE_LIMIT),
                "X-RateLimit-Remaining": "0",
            },
        )
    return RateLimitResult(
        allowed=True, count=count, remaining=remaining, reset_after_ms=ttl
    )


def _text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


@cache_router.post(
    "/structures/{demo_id}", summary="6. 数据结构与事务：Hash / Set / List / Sorted Set"
)
async def use_data_structures(
    demo_id: UUID, redis: AsyncRedisDep
) -> DataStructuresResult:
    """在独立教学命名空间写入少量固定数据，所有 key 60 秒后过期。

    Hash 存对象字段，Set 去重标签，List 存最近 10 条活动，Sorted Set 存排行榜。
    List 重复调用会追加；Set/ZADD 相同成员更新或去重。这里的 60 秒会在调用时续期。
    本例带短 TTL 的集合仅作演示/DB 派生数据，不应用作持久化关系、审计日志或
    积分事实来源。

    transaction=True 使用 MULTI/EXEC，命令执行期间不会被其他客户端插入；它既不
    包含 PostgreSQL，也没有 SQL 式回滚：EXEC 中某条命令运行失败不撤回其他命令。
    读回使用另一批 pipeline，所以响应只是读回时的视图，不是写事务的快照。
    对依赖读结果的并发更新，使用 WATCH + 有界重试或 Lua，避免 GET 后直接 SET。
    """
    base = f"{_prefix()}:{{structures:{demo_id}}}"
    profile_key, tags_key, recent_key, scores_key = (
        f"{base}:profile",
        f"{base}:tags",
        f"{base}:recent",
        f"{base}:scores",
    )
    try:
        async with asyncio.timeout(REDIS_BUDGET_SECONDS):
            async with redis.pipeline(transaction=True) as pipe:
                pipe.hset(profile_key, mapping={"name": "Redis learner", "level": "1"})
                pipe.expire(profile_key, 60)
                pipe.sadd(tags_key, "redis", "postgres", "redis")
                pipe.expire(tags_key, 60)
                pipe.lpush(recent_key, "read-cache-example")
                pipe.ltrim(recent_key, 0, 9)
                pipe.expire(recent_key, 60)
                pipe.zadd(scores_key, {"alice": 10, "bob": 20})
                pipe.expire(scores_key, 60)
                await pipe.execute()

            async with redis.pipeline(transaction=False) as pipe:
                pipe.hgetall(profile_key)
                pipe.smembers(tags_key)
                pipe.lrange(recent_key, 0, 9)
                pipe.zrevrange(scores_key, 0, 9, withscores=True)
                pipe.ttl(profile_key)
                profile, tags, recent, leaderboard, ttl = await pipe.execute()
    except (RedisError, TimeoutError) as error:
        _log_redis_failure("data structures", error)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Redis 数据结构演示暂不可用"
        ) from error
    return DataStructuresResult(
        profile={_text(key): _text(value) for key, value in profile.items()},
        tags=sorted(_text(value) for value in tags),
        recent=[_text(value) for value in recent],
        leaderboard=[(_text(member), float(score)) for member, score in leaderboard],
        ttl_seconds=ttl,
    )


# ---------------------------------------------------------------------------
# SDK 原生依赖：以下代码使用上面相同的 router，但采用独立缓存 key 和会话路径。
# ---------------------------------------------------------------------------

SDK_SESSION_PATH = "/api/examples/cache/sdk/session"
SDK_HTTP_CACHE_PREFIX = "project-template:examples:sdk:http:v1"
SDK_CACHE_TTL_SECONDS = 30
SDK_MODEL_TTL_SECONDS = 60


def _skip_sdk_session(request: Request) -> bool:
    path = request.url.path
    return settings.app.env == "prod" or not (
        path == SDK_SESSION_PATH or path.startswith(f"{SDK_SESSION_PATH}/")
    )


def _sdk_session_cookie(spec: CookieSpec) -> str:
    # 不改 name：middleware 读取的名字来自 SDK settings，必须与设置 Cookie 一致。
    # 相同构造器同时处理设置/清除，确保退出时 Path/Domain 等属性完全匹配。
    return build_cookie(
        replace(
            spec,
            path=SDK_SESSION_PATH,
            domain=None,
            secure=False,
            http_only=True,
            same_site="lax",
        )
    )


def configure_sdk_examples(app: FastAPI) -> None:
    """由 main.create_app 在 .lifespan().caching() 后、开始服务前调用。

    只配置教学所需 middleware，不创建客户端。若将路由挂到不同前缀，需同步修改
    SDK_SESSION_PATH，否则 Cookie 路径和 skip 判断不会匹配。
    """
    if settings.app.env == "prod":
        return
    (
        FastAPIRedis(app)
        # 此 skip_when 仅控制自动全局限流，路由 Depends(rate_limit(...)) 仍执行。
        # 避免环境中 REDIS_RATE_LIMIT_DEFAULT_LIMIT 意外限制所有现有业务接口。
        .rate_limiting(skip_when=lambda _request: True)
        .sessions(
            skip=_skip_sdk_session,
            cookie_builder=_sdk_session_cookie,
            key_prefix=f"{_prefix()}:sdk:sessions",
            idle_ttl=300,
            absolute_ttl=1800,
        )
    )


class SDKCachedResponse(BaseModel):
    generated_at: datetime
    nonce: str


class SessionPreferences(BaseModel):
    """只允许少量明确的匿名偏好，避免把任意请求体写入会话。"""

    model_config = ConfigDict(extra="forbid")

    theme: Literal["light", "dark"] = "light"
    language: Literal["zh", "en"] = "zh"


def _sdk_response_key(
    request: Request, eviction_group: str = "", prefix: str = ""
) -> str:
    # 遵守 SDK KeyBuilder 签名。这个公共样本不依赖请求参数，故统一三个端点的 key。
    # 路由 path/method 不同，若直接用 default_key_builder，刷新和删除将对不上 GET。
    return f"{prefix}:{settings.app.env}:clock"


def _sdk_limit_rejected(request: Request, result: SDKRateLimitResult) -> Response:
    # SDK fail_closed 默认将故障也作为 429；这里显式区分服务不可用与配额耗尽。
    # SDK 会给此响应补充 Retry-After / X-RateLimit-*，无需自行重复计算。
    return JSONResponse(
        status_code=503 if result.degraded else 429,
        content={"detail": "限流服务暂不可用" if result.degraded else "请求过于频繁"},
    )


@cache_router.get(
    "/sdk/cache",
    dependencies=[
        Depends(
            rate_limit(
                "5/minute",
                scope=f"{settings.app.env}:examples:sdk:cached-response",
                fail_closed=True,
                emit_headers=True,
                on_limit_exceeded=_sdk_limit_rejected,
            )
        ),
        Depends(
            cache(
                ttl=SDK_CACHE_TTL_SECONDS,
                cache_prefix=SDK_HTTP_CACHE_PREFIX,
                key_builder=_sdk_response_key,
                no_store=True,
            )
        ),
    ],
    summary="7. SDK cache：限流先执行，命中后跳过路由函数",
)
async def read_sdk_response() -> SDKCachedResponse:
    """30 秒内重复读取 nonce 不变，但每次请求都会消耗 SDK 限流额度。

    no_store=True 禁止浏览器/CDN 保存，Redis 仍缓存，便于每次 curl 观察服务器行为。
    SDK 还会生成 ETag，发送 If-None-Match 可得到 304；请求 Cache-Control: no-cache
    可强制重新生成，no-store 可绕过本次读写缓存。TTL 结束后允许自然重建。
    """
    return SDKCachedResponse(generated_at=datetime.now(UTC), nonce=secrets.token_hex(8))


@cache_router.post(
    "/sdk/cache/refresh",
    dependencies=[
        Depends(
            cache_put(
                ttl=SDK_CACHE_TTL_SECONDS,
                prefix=SDK_HTTP_CACHE_PREFIX,
                key_builder=_sdk_response_key,
            )
        )
    ],
    summary="8. SDK cache_put：强制执行并刷新相同缓存 key",
)
async def refresh_sdk_response() -> SDKCachedResponse:
    """生成新的 nonce，后续 GET 读取新值；返回结构必须与 GET 完全一致。

    这仅刷新时间样本，没有修改 DB。移植到业务写入时须在返回前 commit，并处理
    Redis 写失败/并发写乱序；cache_put 本身不提供数据库与缓存的原子事务。
    """
    return SDKCachedResponse(generated_at=datetime.now(UTC), nonce=secrets.token_hex(8))


@cache_router.delete(
    "/sdk/cache",
    dependencies=[
        Depends(
            cache_evict(prefix=SDK_HTTP_CACHE_PREFIX, key_builder=_sdk_response_key)
        )
    ],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="9. SDK cache_evict：只失效明确指定的 key",
)
async def evict_sdk_response() -> Response:
    """成功执行后尝试删除时间样本缓存，不清理整个 Redis 或其他 SDK 缓存。

    Redis 删除失败由 SDK 记录日志，204 不是删除已确认的证明。数据库写入也不能
    因这个响应码假定缓存已强一致同步；关键投递使用持久化补偿。
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sdk_model_key(conversation_id: str) -> str:
    # CacheBackend 会再加 SDK cache prefix。这里与 HTTP envelope 使用不同命名空间。
    return f"{_prefix()}:sdk:model:conversation:{conversation_id}"


@cache_router.get(
    "/sdk/cache-backend/conversations/{conversation_id}",
    dependencies=[Depends(_require_postgres)],
    summary="10. SDK CacheBackendDep：缓存数据库的 Pydantic 投影",
)
async def read_sdk_model(
    conversation_id: UUID, backend: CacheBackendDep, db: PostgresDep, response: Response
) -> ConversationSnapshot:
    """backend.get/set 处理 JSON 和 key 前缀，模型验证仍由业务负责。

    SDK get 在 miss、解码错误、Redis 异常时返回默认值；这里不缓存不存在的对象，
    如需负缓存必须引入独立 sentinel（不能将 miss 和 null 混淆）。SDK set 不返回
    写成功标志；数据库读取成功不代表缓存一定已写入。其他会话写入口不会自动失效
    此独立投影，可使用同路径 DELETE 观察重建，生产则接入统一提交后失效逻辑。
    """
    identifier = str(conversation_id)
    key = _sdk_model_key(identifier)
    response.headers["Cache-Control"] = "no-store"
    cached = await backend.get(key)
    if cached is not None:
        try:
            snapshot = ConversationSnapshot.model_validate(cached)
            if snapshot.id == identifier:
                response.headers["X-Cache"] = "HIT"
                return snapshot
        except ValidationError:
            pass
        logger.warning("Redis SDK example: invalid cached model; rebuilding")

    snapshot = _found(await _load_snapshot(db, identifier), "MISS")
    await backend.set(key, snapshot.model_dump(mode="json"), ttl=SDK_MODEL_TTL_SECONDS)
    response.headers["X-Cache"] = "MISS"
    return snapshot


@cache_router.delete(
    "/sdk/cache-backend/conversations/{conversation_id}",
    summary="11. SDK CacheBackendDep.delete：业务对象缓存的精确删除",
)
async def evict_sdk_model(
    conversation_id: UUID, backend: CacheBackendDep
) -> dict[str, bool]:
    """仅删 SDK 对象投影，不删除数据库记录或原生命令示例的投影。

    delete 返回 False 既可能是 key 不存在，也可能是 Redis 故障，不能据此断言数据库
    对象不存在。delete_group 会清整组，应只用于范围明确、数量受控的业务场景。
    """
    return {"deleted": await backend.delete(_sdk_model_key(str(conversation_id)))}


@cache_router.get(
    "/sdk/rate-limit",
    dependencies=[
        Depends(
            rate_limit(
                "5/minute",
                scope=f"{settings.app.env}:examples:sdk:rate-limit",
                fail_closed=True,
                emit_headers=True,
                on_limit_exceeded=_sdk_limit_rejected,
            )
        )
    ],
    summary="12. SDK rate_limit：按客户端 IP 限流，返回配额响应头",
)
async def sdk_rate_limited() -> dict[str, str]:
    """从首次允许请求起 60 秒最多 5 次，超额 429，Redis 故障 503。

    读取 X-RateLimit-Limit/Remaining/Reset 和 Retry-After；GET 缓存样本用独立
    scope，故与此端点的额度分开。需要多个端点共享额度时设置相同 scope。
    默认 ip_identifier 使用 request.client.host，NAT 用户会共享额度；生产通常
    用已认证用户/租户作为 identifier，不能信任任意 User-ID 或 X-Forwarded-For。
    代理转发 IP 应在 ASGI 服务器配置可信代理。SDK 使用原子固定时长窗口，窗口边缘
    仍可突发；更复杂的成本计算可用 RateLimitBackendDep.hit(cost=...) 并自行处理结果。
    """
    return {"message": "SDK 已允许本次请求；剩余额度见响应头"}


def _sdk_session_rejected(request: Request, reason: str) -> Response:
    return JSONResponse(
        status_code=503 if reason == "unavailable" else 401,
        content={
            "detail": "会话服务暂不可用" if reason == "unavailable" else "需要有效会话"
        },
        headers={"Cache-Control": "no-store"},
    )


@cache_router.get("/sdk/session", summary="13. SDK SessionDep：读取匿名偏好")
async def read_sdk_session(
    session: SessionDep, response: Response
) -> SessionPreferences:
    """无会话时返回默认偏好，不创建空会话；不会返回 session ID。

    middleware 已加载 Cookie 对应的 Redis 记录，依赖本身不再读取 Redis。
    普通读取失败时 SDK 可降级为空匿名会话；若必须有会话应使用 /required 的门禁。
    """
    response.headers["Cache-Control"] = "no-store"
    return SessionPreferences(
        theme=session.get("theme", "light"), language=session.get("language", "zh")
    )


@cache_router.put(
    "/sdk/session", summary="14. SDK SessionDep：写入偏好并自动保存 Cookie"
)
async def write_sdk_session(
    payload: SessionPreferences, session: SessionDep, response: Response
) -> SessionPreferences:
    """替换偏好；SDK 随响应自动创建或保存会话，并设置 HttpOnly Cookie。

    使用顶层 update 触发修改追踪。不要只改 session['nested']['value']，应将修改后
    的对象重新赋给 session['nested']。这些偏好不是账号信息，不表示已经认证。
    """
    session.update(payload.model_dump())
    response.headers["Cache-Control"] = "no-store"
    return payload


@cache_router.get(
    "/sdk/session/required",
    dependencies=[Depends(valid_session(on_reject=_sdk_session_rejected))],
    summary="15. SDK valid_session：要求会话存在，独立于身份认证",
)
async def read_required_sdk_session(
    session: SessionDep, response: Response
) -> SessionPreferences:
    """先 PUT 创建匿名会话，再带 Cookie 访问；缺失/过期401，默认配置下加载故障503。

    这不验证用户身份或权限。组合 cache 时 valid_session 必须先执行；用户相关响应
    不可因为设置 private=True 就使用所有人共享的 Redis key。
    """
    return await read_sdk_session(session, response)


@cache_router.post(
    "/sdk/session/rotate",
    dependencies=[Depends(valid_session(on_reject=_sdk_session_rejected))],
    summary="16. SDK SessionStoreDep：轮换 ID，保留匿名偏好",
)
async def rotate_sdk_session(
    state: SessionStateDep, store: SessionStoreDep, response: Response
) -> dict[str, bool]:
    """使用真实 store.rotate，旧 ID 失效，新 Cookie 随本次响应发出。

    0.9.0 的 SessionStateDep 需从 redis_fastapi.deps 导入；没有 session.renew()。
    生产认证应验证凭据后再轮换（或配置 principal_keys 自动轮换），此路由只演示
    匿名偏好。轮换先删除旧 key，故中途失败可能已经退出，不能承诺保留旧会话。
    """
    try:
        await store.rotate(state)
    except SessionStoreError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "会话轮换失败"
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return {"rotated": True}


@cache_router.delete(
    "/sdk/session",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="17. SDK SessionStoreDep.revoke：服务端注销并清除 Cookie",
)
async def revoke_sdk_session(
    state: SessionStateDep, store: SessionStoreDep
) -> Response:
    """退出不要求已有会话，可重复调用；只清浏览器 Cookie 不会撤销服务端会话。

    也可 session.clear() 让 middleware 在响应阶段注销；这里显式 await revoke，
    使可捕获的删除故障先于成功响应。并发请求不会因此自动串行化，需要业务层处理。
    """
    try:
        await store.revoke(state)
    except SessionStoreError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "会话注销失败"
        ) from error
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"}
    )
