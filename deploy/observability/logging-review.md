# FastAPI 日志采集评估

核对日期：2026-10-16。本文保留实施前的代码评估与只读查询快照；下文“当前”指该次评估时的状态。日志推送现已实现，实际使用与验收以 [接入文档](README.md) 为准。

## 当前事实与证据边界

- [`api/src/api/core/log.py`](../../api/src/api/core/log.py) 使用标准库 `logging.config.dictConfig()`，统一业务、Uvicorn 和 root 日志；`TraceContextFilter` 从当前 span 加入 `trace_id`、`span_id`。输出是文本；业务及服务器日志写 stderr，access 日志写 stdout。
- 日志里有 trace ID，只说明可以关联；它不会自动把日志发送到 Collector。现有源码尚未配置 logs provider/exporter。Traces、metrics、logs 是分别配置的信号。[OTel 日志关联模型](https://opentelemetry.io/docs/specs/otel/logs/)
- 当前工作环境核对到 SDK/HTTP exporter 为 `1.45.1`、现有 instrumentation 为 `0.66b1`；`opentelemetry-instrumentation-logging` 尚未安装。旧 `opentelemetry.sdk._logs.LoggingHandler` 已有弃用警告，后续接入应使用匹配版本的 logging instrumentation 提供的 handler。[官方迁移说明](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/logging/logging.html)
- [现有说明](README.md) 描述的是 Docker 日志 → Alloy → Loki，且明确本机直接运行的日志留在终端。该说明是历史配置依据，不能替代本次后端查询验证。
- 本次浏览器只读检查刷新了 Grafana Logs Drilldown 的 Loki 最近 15 分钟查询：显示 6 个基础设施/其他应用服务，未出现本项目 API。这不能推出所有历史时间范围都没有本项目日志，也没有核实远端 OTLP logs pipeline。
- 本机运行中的 OTel 示例请求产生有效 trace ID，`sampled=true`、`recording=true`；这只证明请求内存在活动 span，不能证明 Tempo 已收到 trace。结合尚无 logs exporter 的代码现状，本机终端日志没有应用主动推送通路。

## 推荐：本机和 Docker 共用 OTLP 推送

基于“本机运行和 Docker 部署都要直接采集，且人工和 AI 都方便排查”的要求，推荐保留标准 `logging` 入口，同一条记录进入两个输出：

```text
endpoint/service: logging.getLogger(__name__)
                    │
                    ├─ console handler → 可读文本 → 终端 / docker logs
                    │
                    └─ OTel logging handler → LoggerProvider
                         → BatchLogRecordProcessor → OTLP/HTTP
                         → Alloy logs pipeline → Loki → Grafana
```

这是适合本项目需求的设计选择。JSON stdout → Alloy 采集也是有效方案，但本机源码运行时需要额外的本地采集器；OTLP 方案由应用主动推送，环境间主要改变 endpoint、认证和 resource 属性。[Alloy Docker source](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/)、[Python OTLP exporter](https://opentelemetry-python.readthedocs.io/en/latest/exporter/otlp/otlp.html)

**同一条应用日志只走一条远端入库路径。** 保留 console 不等于应再将其采集进 Loki。启用应用 OTLP 推送后，应在现有 Docker discovery/processing 中排除该 API 的重复应用日志；其他容器的日志仍按各自规则采集。若要保留进程启动前的 stderr 或 exporter 故障诊断，需明确分类和过滤，不能将整个 API 容器的双路输出都无差别入库。

## Python 接入边界

1. `setup_logging()` 继续统一配置，模块仅调用 `logging.getLogger(__name__)`。无需从 `routes/examples/__init__.py` 导入单例，也无需在 endpoint 添加 handler。[Python logging](https://docs.python.org/3/library/logging.html)
2. 在每个 worker 初始化一套 `LoggerProvider(resource=...)`，复用 traces/metrics 的服务名、命名空间、版本和环境；添加 `BatchLogRecordProcessor(OTLPLogExporter(...))`，再连接标准 logging bridge。provider 的生命周期归应用观测初始化管理。[LoggerProvider](https://opentelemetry-python.readthedocs.io/en/latest/sdk/_logs.html)、[日志 processor](https://opentelemetry-python.readthedocs.io/en/latest/sdk/_logs.export.html)
3. 使用匹配现有依赖版本的 `opentelemetry-instrumentation-logging`，不要复制旧 SDK handler 示例。保留项目自己的 console formatter；不需要让 instrumentation 再调用 `basicConfig()`。其“注入 trace 字段”和“安装日志导出 handler”是不同功能，须显式选择。[Logging instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/logging/logging.html)
4. **检查 logger 传播路径。** `0.66b1` 的自动 bridge 安装在 root；目前 `api`、`uvicorn`、`uvicorn.error`、`uvicorn.access` 都有 `propagate=False`，仅调用 `instrument()` 不会捕获它们。应统一传播到 root，或在终止传播的 logger 上安装所需 handler；每条记录只能经过一次 OTLP handler。handler 安装顺序也必须与 `dictConfig()` 配合。[版本固定的 bridge 源码](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/v0.66b1/instrumentation/opentelemetry-instrumentation-logging/src/opentelemetry/instrumentation/logging/handler.py)
5. HTTP exporter 使用 `opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter`。应用连接 Alloy 的 `/v1/logs`，不是直接连接 Grafana；设置通用 `OTEL_EXPORTER_OTLP_ENDPOINT` 时追加信号路径，日志专用 endpoint 或显式 exporter endpoint 则使用完整 URL。应沿用项目 Settings 解析、超时和认证，不另建配置来源。[OTLP 配置](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)

批量 processor 将网络导出放在后台线程，但格式化及 console 写入仍有同步成本。它使用有界内存队列；队列满、导出失败或进程被强杀可能丢失日志，不能当作持久化审计系统。退出时在业务资源清理日志完成后执行 flush/shutdown，避免每请求 flush。SDK `1.45.1` 的 `force_flush(timeout_millis)` 和 batch export timeout 当前并不严格执行所传超时，应配置 exporter 的网络 timeout 并核实实际退出耗时。[固定版本批量实现](https://github.com/open-telemetry/opentelemetry-python/blob/v1.45.1/opentelemetry-sdk/src/opentelemetry/sdk/_shared_internal/__init__.py)、[HTTP exporter](https://opentelemetry-python.readthedocs.io/en/latest/_modules/opentelemetry/exporter/otlp/proto/http/_log_exporter.html)

## 人工和 AI 共用的字段

OTLP 自带结构，不需要把整条 JSON 字符串塞进 `body`。建议 `body` 保留可读消息，业务上下文通过 `extra` 进入 attributes，级别、时间、trace/span、resource 保持原生字段。console 可用短文本格式展示同一事件。[OTel Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)

| 信息 | 建议表示 |
| --- | --- |
| 发生时间与级别 | OTel timestamp、severity；console 明确时区 |
| 哪个服务/版本/环境 | resource：`service.name`、`service.namespace`、`service.version`、`deployment.environment.name` |
| 哪里记录 | logger/instrumentation scope；需要时启用代码文件、函数、行号 |
| 发生什么 | 人类可读 message；稳定事件名，如 `order.created` |
| 哪次调用 | 原生 trace/span context；必要时额外 request ID |
| 请求结果 | route 模板、method、status code、duration；数值保留数值类型 |
| 业务定位 | 精选业务 ID、操作结果、错误类型；避免整个对象转字符串 |
| 异常 | 一条记录携带 exception type/message/stacktrace |

推荐调用方式（接口示例，不表示已接入 exporter）：

```python
import logging

logger = logging.getLogger(__name__)

logger.info(
    "订单创建成功 order_id=%s",
    order_id,
    extra={"otel.event.name": "order.created", "order.id": order_id},
)

# 在负责处理/报告该异常的一层记录，避免逐层重复打印同一堆栈。
try:
    ...
except Exception:
    logger.exception(
        "订单创建失败",
        extra={"otel.event.name": "order.create_failed"},
    )
    raise
```

`0.66b1` bridge 会转换 `extra`、异常信息与当前 context，并把 `otel.event.name` 提升为原生 event name。不要给 OTLP handler 套 console formatter，否则 body 会混入显示用时间、级别等文本。业务层仍需保证 extra 值可序列化、字段不与 `LogRecord` 保留字段冲突，并在异常由外层统一记录时避免重复 `exception()`。[bridge 源码](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/v0.66b1/instrumentation/opentelemetry-instrumentation-logging/src/opentelemetry/instrumentation/logging/handler.py)

请求体、响应体、认证头、Cookie、密码和完整配置不作为默认日志上下文；错误消息和 URL 参数同样需要检查。AI 排查更依赖稳定字段、事件名、部署版本和上下文关联，而不是输出更多无筛选文本。Trace 被采样丢弃时日志仍可能存在，因此有 trace ID 不代表 Tempo 一定有对应链路。

Uvicorn 的服务器日志和 access 日志都是标准 logging，但 access formatter 的 HTTP 字段不是普通 LogRecord 的固定属性。如果需要结构化 method/route/status/duration，应专门映射 access 记录或增加请求完成事件，并明确谁负责记录请求结果，避免重复。[Uvicorn logging](https://uvicorn.dev/concepts/logging/)

## Alloy、Loki 与 Grafana

Alloy 的 OTLP receiver 必须显式连接 `output.logs`，并经 logs processor/exporter 转发；receiver 默认没有 logs consumer 时不会因为 traces 正常就自动保存 logs。建议复用 memory limiter、batch，再经 OTLP/HTTP exporter 发给 Loki 原生 `/otlp` endpoint。[Alloy receiver](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.otlp/)

Loki 原生 OTLP ingestion 需要启用 structured metadata（Loki 3.0 起默认开启）；还需核对实际部署的 schema/存储支持。资源属性中的点会规范化为下划线，例如 `service.name` → `service_name`。只把服务、环境等稳定低基数字段作为索引标签；trace ID、request ID、用户/订单 ID 等放 structured metadata。新配置也不宜默认把 `service.instance.id` 当索引标签。[Loki OTLP ingestion](https://grafana.com/docs/loki/latest/send-data/otel/)、[标签最佳实践](https://grafana.com/docs/loki/latest/get-started/labels/bp-labels/)、[Structured metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/)

Grafana 需要两侧关联：Tempo 配置 Trace to logs 的服务/环境映射、时间窗与 trace ID 过滤；Loki 配置 derived field 到 Tempo 的内部链接。应按实际入库的 trace 字段选择 metadata/label 或文本提取，不能套用与实际日志不匹配的正则。[双向关联配置](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/configure-trace-to-logs/)

## 实施后的验收条件

1. 分别从本机和 Docker 的实际 HTTP 请求产生唯一事件标识；console 可读，Loki 都能按 service/environment/事件标识查询到。
2. 活动 span 内的日志关联正确；无 span 的启动日志正常入库。异常在 Loki 中是一条带完整异常信息的记录。
3. 确认模块业务日志、Uvicorn access/error 和选定第三方日志覆盖范围；同一事件没有因 root 传播或 Docker 双路采集重复入库。
4. Grafana 能从日志打开 trace，也能从 trace 找到日志；trace 采样和查询时间窗符合预期。
5. 验证短暂 Collector 不可达、恢复、正常退出时的行为，观察 exporter 诊断；flush 返回成功或 HTTP 接收成功仍需配合 Loki 查询确认落库。

本次完成了代码、官方文档/源码核对及上述 Grafana 只读检查；以上新方案的远端验收条件尚未完成。
