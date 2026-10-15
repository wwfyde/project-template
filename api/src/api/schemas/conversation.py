from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MessageRole = Literal["system", "user", "assistant", "tool"]
ConversationMode = Literal["agent", "image"]


def _datetime_to_iso(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone().isoformat(timespec="seconds")
    return value


class MessageBase(BaseModel):
    role: MessageRole
    content: str | list[dict[str, object]] | dict[str, object] | None = None
    text: str | None = None
    sender: str | None = None
    parent_message_id: str | None = Field(default=None, alias="parentMessageId")
    model: str | None = None
    endpoint: str | None = None
    is_created_by_user: bool = Field(default=False, alias="isCreatedByUser")
    unfinished: bool = False
    cancelled: bool = False
    error: str | None = None
    meta: dict[str, object] | None = None

    model_config = ConfigDict(populate_by_name=True)


class MessageCreate(MessageBase):
    id: str | None = Field(default=None, alias="messageId")
    conversation_id: str | None = Field(default=None, alias="conversationId")


class MessageRead(MessageBase):
    id: str = Field(validation_alias="messageId")
    conversation_id: str = Field(validation_alias="conversationId")
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def format_datetime(cls, value: object) -> object:
        return _datetime_to_iso(value)


class ConversationCreate(BaseModel):
    title: str | None = None
    endpoint: str | None = None
    model: str | None = None
    mode: ConversationMode = "agent"
    user_id: str | None = None
    is_pinned: bool = False
    meta: dict[str, object] | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    endpoint: str | None = None
    model: str | None = None
    mode: ConversationMode | None = None
    is_archived: bool | None = None
    is_pinned: bool | None = None
    meta: dict[str, object] | None = None


class ConversationRead(BaseModel):
    id: str = Field(validation_alias="conversationId")
    title: str
    endpoint: str | None = None
    model: str | None = None
    mode: ConversationMode
    user_id: str | None = None
    is_archived: bool = Field(validation_alias="isArchived")
    is_pinned: bool = Field(validation_alias="isPinned")
    meta: dict[str, object] | None = None
    created_at: str
    updated_at: str
    latest_message: MessageRead | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def format_datetime(cls, value: object) -> object:
        return _datetime_to_iso(value)


class ConversationDetail(ConversationRead):
    messages: list[MessageRead] = Field(default_factory=list)
