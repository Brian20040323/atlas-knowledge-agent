"""Unit tests for scoped local vector index isolation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.rag import vector_index as vi  # noqa: E402


def _doc(doc_id: int, title: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(id=doc_id, title=title, content=content, source_type="text")


def _settings(index_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        rag_embedding_provider="hash",
        rag_embedding_dim=64,
        llm_api_key="",
        llm_base_url="",
        rag_embedding_model="",
        llm_timeout_seconds=10.0,
        rag_vector_index_dir=str(index_root),
    )


class VectorIndexScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reset process-global dirty/lock registries between tests.
        with vi._REGISTRY_LOCK:
            vi._DIRTY.clear()
            vi._LOCKS.clear()

    def test_scope_key_and_directory_partition(self) -> None:
        self.assertEqual(vi.index_scope_key(None), "shared")
        self.assertEqual(vi.index_scope_key(7), "user-7")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = vi.default_index_dir(str(root), scope="shared")
            user = vi.default_index_dir(str(root), scope="user-3")
            self.assertEqual(shared, root / "shared")
            self.assertEqual(user, root / "user-3")
            self.assertNotEqual(shared, user)

    def test_two_users_do_not_overwrite_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            docs_a = [_doc(1, "Alpha Secret", "user A private travel policy alpha-token")]
            docs_b = [_doc(2, "Beta Secret", "user B private salary policy beta-token")]

            idx_a = vi.build_index_from_settings(settings, user_id=1)
            idx_b = vi.build_index_from_settings(settings, user_id=2)
            idx_a.ensure(docs_a, chunk_size=80, overlap=10, max_chunks=4)
            idx_b.ensure(docs_b, chunk_size=80, overlap=10, max_chunks=4)

            self.assertTrue((root / "user-1" / "meta.json").exists())
            self.assertTrue((root / "user-2" / "meta.json").exists())
            self.assertNotEqual(idx_a.index_dir, idx_b.index_dir)

            # Reload into fresh instances — disk partitions must stay separate.
            reload_a = vi.build_index_from_settings(settings, user_id=1)
            reload_b = vi.build_index_from_settings(settings, user_id=2)
            self.assertTrue(reload_a.load())
            self.assertTrue(reload_b.load())
            ids_a = {c.doc_id for c in reload_a.chunks}
            ids_b = {c.doc_id for c in reload_b.chunks}
            self.assertEqual(ids_a, {1})
            self.assertEqual(ids_b, {2})

    def test_dirty_scopes_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            docs = [_doc(10, "Shared Doc", "common knowledge about Atlas")]

            idx_u1 = vi.build_index_from_settings(settings, user_id=1)
            idx_u2 = vi.build_index_from_settings(settings, user_id=2)
            idx_u1.ensure(docs, chunk_size=80, overlap=10, max_chunks=4)
            idx_u2.ensure(docs, chunk_size=80, overlap=10, max_chunks=4)
            self.assertFalse(vi._is_dirty("user-1"))
            self.assertFalse(vi._is_dirty("user-2"))

            # Dirty user-1 (+ shared for auth-toggle safety) must not dirty user-2.
            vi.mark_vector_index_dirty(user_id=1)
            self.assertTrue(vi._is_dirty("user-1"))
            self.assertTrue(vi._is_dirty("shared"))
            self.assertFalse(vi._is_dirty("user-2"))

    def test_fingerprint_mismatch_forces_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            docs_v1 = [_doc(1, "Doc", "version one content")]
            docs_v2 = [_doc(1, "Doc", "version two content changed substantially")]

            idx = vi.build_index_from_settings(settings, user_id=None)
            idx.ensure(docs_v1, chunk_size=80, overlap=10, max_chunks=4)
            fp1 = idx.fingerprint
            self.assertTrue(fp1)

            # Clear dirty so ensure relies on fingerprint mismatch, not dirty flag.
            vi._set_dirty("shared", False)
            idx.chunks = []
            idx.fingerprint = ""
            idx.ensure(docs_v2, chunk_size=80, overlap=10, max_chunks=4)
            self.assertNotEqual(fp1, idx.fingerprint)
            self.assertTrue(any("version two" in c.text for c in idx.chunks))


if __name__ == "__main__":
    unittest.main()
