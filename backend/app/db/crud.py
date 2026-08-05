from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Document, Message, User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_conversation(
    session: AsyncSession,
    title: str,
    user_id: int | None = None,
) -> Conversation:
    conv = Conversation(title=title[:200] or "新对话", user_id=user_id)
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(
    session: AsyncSession,
    conversation_id: int,
    user_id: int | None = None,
) -> Conversation | None:
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_conversations(
    session: AsyncSession,
    limit: int = 50,
    user_id: int | None = None,
) -> list[Conversation]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_conversation(
    session: AsyncSession,
    conversation_id: int,
    user_id: int | None = None,
) -> bool:
    conv = await get_conversation(session, conversation_id, user_id=user_id)
    if conv is None:
        return False
    await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await session.delete(conv)
    await session.flush()
    return True


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(
        select(User).where(User.username == username.strip().lower()).limit(1)
    )
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    username: str,
    password_hash: str,
    display_name: str = "",
) -> User:
    user = User(
        username=username.strip().lower()[:64],
        password_hash=password_hash,
        display_name=(display_name or username).strip()[:100],
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


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
    user_id: int | None = None,
) -> Document:
    doc = Document(
        user_id=user_id,
        title=title[:200],
        content=content,
        source_type=source_type or "text",
        file_path=file_path or "",
    )
    session.add(doc)
    await session.flush()
    # P3: any new document invalidates optional local vector index (user + shared)
    from app.rag.vector_index import mark_vector_index_dirty

    mark_vector_index_dirty(user_id=user_id)
    try:
        from app.rag.answer_cache import invalidate as invalidate_answer_cache

        invalidate_answer_cache()
    except Exception:  # noqa: BLE001
        pass
    return doc


async def list_documents(
    session: AsyncSession, limit: int = 100, user_id: int | None = None
) -> list[Document]:
    stmt = select(Document).order_by(Document.created_at.desc()).limit(limit)
    if user_id is not None:
        stmt = stmt.where(Document.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_documents_by_ids(
    session: AsyncSession, ids: list[int], user_id: int | None = None
) -> list[Document]:
    clean = []
    seen: set[int] = set()
    for raw in ids or []:
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if i in seen:
            continue
        seen.add(i)
        clean.append(i)
    if not clean:
        return []
    stmt = select(Document).where(Document.id.in_(clean))
    if user_id is not None:
        stmt = stmt.where(Document.user_id == user_id)
    result = await session.execute(stmt)
    by_id = {d.id: d for d in result.scalars().all()}
    return [by_id[i] for i in clean if i in by_id]


async def find_document_by_title(
    session: AsyncSession, title: str, user_id: int | None = None
) -> Document | None:
    stmt = select(Document).where(Document.title == title[:200]).limit(1)
    if user_id is not None:
        stmt = stmt.where(Document.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_document(
    session: AsyncSession, document_id: int, user_id: int | None = None
) -> Document | None:
    stmt = select(Document).where(Document.id == document_id)
    if user_id is not None:
        stmt = stmt.where(Document.user_id == user_id)
    result = await session.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        return None
    await session.delete(document)
    await session.flush()
    from app.rag.vector_index import mark_vector_index_dirty

    # Prefer the document's owner when present so private indexes are invalidated.
    mark_vector_index_dirty(user_id=getattr(document, "user_id", None) if user_id is None else user_id)
    try:
        from app.rag.answer_cache import invalidate as invalidate_answer_cache

        invalidate_answer_cache()
    except Exception:  # noqa: BLE001
        pass
    return document
