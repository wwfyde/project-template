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

from api.dependencies.auth import (
    get_optional_auth_user,
    get_user_repository,
    require_auth_user,
)
from api.models.conversation import Conversation, Message
from api.routes import conversations
from api.schemas.auth import AuthUser
from api.schemas.conversation import ConversationRead

TEST_USER = AuthUser(
    id="00000000-0000-0000-0000-000000000001",
    account_id="tenant-test",
    provider="google",
    display_name="Test User",
)
OTHER_USER = TEST_USER.model_copy(update={"id": "00000000-0000-0000-0000-000000000002"})
OTHER_ACCOUNT = TEST_USER.model_copy(update={"account_id": "different-tenant"})


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


@pytest.fixture
def app(monkeypatch: MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(conversations.settings, "repo_type", "memory")
    monkeypatch.setattr(conversations, "_memory_conversations", {})
    monkeypatch.setattr(
        conversations, "_memory_messages", conversations.defaultdict(list)
    )
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
    app.dependency_overrides[get_user_repository] = lambda: users
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


@pytest.mark.parametrize("visitor", [OTHER_USER, OTHER_ACCOUNT])
def test_conversations_and_messages_are_private_to_both_user_and_account(
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


def test_legacy_records_without_ownership_remain_unavailable(
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
    assert client.get("/api/conversations").json() == []
    assert client.get("/api/conversations/legacy").status_code == 404


def test_collection_endpoints_require_authentication(
    app: FastAPI, client: TestClient
) -> None:
    app.state.current_user = None
    for method, path, body in (
        ("GET", "/api/conversations", None),
        ("POST", "/api/conversations", {}),
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
    for headers in (
        {"User-Code": OTHER_USER.id},
        [("User-Code", TEST_USER.id), ("User-Code", OTHER_USER.id)],
    ):
        assert (
            client.post("/api/conversations", json={}, headers=headers).status_code
            == 403
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
