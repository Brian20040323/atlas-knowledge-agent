"""
Simple document chunking for better retrieval — inspired by common RAG pipelines
(LangChain RecursiveCharacterTextSplitter ideas), implemented without LangChain.
"""

from __future__ import annotations

import re


def chunk_text(text: str, chunk_size: int = 280, overlap: int = 40) -> list[str]:
    """Split text into overlapping chunks, preferring sentence boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    # Split on Chinese/English sentence ends first
    parts = re.split(r"(?<=[。！？；!?;])\s*", text)
    parts = [p for p in parts if p and p.strip()]
    if len(parts) <= 1:
        parts = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size - overlap)]
        return [p.strip() for p in parts if p.strip()]

    chunks: list[str] = []
    buf = ""
    for part in parts:
        if len(buf) + len(part) <= chunk_size:
            buf += part
            continue
        if buf:
            chunks.append(buf.strip())
        if len(part) > chunk_size:
            for i in range(0, len(part), chunk_size - overlap):
                piece = part[i : i + chunk_size].strip()
                if piece:
                    chunks.append(piece)
            buf = ""
        else:
            # overlap: keep tail of previous
            tail = chunks[-1][-overlap:] if chunks and overlap else ""
            buf = (tail + part) if tail else part
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or [text]
