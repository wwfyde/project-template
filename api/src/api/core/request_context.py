"""Request correlation and authenticated identity, independent of transport input.

Only ``Request-ID`` is accepted from a caller. Authentication binds identity after
checking the session and database. An incoming trace context is propagated when
tracing is disabled, without pretending that this service recorded a span.
"""

import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_RESERVED_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "host",
    "connection",
    "content-type",
    "content-length",
    "transfer-encoding",
    "keep-alive",
    "upgrade",
    "cache-control",
    "vary",
    "location",
    "www-authenticate",
    "traceparent",
    "tracestate",
}
_trace_propagator = TraceContextTextMapPropagator()


class RequestContextConfig(BaseModel):
    enabled: bool = True
    request_id_header: str = Field(default="Request-ID", min_length=1, max_length=64)
    user_id_header: str = Field(default="User-ID", min_length=1, max_length=64)
    tenant_id_header: str = Field(default="Tenant-ID", min_length=1, max_length=64)
    accept_request_id: bool = True
    expose_identity_headers: bool = True
    log_requests: bool = True

    @field_validator("request_id_header", "user_id_header", "tenant_id_header")
    @classmethod
    def validate_header_name(cls, value: str) -> str:
        if not _HEADER_NAME.fullmatch(value) or value.lower() in _RESERVED_HEADERS:
            raise ValueError("Correlation headers must use valid, dedicated HTTP names")
        return value

    @model_validator(mode="after")
    def validate_distinct_headers(self) -> "RequestContextConfig":
        if "account-id" in {
            self.request_id_header.lower(),
            self.user_id_header.lower(),
        }:
            raise ValueError("Account-ID is reserved for the account context")
        if (
            len(
                {
                    self.request_id_header.lower(),
                    self.user_id_header.lower(),
                    self.tenant_id_header.lower(),
                }
            )
            != 3
        ):
            raise ValueError("Correlation header names must be distinct")
        return self


@dataclass(slots=True)
class RequestContext:
    request_id: str
    config: RequestContextConfig
    incoming_trace: Context
    user_id: str | None = None
    tenant_id: str | None = None


_context: ContextVar[RequestContext | None] = ContextVar(
    "api_request_context", default=None
)


def get_request_context() -> RequestContext | None:
    return _context.get()


def _identity(value: object | None) -> str | None:
    if value is None:
        return None
    result = str(value)
    if not _IDENTIFIER.fullmatch(result):
        raise ValueError("Identity must be a bounded ASCII identifier")
    return result


def bind_identity(user_id: object | None, tenant_id: object | None = None) -> None:
    """Bind server-verified IDs; never pass the caller's identity headers here."""
    user, tenant = _identity(user_id), _identity(tenant_id)
    context = get_request_context()
    if context is not None:
        context.user_id, context.tenant_id = user, tenant
    span = trace.get_current_span()
    if span.is_recording():
        if user is not None:
            span.set_attribute("user.id", user)
        if tenant is not None:
            span.set_attribute("tenant.id", tenant)


def correlation_attributes() -> dict[str, str]:
    """Stable structured fields shared by application and OTLP log handlers."""
    context = get_request_context()
    if context is None:
        return {}
    attributes = {"request_id": context.request_id}
    if context.user_id is not None:
        attributes["user_id"] = context.user_id
    if context.tenant_id is not None:
        attributes["tenant_id"] = context.tenant_id
    # This is explicitly an incoming correlation ID, not a locally recorded span.
    if not trace.get_current_span().get_span_context().is_valid:
        incoming = trace.get_current_span(context.incoming_trace).get_span_context()
        if incoming.is_valid:
            attributes["incoming_trace_id"] = f"{incoming.trace_id:032x}"
    return attributes


def _trace_headers(context: RequestContext | None) -> dict[str, str]:
    carrier: dict[str, str] = {}
    current = trace.get_current_span().get_span_context()
    if current.is_valid:
        _trace_propagator.inject(carrier)
    elif context is not None:
        _trace_propagator.inject(carrier, context=context.incoming_trace)
    return carrier


def outbound_context_headers() -> dict[str, str]:
    """Return trusted IDs and W3C trace headers; never forward cookies or baggage."""
    context = get_request_context()
    headers = _trace_headers(context)
    if context is not None:
        config = context.config
        headers[config.request_id_header] = context.request_id
        if context.user_id is not None:
            headers[config.user_id_header] = context.user_id
        if context.tenant_id is not None:
            headers[config.tenant_id_header] = context.tenant_id
    return headers


class RequestContextMiddleware:
    def __init__(
        self, app: ASGIApp, config: RequestContextConfig | None = None
    ) -> None:
        self.app = app
        self.config = config or RequestContextConfig()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.config.enabled:
            await self.app(scope, receive, send)
            return

        config = self.config
        headers = Headers(scope=scope)
        supplied = headers.getlist(config.request_id_header)
        request_id = (
            supplied[0] if config.accept_request_id and len(supplied) == 1 else ""
        )
        if not _IDENTIFIER.fullmatch(request_id):
            request_id = uuid4().hex
        # Reject ambiguous duplicate trace headers instead of selecting a parent.
        trace_headers = {
            name: headers[name]
            for name in ("traceparent", "tracestate")
            if len(headers.getlist(name)) == 1
        }
        context = RequestContext(
            request_id,
            config,
            _trace_propagator.extract(trace_headers, context=Context()),
        )
        token = _context.set(context)
        scope.setdefault("state", {})["request_id"] = request_id
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("request.id", request_id)

        started = False
        status = 500
        error_type: str | None = None
        begin = perf_counter()

        async def send_with_context(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                # Always replace transport metadata, including on a cache hit.
                for name in (
                    config.request_id_header,
                    config.user_id_header,
                    config.tenant_id_header,
                    "traceparent",
                    "tracestate",
                ):
                    if name in response_headers:
                        del response_headers[name]
                response_headers[config.request_id_header] = request_id
                if config.expose_identity_headers:
                    if context.user_id is not None:
                        response_headers[config.user_id_header] = context.user_id
                    if context.tenant_id is not None:
                        response_headers[config.tenant_id_header] = context.tenant_id
                if context.user_id is not None or context.tenant_id is not None:
                    response_headers["Cache-Control"] = "private, no-store"
                response_headers.update(_trace_headers(context))
                status = message["status"]
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception as error:
            error_type = type(error).__name__
            if not started:
                # Starlette's outer ServerErrorMiddleware cannot add these IDs.
                # Send a safe body here, then re-raise for normal server reporting.
                await JSONResponse(
                    {"detail": "Internal Server Error"},
                    status_code=500,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send_with_context)
            raise
        finally:
            try:
                if config.log_requests:
                    attributes: dict[str, str | int | float] = {
                        **correlation_attributes(),
                        "otel.event.name": "http.request.completed",
                        "http.request.method": scope["method"],
                        "http.route": getattr(
                            scope.get("route"), "path", "<unmatched>"
                        ),
                        "http.response.status_code": status,
                        "http.request.duration_ms": round(
                            (perf_counter() - begin) * 1000, 3
                        ),
                    }
                    if error_type is not None:
                        attributes["error.type"] = error_type
                    logger.log(
                        logging.ERROR
                        if status >= 500 or "error.type" in attributes
                        else logging.INFO,
                        "HTTP request completed",
                        extra=attributes,
                    )
            finally:
                _context.reset(token)
