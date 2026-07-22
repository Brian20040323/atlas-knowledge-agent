"""DB-backed session tokens (httponly cookie)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, User

SESSION_COOKIE = "atlas_session"
SESSION_DAYS = 14


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session_token(db: AsyncSession, user_id: int) -> str:
    token = new_token()
    row = AuthSession(
        token=token,
        user_id=user_id,
        expires_at=_utcnow() + timedelta(days=SESSION_DAYS),
    )
    db.add(row)
    await db.flush()
    return token


async def resolve_session(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    result = await db.execute(
        select(AuthSession).where(AuthSession.token == token).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < _utcnow():
        await db.execute(delete(AuthSession).where(AuthSession.id == row.id))
        await db.flush()
        return None
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


async def delete_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    await db.execute(delete(AuthSession).where(AuthSession.token == token))
    await db.flush()
