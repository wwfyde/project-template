"""Session/turn orchestration, independent of FastAPI and any agent SDK."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import timedelta

from pydantic import JsonValue

from api.agents.contracts import (
    AgentBackend,
    AgentError,
    AgentEvent,
    AgentEventType,
    AgentFailure,
    AgentItem,
    AgentSession,
    AgentTurn,
    BackendState,
    RunRequest,
    RunResult,
    SessionCreate,
    SessionStore,
    TurnCreate,
    utc_now,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedTurn:
    backend: AgentBackend
    request: RunRequest
    turn: AgentTurn


class AgentService:
    def __init__(
        self,
        backends: dict[str, AgentBackend],
        store: SessionStore,
        default_backend: str = "openai-agents",
        run_timeout_seconds: float = 120,
    ) -> None:
        if run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds must be positive")
        if any(name != backend.name for name, backend in backends.items()):
            raise ValueError("Backend registry keys must match backend names")
        self.backends = dict(backends)
        self.store = store
        self.default_backend = default_backend
        self.run_timeout_seconds = run_timeout_seconds
        self._pending_writes: set[asyncio.Task[None]] = set()

    def _backend(self, name: str) -> AgentBackend:
        backend = self.backends.get(name)
        if backend is None:
            raise AgentFailure(
                "backend_unavailable",
                "The requested agent backend is not configured.",
                503,
            )
        return backend

    async def create_session(self, payload: SessionCreate) -> AgentSession:
        backend = self._backend(payload.backend or self.default_backend)
        agent = backend.validate(payload.agent.model_copy(deep=True))
        session = AgentSession(backend=backend.name, agent=agent)
        await self.store.create_session(session)
        return session

    async def get_session(self, session_id: str) -> AgentSession:
        return (await self.store.get_session(session_id)).session

    async def delete_session(self, session_id: str) -> None:
        await self.store.delete_session(session_id)

    async def get_turn(self, session_id: str, turn_id: str) -> AgentTurn:
        return await self.store.get_turn(session_id, turn_id)

    async def list_turns(self, session_id: str, limit: int = 50) -> list[AgentTurn]:
        return await self.store.list_turns(session_id, limit)

    async def start_turn(self, session_id: str, payload: TurnCreate) -> PreparedTurn:
        if not payload.input.strip():
            raise AgentFailure(
                "invalid_input", "Input must contain non-whitespace text.", 422
            )
        record = await self.store.get_session(session_id)
        backend = self._backend(record.session.backend)
        # Revalidate server-side tool availability after deployment/configuration changes.
        backend.validate(record.session.agent.model_copy(deep=True))
        turn = AgentTurn(
            session_id=session_id,
            input=payload.input,
            items=[AgentItem(type="message", role="user", text=payload.input)],
        )
        # The lease outlives the execution timeout to allow SDK cancellation and commit.
        claim = asyncio.create_task(
            self.store.start_turn(
                turn, utc_now() + timedelta(seconds=self.run_timeout_seconds + 30)
            )
        )
        try:
            record = await asyncio.shield(claim)
        except asyncio.CancelledError:
            # A commit can succeed while its awaiting request is cancelled. Resolve
            # the claim before releasing it; never cancel another request's turn.
            async def release_claim() -> None:
                try:
                    await claim
                except Exception:
                    return
                await self._cancel(turn)

            cleanup = asyncio.create_task(release_claim())
            self._track_write(cleanup, turn.id)
            raise
        return PreparedTurn(
            backend=backend,
            request=RunRequest(
                session_id=session_id,
                turn_id=turn.id,
                agent=record.session.agent,
                input=payload.input,
                state=record.state,
            ),
            turn=turn,
        )

    async def run_turn(self, prepared: PreparedTurn) -> AgentTurn:
        async with aclosing(self.stream_turn(prepared)) as events:
            async for _ in events:
                pass
        return await self.get_turn(prepared.turn.session_id, prepared.turn.id)

    async def cancel_unstarted_turn(self, prepared: PreparedTurn) -> None:
        """Release a claim when HTTP headers fail before the generator is entered.

        The caller must close the stream first; cancellation of an entered stream
        is owned by stream_turn's finally block.
        """
        turn = prepared.turn
        if turn.status == "running":
            await self._cancel(turn)

    async def _cancel(self, turn: AgentTurn) -> None:
        turn.status = "cancelled"
        turn.error = AgentError(
            code="run_cancelled", message="Agent execution was cancelled."
        )
        turn.completed_at = utc_now()
        await self._finish(turn, None)

    def _track_write(self, task: asyncio.Task[None], turn_id: str) -> None:
        self._pending_writes.add(task)

        def done(completed: asyncio.Task[None]) -> None:
            self._pending_writes.discard(completed)
            if (
                not completed.cancelled()
                and (error := completed.exception()) is not None
            ):
                logger.warning(
                    "Agent turn persistence failed turn_id=%s error_type=%s",
                    turn_id,
                    type(error).__name__,
                )

        task.add_done_callback(done)

    async def _finish(self, turn: AgentTurn, state: BackendState | None) -> None:
        # Preserve the terminal write when the HTTP request is cancelled. Keep a
        # strong task reference and drain outstanding writes at application shutdown.
        async def write() -> None:
            async with asyncio.timeout(10):
                await self.store.finish_turn(turn, state)

        task = asyncio.create_task(write())
        self._track_write(task, turn.id)
        await asyncio.shield(task)

    async def stream_turn(
        self, prepared: PreparedTurn
    ) -> AsyncGenerator[AgentEvent, None]:
        turn = prepared.turn
        sequence = 0
        finalizing = False

        def event(kind: AgentEventType, data: dict[str, JsonValue]) -> AgentEvent:
            nonlocal sequence
            sequence += 1
            return AgentEvent(
                type=kind,
                session_id=turn.session_id,
                turn_id=turn.id,
                sequence=sequence,
                data=data,
            )

        try:
            yield event("turn.started", {"turn": turn.model_dump(mode="json")})
            result: RunResult | None = None
            async with asyncio.timeout(self.run_timeout_seconds):
                async with aclosing(
                    prepared.backend.stream(prepared.request)
                ) as events:
                    async for update in events:
                        if result is not None:
                            raise AgentFailure(
                                "invalid_backend_result",
                                "Backend emitted data after its result.",
                                502,
                            )
                        if update.type == "result":
                            result = update.result
                            if (
                                result is None
                                or result.state.backend != prepared.backend.name
                            ):
                                raise AgentFailure(
                                    "invalid_backend_result",
                                    "Backend returned invalid continuation state.",
                                    502,
                                )
                        else:
                            if update.type == "item.completed":
                                item = AgentItem.model_validate(update.data["item"])
                                turn.items.append(item)
                            yield event(update.type, update.data)
            if result is None:
                raise AgentFailure(
                    "incomplete_run", "Backend stopped without a final result.", 502
                )
            turn.status = "completed"
            turn.output = result.output
            turn.usage = result.usage
            turn.items = [turn.items[0], *result.items]
            turn.completed_at = utc_now()
            finalizing = True
            await self._finish(turn, result.state)
            yield event("turn.completed", {"turn": turn.model_dump(mode="json")})
        except asyncio.CancelledError, GeneratorExit:
            raise
        except Exception as exc:
            if finalizing:
                raise
            if isinstance(exc, TimeoutError):
                error = AgentError(
                    code="run_timeout",
                    message="Agent execution exceeded its time limit.",
                )
            elif isinstance(exc, AgentFailure):
                error = AgentError(code=exc.code, message=exc.message)
            else:
                # Never log provider exception text, prompts, tool results or credentials.
                logger.warning(
                    "Agent turn failed turn_id=%s error_type=%s",
                    turn.id,
                    type(exc).__name__,
                )
                error = AgentError(
                    code="execution_failed", message="Agent execution failed."
                )
            turn.status = "failed"
            turn.error = error
            turn.completed_at = utc_now()
            finalizing = True
            await self._finish(turn, None)
            yield event("turn.failed", {"turn": turn.model_dump(mode="json")})
        finally:
            if not finalizing:
                await self._cancel(turn)

    async def aclose(self) -> None:
        while self._pending_writes:
            await asyncio.gather(*self._pending_writes, return_exceptions=True)
        for backend in self.backends.values():
            await backend.aclose()
