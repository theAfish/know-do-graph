"""Mem-Graph: lightweight, mutable session memory traces.

Mem-Graph entries are shallow, episodic notes captured during agent
interactions.  Over time, stable patterns may be promoted into full
Know-Do Graph entries.

Memory traces are ordinary Know-Do Graph entries with ``entry_type="memory"``.
Session-specific fields live in ``EntryMetadata.custom["memory"]`` and links
between traces are persisted in the shared edges table.

Connecting external agent frameworks
--------------------------------------
Any agent framework can write to MemGraph as long as it can produce one
of the following shapes.  Use the matching ``ingest_*`` helper, or call
``add()`` directly with a plain string.

**1. Plain text / single observation**

    mg = MemGraph("my-session")
    mg.add("user asked about MACE relaxation; answered with [[ASE Relaxation]]",
           tags=["qa"], success=True)

**2. OpenAI-style chat messages** – a list of ``{"role": ..., "content": ...}`` dicts.
   Roles are concatenated into a readable transcript.

    mg.ingest_openai_messages(openai_response["messages"], tags=["openai"])

**3. LangChain / generic message objects** – any object with ``.content`` and
   optionally ``.type`` attributes (HumanMessage, AIMessage, SystemMessage …).

    mg.ingest_langchain_messages(chain.memory.chat_memory.messages)

**4. AutoGen / multi-agent conversation list** – list of dicts with at minimum
   ``"name"`` (or ``"role"``) and ``"content"`` keys.

    mg.ingest_autogen_messages(groupchat.messages)

**5. Raw JSON file** – a path to a file containing one of the above schemas:
   - a JSON array  → treated as a message list (OpenAI / AutoGen format)
   - a JSON object → its ``messages`` or ``history`` key is extracted; otherwise
     the whole object is serialised as a single trace

    mg.ingest_file(Path("session_dump.json"))

**6. Raw text file** – split into chunks or stored as one entry.

    mg.ingest_text_file(Path("agent_log.txt"), chunk_by="paragraph")

The resulting MemEntry objects are identical regardless of source and can all
be listed, queried, and promoted into full Know-Do Graph entries.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus
from core.storage.database import SessionLocal
from core.storage.repository import EdgeRepository, EntryRepository

def _default_memory_dir() -> Path:
    configured = os.environ.get("KDG_MEMORY_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "data" / "memory").resolve()


class MemSourceFormat(str, Enum):
    """Describes where / how a MemEntry was ingested."""
    manual = "manual"
    openai_messages = "openai_messages"
    langchain_messages = "langchain_messages"
    autogen_messages = "autogen_messages"
    raw_text = "raw_text"
    json_file = "json_file"
    text_file = "text_file"
    api = "api"


class MemEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = "default"
    content: str
    tags: list[str] = Field(default_factory=list)
    source_entry_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    success: Optional[bool] = None
    promoted: bool = False
    promotion_target_id: Optional[str] = None
    source_format: MemSourceFormat = MemSourceFormat.manual
    raw_source: Optional[dict] = None


class MemGraph:
    """Session-scoped view of memory nodes in the shared graph database.

    Parameters
    ----------
    session_id:
        Logical name used to group memory nodes.
    storage_dir:
        Deprecated JSON directory. Existing ``<session_id>.json`` files are
        imported once when the database has no memory nodes for the session.
    """

    def __init__(
        self,
        session_id: str = "default",
        *,
        storage_dir: str | Path | None = None,
        session_factory: Callable[[], Session] | None = None,
        graph: Any = None,
    ) -> None:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("session_id must be a non-empty filename-safe name")
        self.session_id = session_id
        self.storage_dir = (
            Path(storage_dir).expanduser().resolve()
            if storage_dir is not None
            else _default_memory_dir()
        )
        self._session_factory = session_factory or SessionLocal
        if graph is None and session_factory is None:
            try:
                from core.app_state import graph as app_graph
                graph = app_graph
            except Exception:
                graph = None
        self._graph = graph
        self._entries: dict[str, MemEntry] = {}
        self._ensure_database()
        self._load()

    @property
    def _path(self) -> Path:
        return self.storage_dir / f"{self.session_id}.json"

    def _ensure_database(self) -> None:
        from core.storage.models import Base

        with self._session_factory() as db:
            Base.metadata.create_all(bind=db.get_bind())

    def _load(self) -> None:
        with self._session_factory() as db:
            entries = [
                entry
                for entry in EntryRepository(db).get_all()
                if entry.entry_type == EntryType.memory
                and _memory_data(entry).get("session_id") == self.session_id
            ]
        self._entries = {entry.id: _entry_to_mem(entry) for entry in entries}

        # Backward-compatible one-time import. JSON remains untouched as a
        # backup, but is no longer read after the session exists in SQLite.
        if not self._entries and self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = {k: MemEntry(**v) for k, v in raw.items()}
            self._save()

    def _save(self) -> None:
        with self._session_factory() as db:
            repo = EntryRepository(db)
            existing = {entry.id for entry in repo.get_all()}
            for mem_entry in self._entries.values():
                entry = _mem_to_entry(mem_entry)
                saved = repo.update(entry) if entry.id in existing else repo.create(entry)
                if saved is not None and self._graph is not None:
                    self._graph.add_entry(saved)

    def _make_entry(
        self,
        content: str,
        tags: Optional[list[str]] = None,
        source_entry_ids: Optional[list[str]] = None,
        success: Optional[bool] = None,
        source_format: MemSourceFormat = MemSourceFormat.manual,
        raw_source: Optional[dict] = None,
    ) -> MemEntry:
        entry = MemEntry(
            session_id=self.session_id,
            content=content,
            tags=tags or [],
            source_entry_ids=source_entry_ids or [],
            success=success,
            source_format=source_format,
            raw_source=raw_source,
        )
        self._entries[entry.id] = entry
        return entry

    # ------------------------------------------------------------------
    # Core write API
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        tags: Optional[list[str]] = None,
        source_entry_ids: Optional[list[str]] = None,
        success: Optional[bool] = None,
    ) -> MemEntry:
        """Record a single free-text observation or note."""
        entry = self._make_entry(
            content=content,
            tags=tags,
            source_entry_ids=source_entry_ids,
            success=success,
            source_format=MemSourceFormat.manual,
        )
        self._save()
        return entry

    # ------------------------------------------------------------------
    # Framework ingestion helpers
    # ------------------------------------------------------------------

    def ingest_openai_messages(
        self,
        messages: list[dict[str, Any]],
        tags: Optional[list[str]] = None,
        as_single_trace: bool = True,
    ) -> list[MemEntry]:
        """Ingest an OpenAI-style messages list.

        Parameters
        ----------
        messages:
            ``[{"role": "user"|"assistant"|"system", "content": "..."}]``
        as_single_trace:
            If True (default) the whole conversation is stored as one
            MemEntry transcript.  If False, each message becomes its own entry.
        """
        tags = (tags or []) + ["openai"]
        created: list[MemEntry] = []

        if as_single_trace:
            lines = [
                f"[{m.get('role', 'unknown')}] {_extract_content(m)}"
                for m in messages
                if _extract_content(m)
            ]
            entry = self._make_entry(
                content="\n".join(lines),
                tags=tags,
                source_format=MemSourceFormat.openai_messages,
                raw_source={"messages": messages},
            )
            created.append(entry)
        else:
            for m in messages:
                content = _extract_content(m)
                if not content:
                    continue
                role_tag = m.get("role", "unknown")
                entry = self._make_entry(
                    content=content,
                    tags=tags + [role_tag],
                    source_format=MemSourceFormat.openai_messages,
                    raw_source=m,
                )
                created.append(entry)

        self._save()
        return created

    def ingest_langchain_messages(
        self,
        messages: list[Any],
        tags: Optional[list[str]] = None,
        as_single_trace: bool = True,
    ) -> list[MemEntry]:
        """Ingest LangChain message objects (HumanMessage, AIMessage, etc.).

        Accepts any object that has a ``.content`` attribute and optionally
        a ``.type`` attribute (e.g. ``"human"``, ``"ai"``, ``"system"``).
        Plain dicts with ``"content"`` keys are also accepted.
        """
        tags = (tags or []) + ["langchain"]
        dicts = [_langchain_to_dict(m) for m in messages]
        created: list[MemEntry] = []

        if as_single_trace:
            lines = [
                f"[{d['role']}] {d['content']}" for d in dicts if d["content"]
            ]
            entry = self._make_entry(
                content="\n".join(lines),
                tags=tags,
                source_format=MemSourceFormat.langchain_messages,
                raw_source={"messages": dicts},
            )
            created.append(entry)
        else:
            for d in dicts:
                if not d["content"]:
                    continue
                entry = self._make_entry(
                    content=d["content"],
                    tags=tags + [d["role"]],
                    source_format=MemSourceFormat.langchain_messages,
                    raw_source=d,
                )
                created.append(entry)

        self._save()
        return created

    def ingest_autogen_messages(
        self,
        messages: list[dict[str, Any]],
        tags: Optional[list[str]] = None,
        as_single_trace: bool = True,
    ) -> list[MemEntry]:
        """Ingest AutoGen / multi-agent conversation records.

        Expects dicts with at minimum a ``"content"`` key and optionally
        ``"name"`` or ``"role"`` identifying the speaker.
        """
        tags = (tags or []) + ["autogen"]
        created: list[MemEntry] = []

        if as_single_trace:
            lines = []
            for m in messages:
                speaker = m.get("name") or m.get("role", "agent")
                content = _extract_content(m)
                if content:
                    lines.append(f"[{speaker}] {content}")
            entry = self._make_entry(
                content="\n".join(lines),
                tags=tags,
                source_format=MemSourceFormat.autogen_messages,
                raw_source={"messages": messages},
            )
            created.append(entry)
        else:
            for m in messages:
                content = _extract_content(m)
                if not content:
                    continue
                speaker = m.get("name") or m.get("role", "agent")
                entry = self._make_entry(
                    content=content,
                    tags=tags + [speaker],
                    source_format=MemSourceFormat.autogen_messages,
                    raw_source=m,
                )
                created.append(entry)

        self._save()
        return created

    def ingest_file(
        self,
        path: Path,
        tags: Optional[list[str]] = None,
        as_single_trace: bool = True,
    ) -> list[MemEntry]:
        """Ingest a JSON session dump.

        Accepted shapes
        ---------------
        - JSON array of message dicts → treated as OpenAI/AutoGen format
        - JSON object with ``"messages"`` or ``"history"`` key → that list is extracted
        - Any other JSON object → serialised as a single trace
        """
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        file_tags = (tags or []) + [f"file:{path.name}"]

        if isinstance(raw, list):
            return self.ingest_openai_messages(raw, tags=file_tags, as_single_trace=as_single_trace)

        if isinstance(raw, dict):
            for key in ("messages", "history", "conversation", "turns"):
                if key in raw and isinstance(raw[key], list):
                    return self.ingest_openai_messages(
                        raw[key], tags=file_tags, as_single_trace=as_single_trace
                    )
            # Fallback: serialise entire object as one trace
            entry = self._make_entry(
                content=json.dumps(raw, indent=2, default=str),
                tags=file_tags,
                source_format=MemSourceFormat.json_file,
                raw_source={"file": str(path), "data": raw},
            )
            self._save()
            return [entry]

        # Unexpected shape — store as raw text
        entry = self._make_entry(
            content=str(raw),
            tags=file_tags,
            source_format=MemSourceFormat.json_file,
        )
        self._save()
        return [entry]

    def ingest_text_file(
        self,
        path: Path,
        tags: Optional[list[str]] = None,
        chunk_by: str = "none",
    ) -> list[MemEntry]:
        """Ingest a plain-text file.

        Parameters
        ----------
        chunk_by:
            ``"none"`` — store as one entry (default).
            ``"line"`` — one entry per non-empty line.
            ``"paragraph"`` — split on blank lines; one entry per paragraph.
        """
        path = Path(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        file_tags = (tags or []) + [f"file:{path.name}"]
        created: list[MemEntry] = []

        chunks: list[str] = []
        if chunk_by == "line":
            chunks = [ln.strip() for ln in text.splitlines() if ln.strip()]
        elif chunk_by == "paragraph":
            chunks = [
                p.strip()
                for p in text.split("\n\n")
                if p.strip()
            ]
        else:
            chunks = [text]

        for chunk in chunks:
            entry = self._make_entry(
                content=chunk,
                tags=file_tags,
                source_format=MemSourceFormat.text_file,
                raw_source={"file": str(path)},
            )
            created.append(entry)

        self._save()
        return created

    # ------------------------------------------------------------------
    # Read / management API
    # ------------------------------------------------------------------

    def list(self) -> list[MemEntry]:
        return list(self._entries.values())

    def get(self, mem_id: str) -> Optional[MemEntry]:
        return self._entries.get(mem_id)

    def mark_promoted(self, mem_id: str, target_id: str) -> None:
        if mem_id in self._entries:
            self._entries[mem_id].promoted = True
            self._entries[mem_id].promotion_target_id = target_id
            self._save()

    def delete(self, mem_id: str) -> bool:
        if mem_id not in self._entries:
            return False
        with self._session_factory() as db:
            edge_repo = EdgeRepository(db)
            for edge in edge_repo.get_all():
                if edge.source_id == mem_id or edge.target_id == mem_id:
                    edge_repo.delete(edge.id)
                    if self._graph is not None:
                        self._graph.remove_edge(edge.source_id, edge.target_id)
            deleted = EntryRepository(db).delete(mem_id)
        if not deleted:
            return False
        del self._entries[mem_id]
        if self._graph is not None:
            self._graph.remove_entry(mem_id)
        return True

    @staticmethod
    def list_sessions(
        storage_dir: str | Path | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> list[str]:
        factory = session_factory or SessionLocal
        with factory() as db:
            from core.storage.models import Base
            Base.metadata.create_all(bind=db.get_bind())
            sessions = {
                _memory_data(entry).get("session_id")
                for entry in EntryRepository(db).get_all()
                if entry.entry_type == EntryType.memory
            }
        sessions.discard(None)

        # Include legacy sessions so callers can discover and trigger import.
        directory = Path(storage_dir).expanduser().resolve() if storage_dir else _default_memory_dir()
        if directory.exists():
            sessions.update(p.stem for p in directory.glob("*.json"))
        return sorted(str(session) for session in sessions)

    def connect(
        self,
        source_id: str,
        target_id: str,
        *,
        relation: EdgeRelation | str = EdgeRelation.related_memory,
        weight: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Edge:
        """Create a typed edge between two memory nodes."""
        with self._session_factory() as db:
            entries = {entry.id: entry for entry in EntryRepository(db).get_all()}
            source = entries.get(source_id)
            target = entries.get(target_id)
            if (
                source is None
                or target is None
                or source.entry_type != EntryType.memory
                or target.entry_type != EntryType.memory
            ):
                raise KeyError("Both edge endpoints must be memory nodes")
            edge = Edge(
                source_id=source_id,
                target_id=target_id,
                relation=EdgeRelation(relation),
                weight=weight,
                metadata=metadata or {},
            )
            saved = EdgeRepository(db).create(edge)
        if self._graph is not None:
            self._graph.add_edge(saved)
        return saved

    def edges(self, mem_id: str | None = None) -> list[Edge]:
        """List memory-to-memory edges incident to this session's nodes."""
        session_ids = set(self._entries)
        with self._session_factory() as db:
            memory_ids = {
                entry.id
                for entry in EntryRepository(db).get_all()
                if entry.entry_type == EntryType.memory
            }
            edges = [
                edge
                for edge in EdgeRepository(db).get_all()
                if edge.source_id in memory_ids
                and edge.target_id in memory_ids
                and (edge.source_id in session_ids or edge.target_id in session_ids)
            ]
        if mem_id is not None:
            edges = [
                edge for edge in edges
                if edge.source_id == mem_id or edge.target_id == mem_id
            ]
        return edges


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _extract_content(m: Any) -> str:
    """Pull text content out of a message dict or object."""
    if isinstance(m, dict):
        content = m.get("content", "")
        if isinstance(content, list):
            # OpenAI vision-style: content is a list of parts
            parts = [
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            ]
            return " ".join(p for p in parts if p).strip()
        return str(content).strip()
    if hasattr(m, "content"):
        return str(m.content).strip()
    return str(m).strip()


def _langchain_to_dict(m: Any) -> dict[str, str]:
    """Normalise a LangChain message object to a plain dict."""
    if isinstance(m, dict):
        return {
            "role": m.get("type", m.get("role", "unknown")),
            "content": str(m.get("content", "")),
        }
    role = getattr(m, "type", None) or getattr(m, "role", "unknown")
    content = getattr(m, "content", str(m))
    return {"role": str(role), "content": str(content)}


def _memory_data(entry: Entry) -> dict[str, Any]:
    data = entry.metadata.custom.get("memory", {})
    return data if isinstance(data, dict) else {}


def _entry_to_mem(entry: Entry) -> MemEntry:
    data = _memory_data(entry)
    return MemEntry(
        id=entry.id,
        session_id=data.get("session_id", "default"),
        content=entry.content,
        tags=list(entry.tags),
        source_entry_ids=list(data.get("source_entry_ids", [])),
        created_at=entry.metadata.timestamp,
        success=data.get("success"),
        promoted=bool(data.get("promoted", False)),
        promotion_target_id=data.get("promotion_target_id"),
        source_format=data.get("source_format", MemSourceFormat.manual),
        raw_source=data.get("raw_source"),
    )


def _mem_to_entry(mem: MemEntry) -> Entry:
    first_line = next((line.strip("# ").strip() for line in mem.content.splitlines() if line.strip()), "")
    title = first_line[:80] or f"Memory {mem.id[:8]}"
    return Entry(
        id=mem.id,
        title=title,
        entry_type=EntryType.memory,
        content=mem.content,
        tags=list(mem.tags),
        metadata=EntryMetadata(
            timestamp=mem.created_at,
            source_provenance=f"memory:{mem.session_id}",
            extraction_method=mem.source_format.value,
            refinement_status=RefinementStatus.raw,
            custom={
                "memory": {
                    "session_id": mem.session_id,
                    "source_entry_ids": list(mem.source_entry_ids),
                    "success": mem.success,
                    "promoted": mem.promoted,
                    "promotion_target_id": mem.promotion_target_id,
                    "source_format": mem.source_format.value,
                    "raw_source": mem.raw_source,
                }
            },
        ),
    )
