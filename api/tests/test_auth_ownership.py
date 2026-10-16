"""Authorization is applied before resource access and before list pagination."""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import Result, Select, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_agents import FakeBackend, MemoryOwnershipRepository, TEST_USER, new_app

from api.agents.contracts import SessionCreate
from api.agents.service import AgentService
from api.agents.store import InMemorySessionStore
from api.auth.dependencies import get_optional_auth_user, require_auth_user
from api.auth.schemas import AuthUser
from api.models.conversation import Conversation, Message
from api.routes import conversations
from api.schemas.conversation import ConversationRead

OTHER_USER = TEST_USER.model_copy(update={"id": "00000000-0000-0000-0000-000000000002"})
OTHER_TENANT = TEST_USER.model_copy(update={"tenant_id": "different-tenant"})


@pytest.fixture
def app(monkeypatch: MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(conversations.settings, "repo_type", "in-memory")
    monkeypatch.setattr(conversations, "_memory_conversations", {})
    monkeypatch.setattr(
        conversations, "_memory_messages", conversations.defaultdict(list)
    )
    backend = FakeBackend()
    service = AgentService(
        backends={backend.name: backend},
        store=InMemorySessionStore(),
        default_backend=backend.name,
    )
    app = new_app(service)
    app.include_router(conversations.conversations_router, prefix="/api/conversations")
    app.state.current_user = TEST_USER

    async def authenticated_user() -> AuthUser:
        if app.state.current_user is None:
            raise HTTPException(401, "Not authenticated")
        return app.state.current_user

    app.dependency_overrides[require_auth_user] = authenticated_user
    app.dependency_overrides[get_optional_auth_user] = authenticated_user
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("visitor", [OTHER_USER, OTHER_TENANT])
def test_conversations_and_messages_are_private_to_both_user_and_tenant(
    app: FastAPI,
    client: TestClient,
    visitor: AuthUser,
) -> None:
    created = client.post("/api/conversations", json={"title": "private"})
    assert created.status_code == 201
    assert created.json()["user_id"] == TEST_USER.id
    path = f"/api/conversations/{created.json()['id']}"
    assert (
        client.post(
            f"{path}/messages", json={"role": "user", "content": "private message"}
        ).status_code
        == 201
    )
    app.state.current_user = visitor

    assert client.get("/api/conversations").json() == []
    for method, suffix, body in (
        ("GET", "", None),
        ("GET", "/messages", None),
        ("PATCH", "", {"title": "stolen"}),
        ("POST", "/messages", {"role": "user", "content": "injected"}),
        ("DELETE", "", None),
    ):
        response = client.request(method, path + suffix, json=body)
        assert response.status_code == 404
        assert response.json() == {"detail": "Resource not found"}

    app.state.current_user = TEST_USER
    assert client.get(path).json()["title"] == "private"
    assert len(client.get(f"{path}/messages").json()) == 1


@pytest.mark.parametrize("visitor", [OTHER_USER, OTHER_TENANT])
def test_agent_turns_and_streams_are_private_to_both_user_and_tenant(
    app: FastAPI,
    client: TestClient,
    visitor: AuthUser,
) -> None:
    created = client.post("/api/agents/sessions", json={})
    assert created.status_code == 201
    path = f"/api/agents/sessions/{created.json()['id']}"
    turn = client.post(f"{path}/turns", json={"input": "private"}).json()
    backend = app.state.agent_service.backends["fake"]
    previous_runs = len(backend.requests)
    app.state.current_user = visitor
    for method, suffix, body in (
        ("GET", "", None),
        ("GET", "/turns", None),
        ("GET", f"/turns/{turn['id']}", None),
        ("POST", "/turns", {"input": "injected", "stream": True}),
        ("DELETE", "", None),
    ):
        response = client.request(method, path + suffix, json=body)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"
    assert len(backend.requests) == previous_runs
    app.state.current_user = TEST_USER
    assert client.get(path).status_code == 200
    assert len(client.get(f"{path}/turns").json()) == 1


def test_legacy_records_without_ownership_remain_unavailable(
    app: FastAPI,
    client: TestClient,
) -> None:
    legacy = ConversationRead(
        id="legacy",
        title="legacy",
        mode="agent",
        user_id=TEST_USER.id,
        is_archived=False,
        is_pinned=False,
        created_at="",
        updated_at="",
    )
    conversations._memory_conversations[legacy.id] = legacy
    assert client.portal is not None
    agent_session = client.portal.call(
        app.state.agent_service.create_session, SessionCreate()
    )

    assert client.get("/api/conversations").json() == []
    assert client.get("/api/conversations/legacy").status_code == 404
    assert client.get(f"/api/agents/sessions/{agent_session.id}").status_code == 404


def test_collection_endpoints_require_authentication(
    app: FastAPI, client: TestClient
) -> None:
    app.state.current_user = None
    for method, path, body in (
        ("GET", "/api/conversations", None),
        ("POST", "/api/conversations", {}),
        ("GET", "/api/agents/backends", None),
        ("POST", "/api/agents/sessions", {}),
    ):
        assert client.request(method, path, json=body).status_code == 401


def test_creation_rejects_forged_owner_and_legacy_user_code(
    app: FastAPI,
    client: TestClient,
) -> None:
    assert (
        client.post("/api/conversations", json={"user_id": OTHER_USER.id}).status_code
        == 403
    )
    for path in ("/api/conversations", "/api/agents/sessions"):
        for headers in (
            {"User-Code": OTHER_USER.id},
            [("User-Code", TEST_USER.id), ("User-Code", OTHER_USER.id)],
        ):
            assert client.post(path, json={}, headers=headers).status_code == 403
    assert (
        client.post("/api/agents/sessions", json={"user_id": OTHER_USER.id}).status_code
        == 422
    )
    assert not app.state.ownership_repository.owners
    assert not conversations._memory_conversations

    accepted = client.post(
        "/api/conversations",
        json={"user_id": TEST_USER.id},
        headers={"User-Code": TEST_USER.id},
    )
    assert accepted.status_code == 201
    assert accepted.json()["user_id"] == TEST_USER.id


def test_in_memory_listing_filters_owned_records_before_limit(
    app: FastAPI,
    client: TestClient,
) -> None:
    own = client.post("/api/conversations", json={"title": "own"}).json()
    app.state.current_user = OTHER_USER
    other = client.post("/api/conversations", json={"title": "other"}).json()
    conversations._memory_conversations[other["id"]].updated_at = "2099-01-01"
    app.state.current_user = TEST_USER
    response = client.get("/api/conversations?limit=1")
    assert [item["id"] for item in response.json()] == [own["id"]]


def test_database_listing_filters_owned_records_before_limit(
    app: FastAPI,
    client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    cast(Table, Conversation.__table__).create(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add_all(
            [
                Conversation(
                    id="owned",
                    title="owned",
                    user_id=TEST_USER.id,
                    created_at=now,
                    updated_at=now,
                ),
                Conversation(
                    id="foreign",
                    title="foreign",
                    user_id=OTHER_USER.id,
                    created_at=now,
                    updated_at=now + timedelta(days=1),
                ),
            ]
        )
        db.commit()

    class DatabaseSession:
        def __init__(self, db: Session) -> None:
            self.db = db

        async def execute(
            self, statement: Select[tuple[Conversation]] | Select[tuple[Message]]
        ) -> Result[tuple[Conversation]] | Result[tuple[Message]] | MagicMock:
            if statement.column_descriptions[0]["entity"] is Message:
                empty = MagicMock()
                empty.scalar_one_or_none.return_value = None
                return empty
            return self.db.execute(statement)

    @asynccontextmanager
    async def database() -> AsyncGenerator[DatabaseSession]:
        with Session(engine) as db:
            yield DatabaseSession(db)

    monkeypatch.setattr("api.core.db.AsyncSessionLocal", database)
    monkeypatch.setattr(conversations.settings, "repo_type", "postgres")
    ownership: MemoryOwnershipRepository = app.state.ownership_repository
    assert client.portal is not None
    client.portal.call(ownership.own, "conversation", "owned", TEST_USER)
    client.portal.call(ownership.own, "conversation", "foreign", OTHER_USER)
    try:
        response = client.get("/api/conversations?limit=1")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == ["owned"]
    finally:
        engine.dispose()
