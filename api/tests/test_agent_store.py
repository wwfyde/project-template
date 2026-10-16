"""Store contracts against memory and real SQLite transactions, without services.

SQLite exercises serialization, atomic rollback and cascades. PostgreSQL row-lock
syntax is checked separately; SQLite does not simulate PostgreSQL concurrency.
"""

import asyncio
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pytest import FixtureRequest, MonkeyPatch
from sqlalchemy import Engine, Table, create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from api.agents.contracts import (
    AgentDefinition,
    AgentError,
    AgentFailure,
    AgentItem,
    AgentSession,
    AgentTurn,
    BackendState,
    SessionStore,
)
from api.agents.store import InMemorySessionStore, PostgresSessionStore
from api.models.agent_session import AgentSessionRecord, AgentTurnRecord

NOW = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)


class SqliteSessionFactory:
    """Adapt synchronous transactions only; production uses async_sessionmaker."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.fail_commit = False
        self.statements: list[str] = []

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[AsyncSession]:
        with Session(self.engine) as session, session.begin():
            database = MagicMock(spec=AsyncSession)
            database.execute = AsyncMock(side_effect=session.execute)
            database.get = AsyncMock(side_effect=session.get)
            database.delete = AsyncMock(side_effect=session.delete)
            database.add = session.add
            yield cast(AsyncSession, database)
            self.statements.extend(
                str(call.args[0].compile(dialect=postgresql.dialect()))
                for call in database.execute.call_args_list
            )
            if self.fail_commit:
                session.flush()
                raise RuntimeError("injected commit failure")


@pytest.fixture
def sqlite_factory() -> Iterator[SqliteSessionFactory]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    cast(Table, AgentSessionRecord.__table__).create(engine)
    cast(Table, AgentTurnRecord.__table__).create(engine)
    try:
        yield SqliteSessionFactory(engine)
    finally:
        engine.dispose()


@pytest.fixture(params=["memory", "database"])
def store(
    request: FixtureRequest,
    sqlite_factory: SqliteSessionFactory,
    monkeypatch: MonkeyPatch,
) -> SessionStore:
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW)
    if request.param == "memory":
        return InMemorySessionStore()
    return PostgresSessionStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))


def make_session(session_id: str = "session-1") -> AgentSession:
    return AgentSession(
        id=session_id,
        backend="example",
        agent=AgentDefinition(tools=["echo"]),
        created_at=NOW,
        updated_at=NOW,
    )


def make_turn(turn_id: str = "turn-1", session_id: str = "session-1") -> AgentTurn:
    return AgentTurn(id=turn_id, session_id=session_id, input="Hello", created_at=NOW)


def make_state(value: str = "first") -> BackendState:
    return BackendState(backend="example", payload={"history": [{"text": value}]})


def completed(turn: AgentTurn) -> AgentTurn:
    result = turn.model_copy(deep=True)
    result.status = "completed"
    result.output = "Hello back"
    result.items = [
        AgentItem(type="message", role="assistant", data={"nested": ["value"]})
    ]
    result.completed_at = NOW + timedelta(seconds=1)
    return result


@pytest.mark.asyncio
async def test_sessions_are_copied_and_duplicates_conflict(store: SessionStore) -> None:
    session = make_session()
    await store.create_session(session)
    session.agent.tools.append("unregistered")
    read = await store.get_session(session.id)
    read.session.agent.tools.append("another")
    assert (await store.get_session(session.id)).session.agent.tools == ["echo"]
    with pytest.raises(AgentFailure) as failure:
        await store.create_session(make_session())
    assert failure.value.status_code == 409
    assert (await store.get_session(session.id)).state is None


@pytest.mark.asyncio
async def test_finish_saves_turn_and_continuation_and_releases_lease(
    store: SessionStore,
) -> None:
    session = make_session()
    await store.create_session(session)
    turn = make_turn()
    record = await store.start_turn(turn, NOW + timedelta(minutes=5))
    assert record.session.active_turn_id == turn.id
    assert record.lease_expires_at == NOW + timedelta(minutes=5)
    record.session.agent.tools.append("not-persisted")
    turn.input = "mutated caller input"
    assert (await store.get_turn(session.id, turn.id)).input == "Hello"

    result = completed(turn)
    state = make_state()
    await store.finish_turn(result, state)
    nested = result.items[0].data["nested"]
    assert isinstance(nested, list)
    nested.append("caller mutation")
    history = state.payload["history"]
    assert isinstance(history, list)
    message = history[0]
    assert isinstance(message, dict)
    message["text"] = "caller mutation"
    record = await store.get_session(session.id)
    assert record.session.active_turn_id is None
    assert record.lease_expires_at is None
    assert record.session.agent.tools == ["echo"]
    assert record.state == make_state()
    assert record.state is not None
    history = record.state.payload["history"]
    assert isinstance(history, list)
    message = history[0]
    assert isinstance(message, dict)
    message["text"] = "read mutation"
    assert (await store.get_session(session.id)).state == make_state()
    saved = await store.get_turn(session.id, turn.id)
    assert saved.status == "completed"
    assert saved.items[0].data == {"nested": ["value"]}
    nested = saved.items[0].data["nested"]
    assert isinstance(nested, list)
    nested.append("read mutation")
    assert (await store.get_turn(session.id, turn.id)).items[0].data == {
        "nested": ["value"]
    }


@pytest.mark.asyncio
async def test_live_lease_rejects_overlap_and_deletion(store: SessionStore) -> None:
    await store.create_session(make_session())
    await store.start_turn(make_turn(), NOW + timedelta(minutes=5))
    for operation in (
        store.start_turn(make_turn("turn-2"), NOW + timedelta(minutes=10)),
        store.delete_session("session-1"),
    ):
        with pytest.raises(AgentFailure) as failure:
            await operation
        assert failure.value.code == "session_busy"
        assert failure.value.status_code == 409
    assert len(await store.list_turns("session-1", 100)) == 1


@pytest.mark.asyncio
async def test_expired_turn_recovery_prevents_old_worker_from_overwriting(
    store: SessionStore, monkeypatch: MonkeyPatch
) -> None:
    await store.create_session(make_session())
    previous = make_turn("turn-previous")
    await store.start_turn(previous, NOW + timedelta(minutes=5))
    await store.finish_turn(completed(previous), make_state("preserved"))
    old = make_turn("turn-old")
    await store.start_turn(old, NOW + timedelta(minutes=5))
    later = NOW + timedelta(minutes=5)
    monkeypatch.setattr("api.agents.store.utc_now", lambda: later)
    new = make_turn("turn-new")
    record = await store.start_turn(new, later + timedelta(minutes=5))
    expired = await store.get_turn("session-1", old.id)
    assert expired.status == "failed"
    assert expired.error is not None
    assert expired.error.code == "lease_expired"
    assert expired.completed_at == later
    assert record.state == make_state("preserved")
    assert record.session.active_turn_id == new.id

    with pytest.raises(AgentFailure) as failure:
        await store.finish_turn(completed(old), make_state("stale"))
    assert failure.value.code == "turn_conflict"
    assert failure.value.status_code == 409
    assert (await store.get_session("session-1")).state == make_state("preserved")
    assert (await store.get_turn("session-1", old.id)).status == "failed"
    await store.finish_turn(completed(new), make_state("new"))
    assert (await store.get_session("session-1")).state == make_state("new")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_failed_or_cancelled_turn_keeps_last_successful_state(
    store: SessionStore, status: str
) -> None:
    await store.create_session(make_session())
    previous = make_turn()
    await store.start_turn(previous, NOW + timedelta(minutes=5))
    await store.finish_turn(completed(previous), make_state())
    turn = make_turn("turn-2")
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    result = AgentTurn.model_validate(
        {
            **turn.model_dump(),
            "status": status,
            "error": AgentError(code="execution_failed", message="Failed"),
        }
    )
    await store.finish_turn(result, None)
    record = await store.get_session("session-1")
    assert record.state == make_state()
    assert record.session.active_turn_id is None
    assert (await store.get_turn("session-1", turn.id)).status == status


@pytest.mark.asyncio
async def test_finish_rejects_replay_and_wrong_backend_state(
    store: SessionStore,
) -> None:
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    with pytest.raises(AgentFailure, match="another backend"):
        await store.finish_turn(completed(turn), BackendState(backend="other"))
    assert (await store.get_turn("session-1", turn.id)).status == "running"
    await store.finish_turn(completed(turn), make_state())
    with pytest.raises(AgentFailure) as failure:
        await store.finish_turn(completed(turn), make_state("replayed"))
    assert failure.value.status_code == 409
    assert (await store.get_session("session-1")).state == make_state()


@pytest.mark.asyncio
async def test_history_is_recent_first_and_bounded(store: SessionStore) -> None:
    await store.create_session(make_session())
    for index in range(4):
        turn = make_turn(f"turn-{index}")
        turn.created_at = NOW + timedelta(seconds=index)
        await store.start_turn(turn, NOW + timedelta(minutes=5))
        await store.finish_turn(completed(turn), make_state(str(index)))
    turns = await store.list_turns("session-1", 2)
    assert [turn.id for turn in turns] == ["turn-3", "turn-2"]
    turns[0].items[0].data["nested"] = ["mutated"]
    assert (await store.get_turn("session-1", "turn-3")).items[0].data == {
        "nested": ["value"]
    }
    assert await store.list_turns("session-1", 0) == []


@pytest.mark.asyncio
async def test_turn_lookup_does_not_cross_sessions(store: SessionStore) -> None:
    await store.create_session(make_session())
    await store.create_session(make_session("session-2"))
    await store.start_turn(make_turn(), NOW + timedelta(minutes=5))
    with pytest.raises(AgentFailure) as failure:
        await store.get_turn("session-2", "turn-1")
    assert failure.value.status_code == 404
    assert await store.list_turns("session-2", 100) == []


@pytest.mark.asyncio
async def test_delete_cascades_and_missing_resources_return_404(
    store: SessionStore,
) -> None:
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    await store.finish_turn(completed(turn), make_state())
    await store.delete_session("session-1")
    operations = [
        store.get_session("session-1"),
        store.get_turn("session-1", turn.id),
        store.list_turns("session-1", 10),
        store.delete_session("session-1"),
        store.start_turn(make_turn("turn-new"), NOW + timedelta(minutes=5)),
        store.finish_turn(completed(turn), make_state()),
    ]
    for operation in operations:
        with pytest.raises(AgentFailure) as failure:
            await operation
        assert failure.value.status_code == 404
    # Re-creating the session does not expose deleted history.
    await store.create_session(make_session())
    assert await store.list_turns("session-1", 100) == []
    with pytest.raises(AgentFailure) as failure:
        await store.get_turn("session-1", turn.id)
    assert failure.value.code == "turn_not_found"


@pytest.mark.asyncio
async def test_expired_lease_allows_delete(
    store: SessionStore, monkeypatch: MonkeyPatch
) -> None:
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW + timedelta(minutes=6))
    await store.delete_session("session-1")
    with pytest.raises(AgentFailure) as failure:
        await store.finish_turn(completed(turn), make_state())
    assert failure.value.status_code == 404


@pytest.mark.asyncio
async def test_invalid_claim_does_not_modify_session(store: SessionStore) -> None:
    await store.create_session(make_session())
    with pytest.raises(AgentFailure, match="future"):
        await store.start_turn(make_turn(), NOW)
    with pytest.raises(AgentFailure, match="must be running"):
        await store.start_turn(completed(make_turn()), NOW + timedelta(minutes=5))
    assert (await store.get_session("session-1")).session.active_turn_id is None
    assert await store.list_turns("session-1", 100) == []


@pytest.mark.asyncio
async def test_duplicate_turn_id_does_not_consume_expired_lease(
    store: SessionStore, monkeypatch: MonkeyPatch
) -> None:
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW + timedelta(minutes=6))
    with pytest.raises(AgentFailure) as failure:
        await store.start_turn(turn, NOW + timedelta(minutes=10))
    assert failure.value.code == "turn_conflict"
    assert (await store.get_turn("session-1", turn.id)).status == "running"
    assert (await store.get_session("session-1")).session.active_turn_id == turn.id


@pytest.mark.asyncio
async def test_failed_turn_cannot_commit_continuation(store: SessionStore) -> None:
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    failed = turn.model_copy(update={"status": "failed"})
    with pytest.raises(AgentFailure, match="Only completed turns"):
        await store.finish_turn(failed, make_state())
    assert (await store.get_session("session-1")).state is None
    assert (await store.get_turn("session-1", turn.id)).status == "running"


@pytest.mark.asyncio
async def test_memory_concurrent_claims_have_exactly_one_owner(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW)
    store = InMemorySessionStore()
    await store.create_session(make_session())
    results = await asyncio.gather(
        *(
            store.start_turn(make_turn(f"turn-{index}"), NOW + timedelta(minutes=5))
            for index in range(12)
        ),
        return_exceptions=True,
    )
    failures = [result for result in results if isinstance(result, AgentFailure)]
    assert len(failures) == 11
    assert all(failure.status_code == 409 for failure in failures)
    assert len(await store.list_turns("session-1", 100)) == 1


@pytest.mark.asyncio
async def test_database_finish_rollback_preserves_turn_and_state(
    sqlite_factory: SqliteSessionFactory, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW)
    store = PostgresSessionStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    sqlite_factory.fail_commit = True
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await store.finish_turn(completed(turn), make_state())
    sqlite_factory.fail_commit = False
    record = await store.get_session("session-1")
    assert record.state is None
    assert record.session.active_turn_id == turn.id
    assert (await store.get_turn("session-1", turn.id)).status == "running"


@pytest.mark.asyncio
async def test_database_claim_rollback_restores_expired_owner(
    sqlite_factory: SqliteSessionFactory, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW)
    store = PostgresSessionStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))
    await store.create_session(make_session())
    old = make_turn()
    await store.start_turn(old, NOW + timedelta(minutes=5))
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW + timedelta(minutes=6))
    sqlite_factory.fail_commit = True
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await store.start_turn(make_turn("turn-2"), NOW + timedelta(minutes=10))
    sqlite_factory.fail_commit = False
    assert (await store.get_session("session-1")).session.active_turn_id == old.id
    assert (await store.get_turn("session-1", old.id)).status == "running"
    assert len(await store.list_turns("session-1", 100)) == 1


@pytest.mark.asyncio
async def test_database_mutations_lock_session_rows(
    sqlite_factory: SqliteSessionFactory, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("api.agents.store.utc_now", lambda: NOW)
    store = PostgresSessionStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))
    await store.create_session(make_session())
    turn = make_turn()
    await store.start_turn(turn, NOW + timedelta(minutes=5))
    await store.finish_turn(completed(turn), make_state())
    await store.delete_session("session-1")
    locked = [
        statement
        for statement in sqlite_factory.statements
        if "FOR UPDATE" in statement
    ]
    assert len(locked) == 3
    assert all("agent_session.id =" in statement for statement in locked)


def test_postgres_schema_uses_jsonb_and_cascade() -> None:
    session_ddl = str(
        CreateTable(cast(Table, AgentSessionRecord.__table__)).compile(
            dialect=postgresql.dialect()
        )
    )
    turn_ddl = str(
        CreateTable(cast(Table, AgentTurnRecord.__table__)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "document JSONB NOT NULL" in session_ddl
    assert "TIMESTAMP WITH TIME ZONE" in session_ddl
    assert "document JSONB NOT NULL" in turn_ddl
    assert "ON DELETE CASCADE" in turn_ddl


def test_migration_round_trip_matches_model_schema() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/8d50b113df31_agent_sessions.py"
    spec = spec_from_file_location("agent_sessions_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
                inspector = inspect(connection)
                assert set(inspector.get_table_names()) == {
                    "agent_session",
                    "agent_turn",
                }
                for model in (AgentSessionRecord, AgentTurnRecord):
                    assert {
                        column["name"]
                        for column in inspector.get_columns(model.__tablename__)
                    } == set(model.__table__.columns.keys())
                migration.downgrade()
                assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
