from collections import defaultdict
from typing import Annotated, cast
from uuid import UUID

import uuid_utils as uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import CursorResult, delete, desc, select

from api.auth.dependencies import CurrentUserDep, UsersDep, authorize_resource
from api.core.config import settings
from api.models.conversation import Conversation as ConversationModel
from api.models.conversation import Message as MessageModel
from api.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
)

conversations_router = APIRouter(dependencies=[Depends(authorize_resource)])

_memory_conversations: dict[str, ConversationRead] = {}
_memory_messages: dict[str, list[MessageRead]] = defaultdict(list)


def _title_from_message(message: MessageCreate) -> str:
    if message.text:
        return message.text.strip().split("\n")[0][:120] or "新对话"
    if isinstance(message.content, str):
        return message.content.strip().split("\n")[0][:120] or "新对话"
    if isinstance(message.content, list):
        for block in message.content:
            if block.get("type") == "text" and block.get("text"):
                return str(block["text"]).strip().split("\n")[0][:120] or "新对话"
    return "新对话"


def _read_conversation(
    conversation: ConversationModel, latest_message: MessageModel | None = None
) -> ConversationRead:
    data = ConversationRead.model_validate(conversation)
    if latest_message:
        data.latest_message = MessageRead.model_validate(latest_message)
    return data


async def _list_conversations_from_db(
    limit: int, include_archived: bool, owned_ids: set[str]
) -> list[ConversationRead]:
    from api.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stmt = select(ConversationModel).where(ConversationModel.id.in_(owned_ids))
        if not include_archived:
            stmt = stmt.where(ConversationModel.is_archived.is_(False))
        stmt = stmt.order_by(desc(ConversationModel.updated_at)).limit(limit)
        result = await session.execute(stmt)
        conversations = list(result.scalars().all())
        items: list[ConversationRead] = []
        for conversation in conversations:
            latest_stmt = (
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation.id)
                .order_by(desc(MessageModel.created_at))
                .limit(1)
            )
            latest_result = await session.execute(latest_stmt)
            items.append(
                _read_conversation(conversation, latest_result.scalar_one_or_none())
            )
        return items


async def _get_conversation_from_db(conversation_id: str) -> ConversationDetail:
    from api.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        conversation = await session.get(ConversationModel, conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        messages_result = await session.execute(
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at, MessageModel.id)
        )
        data = ConversationDetail.model_validate(conversation)
        data.messages = [
            MessageRead.model_validate(message)
            for message in messages_result.scalars().all()
        ]
        return data


@conversations_router.get("", response_model=list[ConversationRead])
async def list_conversations(
    user: CurrentUserDep,
    users: UsersDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    include_archived: bool = False,
) -> list[ConversationRead]:
    owned_ids = await users.owned_ids("conversation", user)
    if not owned_ids:
        return []
    if settings.repo_type == "postgres":
        return await _list_conversations_from_db(limit, include_archived, owned_ids)

    items = [
        item
        for item in _memory_conversations.values()
        if item.id in owned_ids and (include_archived or not item.is_archived)
    ]
    return sorted(items, key=lambda item: item.updated_at, reverse=True)[:limit]


@conversations_router.post(
    "", response_model=ConversationRead, status_code=status.HTTP_201_CREATED
)
async def create_conversation(
    payload: ConversationCreate,
    request: Request,
    user: CurrentUserDep,
    users: UsersDep,
) -> ConversationRead:
    claimed = request.headers.getlist("User-Code")
    if (payload.user_id is not None and payload.user_id != user.id) or (
        claimed and claimed != [user.id]
    ):
        raise HTTPException(403, "Owner does not match the authenticated user")
    conversation_id = str(uuid.uuid7())
    title = payload.title or "新对话"

    if settings.repo_type == "postgres":
        from api.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            conversation = ConversationModel(
                id=conversation_id,
                title=title,
                endpoint=payload.endpoint,
                model=payload.model,
                mode=payload.mode,
                user_id=user.id,
                is_pinned=payload.is_pinned,
                meta=payload.meta,
            )
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
            await users.own("conversation", conversation_id, user)
            return _read_conversation(conversation)

    conversation = ConversationRead(
        id=conversation_id,
        title=title,
        endpoint=payload.endpoint,
        model=payload.model,
        mode=payload.mode,
        user_id=user.id,
        is_archived=False,
        is_pinned=payload.is_pinned,
        meta=payload.meta,
        created_at="",
        updated_at="",
    )
    _memory_conversations[conversation_id] = conversation
    await users.own("conversation", conversation_id, user)
    return conversation


@conversations_router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> ConversationDetail:
    if settings.repo_type == "postgres":
        return await _get_conversation_from_db(conversation_id)

    conversation = _memory_conversations.get(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return ConversationDetail(
        **conversation.model_dump(), messages=_memory_messages[conversation_id]
    )


@conversations_router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: str, payload: ConversationUpdate
) -> ConversationRead:
    updates = payload.model_dump(exclude_unset=True)
    if settings.repo_type == "postgres":
        from api.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            conversation = await session.get(ConversationModel, conversation_id)
            if not conversation:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )
            for key, value in updates.items():
                setattr(conversation, key, value)
            await session.commit()
            await session.refresh(conversation)
            return _read_conversation(conversation)

    conversation = _memory_conversations.get(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    next_data = conversation.model_copy(update=updates)
    _memory_conversations[conversation_id] = next_data
    return next_data


@conversations_router.delete(
    "/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(conversation_id: str) -> Response:
    if settings.repo_type == "postgres":
        from api.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(ConversationModel).where(ConversationModel.id == conversation_id)
            )
            result = cast(CursorResult[ConversationModel], result)
            if result.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )
            await session.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    if conversation_id not in _memory_conversations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    _memory_conversations.pop(conversation_id)
    _memory_messages.pop(conversation_id, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conversations_router.get(
    "/{conversation_id}/messages", response_model=list[MessageRead]
)
async def list_messages(conversation_id: str) -> list[MessageRead]:
    if settings.repo_type == "postgres":
        detail = await _get_conversation_from_db(conversation_id)
        return detail.messages

    if conversation_id not in _memory_conversations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return _memory_messages[conversation_id]


@conversations_router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: str, payload: MessageCreate, user: CurrentUserDep
) -> MessageRead:
    message_id = payload.id or str(uuid.uuid7())
    text = (
        payload.text or payload.content
        if isinstance(payload.content, str)
        else payload.text
    )

    if settings.repo_type == "postgres":
        from api.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            conversation = await session.get(ConversationModel, conversation_id)
            if not conversation:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )
            message = MessageModel(
                id=message_id,
                user_id=UUID(user.id),
                conversation_id=conversation_id,
                parent_message_id=payload.parent_message_id,
                role=payload.role,
                sender=payload.sender,
                content=payload.content,
                text=text,
                model=payload.model,
                endpoint=payload.endpoint,
                is_created_by_user=payload.is_created_by_user,
                unfinished=payload.unfinished,
                cancelled=payload.cancelled,
                error=payload.error,
                meta=payload.meta,
            )
            if conversation.title == "新对话" and payload.role == "user":
                conversation.title = _title_from_message(payload)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return MessageRead.model_validate(message)

    conversation = _memory_conversations.get(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    message = MessageRead(
        id=message_id,
        conversation_id=conversation_id,
        parent_message_id=payload.parent_message_id,
        role=payload.role,
        sender=payload.sender,
        content=payload.content,
        text=text,
        model=payload.model,
        endpoint=payload.endpoint,
        is_created_by_user=payload.is_created_by_user,
        unfinished=payload.unfinished,
        cancelled=payload.cancelled,
        error=payload.error,
        meta=payload.meta,
        created_at="",
        updated_at="",
    )
    _memory_messages[conversation_id].append(message)
    if conversation.title == "新对话" and payload.role == "user":
        _memory_conversations[conversation_id] = conversation.model_copy(
            update={"title": _title_from_message(payload)}
        )
    return message
