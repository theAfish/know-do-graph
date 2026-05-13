"""Mem-Graph: lightweight, mutable session memory traces.

Mem-Graph entries are shallow, episodic notes captured during agent
interactions.  Over time, stable patterns may be promoted into full
Know-Do Graph entries.

Storage is flat JSON files per session, kept under data/memory/.

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
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

_MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"
_MEMORY_DIR.mkdir(parents=True, exist_ok=True)


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
    """Session-scoped memory graph persisted as a JSON file.

    Parameters
    ----------
    session_id:
        Logical name for the session.  Determines the storage filename
        (``data/memory/<session_id>.json``).  Use a stable identifier when
        you want to resume or extend a session across process restarts.
    """

    def __init__(self, session_id: str = "default") -> None:
        self.session_id = session_id
        self._entries: dict[str, MemEntry] = {}
        self._load()

    @property
    def _path(self) -> Path:
        return _MEMORY_DIR / f"{self.session_id}.json"

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = {k: MemEntry(**v) for k, v in raw.items()}

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(
                {k: v.model_dump(mode="json") for k, v in self._entries.items()},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

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
        del self._entries[mem_id]
        self._save()
        return True

    @staticmethod
    def list_sessions() -> list[str]:
        return [p.stem for p in _MEMORY_DIR.glob("*.json")]


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
