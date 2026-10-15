import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


type APIObject = object


def _dump_api_object(value: APIObject) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("API object keys must be strings")
            payload[key] = item
        return payload

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        if isinstance(payload, dict):
            return payload

    raise TypeError("API object must be a mapping or expose model_dump()")


def _api_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, bool):
        raise TypeError("API timestamp cannot be a boolean")
    if isinstance(value, int | float | str):
        return datetime.fromtimestamp(float(value), tz=UTC)
    raise TypeError(f"Unsupported API timestamp: {type(value).__name__}")


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


class Project(Base):
    __tablename__ = "project"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid7,
        server_default=text("uuidv7()"),
        comment="ID",
    )


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid7())
    )
    title: Mapped[str] = mapped_column(
        String(240), nullable=False, default="新对话", index=True
    )
    endpoint: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="agent", index=True
    )
    user_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    openai_responses: Mapped[list["OpenaiResponse"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


type Role = Literal["user", "system", "developer", "assistant", "tool"]


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_conversation_created_at", "conversation_id", "created_at"),
        Index("ix_message_parent_message_id", "parent_message_id"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid7())
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    sender: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="结构化消息"
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_created_by_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    unfinished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    openai_responses: Mapped[list["OpenaiResponse"]] = relationship(
        back_populates="message"
    )


class OpenaiResponse(Base):
    __tablename__ = "openai_response"
    __table_args__ = (
        Index(
            "ix_openai_response_conversation_created_at",
            "conversation_id",
            "api_created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("message.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    previous_response_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    openai_conversation_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )

    object: Mapped[str] = mapped_column(String(32), nullable=False, default="response")
    status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    api_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    api_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    background: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    store: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parallel_tool_calls: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tool_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_logprobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_cache_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_cache_retention: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    safety_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    truncation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user: Mapped[str | None] = mapped_column(Text, nullable=True)

    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    incomplete_details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    instructions: Mapped[str | list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    prompt: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reasoning: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    text: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tool_choice: Mapped[str | dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="openai_responses")
    message: Mapped[Message | None] = relationship(back_populates="openai_responses")
    items: Mapped[list["ResponseItem"]] = relationship(
        back_populates="response",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ResponseItem.output_index",
    )

    @classmethod
    def from_api_response(
        cls,
        response: APIObject,
        *,
        conversation_id: str,
        message_id: str | None = None,
    ) -> "OpenaiResponse":
        payload = _dump_api_object(response)
        response_id = payload.get("id")
        model = payload.get("model")
        api_created_at = _api_timestamp(payload.get("created_at"))
        if not response_id or not model or api_created_at is None:
            raise ValueError("Response must contain id, model, and created_at")

        provider_conversation = payload.get("conversation")
        if isinstance(provider_conversation, Mapping):
            openai_conversation_id = _optional_string(provider_conversation.get("id"))
        else:
            openai_conversation_id = _optional_string(provider_conversation)

        record = cls(
            id=str(response_id),
            conversation_id=conversation_id,
            message_id=message_id,
            previous_response_id=_optional_string(payload.get("previous_response_id")),
            openai_conversation_id=openai_conversation_id,
            object=str(payload.get("object", "response")),
            status=_optional_string(payload.get("status")),
            model=str(model),
            api_created_at=api_created_at,
            api_completed_at=_api_timestamp(payload.get("completed_at")),
            background=payload.get("background"),
            store=payload.get("store"),
            parallel_tool_calls=payload.get("parallel_tool_calls"),
            max_output_tokens=payload.get("max_output_tokens"),
            max_tool_calls=payload.get("max_tool_calls"),
            temperature=payload.get("temperature"),
            top_p=payload.get("top_p"),
            top_logprobs=payload.get("top_logprobs"),
            prompt_cache_key=_optional_string(payload.get("prompt_cache_key")),
            prompt_cache_retention=_optional_string(
                payload.get("prompt_cache_retention")
            ),
            safety_identifier=_optional_string(payload.get("safety_identifier")),
            service_tier=_optional_string(payload.get("service_tier")),
            truncation=_optional_string(payload.get("truncation")),
            user=_optional_string(payload.get("user")),
            error=payload.get("error"),
            incomplete_details=payload.get("incomplete_details"),
            instructions=payload.get("instructions"),
            response_metadata=payload.get("metadata"),
            prompt=payload.get("prompt"),
            reasoning=payload.get("reasoning"),
            text=payload.get("text"),
            tool_choice=payload.get("tool_choice"),
            tools=payload.get("tools") or [],
            usage=payload.get("usage"),
            raw_response=payload,
        )

        output = payload.get("output")
        if isinstance(output, list):
            record.items = [
                ResponseItem.from_api_item(item, output_index=index)
                for index, item in enumerate(output)
            ]
        return record


class ResponseItem(Base):
    __tablename__ = "response_item"
    __table_args__ = (
        UniqueConstraint(
            "response_id",
            "output_index",
            name="uq_response_item_response_output_index",
        ),
        Index("ix_response_item_response_type", "response_id", "type"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid7())
    )
    response_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("openai_response.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    output_index: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    response: Mapped[OpenaiResponse] = relationship(back_populates="items")

    @classmethod
    def from_api_item(cls, item: APIObject, *, output_index: int) -> "ResponseItem":
        payload = _dump_api_object(item)
        item_type = payload.get("type")
        if not item_type:
            raise ValueError("Response output item must contain type")

        return cls(
            item_id=_optional_string(payload.get("id")),
            output_index=output_index,
            type=str(item_type),
            status=_optional_string(payload.get("status")),
            role=_optional_string(payload.get("role")),
            call_id=_optional_string(payload.get("call_id")),
            name=_optional_string(payload.get("name")),
            data=payload,
        )


class ClaudeMessage(Base):
    __abstract__ = True


class MessageBlock(Base):
    __abstract__ = True
