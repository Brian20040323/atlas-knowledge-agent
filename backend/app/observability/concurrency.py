"""Process-wide chat concurrency gate — reject under load instead of melting down."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

_sem: asyncio.Semaphore | None = None
_sem_limit: int | None = None
_active = 0
_rejected = 0


def _get_sem(limit: int) -> asyncio.Semaphore:
    global _sem, _sem_limit
    limit = max(1, int(limit))
    if _sem is None or _sem_limit != limit:
        _sem = asyncio.Semaphore(limit)
        _sem_limit = limit
    return _sem


def concurrency_stats() -> dict[str, int]:
    return {
        "active": _active,
        "limit": int(_sem_limit or 0),
        "rejected": _rejected,
    }


async def acquire_chat_slot(limit: int) -> bool:
    """
    Non-blocking acquire. Returns True if a slot was taken (caller must release).
    Returns False when at capacity (increments rejected counter).
    """
    global _active, _rejected
    sem = _get_sem(limit)
    # locked() == True means value is 0; avoid wait_for(timeout=0) (unreliable on Windows)
    if sem.locked():
        _rejected += 1
        return False
    await sem.acquire()
    _active += 1
    return True


def release_chat_slot() -> None:
    global _active
    if _sem is None:
        return
    _active = max(0, _active - 1)
    _sem.release()


@asynccontextmanager
async def try_acquire_chat_slot(limit: int) -> AsyncIterator[bool]:
    """Context-manager form: hold slot for the whole `async with` block."""
    ok = await acquire_chat_slot(limit)
    if not ok:
        yield False
        return
    try:
        yield True
    finally:
        release_chat_slot()
