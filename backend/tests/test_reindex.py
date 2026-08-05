"""Unit tests for /knowledge/reindex scoped, non-blocking rebuild contract."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException  # noqa: E402

from app.api.routes import reindex_knowledge  # noqa: E402


class _FakeSettings(SimpleNamespace):
    pass


def _settings(*, vector_enabled: bool = True, auth: bool = False) -> _FakeSettings:
    return _FakeSettings(
        rag_vector_enabled=vector_enabled,
        atlas_user_auth=auth,
        rag_scan_limit=50,
        rag_chunk_size=120,
        rag_chunk_overlap=20,
        rag_max_chunks_per_doc=8,
        rag_embedding_provider="hash",
    )


class ReindexRouteTests(unittest.TestCase):
    def test_vector_disabled_returns_ok_false(self) -> None:
        result = asyncio.run(
            reindex_knowledge(settings=_settings(vector_enabled=False), user=None)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "rag_vector_enabled=false")

    def test_reindex_passes_user_scope_and_uses_to_thread(self) -> None:
        user = SimpleNamespace(id=42)
        settings = _settings(vector_enabled=True, auth=True)
        docs = [SimpleNamespace(id=1, title="t", content="c")]

        fake_index = MagicMock()
        fake_index.ensure = MagicMock()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("app.db.session.get_session_maker", return_value=lambda: session), patch(
            "app.db.crud.list_documents", new=AsyncMock(return_value=docs)
        ) as list_docs, patch(
            "app.rag.vector_index.mark_vector_index_dirty"
        ) as mark_dirty, patch(
            "app.rag.vector_index.build_index_from_settings", return_value=fake_index
        ) as build_index, patch(
            "asyncio.to_thread", new=AsyncMock(return_value=None)
        ) as to_thread:
            result = asyncio.run(reindex_knowledge(settings=settings, user=user))

        self.assertTrue(result["ok"])
        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["scope"], "user-42")
        list_docs.assert_awaited()
        self.assertEqual(list_docs.await_args.kwargs.get("user_id"), 42)
        mark_dirty.assert_called_with(user_id=42)
        build_index.assert_called()
        self.assertEqual(build_index.call_args.kwargs.get("user_id"), 42)
        to_thread.assert_awaited()
        # First positional arg to to_thread should be the sync ensure callable.
        self.assertIs(to_thread.await_args.args[0], fake_index.ensure)

    def test_reindex_failure_returns_503_without_raw_exception(self) -> None:
        settings = _settings(vector_enabled=True, auth=False)
        docs = [SimpleNamespace(id=1, title="t", content="c")]
        fake_index = MagicMock()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("app.db.session.get_session_maker", return_value=lambda: session), patch(
            "app.db.crud.list_documents", new=AsyncMock(return_value=docs)
        ), patch("app.rag.vector_index.mark_vector_index_dirty"), patch(
            "app.rag.vector_index.build_index_from_settings", return_value=fake_index
        ), patch(
            "asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError("disk full secret path")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(reindex_knowledge(settings=settings, user=None))

        self.assertEqual(ctx.exception.status_code, 503)
        detail = str(ctx.exception.detail)
        self.assertNotIn("disk full secret path", detail)
        self.assertIn("unavailable", detail.lower())


if __name__ == "__main__":
    unittest.main()
