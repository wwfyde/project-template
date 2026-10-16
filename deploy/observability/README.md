# OpenTelemetry 接入与验证

服务通过 OTLP/HTTP 将 FastAPI、PostgreSQL、Redis 的遥测和 Python 日志发送给 Grafana Alloy，再由 Alloy 转发至 Tempo、Prometheus 和 Loki。Redis 使用 `fastapi-redis-sdk` 自带的 OTel 集成。应用配置统一由 `Settings` 读取，通过环境变量或 API 的 dotenv 文件覆盖。

本文中的服务器、地址和账户都是占位示例。真实地址、认证信息保存在本地未跟踪配置或服务器 `.env` 中。部署方式见[部署说明](../README.md)，开发启动方式见[根 README](../../README.md)。

## 信号与现有基础设施

| 信号 | 应用与采集路径 | 查询位置 |
| --- | --- | --- |
| Traces | API → Alloy OTLP/HTTP → memory limiter → batch → OTLP/gRPC → Tempo | Grafana Explore / Tempo |
| Metrics | API → Alloy OTLP/HTTP → memory limiter → batch → Prometheus exporter → remote write → Prometheus | Grafana Explore / Prometheus |
| Logs | Python logging → 后台批量 OTLP/HTTP → Alloy logs pipeline → Loki 原生 OTLP | Grafana Explore / Loki |

Traces/metrics 沿用已有管线；新增环境需按下文单独接好 logs 输出，traces 正常不能证明 logs 已接通。Prometheus 开启 remote-write receiver 后无需新增 scrape job，也无需开启其 OTLP receiver。应用 exporter 指向 Alloy；Prometheus 的 `9090` 是查询和 remote-write 服务端口，不是本应用的 OTLP 地址。参见 [Alloy OTLP receiver](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.otlp/) 和 [Prometheus OTLP 接收配置](https://prometheus.io/docs/guides/opentelemetry/)。

本机和 Docker 都由应用主动推送日志，无需本机安装采集器。控制台仍保留可读文本及结构化业务字段，便于人工排查；Loki 保存 OTLP 原生字段，便于查询和 AI 分析。同一条日志只保留一条远端入库通路，Docker 环境需配置下文的采集排除规则。

指标保持累计值（cumulative）导出。现有 Alloy 的 Prometheus exporter 不接收 delta 指标，切换为 delta 前必须先增加 delta-to-cumulative 转换。参见 [Alloy Prometheus exporter](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.prometheus/)。

## 最小应用配置

在本地 `api/.env` 或服务器部署目录的 `.env` 中合并以下配置，替换 collector 占位域名：

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=project-template-api
OTEL_DEPLOYMENT_ENVIRONMENT=test
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.internal.example.com:4318
OTEL_LOGS_ENABLED=true
OTEL_LOGS_LEVEL=INFO
REDIS_OTEL_ENABLED=true
REDIS_OTEL_REDIS_ENABLED=true
```

本地开发将 `OTEL_DEPLOYMENT_ENVIRONMENT` 改为 `local`，生产改为 `production`。保持 `OTEL_SERVICE_NAME` 稳定，用环境字段区分同一服务的不同部署。配置修改后重启本地 API 或重新部署服务器上的 API 容器。

使用 HTTP/protobuf 协议和 `4318` 端口，`OTEL_EXPORTER_OTLP_ENDPOINT` 填 collector 基础地址，不加 `/v1/traces`、`/v1/metrics` 或 `/v1/logs`；应用分别追加对应信号路径。日志专用 `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` 则填写包含 `/v1/logs` 的完整 URL。端口 `4317` 是 OTLP/gRPC，不能作为 HTTP exporter 的地址。参见 [OTLP exporter 配置](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)。

Compose 会将部署 `.env` 注入 API，环境变量无需写入镜像或 GitHub workflow。真实 collector 地址保存在各环境自己的配置中，镜像可以在本地、测试和生产环境复用。

## Settings 与开关

`Settings.otel` 使用 `OtelConfig`；Redis 字段沿用 SDK 的 `RedisSettings`，由项目统一合并配置后传给 SDK。优先级为显式构造参数、进程环境变量、API dotenv 文件、TOML、默认值；dotenv/TOML 文件列表中的后项覆盖前项。`OTEL_EXPORTER_OTLP_ENDPOINT` 对应 `settings.otel.exporter_otlp_endpoint`，多下划线字段不会被继续拆成嵌套对象。

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OTEL_ENABLED` | `false` | 总开关，包括 Redis SDK 的有效开关 |
| `OTEL_SDK_DISABLED` | `false` | 设为 `true` 强制关闭，即使总开关已启用 |
| `OTEL_SERVICE_NAME` | `project-template-api` | 服务名 |
| `OTEL_SERVICE_NAMESPACE` | `project-template` | 服务命名空间；Prometheus 的 `job` 通常为 namespace/service |
| `OTEL_SERVICE_VERSION` | API 包版本 | 发布版本标识 |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | `APP_ENV` | 建议明确设为 local/test/production |
| `OTEL_RESOURCE_ATTRIBUTES` | 空 | 额外资源属性，逗号分隔 `key=value` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | 当前只接入此协议 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Collector 基础地址，容器中必须设置可达地址 |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` / `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | 未设置 | 可分别覆盖完整信号 URL |
| `OTEL_EXPORTER_OTLP_HEADERS` | 空 | 认证头，作为 `SecretStr` 保存，例如 `Authorization=Bearer%20token` |
| `OTEL_EXPORTER_OTLP_TIMEOUT` | `10` | 导出 HTTP 超时，秒 |
| `OTEL_TRACES_ENABLED` / `OTEL_METRICS_ENABLED` / `OTEL_LOGS_ENABLED` | `true` | 总开关启用后，分别启停三种信号的导出 |
| `OTEL_LOGS_LEVEL` | `INFO` | 日志导出最低级别；源 logger 级别仍会先过滤日志 |
| `OTEL_FASTAPI_ENABLED` / `OTEL_POSTGRES_ENABLED` | `true` | 分别启停 HTTP / SQL instrumentation |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | 支持同名策略，以及 parentbased_always_on、traceidratio、always_on、always_off |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | ratio 策略的根链路采样比例，范围 0–1；parentbased 保留上游采样决定 |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | 指标导出间隔，毫秒，最小 1000 |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `10000` | 指标收集/导出超时，毫秒 |
| `OTEL_EXCLUDED_URLS` | 匹配 `/api/health` | 逗号分隔的 HTTP URL 正则，不记录匹配的 HTTP 请求 |
| `REDIS_OTEL_ENABLED` | SDK 默认 `false` | SDK 缓存、限流、session 操作的 spans/metrics |
| `REDIS_OTEL_REDIS_ENABLED` | SDK 默认 `false` | 由 SDK 管理 redis-py 原生观测 |

也可配置 `api/config.local.toml`，真实地址不要提交：

```toml
[otel]
enabled = true
service_name = "project-template-api"
deployment_environment = "local"
exporter_otlp_endpoint = "http://collector.internal.example.com:4318"
logs_enabled = true
logs_level = "INFO"
traces_sampler_arg = 0.1

[redis]
otel_enabled = true
otel_redis_enabled = true
```

进程启动后更改这些配置需要重启 API。每个 worker 只有一套全局 provider；不要额外使用 `opentelemetry-instrument` 或 `FASTAPI_OTEL_AUTO_CONFIGURE` 启动第二套导出。FastAPI 自带 telemetry 已显式关闭，统一由上述开关控制官方 instrumentation。SDK 资源关闭后会 flush 遥测，provider 在 worker 退出时由 OTel SDK 关闭。

PostgreSQL 使用官方 psycopg instrumentation，覆盖 SQLAlchemy 的异步数据库查询链路，不重复叠加 SQLAlchemy instrumentation，也不采集绑定参数。默认提供查询 spans，FastAPI 与 Redis 提供应用指标；不包含 Postgres 实例或连接池监控指标。当前 SQLAlchemy 2.1 不在 SQLAlchemy instrumentation 的支持范围内，使用驱动层可保留项目版本。HTTP 不采集请求头；业务日志也不输出数据库 DSN。

Redis 不另加通用 Redis instrumentation。当前 redis-py 8.1 原生集成默认提供连接与重试相关指标，不承诺逐条 Redis 命令 span；缓存、限流和 session 的业务 span 由 SDK 提供。[SDK 官方说明](https://redis.github.io/fastapi-redis-sdk/latest/guide/configuration/#opentelemetry)

## Alloy 与 Loki 日志接入

将 [logs.alloy.example](logs.alloy.example) 合并到实际 Alloy 配置。已有 OTLP receiver 继续使用同一个 `4318` 监听，只增加 `output.logs`，并把 logs 连到 memory limiter → batch → `otelcol.exporter.otlphttp`。如果已有共享 processor，给它们补齐 `output.logs` 即可，不要复制第二个 receiver 或让一条日志连接两条并行出口。Loki exporter 的基础地址为 `http://loki.internal.example.com:3100/otlp`，它会追加 `/v1/logs`；不要填 `/loki/api/v1/push`。[Alloy exporter 配置](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.otlphttp/)

Loki 需要支持 structured metadata 的 TSDB/v13 schema，并开启 `allow_structured_metadata`。合并 [logs.loki.example.yaml](logs.loki.example.yaml) 到已有配置的 `limits_config`；共享 Loki 应按目标 tenant 配置，避免改变其他服务的标签约定。示例只索引 `service.name`、`service.namespace`、`deployment.environment.name`；版本、实例、trace/span、业务字段保留为 structured metadata。字段中的点映射为下划线，例如 `order.id` → `order_id`，`trace_id` 不应成为索引标签。[Loki OTLP 映射](https://grafana.com/docs/loki/latest/send-data/otel/)、[structured metadata 要求](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/)

这些文件是合并模板，未包含实际网络、认证或存储配置。使用目标版本的 `alloy validate /path/to/config.alloy` 校验合并后的完整配置，再重新加载。多租户 Loki 的 tenant header 和认证在 Alloy → Loki 这一跳配置；API → Alloy 的认证仍由 `OTEL_EXPORTER_OTLP_HEADERS` 配置。

### Docker 避免重复采集

Compose 只给 API 服务增加 `observability.logs.source=${API_LOGS_SOURCE:-docker}` 标签，不影响 Redis、Postgres、web 或 migration。按 [Alloy 示例](logs.alloy.example) 在 Docker discovery 后增加 target 过滤，只排除该标签值为 `otlp` 的容器，并让 `loki.source.docker.targets` 使用过滤后的 `.output`；原有 `relabel_rules` 和下游转发保留。不要仅把 drop 放在 source 的 `relabel_rules`：Alloy 1.19.2 中它可能只清空标签，仍发送日志；发现阶段过滤才会阻止该容器被读取。[discovery.relabel](https://grafana.com/docs/alloy/latest/reference/components/discovery/discovery.relabel/)、[Docker source 实现](https://github.com/grafana/alloy/blob/v1.19.2/internal/component/loki/source/docker/tailer.go#L327-L347)

先保留部署 `.env` 的 `API_LOGS_SOURCE=docker`，接通 OTLP 并确认 Loki 已收到应用日志，再设为 `otlp` 并重建 API 容器。这段切换期可能有两份日志，验收完成后不可继续双采。只有 `OTEL_ENABLED=true`、`OTEL_LOGS_ENABLED=true` 且未设 `OTEL_SDK_DISABLED=true` 时才能切换；关闭 OTLP 时也要把标签切回 `docker`。`docker compose restart` 不更新标签或环境变量，需要按部署流程重建容器。

终端及 `docker logs` 始终可读。排除整个 API 容器后，应用日志初始化之前的 stderr、exporter 自身的失败诊断仍留在 `docker logs`；这类诊断不再重复推送，避免导出失败引起递归。后台批量队列是有界内存队列，进程强杀、长期断网或队列满可能丢失日志；日常排查日志不承担持久化审计职责。

## 网络连接

现有 Alloy 使用 host 网络，并将 OTLP receiver 绑定到宿主机的私网地址。应用只需能访问该私网地址的 `4318`，无需加入后端观测服务所在的 Docker 网络，也无需开放公网端口。

容器内的 `127.0.0.1` 指向容器自身；宿主机只绑定某个私网网卡时，Docker host-gateway 地址也不等于该接收地址。配置应使用已确认可达的 collector 私网地址或内部域名，并从实际运行 API 的网络位置验证。生产环境需要独立配置其可达的 collector；测试环境可达不代表生产环境也可达。

本地直接运行 API，可通过 SSH 隧道使用服务器上的 collector。在本地 shell 设置连接目标和 collector 的私网地址，然后保持隧道终端运行：

```bash
export OBSERVABILITY_SSH_TARGET='deploy@observability.example.com'
export COLLECTOR_HOST='collector.internal.example.com'

ssh -N -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:14318:${COLLECTOR_HOST}:4318" \
  "$OBSERVABILITY_SSH_TARGET"
```

另一个本地终端启动 API，使用：

```dotenv
OTEL_DEPLOYMENT_ENVIRONMENT=local
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318
```

该 loopback 示例适用于本机直接运行的 API。API 在 Docker 中运行时，应配置容器实际可达的 collector 地址。

## 验证数据进入后端

已有 API 容器可执行项目提供的探针。下例在仓库根目录运行，按实际部署配置选择 Compose 参数；探针只执行 `SELECT 1`，并创建一个唯一、60 秒 TTL 的 Redis 测试 key，随后删除：

```bash
docker compose --env-file deploy/.env exec -T api python - < deploy/observability/smoke.py
```

探针会输出 `trace_id`、`sampled`、服务名与环境名。需启用 `OTEL_ENABLED`、Postgres 和 Redis SDK 观测；验证时使用采样率 `1.0`，否则某次探针可能按采样策略不导出。在 Tempo 按该 trace ID 查看根 span、SQL 子 span 和 `cache.backend.*` 子 span。探针不是运行中 API 的日志验收；验证 Loki 时应按下文发起实际 HTTP 请求。

需要验证整套临时环境，可在运行 Docker 的机器上先构建 API/web 镜像，再运行：

```bash
SMOKE_OTEL_ENDPOINT='http://collector.internal.example.com:4318' \
API_IMAGE=project-template-api:local WEB_IMAGE=project-template-web:local \
bash scripts/smoke-deploy.sh
```

脚本使用随机 Compose 项目名作为 OTel 服务名、`smoke` 环境和一秒指标周期，结束后清理本次容器及数据卷。未传入 `SMOKE_OTEL_ENDPOINT` 时保留普通部署验证流程，不依赖 collector。

首先发起实际业务请求，覆盖一次数据库查询和一次 Redis 操作。仅检查 HTTP 健康端点不足以验证这些业务链路；也要等待 SDK 的批量导出和指标导出周期。

验证应使用独立服务名（例如 `project-template-api-smoke`）和环境名，避免将验证流量与正式服务混淆。以下查询使用正常服务名，冒烟验证时相应替换。

### 通过 SSH 访问查询 API

Prometheus、Tempo 和 Loki 的查询端口可以保持仅监听服务器 loopback。下例在另一个终端创建隧道；右侧端口应与服务器实际发布的查询端口一致：

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:19090:127.0.0.1:9090 \
  -L 127.0.0.1:13200:127.0.0.1:3200 \
  -L 127.0.0.1:13100:127.0.0.1:3100 \
  "$OBSERVABILITY_SSH_TARGET"
```

本地请求验证 Tempo 就绪和查询服务，不需要业务端口或观测端口的公网访问：

```bash
curl --fail --silent --show-error http://127.0.0.1:13200/ready

curl --fail --silent --show-error --get \
  http://127.0.0.1:13200/api/search \
  --data-urlencode 'q={resource.service.name="project-template-api" && resource.deployment.environment.name="test"}' \
  --data-urlencode 'limit=10'
```

`/ready` 返回成功仅代表 Tempo 就绪；`/api/search` 的 `traces` 数组出现对应服务的 trace 才能确认数据已进入查询后端。查看 trace 时应能看到 FastAPI 请求与其 PostgreSQL、Redis 操作的父子关系。参见 [Tempo HTTP API](https://grafana.com/docs/tempo/latest/api_docs/)。

### Prometheus 指标

现有 Alloy 开启 `resource_to_telemetry_conversion`，将应用的 resource 属性转换为普通指标标签，例如 `service_name` 和 `deployment_environment_name`。服务标识还可能映射为 `job`、`instance`；`target_info` 默认会移除已用于这些标识的 `service_name` 等属性，因此不要只通过 `target_info{service_name="..."}` 判断接入失败。

先列出本服务实际收到的指标名称，避免把不同 instrumentation 版本的指标命名写死：

```bash
curl --fail --silent --show-error --get \
  http://127.0.0.1:19090/api/v1/query \
  --data-urlencode 'query=count by (__name__) ({service_name="project-template-api",deployment_environment_name="test"})'
```

在 Grafana Explore 的 Prometheus 数据源中也可执行同一 PromQL：

```promql
count by (__name__) (
  {service_name="project-template-api", deployment_environment_name="test"}
)
```

确认 HTTP 请求耗时/请求数量与已启用的 Redis SDK 指标有数据，再根据实际指标名建立面板；数据库查询链路在 Tempo 验证。计数器采用 `rate()`，耗时分布按实际单位与 bucket 配置处理。Prometheus 查询返回 HTTP 200 但结果为空，不代表服务已接入。

### Loki 日志与 trace 关联

本机运行和 Docker 都按同一 `service_name` 查询，用 `deployment_environment_name` 区分环境。以下命令在本机 API（端口 `8000`）和测试 Docker 的 web 入口（端口 `18080`）各执行一次；Docker 示例接口需 `APP_ENV=dev/local`，不要为了验证而在生产开启 examples。生产可调用已有业务 endpoint 并查询其业务事件或 Uvicorn access 日志。

```bash
# 本机；Docker 测试环境改成 http://127.0.0.1:18080。
export API_BASE_URL=http://127.0.0.1:8000
# 每次生成新的 trace ID，用于定位这一次请求。
export LOG_TEST_TRACE_ID=$(openssl rand -hex 16)
curl --fail --silent --show-error \
  "$API_BASE_URL/api/examples/otel/trace" \
  -H "traceparent: 00-${LOG_TEST_TRACE_ID}-1234567890123456-01"

# 等待应用和 Alloy 的批量导出后查询；Docker 环境将 local 改成 test。
curl --fail --silent --show-error --get \
  http://127.0.0.1:13100/loki/api/v1/query_range \
  --data-urlencode "query={service_name=\"project-template-api\",deployment_environment_name=\"local\"} | trace_id=\"${LOG_TEST_TRACE_ID}\"" \
  --data-urlencode 'since=15m' --data-urlencode 'limit=100'
```

HTTP 200 不代表已有日志，检查响应 `data.result` 中的实际记录。成功消息 `OTel example completed` 应只出现一次，并包含该 trace ID、事件名及业务字段；`fail=true` 请求应得到 503 和一条含异常类型、堆栈的业务错误日志。若同时收到了以容器名作为服务名的副本，说明 Docker 排除规则尚未生效。还应检查无活动 span 的启动日志正常入库；trace 采样关闭不应阻止日志导出。

Grafana Explore / Loki 可使用以下 LogQL（structured metadata 直接筛选，无需 `| json`）：

```logql
{service_name="project-template-api", deployment_environment_name="local"}
  | trace_id="<trace-id>"
```

日志正文、级别、logger scope、代码位置和 `exception_stacktrace` 能用于人工/AI 排查；业务字段应采用稳定名称和简单类型。`extra={"otel.event.name": "order.created"}` 同时映射到原生事件名及 `event_name` 属性，兼容尚未保留原生事件名的后端，可用 `| event_name="order.created"` 查询。OTLP body 保留原始消息，console 的时间前缀不会混进 body。超大异常堆栈可能触发 Loki structured metadata 大小限制，应检查 Loki 拒收指标再调整策略。[日志字段与限制](https://grafana.com/docs/loki/latest/send-data/otel/)

需要独立检查日志通路时，可运行 [smoke_logs.py](smoke_logs.py)。它使用进程内 FastAPI 请求产生 INFO 与模拟异常日志，不连接 Redis/Postgres、不监听端口，也不要求开启生产 examples：

```bash
# 本机，在仓库根目录运行，读取 API 的常规配置。
uv run --directory api python ../deploy/observability/smoke_logs.py
# 已部署容器，读取容器现有环境变量。
docker compose --env-file deploy/.env exec -T api python - < deploy/observability/smoke_logs.py
```

启用 `OTEL_ENABLED=true`、`OTEL_LOGS_ENABLED=true`，并将 `OTEL_LOGS_LEVEL` 设为 `INFO`。按探针 JSON 输出的环境、trace ID 或 `verification_id` 查询 Loki，预期恰好两条业务记录，分别为成功消息和含固定异常的错误消息。探针成功退出只代表已尝试导出，仍需后端查询验证。

Uvicorn 在请求上下文退出后记录的未处理异常可能没有 trace ID；需要完整关联时，应在负责处理异常的业务层、活动 span 内调用 `logger.exception`。当前实现不改变 HTTP 异常处理语义。`httpx`/`httpx2` 默认只输出 WARNING 及以上，避免 INFO 请求日志将带签名的完整 URL 发送到后端。

### Grafana 双向跳转

在 Tempo 数据源的 **Trace to logs** 中选择 Loki，将 `service.name` 映射为 `service_name`、`deployment.environment.name` 映射为 `deployment_environment_name`；时间窗可设为开始前 `2s`、结束后 `2s`。启用自定义查询：

```logql
{${__tags}} | trace_id="${__trace.traceId}"
```

在 Loki 数据源 **Derived fields** 增加 `TraceID`，类型选 **Label**，匹配字段名 `^trace_id$`；启用 Internal link，指向 Tempo，Query 填 `${__value.raw}`。这里从 structured metadata 读取字段，不要求消息正文包含 trace ID。两侧保存后分别测试日志 → trace 和 trace → 日志；无活动 span 的启动日志、被采样丢弃的 trace 不能要求有可打开的链路。界面或 provisioning 细节以实际 Grafana 版本为准。[Grafana 双向关联配置](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/configure-trace-to-logs/)

## 排查顺序

1. 确认配置进入 API 进程，`OTEL_ENABLED` 已开启，服务名与环境名与查询一致；不要将整份环境变量或配置对象打印到日志。
2. 从 API 实际网络位置确认 collector 地址可达，HTTP exporter 指向 `4318`。对 `/v1/traces` 发 GET 返回 `405` 只能确认路径存在，不能证明遥测已保存。
3. 发起业务请求并等待导出周期，检查 API 与 Alloy 中的导出错误。
4. 先在 Tempo 查询 trace，再在 Prometheus 查询该服务指标；确认查询时间范围覆盖请求时间。
5. 日志按 service/environment 查询，再筛选 trace ID；确认 Alloy 的 `output.logs`、Loki structured metadata 和 Docker 去重规则。Loki 查到实际记录才代表入库成功。
