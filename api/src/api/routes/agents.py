from collections.abc import AsyncGenerator, Awaitable
from contextlib import aclosing
from typing import Annotated

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from api.agents.contracts import (
    AgentFailure,
    AgentSession,
    AgentTurn,
    SessionCreate,
    TurnCreate,
)
from api.agents.runtime import create_agent_service
from api.agents.service import AgentService, PreparedTurn
from api.core.config import get_settings

agents_router = APIRouter()


def _http_error(exc: AgentFailure) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


async def get_agent_service(request: Request) -> AgentService:
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        try:
            service = create_agent_service(get_settings())
        except AgentFailure as exc:
            raise _http_error(exc) from exc
        request.app.state.agent_service = service
    return service


AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]


async def _call[T](operation: Awaitable[T]) -> T:
    try:
        return await operation
    except AgentFailure as exc:
        raise _http_error(exc) from exc


@agents_router.get("/backends")
async def list_backends(service: AgentServiceDep) -> dict[str, object]:
    return {
        "default": service.default_backend,
        "available": sorted(service.backends),
    }


@agents_router.post("/sessions", response_model=AgentSession, status_code=201)
async def create_session(
    payload: SessionCreate, service: AgentServiceDep
) -> AgentSession:
    return await _call(service.create_session(payload))


@agents_router.get("/sessions/{session_id}", response_model=AgentSession)
async def get_session(session_id: str, service: AgentServiceDep) -> AgentSession:
    return await _call(service.get_session(session_id))


@agents_router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, service: AgentServiceDep) -> Response:
    await _call(service.delete_session(session_id))
    return Response(status_code=204)


async def _sse(
    service: AgentService, prepared: PreparedTurn
) -> AsyncGenerator[str, None]:
    async with aclosing(service.stream_turn(prepared)) as events:
        async for event in events:
            yield (
                f"id: {event.turn_id}:{event.sequence}\n"
                f"event: {event.type}\n"
                f"data: {event.model_dump_json()}\n\n"
            )


class AgentStreamingResponse(StreamingResponse):
    """Own iterator cleanup even when ASGI 2.4 send() raises on disconnect."""

    def __init__(self, service: AgentService, prepared: PreparedTurn) -> None:
        self._service = service
        self._prepared = prepared
        self._events = _sse(service, prepared)
        super().__init__(
            self._events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                try:
                    await self._events.aclose()
                finally:
                    await self._service.cancel_unstarted_turn(self._prepared)


@agents_router.post(
    "/sessions/{session_id}/turns",
    response_model=AgentTurn,
    responses={
        200: {
            "description": "Completed turn record, or SSE events when stream=true.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def create_turn(
    session_id: str, payload: TurnCreate, service: AgentServiceDep
) -> AgentTurn | StreamingResponse:
    # Claim/validation happens before streaming headers, so 404/409/503 remain HTTP errors.
    prepared = await _call(service.start_turn(session_id, payload))
    if payload.stream:
        return AgentStreamingResponse(service, prepared)
    return await _call(service.run_turn(prepared))


@agents_router.get("/sessions/{session_id}/turns", response_model=list[AgentTurn])
async def list_turns(
    session_id: str,
    service: AgentServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AgentTurn]:
    return await _call(service.list_turns(session_id, limit))


@agents_router.get("/sessions/{session_id}/turns/{turn_id}", response_model=AgentTurn)
async def get_turn(
    session_id: str, turn_id: str, service: AgentServiceDep
) -> AgentTurn:
    return await _call(service.get_turn(session_id, turn_id))
