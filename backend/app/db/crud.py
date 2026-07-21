from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Document, Message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_conversation(session: AsyncSession, title: str) -> Conversation:
    conv = Conversation(title=title[:200] or "新对话")
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(session: AsyncSession, conversation_id: int) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def list_conversations(session: AsyncSession, limit: int = 50) -> list[Conversation]:
    result = await session.execute(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def delete_conversation(session: AsyncSession, conversation_id: int) -> bool:
    conv = await get_conversation(session, conversation_id)
    if conv is None:
        return False
    await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await session.delete(conv)
    await session.flush()
    return True


async def add_message(
    session: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
) -> Message:
    msg = Message(conversation_id=conversation_id, role=role, content=content)
    session.add(msg)
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=utcnow())
    )
    await session.flush()
    return msg


async def list_messages(session: AsyncSession, conversation_id: int) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars().all())


async def create_document(
    session: AsyncSession,
    title: str,
    content: str,
    source_type: str = "text",
    file_path: str = "",
) -> Document:
    doc = Document(
        title=title[:200],
        content=content,
        source_type=source_type or "text",
        file_path=file_path or "",
    )
    session.add(doc)
    await session.flush()
    # P3: any new document invalidates optional local vector index
    from app.rag.vector_index import mark_vector_index_dirty

    mark_vector_index_dirty()
    try:
        from app.rag.answer_cache import invalidate as invalidate_answer_cache

        invalidate_answer_cache()
    except Exception:  # noqa: BLE001
        pass
    return doc


async def list_documents(session: AsyncSession, limit: int = 100) -> list[Document]:
    result = await session.execute(
        select(Document).order_by(Document.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def find_document_by_title(session: AsyncSession, title: str) -> Document | None:
    result = await session.execute(
        select(Document).where(Document.title == title[:200]).limit(1)
    )
    return result.scalar_one_or_none()
