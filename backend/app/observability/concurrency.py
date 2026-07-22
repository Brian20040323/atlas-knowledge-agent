"""Fair chat concurrency: global cap + per-user cap so one client cannot starve others."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

_sem: asyncio.Semaphore | None = None
_sem_limit: int | None = None
_active = 0
_rejected = 0
_queued = 0
_user_active: dict[str, int] = {}
_slot_owners: list[str | None] = []
_lock = asyncio.Lock()


def _get_sem(limit: int) -> asyncio.Semaphore:
    global _sem, _sem_limit
    limit = max(1, int(limit))
    if _sem is None or _sem_limit != limit:
        _sem = asyncio.Semaphore(limit)
        _sem_limit = limit
    return _sem


def concurrency_stats() -> dict[str, Any]:
    return {
        "active": _active,
        "limit": int(_sem_limit or 0),
        "rejected": _rejected,
        "queued": _queued,
        "per_user": dict(_user_active),
    }


async def acquire_chat_slot(
    limit: int,
    wait_seconds: float = 0.0,
    *,
    user_key: str | None = None,
    per_user_limit: int = 2,
) -> bool:
    """
    Acquire a chat slot (global semaphore + optional per-user cap).
    Returns False when still at capacity after waiting.
    """
    global _active, _rejected, _queued

    key = (user_key or "").strip() or None
    per_cap = max(1, int(per_user_limit or 1))
    wait = max(0.0, float(wait_seconds or 0.0))
    sem = _get_sem(limit)

    async def _user_ok() -> bool:
        if not key:
            return True
        async with _lock:
            return int(_user_active.get(key, 0)) < per_cap

    async def _commit() -> None:
        global _active
        async with _lock:
            _active += 1
            _slot_owners.append(key)
            if key:
                _user_active[key] = int(_user_active.get(key, 0)) + 1

    # Fast path: respect per-user cap before waiting on global queue
    if not await _user_ok():
        _rejected += 1
        return False

    if wait <= 0:
        if sem.locked() or not await _user_ok():
            _rejected += 1
            return False
        await sem.acquire()
        if not await _user_ok():
            sem.release()
            _rejected += 1
            return False
        await _commit()
        return True

    _queued += 1
    try:
        deadline = asyncio.get_event_loop().time() + wait
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                _rejected += 1
                return False
            if not await _user_ok():
                # Someone else on same account holds slots — short poll
                await asyncio.sleep(min(0.35, remaining))
                continue
            try:
                await asyncio.wait_for(sem.acquire(), timeout=min(remaining, 1.5))
            except asyncio.TimeoutError:
                continue
            if not await _user_ok():
                sem.release()
                await asyncio.sleep(0.15)
                continue
            await _commit()
            return True
    finally:
        _queued = max(0, _queued - 1)


def release_chat_slot() -> None:
    global _active
    if _sem is None:
        return
    key: str | None = None
    # Best-effort: pop last owner (LIFO matches typical finally nesting)
    if _slot_owners:
        key = _slot_owners.pop()
    _active = max(0, _active - 1)
    if key:
        cur = int(_user_active.get(key, 0)) - 1
        if cur <= 0:
            _user_active.pop(key, None)
        else:
            _user_active[key] = cur
    _sem.release()


@asynccontextmanager
async def try_acquire_chat_slot(
    limit: int,
    *,
    user_key: str | None = None,
    per_user_limit: int = 2,
) -> AsyncIterator[bool]:
    ok = await acquire_chat_slot(
        limit, user_key=user_key, per_user_limit=per_user_limit
    )
    if not ok:
        yield False
        return
    try:
        yield True
    finally:
        release_chat_slot()
