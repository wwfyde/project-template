"""Application-owned agent contracts. No SDK or transport types cross this module."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentDefinition(Contract):
    name: str = Field(default="Assistant", min_length=1, max_length=100)
    instructions: str = Field(default="You are a helpful assistant.", max_length=32000)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    tools: list[str] = Field(default_factory=list, max_length=64)
    max_steps: int = Field(default=10, ge=1, le=100)


class SessionCreate(Contract):
    backend: str | None = Field(default=None, min_length=1, max_length=100)
    agent: AgentDefinition = Field(default_factory=AgentDefinition)


class AgentSession(Contract):
    id: str = Field(default_factory=new_id)
    backend: str
    agent: AgentDefinition
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    active_turn_id: str | None = None


class TurnCreate(Contract):
    input: str = Field(min_length=1, max_length=128000)
    stream: bool = False


class AgentItem(Contract):
    id: str = Field(default_factory=new_id)
    type: Literal["message", "tool_call", "tool_result", "handoff", "reasoning"]
    role: Literal["user", "assistant", "tool"] | None = None
    text: str | None = None
    call_id: str | None = None
    name: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)


class AgentUsage(Contract):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AgentError(Contract):
    code: str
    message: str


class AgentTurn(Contract):
    id: str = Field(default_factory=new_id)
    session_id: str
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    input: str
    output: str | None = None
    items: list[AgentItem] = Field(default_factory=list)
    usage: AgentUsage = Field(default_factory=AgentUsage)
    error: AgentError | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


type AgentEventType = Literal[
    "turn.started",
    "output_text.delta",
    "item.completed",
    "agent.updated",
    "turn.completed",
    "turn.failed",
]


class AgentEvent(Contract):
    type: AgentEventType
    session_id: str
    turn_id: str
    sequence: int
    data: dict[str, JsonValue] = Field(default_factory=dict)


class BackendState(Contract):
    """Opaque, backend-versioned continuation; never returned by HTTP endpoints."""

    backend: str
    version: int = 1
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class SessionRecord(Contract):
    session: AgentSession
    state: BackendState | None = None
    lease_expires_at: datetime | None = None


@dataclass(frozen=True)
class RunRequest:
    session_id: str
    turn_id: str
    agent: AgentDefinition
    input: str
    state: BackendState | None = None


@dataclass(frozen=True)
class RunResult:
    output: str
    state: BackendState
    items: list[AgentItem] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)


@dataclass(frozen=True)
class RunEvent:
    """Backend stream: progress events followed by exactly one result, then EOF."""

    type: Literal["output_text.delta", "item.completed", "agent.updated", "result"]
    data: dict[str, JsonValue] = field(default_factory=dict)
    result: RunResult | None = None


class AgentBackend(Protocol):
    name: str

    def validate(self, agent: AgentDefinition) -> AgentDefinition:
        """Resolve defaults and reject unsupported configuration before creating a session."""
        ...

    def stream(self, request: RunRequest) -> AsyncGenerator[RunEvent, None]:
        """Closing the iterator must stop its model/tool execution."""
        ...

    async def aclose(self) -> None: ...


class SessionStore(Protocol):
    async def create_session(self, session: AgentSession) -> None: ...

    async def get_session(self, session_id: str) -> SessionRecord: ...

    async def start_turn(
        self, turn: AgentTurn, lease_expires_at: datetime
    ) -> SessionRecord:
        """Atomically claim a session; reject overlap, recover an expired lease as failed."""
        ...

    async def finish_turn(self, turn: AgentTurn, state: BackendState | None) -> None:
        """CAS on active_turn_id; commit result and continuation together, release lease.

        None leaves the previous successful continuation intact.
        """
        ...

    async def get_turn(self, session_id: str, turn_id: str) -> AgentTurn: ...

    async def list_turns(self, session_id: str, limit: int) -> list[AgentTurn]: ...

    async def delete_session(self, session_id: str) -> None:
        """Reject deletion while a non-expired run owns the session."""
        ...


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    turn_id: str


@dataclass(frozen=True)
class AgentTool:
    """Server-registered tool; clients may select names, never provide executable code."""

    name: str
    description: str
    parameters: dict[str, JsonValue]
    invoke: Callable[[ToolContext, dict[str, JsonValue]], Awaitable[JsonValue]]


class AgentFailure(Exception):
    """Safe application error: message may be sent to the caller."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
