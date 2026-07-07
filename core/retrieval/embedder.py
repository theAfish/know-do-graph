"""Embedding service for hybrid retrieval.

Pluggable via the ``Embedder`` protocol. Embeddings are disabled by default
to keep the base install lightweight. Set ``KDG_EMBED_PROVIDER`` to ``local``
or ``openai`` to opt in.

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
    """Stand-in used when vector embeddings are disabled or unavailable."""

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
                "Install with: pip install 'know-do-graph[local-embeddings]'"
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


class OpenAIEmbedder:
    """OpenAI-compatible embeddings API backend."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        dimensions: Optional[int] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.model_name = model_name or os.environ.get("KDG_EMBED_MODEL", "text-embedding-3-small")
        self.dimensions = dimensions or _optional_int(os.environ.get("KDG_EMBED_DIM")) or 384
        self.api_key = (
            api_key or os.environ.get("KDG_EMBED_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )
        self.base_url = (
            base_url or os.environ.get("KDG_EMBED_BASE_URL") or os.environ.get("OPENAI_API_BASE")
        )
        self._client = None
        self.available = True

    def _load(self) -> None:
        if self._client is not None or not self.available:
            return
        if not self.api_key:
            logger.warning(
                "KDG_EMBED_PROVIDER=openai but no API key is configured; "
                "set KDG_EMBED_API_KEY or OPENAI_API_KEY."
            )
            self.available = False
            return
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package not installed; API embeddings disabled.")
            self.available = False
            return
        try:
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        except Exception as exc:
            logger.warning("Failed to initialize embeddings API client: %s", exc)
            self.available = False

    @property
    def dim(self) -> int:
        self._load()
        return self.dimensions if self.available else 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        if not self.available or self._client is None:
            return [[] for _ in texts]
        try:
            response = self._client.embeddings.create(
                model=self.model_name,
                input=texts,
                dimensions=self.dimensions,
            )
            data = sorted(response.data, key=lambda item: item.index)
            return [list(item.embedding) for item in data]
        except TypeError:
            # Some OpenAI-compatible providers do not accept the dimensions argument.
            try:
                response = self._client.embeddings.create(
                    model=self.model_name,
                    input=texts,
                )
                data = sorted(response.data, key=lambda item: item.index)
                return [list(item.embedding) for item in data]
            except Exception as exc:
                logger.warning("Embedding API request failed: %s", exc)
                self.available = False
                return [[] for _ in texts]
        except Exception as exc:
            logger.warning("Embedding API request failed: %s", exc)
            self.available = False
            return [[] for _ in texts]


def _optional_int(value: Optional[str]) -> Optional[int]:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid KDG_EMBED_DIM=%r; using the default.", value)
        return None


def _provider_name() -> str:
    return os.environ.get("KDG_EMBED_PROVIDER", "none").strip().lower()


_default: Optional[Embedder] = None


def get_default_embedder() -> Embedder:
    """Process-wide singleton embedder."""
    global _default
    if _default is None:
        provider = _provider_name()
        if provider in {"", "0", "false", "no", "none", "off", "disabled"}:
            _default = _NullEmbedder()
            return _default
        if provider in {"local", "sentence-transformers", "sentence_transformers"}:
            candidate: Embedder = SentenceTransformerEmbedder()
        elif provider in {"openai", "api", "remote"}:
            candidate = OpenAIEmbedder()
        else:
            logger.warning("Unknown KDG_EMBED_PROVIDER=%r; hybrid retrieval disabled.", provider)
            _default = _NullEmbedder()
            return _default
        # Trigger load eagerly so we know whether it works; downgrade to null if not.
        _ = candidate.dim
        _default = candidate if candidate.available else _NullEmbedder()
    return _default
