"""FastAPI dependencies for current user."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import SESSION_COOKIE, resolve_session
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    if not settings.atlas_user_auth:
        return None
    token = request.cookies.get(SESSION_COOKIE) or ""
    return await resolve_session(db, token)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    """Return user when auth enabled; None when user-auth is off (legacy single-tenant)."""
    if not settings.atlas_user_auth:
        return None
    token = request.cookies.get(SESSION_COOKIE) or ""
    user = await resolve_session(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


async def require_user(user: Optional[User] = Depends(get_current_user)) -> Optional[User]:
    return user
