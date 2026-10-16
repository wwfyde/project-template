"""Atomic session continuation and turn leases, independent of agent backends."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.agents.contracts import (
    AgentError,
    AgentFailure,
    AgentSession,
    AgentTurn,
    BackendState,
    SessionRecord,
    utc_now,
)
from api.models.agent_session import AgentSessionRecord, AgentTurnRecord


def _as_utc(value: datetime) -> datetime:
    # SQLite's test dialect strips timezone information from DateTime columns.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _has_live_lease(record: SessionRecord, now: datetime) -> bool:
    return (
        record.session.active_turn_id is not None
        and record.lease_expires_at is not None
        and _as_utc(record.lease_expires_at) > now
    )


def _validate_claim(turn: AgentTurn, lease_expires_at: datetime, now: datetime) -> None:
    if turn.status != "running":
        raise AgentFailure("invalid_turn", "A new turn must be running.")
    if _as_utc(lease_expires_at) <= now:
        raise AgentFailure("invalid_lease", "The turn lease must expire in the future.")


def _validate_result(
    turn: AgentTurn, state: BackendState | None, record: SessionRecord
) -> None:
    if record.session.active_turn_id != turn.id:
        raise AgentFailure(
            "turn_conflict", "The turn no longer owns this session.", 409
        )
    if turn.status == "running":
        raise AgentFailure(
            "invalid_turn", "A finished turn must have a terminal status."
        )
    if state is not None:
        if turn.status != "completed":
            raise AgentFailure(
                "invalid_state", "Only completed turns can save continuation."
            )
        if state.backend != record.session.backend:
            raise AgentFailure(
                "invalid_state", "Continuation belongs to another backend."
            )


def _expire_turn(turn: AgentTurn, now: datetime) -> AgentTurn:
    expired = turn.model_copy(deep=True)
    expired.status = "failed"
    expired.error = AgentError(
        code="lease_expired", message="The previous turn's execution lease expired."
    )
    expired.completed_at = now
    return expired


def _claim(
    record: SessionRecord, turn: AgentTurn, lease_expires_at: datetime, now: datetime
) -> None:
    record.session.active_turn_id = turn.id
    record.session.updated_at = now
    record.lease_expires_at = _as_utc(lease_expires_at)


def _finish(record: SessionRecord, state: BackendState | None, now: datetime) -> None:
    if state is not None:
        record.state = state.model_copy(deep=True)
    record.session.active_turn_id = None
    record.session.updated_at = now
    record.lease_expires_at = None


class InMemorySessionStore:
    """Single-process store; PostgreSQL is required for shared worker state."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._turns: dict[str, AgentTurn] = {}
        self._lock = asyncio.Lock()

    def _session(self, session_id: str) -> SessionRecord:
        record = self._sessions.get(session_id)
        if record is None:
            raise AgentFailure("session_not_found", "Agent session not found.", 404)
        return record

    async def create_session(self, session: AgentSession) -> None:
        async with self._lock:
            if session.id in self._sessions:
                raise AgentFailure(
                    "duplicate_session", "Agent session already exists.", 409
                )
            self._sessions[session.id] = SessionRecord(
                session=session.model_copy(deep=True)
            )

    async def get_session(self, session_id: str) -> SessionRecord:
        async with self._lock:
            return self._session(session_id).model_copy(deep=True)

    async def start_turn(
        self, turn: AgentTurn, lease_expires_at: datetime
    ) -> SessionRecord:
        async with self._lock:
            record = self._session(turn.session_id)
            now = utc_now()
            _validate_claim(turn, lease_expires_at, now)
            if _has_live_lease(record, now):
                raise AgentFailure(
                    "session_busy", "An agent turn is already running.", 409
                )
            if turn.id in self._turns:
                raise AgentFailure("turn_conflict", "Agent turn already exists.", 409)
            previous_id = record.session.active_turn_id
            if previous_id is not None:
                self._turns[previous_id] = _expire_turn(self._turns[previous_id], now)
            _claim(record, turn, lease_expires_at, now)
            self._turns[turn.id] = turn.model_copy(deep=True)
            return record.model_copy(deep=True)

    async def finish_turn(self, turn: AgentTurn, state: BackendState | None) -> None:
        async with self._lock:
            record = self._session(turn.session_id)
            _validate_result(turn, state, record)
            self._turns[turn.id] = turn.model_copy(deep=True)
            _finish(record, state, utc_now())

    async def get_turn(self, session_id: str, turn_id: str) -> AgentTurn:
        async with self._lock:
            self._session(session_id)
            turn = self._turns.get(turn_id)
            if turn is None or turn.session_id != session_id:
                raise AgentFailure("turn_not_found", "Agent turn not found.", 404)
            return turn.model_copy(deep=True)

    async def list_turns(self, session_id: str, limit: int) -> list[AgentTurn]:
        async with self._lock:
            self._session(session_id)
            turns = sorted(
                (
                    turn
                    for turn in self._turns.values()
                    if turn.session_id == session_id
                ),
                key=lambda turn: (_as_utc(turn.created_at), turn.id),
                reverse=True,
            )
            return [turn.model_copy(deep=True) for turn in turns[: max(0, limit)]]

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            record = self._session(session_id)
            if _has_live_lease(record, utc_now()):
                raise AgentFailure(
                    "session_busy", "An agent turn is already running.", 409
                )
            del self._sessions[session_id]
            self._turns = {
                turn_id: turn
                for turn_id, turn in self._turns.items()
                if turn.session_id != session_id
            }


class PostgresSessionStore:
    """Every mutation serializes on the session row inside one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def _session(
        database: AsyncSession, session_id: str, *, lock: bool = False
    ) -> AgentSessionRecord:
        query = select(AgentSessionRecord).where(AgentSessionRecord.id == session_id)
        if lock:
            query = query.with_for_update()
        row = (await database.execute(query)).scalar_one_or_none()
        if row is None:
            raise AgentFailure("session_not_found", "Agent session not found.", 404)
        return row

    @staticmethod
    def _read(row: AgentSessionRecord) -> SessionRecord:
        record = SessionRecord.model_validate(row.document)
        record.session.active_turn_id = row.active_turn_id
        record.lease_expires_at = (
            _as_utc(row.lease_expires_at) if row.lease_expires_at is not None else None
        )
        return record

    @staticmethod
    def _write(row: AgentSessionRecord, record: SessionRecord) -> None:
        row.document = record.model_dump(mode="json")
        row.active_turn_id = record.session.active_turn_id
        row.lease_expires_at = record.lease_expires_at

    async def create_session(self, session: AgentSession) -> None:
        try:
            async with self._session_factory.begin() as database:
                database.add(
                    AgentSessionRecord(
                        id=session.id,
                        document=SessionRecord(session=session).model_dump(mode="json"),
                        active_turn_id=None,
                        lease_expires_at=None,
                    )
                )
        except IntegrityError as error:
            raise AgentFailure(
                "duplicate_session", "Agent session already exists.", 409
            ) from error

    async def get_session(self, session_id: str) -> SessionRecord:
        async with self._session_factory.begin() as database:
            return self._read(await self._session(database, session_id))

    async def start_turn(
        self, turn: AgentTurn, lease_expires_at: datetime
    ) -> SessionRecord:
        try:
            async with self._session_factory.begin() as database:
                row = await self._session(database, turn.session_id, lock=True)
                record = self._read(row)
                now = utc_now()
                _validate_claim(turn, lease_expires_at, now)
                if _has_live_lease(record, now):
                    raise AgentFailure(
                        "session_busy", "An agent turn is already running.", 409
                    )
                if await database.get(AgentTurnRecord, turn.id) is not None:
                    raise AgentFailure(
                        "turn_conflict", "Agent turn already exists.", 409
                    )
                previous_id = record.session.active_turn_id
                if previous_id is not None:
                    previous = await database.get(AgentTurnRecord, previous_id)
                    if previous is not None:
                        previous.document = _expire_turn(
                            AgentTurn.model_validate(previous.document), now
                        ).model_dump(mode="json")
                _claim(record, turn, lease_expires_at, now)
                self._write(row, record)
                database.add(
                    AgentTurnRecord(
                        id=turn.id,
                        session_id=turn.session_id,
                        document=turn.model_dump(mode="json"),
                        created_at=turn.created_at,
                    )
                )
                return record
        except IntegrityError as error:
            raise AgentFailure(
                "turn_conflict", "Agent turn already exists.", 409
            ) from error

    async def finish_turn(self, turn: AgentTurn, state: BackendState | None) -> None:
        async with self._session_factory.begin() as database:
            row = await self._session(database, turn.session_id, lock=True)
            record = self._read(row)
            _validate_result(turn, state, record)
            previous = await database.get(AgentTurnRecord, turn.id)
            if previous is None or previous.session_id != turn.session_id:
                raise AgentFailure("turn_not_found", "Agent turn not found.", 404)
            previous.document = turn.model_dump(mode="json")
            _finish(record, state, utc_now())
            self._write(row, record)

    async def get_turn(self, session_id: str, turn_id: str) -> AgentTurn:
        async with self._session_factory.begin() as database:
            await self._session(database, session_id)
            row = await database.get(AgentTurnRecord, turn_id)
            if row is None or row.session_id != session_id:
                raise AgentFailure("turn_not_found", "Agent turn not found.", 404)
            return AgentTurn.model_validate(row.document)

    async def list_turns(self, session_id: str, limit: int) -> list[AgentTurn]:
        async with self._session_factory.begin() as database:
            await self._session(database, session_id)
            result = await database.execute(
                select(AgentTurnRecord)
                .where(AgentTurnRecord.session_id == session_id)
                .order_by(AgentTurnRecord.created_at.desc(), AgentTurnRecord.id.desc())
                .limit(max(0, limit))
            )
            return [AgentTurn.model_validate(row.document) for row in result.scalars()]

    async def delete_session(self, session_id: str) -> None:
        async with self._session_factory.begin() as database:
            row = await self._session(database, session_id, lock=True)
            if _has_live_lease(self._read(row), utc_now()):
                raise AgentFailure(
                    "session_busy", "An agent turn is already running.", 409
                )
            await database.delete(row)
