"""OpenTelemetry 手动追踪示例：业务 span、异常与跨服务上下文传播。

应用已在 api.otel.setup_telemetry 中配置 SDK；这里仅使用 OTel API。
开启 OTEL_ENABLED=true、OTEL_TRACES_ENABLED=true，并将
OTEL_EXPORTER_OTLP_ENDPOINT 指向可达的 collector，重启 API 后试用：

  curl http://localhost:8000/api/examples/otel/trace
  curl -i 'http://localhost:8000/api/examples/otel/trace?fail=true'
  curl http://localhost:8000/api/examples/otel/propagation \
      -H 'traceparent: 00-12345678901234567890123456789012-1234567890123456-01'

在 /docs 中也可试用。与其他教学接口一致，APP_ENV=prod 时返回 404。
示例处理函数不访问数据库或 Redis；完整应用启动仍使用原有 lifespan。

阅读顺序
========
1. trace_example：FastAPI 自动创建 HTTP SERVER span，业务 span 自动成为其子项。
2. _run_work：跨 await 的当前上下文自动保留，子 span 包含属性和事件。
3. fail=true：子 span 上下文记录逃逸异常；父 span 捕获后须显式记录异常并标记
   ERROR。不要只返回 HTTP 错误而遗漏被捕获异常的业务 span 状态。
4. propagation_example：FastAPI 自动提取入站 traceparent/tracestate；inject 将
   当前上下文写入出站 carrier。本例只展示追踪头，不实际发送 HTTP 请求。
   未使用 HTTP 客户端自动埋点时，应在实际请求的 CLIENT span 内 inject，再将
   carrier 传给客户端；已自动埋点的客户端由 instrumentation 负责，避免重复 span。

观察结果
========
- 用响应 trace.trace_id 在 Tempo 中查找链路；trace.span_id 是业务父 span 的 ID。
  logger 在 span 内输出，现有 TraceContextFilter 会附加对应的 trace_id/span_id。
- sampled 表示采样决定，recording 表示当前 span 是否记录；均不保证 collector
  已接收。未初始化 SDK 且无有效上下文时 ID 为 null；未采样的链路仍可有有效 ID。
- 默认 parentbased 采样会继承上游的决定；验证时使用采样率 1.0 和采样标记 01。
- span 名保持固定，变化值放属性；不记录令牌、完整请求体或任意用户输入。
  出站演示仅回显 traceparent/tracestate，不回显 baggage 等其他传播字段。

配置和查询见 deploy/observability/README.md。
官方手动埋点参考：https://opentelemetry.io/docs/languages/python/instrumentation/
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from opentelemetry import propagate, trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from api.core.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def _require_example_environment() -> None:
    if settings.app.env == "prod":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


otel_router = APIRouter(
    prefix="/otel",
    tags=["OTel 教学"],
    dependencies=[Depends(_require_example_environment)],
)


class TraceContext(BaseModel):
    trace_id: str | None
    span_id: str | None
    sampled: bool
    recording: bool


class TraceResult(BaseModel):
    status: Literal["ok", "error"]
    trace: TraceContext


class PropagationResult(BaseModel):
    trace: TraceContext
    headers: dict[str, str]


def _current_trace() -> TraceContext:
    span = trace.get_current_span()
    context = span.get_span_context()
    return TraceContext(
        trace_id=f"{context.trace_id:032x}" if context.is_valid else None,
        span_id=f"{context.span_id:016x}" if context.is_valid else None,
        sampled=context.trace_flags.sampled,
        recording=span.is_recording(),
    )


async def _run_work(fail: bool) -> None:
    # 异步函数仍使用普通 with；上下文管理器会自动结束 span 并记录逃逸异常。
    with tracer.start_as_current_span("examples.otel.work") as span:
        span.set_attribute("example.work", "simulated_io")
        await asyncio.sleep(0.01)
        if fail:
            raise RuntimeError("Simulated example failure")
        span.add_event("work.completed", {"example.items_processed": 1})


@otel_router.get(
    "/trace",
    summary="业务父子 span、事件与异常追踪",
    responses={503: {"model": TraceResult, "description": "模拟业务失败"}},
)
async def trace_example(response: Response, fail: bool = False) -> TraceResult:
    with tracer.start_as_current_span(
        "examples.otel.trace", attributes={"example.fail": fail}
    ) as span:
        result: Literal["ok", "error"] = "ok"
        try:
            await _run_work(fail)
        except RuntimeError as error:
            # 异常在此被处理，不会逃逸父 span，须显式记录；每个 span 只记录一次。
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            result = "error"
            logger.warning(
                "OTel example failed",
                exc_info=True,
                extra={"otel.event.name": "otel.example.failed", "example.fail": True},
            )
        else:
            logger.info(
                "OTel example completed",
                extra={
                    "otel.event.name": "otel.example.completed",
                    "example.fail": False,
                },
            )
        span.set_attribute("example.result", result)
        # 在 span 结束之前读取；成功保持默认 UNSET，无需强制标记 OK。
        return TraceResult(status=result, trace=_current_trace())


@otel_router.get("/propagation", summary="生成跨服务传播的追踪头（不发送请求）")
async def propagation_example() -> PropagationResult:
    with tracer.start_as_current_span("examples.otel.propagation"):
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        headers = {
            key: value
            for key, value in carrier.items()
            if key.lower() in {"traceparent", "tracestate"}
        }
        return PropagationResult(trace=_current_trace(), headers=headers)
