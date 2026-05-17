"""Embedding service for hybrid retrieval.

Pluggable via the ``Embedder`` protocol. Default backend is a local
sentence-transformers model (MiniLM, 384 dim, CPU). Override the model via
the ``KDG_EMBED_MODEL`` env var.

Failures (missing dependency, model download error, etc.) are logged once
and the embedder reports ``available=False`` so retrieval falls back to
keyword search rather than raising.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


def build_embedding_text(
    title: str,
    aliases: list[str],
    tags: list[str],
    content: str,
    content_chars: int = 2000,
) -> str:
    """Canonical text representation used to embed an entry."""
    parts = [title.strip()]
    if aliases:
        parts.append(" | ".join(a.strip() for a in aliases if a.strip()))
    if tags:
        parts.append("tags: " + ", ".join(t.strip() for t in tags if t.strip()))
    body = (content or "").strip()
    if body:
        parts.append("")
        parts.append(body[:content_chars])
    return "\n".join(parts)


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class Embedder(Protocol):
    dim: int
    available: bool

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class _NullEmbedder:
    """Stand-in used when sentence-transformers is not installed."""

    dim = 0
    available = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class SentenceTransformerEmbedder:
    """Local CPU embedder using sentence-transformers."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or os.environ.get(
            "KDG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self._model = None
        self._dim: Optional[int] = None
        self.available = True  # set to False on first failed load

    def _load(self) -> None:
        if self._model is not None or not self.available:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; hybrid retrieval disabled. "
                "Install with: pip install 'know-do-graph[embeddings]'"
            )
            self.available = False
            return
        try:
            self._model = SentenceTransformer(self.model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
        except Exception as exc:
            logger.warning("Failed to load embedding model %s: %s", self.model_name, exc)
            self.available = False

    @property
    def dim(self) -> int:
        self._load()
        return self._dim or 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        if not self.available or self._model is None:
            return [[] for _ in texts]
        vecs = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vecs]


_default: Optional[Embedder] = None


def get_default_embedder() -> Embedder:
    """Process-wide singleton embedder."""
    global _default
    if _default is None:
        candidate = SentenceTransformerEmbedder()
        # Trigger load eagerly so we know whether it works; downgrade to null if not.
        _ = candidate.dim
        _default = candidate if candidate.available else _NullEmbedder()
    return _default
