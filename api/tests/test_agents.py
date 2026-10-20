"""Service and HTTP contracts exercised without a model, database or Redis server."""

import asyncio
import json
from collections.abc import AsyncGenerator, Iterator
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import LogCaptureFixture, MonkeyPatch
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope

from api.agents import store as store_module
from api.agents.contracts import (
    AgentBackend,
    AgentDefinition,
    AgentFailure,
    AgentItem,
    AgentTurn,
    AgentUsage,
    BackendState,
    RunEvent,
    RunRequest,
    RunResult,
    SessionCreate,
    SessionRecord,
    TurnCreate,
    utc_now,
)
from api.agents.service import AgentService
from api.agents.store import InMemorySessionStore
from api.dependencies.auth import (
    get_optional_auth_user,
    get_user_repository,
    require_auth_user,
)
from api.schemas.auth import AuthUser
from api.routes.agents import agents_router, get_agent_service


TEST_USER = AuthUser(
    id="00000000-0000-0000-0000-000000000001",
    account_id="tenant-test",
    provider="google",
    display_name="Test User",
)


class MemoryOwnershipRepository:
    def __init__(self) -> None:
        self.owners: dict[tuple[str, str], tuple[str, str]] = {}

    async def own(self, kind: str, resource_id: str, user: AuthUser) -> None:
        self.owners[(kind, resource_id)] = (user.id, user.account_id)

    async def owns(self, kind: str, resource_id: str, user: AuthUser) -> bool:
        return self.owners.get((kind, resource_id)) == (user.id, user.account_id)

    async def owned_ids(self, kind: str, user: AuthUser) -> set[str]:
        return {
            resource_id
            for (resource_kind, resource_id), owner in self.owners.items()
            if resource_kind == kind and owner == (user.id, user.account_id)
        }


class FakeBackend:
    """A second runtime with its own opaque state and no OpenAI SDK imports."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.requests: list[RunRequest] = []
        self.closed_runs: list[str] = []
        self.closed = False

    def validate(self, agent: AgentDefinition) -> AgentDefinition:
        if agent.tools:
            raise AgentFailure("unsupported_tool", "Tool is not registered.")
        return agent.model_copy(update={"model": agent.model or "fake-model"})

    async def stream(self, request: RunRequest) -> AsyncGenerator[RunEvent, None]:
        self.requests.append(request)
        try:
            yield RunEvent(type="output_text.delta", data={"delta": "Hello 世界"})
            if request.input == "wait":
                await asyncio.Event().wait()
            if request.input == "failure":
                raise RuntimeError("private-provider-detail-and-secret")
            if request.input == "safe-failure":
                raise AgentFailure("tool_failed", "Registered tool failed.", 502)
            if request.input == "no-result":
                return
            previous = request.state.payload["history"] if request.state else []
            assert isinstance(previous, list)
            history = list(previous)
            history.append(request.input)
            item = AgentItem(type="message", role="assistant", text="Hello 世界")
            yield RunEvent(
                type="item.completed", data={"item": item.model_dump(mode="json")}
            )
            yield RunEvent(
                type="result",
                result=RunResult(
                    output="Hello 世界",
                    state=BackendState(
                        backend="other"
                        if request.input == "wrong-state"
                        else self.name,
                        payload={"history": history, "private": "opaque-runtime-state"},
                    ),
                    items=[item],
                    usage=AgentUsage(
                        requests=1, input_tokens=2, output_tokens=3, total_tokens=5
                    ),
                ),
            )
            if request.input == "after-result":
                yield RunEvent(type="output_text.delta", data={"delta": "too late"})
        finally:
            self.closed_runs.append(request.turn_id)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def service(backend: FakeBackend) -> AgentService:
    backends: dict[str, AgentBackend] = {backend.name: backend}
    return AgentService(
        backends=backends,
        store=InMemorySessionStore(),
        default_backend=backend.name,
    )


def new_app(service: AgentService, *, override: bool = False) -> FastAPI:
    app = FastAPI(
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        }
    )
    users = MemoryOwnershipRepository()
    app.state.ownership_repository = users
    app.dependency_overrides[require_auth_user] = lambda: TEST_USER
    app.dependency_overrides[get_optional_auth_user] = lambda: TEST_USER
    app.dependency_overrides[get_user_repository] = lambda: users
    app.include_router(agents_router, prefix="/api/agents")
    if override:
        app.dependency_overrides[get_agent_service] = lambda: service
    else:
        app.state.agent_service = service
    return app


@pytest.fixture
def client(service: AgentService) -> Iterator[TestClient]:
    with TestClient(new_app(service)) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_backend_selection_and_opaque_continuation_are_independent() -> None:
    first = FakeBackend("first-runtime")
    second = FakeBackend("second-runtime")
    service = AgentService(
        backends={first.name: first, second.name: second},
        store=InMemorySessionStore(),
        default_backend=first.name,
    )
    first_session = await service.create_session(SessionCreate())
    second_session = await service.create_session(SessionCreate(backend=second.name))

    for session in (first_session, second_session):
        for text in ("one", "two"):
            prepared = await service.start_turn(session.id, TurnCreate(input=text))
            turn = await service.run_turn(prepared)
            assert turn.status == "completed"
            assert turn.usage.total_tokens == 5
            assert [item.role for item in turn.items] == ["user", "assistant"]
        assert (await service.get_session(session.id)).active_turn_id is None
    for backend in (first, second):
        assert backend.requests[0].state is None
        state = backend.requests[1].state
        assert state is not None
        assert state.backend == backend.name
        assert state.payload["history"] == ["one"]
    await service.aclose()
    assert first.closed and second.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_text", "error_code"),
    [
        ("failure", "execution_failed"),
        ("safe-failure", "tool_failed"),
        ("no-result", "incomplete_run"),
        ("wrong-state", "invalid_backend_result"),
        ("after-result", "invalid_backend_result"),
    ],
)
async def test_failed_runs_release_session_without_advancing_state(
    service: AgentService,
    backend: FakeBackend,
    caplog: LogCaptureFixture,
    input_text: str,
    error_code: str,
) -> None:
    session = await service.create_session(SessionCreate())
    first = await service.start_turn(session.id, TurnCreate(input="saved"))
    await service.run_turn(first)
    failing = await service.start_turn(session.id, TurnCreate(input=input_text))

    events = [event async for event in service.stream_turn(failing)]

    assert events[-1].type == "turn.failed"
    failure = await service.get_turn(session.id, failing.turn.id)
    assert failure.status == "failed"
    assert failure.error is not None
    assert failure.error.code == error_code
    assert failure.completed_at is not None
    assert failing.turn.id in backend.closed_runs
    assert (await service.get_session(session.id)).active_turn_id is None
    assert "private-provider-detail-and-secret" not in failure.model_dump_json()
    assert "private-provider-detail-and-secret" not in caplog.text
    next_turn = await service.start_turn(session.id, TurnCreate(input="retry"))
    assert next_turn.request.state is not None
    assert next_turn.request.state.payload["history"] == ["saved"]
    await service.run_turn(next_turn)


@pytest.mark.asyncio
async def test_timeout_stops_backend_and_releases_session(
    service: AgentService, backend: FakeBackend
) -> None:
    service.run_timeout_seconds = 0.01
    session = await service.create_session(SessionCreate())
    prepared = await service.start_turn(session.id, TurnCreate(input="wait"))

    turn = await service.run_turn(prepared)

    assert turn.status == "failed"
    assert turn.error is not None
    assert turn.error.code == "run_timeout"
    assert prepared.turn.id in backend.closed_runs
    assert (await service.get_session(session.id)).active_turn_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("start_backend", [False, True])
async def test_closing_stream_records_cancellation_and_releases_session(
    service: AgentService, backend: FakeBackend, start_backend: bool
) -> None:
    session = await service.create_session(SessionCreate())
    prepared = await service.start_turn(session.id, TurnCreate(input="wait"))
    events = service.stream_turn(prepared)
    assert (await anext(events)).type == "turn.started"
    if start_backend:
        assert (await anext(events)).type == "output_text.delta"

    await events.aclose()

    turn = await service.get_turn(session.id, prepared.turn.id)
    assert turn.status == "cancelled"
    assert turn.error is not None
    assert turn.error.code == "run_cancelled"
    assert (await service.get_session(session.id)).active_turn_id is None
    assert (await service.store.get_session(session.id)).state is None
    if start_backend:
        assert prepared.turn.id in backend.closed_runs


@pytest.mark.asyncio
async def test_task_cancellation_preserves_previous_successful_state(
    service: AgentService, backend: FakeBackend
) -> None:
    session = await service.create_session(SessionCreate())
    first = await service.start_turn(session.id, TurnCreate(input="saved"))
    await service.run_turn(first)
    prepared = await service.start_turn(session.id, TurnCreate(input="wait"))
    events = service.stream_turn(prepared)
    await anext(events)
    await anext(events)
    waiting = asyncio.create_task(anext(events))
    await asyncio.sleep(0)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await service.aclose()

    assert (await service.get_turn(session.id, prepared.turn.id)).status == "cancelled"
    record = await service.store.get_session(session.id)
    assert record.session.active_turn_id is None
    assert record.state is not None
    assert record.state.payload["history"] == ["saved"]
    assert prepared.turn.id in backend.closed_runs


@pytest.mark.asyncio
async def test_cancellation_after_claim_commit_releases_unstarted_turn() -> None:
    class CommitPauseStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__()
            self.committed = asyncio.Event()
            self.release = asyncio.Event()

        async def start_turn(
            self, turn: AgentTurn, lease_expires_at: datetime
        ) -> SessionRecord:
            record = await super().start_turn(turn, lease_expires_at)
            self.committed.set()
            # A database can commit successfully before cancellation is delivered
            # to the caller during transaction-context cleanup.
            await self.release.wait()
            return record

    store = CommitPauseStore()
    backend = FakeBackend()
    service = AgentService(
        backends={backend.name: backend}, store=store, default_backend=backend.name
    )
    session = await service.create_session(SessionCreate())
    starting = asyncio.create_task(
        service.start_turn(session.id, TurnCreate(input="cancel before execution"))
    )
    await asyncio.wait_for(store.committed.wait(), timeout=1)
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    store.release.set()
    await asyncio.wait_for(service.aclose(), timeout=1)

    turns = await service.list_turns(session.id)
    assert len(turns) == 1
    assert turns[0].status == "cancelled"
    assert turns[0].error is not None
    assert turns[0].error.code == "run_cancelled"
    assert (await service.get_session(session.id)).active_turn_id is None
    assert (await store.get_session(session.id)).state is None
    assert backend.requests == []


@pytest.mark.asyncio
async def test_cancelled_failed_claim_preserves_another_active_turn() -> None:
    class RejectedClaimPauseStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__()
            self.pause_claim = False
            self.claim_started = asyncio.Event()
            self.release = asyncio.Event()

        async def start_turn(
            self, turn: AgentTurn, lease_expires_at: datetime
        ) -> SessionRecord:
            if self.pause_claim:
                self.claim_started.set()
                await self.release.wait()
            return await super().start_turn(turn, lease_expires_at)

    store = RejectedClaimPauseStore()
    backend = FakeBackend()
    service = AgentService(
        backends={backend.name: backend}, store=store, default_backend=backend.name
    )
    session = await service.create_session(SessionCreate())
    active = await service.start_turn(
        session.id, TurnCreate(input="owned by another request")
    )
    store.pause_claim = True
    starting = asyncio.create_task(
        service.start_turn(session.id, TurnCreate(input="cancel this rejected request"))
    )
    await asyncio.wait_for(store.claim_started.wait(), timeout=1)
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    store.release.set()
    await asyncio.wait_for(service.aclose(), timeout=1)

    assert (await service.get_session(session.id)).active_turn_id == active.turn.id
    turns = await service.list_turns(session.id)
    assert len(turns) == 1
    assert turns[0].id == active.turn.id
    assert turns[0].status == "running"
    assert turns[0].error is None
    assert backend.requests == []


@pytest.mark.asyncio
async def test_expired_lease_recovers_session_and_rejects_stale_result(
    service: AgentService, monkeypatch: MonkeyPatch
) -> None:
    session = await service.create_session(SessionCreate())
    old = await service.start_turn(session.id, TurnCreate(input="old"))
    future = utc_now() + timedelta(seconds=service.run_timeout_seconds + 31)
    with monkeypatch.context() as patch:
        patch.setattr(store_module, "utc_now", lambda: future)
        # The new lease must be calculated from the same clock as the store.
        patch.setattr("api.agents.service.utc_now", lambda: future)
        current = await service.start_turn(session.id, TurnCreate(input="new"))

    expired = await service.get_turn(session.id, old.turn.id)
    assert expired.status == "failed"
    assert expired.error is not None
    assert expired.error.code == "lease_expired"
    with pytest.raises(AgentFailure) as stale:
        await service.run_turn(old)
    assert stale.value.code == "turn_conflict"
    assert (await service.get_session(session.id)).active_turn_id == current.turn.id
    assert (await service.run_turn(current)).status == "completed"


def test_http_json_crud_and_history_hide_runtime_state(client: TestClient) -> None:
    assert client.get("/api/agents/backends").json() == {
        "default": "fake",
        "available": ["fake"],
    }
    created = client.post("/api/agents/sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["id"]
    path = f"/api/agents/sessions/{session_id}"
    assert created.json()["agent"]["model"] == "fake-model"
    response = client.post(f"{path}/turns", json={"input": "你好"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["output"] == "Hello 世界"
    assert result["usage"]["total_tokens"] == 5
    assert client.get(f"{path}/turns/{result['id']}").json() == result
    assert client.get(f"{path}/turns").json() == [result]
    assert client.get(path).json()["active_turn_id"] is None
    for url in (path, f"{path}/turns", f"{path}/turns/{result['id']}"):
        assert "opaque-runtime-state" not in client.get(url).text
        assert "payload" not in client.get(url).text
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get(f"{path}/turns/{result['id']}").status_code == 404


@pytest.mark.parametrize("input_text", ["hello", "failure"])
def test_sse_events_have_consistent_ids_and_persist_the_terminal_turn(
    client: TestClient, input_text: str
) -> None:
    session_id = client.post("/api/agents/sessions", json={}).json()["id"]
    response = client.post(
        f"/api/agents/sessions/{session_id}/turns",
        json={"input": input_text, "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    frames = [
        dict(line.split(": ", 1) for line in frame.splitlines())
        for frame in response.text.strip().split("\n\n")
    ]
    events = [json.loads(frame["data"]) for frame in frames]
    assert events[0]["type"] == "turn.started"
    assert events[-1]["type"] == (
        "turn.failed" if input_text == "failure" else "turn.completed"
    )
    turn_id = events[0]["turn_id"]
    for sequence, (frame, event) in enumerate(zip(frames, events), start=1):
        assert frame["id"] == f"{turn_id}:{sequence}"
        assert frame["event"] == event["type"]
        assert event["sequence"] == sequence
        assert event["turn_id"] == turn_id
        assert event["session_id"] == session_id
    stored = client.get(f"/api/agents/sessions/{session_id}/turns/{turn_id}").json()
    assert events[-1]["data"]["turn"] == stored
    assert "private-provider-detail-and-secret" not in response.text


def test_initial_errors_are_json_before_stream_headers(
    client: TestClient, service: AgentService
) -> None:
    missing = client.post(
        "/api/agents/sessions/missing/turns", json={"input": "x", "stream": True}
    )
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/json"
    assert missing.json()["detail"] == "Resource not found"
    assert (
        client.post(
            "/api/agents/sessions", json={"backend": "unregistered"}
        ).status_code
        == 503
    )
    assert (
        client.post(
            "/api/agents/sessions", json={"agent": {"tools": ["not-registered"]}}
        ).status_code
        == 400
    )
    session_id = client.post("/api/agents/sessions", json={}).json()["id"]
    path = f"/api/agents/sessions/{session_id}"
    assert client.portal is not None
    prepared = client.portal.call(
        service.start_turn, session_id, TurnCreate(input="held")
    )
    conflict = client.post(f"{path}/turns", json={"input": "x", "stream": True})
    assert conflict.status_code == 409
    assert conflict.headers["content-type"] == "application/json"
    assert conflict.json()["detail"]["code"] == "session_busy"
    assert client.delete(path).status_code == 409
    client.portal.call(service.run_turn, prepared)


def test_http_rejects_blank_input_extra_fields_and_cross_session_turns(
    client: TestClient,
) -> None:
    first_id = client.post("/api/agents/sessions", json={}).json()["id"]
    second_id = client.post("/api/agents/sessions", json={}).json()["id"]
    path = f"/api/agents/sessions/{first_id}/turns"
    for body in ({"input": ""}, {"input": " \n"}, {"input": "x", "sdk": {}}):
        assert client.post(path, json=body).status_code == 422
    assert client.get(path).json() == []
    assert client.get(path, params={"limit": 0}).status_code == 422
    result = client.post(path, json={"input": "ok"}).json()
    assert (
        client.get(f"/api/agents/sessions/{second_id}/turns/{result['id']}").status_code
        == 404
    )


def test_dependency_override_can_supply_another_runtime() -> None:
    backend = FakeBackend("another-runtime")
    service = AgentService(
        backends={backend.name: backend},
        store=InMemorySessionStore(),
        default_backend=backend.name,
    )
    with TestClient(new_app(service, override=True)) as client:
        session = client.post("/api/agents/sessions", json={}).json()
        assert session["backend"] == "another-runtime"
        result = client.post(
            f"/api/agents/sessions/{session['id']}/turns", json={"input": "custom"}
        ).json()
        assert result["status"] == "completed"
        assert backend.requests[0].agent.model == "fake-model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("asgi_version", "disconnect_at"),
    [("2.3", "delta"), ("2.4", "delta"), ("2.4", "headers")],
)
async def test_http_stream_disconnect_cancels_the_backend(
    service: AgentService,
    backend: FakeBackend,
    asgi_version: str,
    disconnect_at: str,
) -> None:
    session = await service.create_session(SessionCreate())
    app = new_app(service)
    await app.state.ownership_repository.own("agent_session", session.id, TEST_USER)
    body = json.dumps({"input": "wait", "stream": True}).encode()
    disconnected = asyncio.Event()
    sent_request = False
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": asgi_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/agents/sessions/{session.id}/turns",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test-client", 12345),
        "server": ("test-server", 80),
        "root_path": "",
    }

    async def receive() -> Message:
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if disconnect_at == "headers" and message["type"] == "http.response.start":
            raise OSError("client connection closed before headers")
        if message[
            "type"
        ] == "http.response.body" and b"output_text.delta" in message.get("body", b""):
            disconnected.set()
            if asgi_version == "2.4":
                raise OSError("client connection closed")

    try:
        async with asyncio.timeout(1):
            await app(scope, receive, send)
    except ClientDisconnect:
        pass
    await service.aclose()
    turns = await service.list_turns(session.id)
    assert len(turns) == 1
    assert turns[0].status == "cancelled"
    if disconnect_at == "headers":
        assert backend.requests == []
    else:
        assert turns[0].id in backend.closed_runs
    assert (await service.get_session(session.id)).active_turn_id is None
