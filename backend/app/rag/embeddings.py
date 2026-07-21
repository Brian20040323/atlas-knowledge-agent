"""Optional embedding backends for P3 vector retrieval (default path uses none)."""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

from app.rag.hybrid import tokenize


class EmbeddingBackend(Protocol):
    name: str
    dim: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        return vec
    return [v / norm for v in vec]


class HashEmbedding:
    """
    Deterministic local hash embedding (feature hashing).

    Zero model download / no GPU — suitable as default when RAG_VECTOR_ENABLED=true
    without pulling sentence-transformers. Not as strong as neural embeddings, but
    enables a real local vector index path that can be switched off.
    """

    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        self.dim = max(32, int(dim))

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text or "")
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if (digest[4] % 2 == 0) else -1.0
            # mild TF: longer / rarer tokens get same unit weight (hashing trick)
            vec[idx] += sign
        return _l2_normalize(vec)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class OpenAIEmbedding:
    """OpenAI-compatible remote embeddings (uses LLM_BASE_URL / LLM_API_KEY)."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dim: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model or "text-embedding-3-small"
        self.dim = max(32, int(dim))
        self.timeout = max(1.0, float(timeout))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise RuntimeError("OpenAI embedding requires LLM_API_KEY")
        import httpx

        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": texts}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        items = sorted(data.get("data") or [], key=lambda x: int(x.get("index", 0)))
        vectors: list[list[float]] = []
        for item in items:
            emb = item.get("embedding") or []
            vectors.append(_l2_normalize([float(x) for x in emb]))
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding count mismatch: got {len(vectors)} want {len(texts)}"
            )
        if vectors:
            self.dim = len(vectors[0])
        return vectors


def get_embedding_backend(
    provider: str,
    *,
    dim: int = 256,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    timeout: float = 30.0,
) -> EmbeddingBackend:
    name = (provider or "hash").strip().lower()
    if name in {"openai", "remote", "api"}:
        return OpenAIEmbedding(
            api_key=api_key,
            base_url=base_url,
            model=model or "text-embedding-3-small",
            dim=dim,
            timeout=timeout,
        )
    # hash is the zero-dep default when vector mode is on
    return HashEmbedding(dim=dim)
