from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.utils.slug import slug_from_title


class RemoteSource(BaseModel):
    """Link to an upstream file (e.g. a SKILL.md in another repo) that should be
    mirrored periodically into this node's ``content``.

    The identity of the node (id, slug, title, wikilinks-pointing-at-it) is
    intentionally NOT touched by the sync — only the body is refreshed.
    """

    kind: Literal["github", "http"] = "github"
    # Display URL (e.g. https://github.com/owner/repo or https://github.com/owner/repo/blob/ref/path)
    url: str
    # For kind="github": owner/repo and path-in-repo.
    owner: Optional[str] = None
    repo: Optional[str] = None
    ref: str = "main"  # branch / tag / commit
    path: Optional[str] = None  # e.g. "skills/extractor/SKILL.md"
    # Cache / change-detection
    content_hash: Optional[str] = None  # sha256 of last-fetched body
    etag: Optional[str] = None  # GitHub blob sha or HTTP ETag
    fetched_at: Optional[datetime] = None
    status: Literal["ok", "stale", "error", "never"] = "never"
    last_error: Optional[str] = None
    # Auto-sync controls
    auto_sync: bool = True
    sync_interval_seconds: int = 3600


class EntryType(str, Enum):
    capability = "capability"
    procedure = "procedure"
    # Legacy public types are accepted for compatibility and normalized to one
    # of the four canonical knowledge-node types on Entry construction.
    workflow = "workflow"
    tool = "tool"
    repository = "repository"
    environment = "environment"
    dependency = "dependency"
    data = "data"
    analytical = "analytical"
    # Internal/transient memory traces remain distinct so MemGraph and review
    # policy internals can keep excluding raw session memory.
    memory = "memory"
    # Hierarchical-memory layers (see SkillLevel).
    heuristic = "heuristic"  # L3: operational experience / empirical guidance
    constraint = "constraint"  # L4: known failure modes / limitations
    generic = "generic"


CANONICAL_ENTRY_TYPES = (
    EntryType.capability,
    EntryType.procedure,
    EntryType.heuristic,
    EntryType.constraint,
)

PUBLIC_ENTRY_TYPE_VALUES = tuple(entry_type.value for entry_type in CANONICAL_ENTRY_TYPES)

LEGACY_ENTRY_TYPE_TO_CANONICAL: dict[str, EntryType] = {
    "capability": EntryType.capability,
    "procedure": EntryType.procedure,
    "heuristic": EntryType.heuristic,
    "constraint": EntryType.constraint,
    "workflow": EntryType.capability,
    "tool": EntryType.procedure,
    "repository": EntryType.procedure,
    "data": EntryType.procedure,
    "environment": EntryType.constraint,
    "dependency": EntryType.constraint,
    "analytical": EntryType.heuristic,
    "generic": EntryType.capability,
}


def canonical_entry_type(entry_type: "EntryType | str | None") -> EntryType:
    """Return the canonical public type for a requested entry type."""
    value = entry_type.value if isinstance(entry_type, EntryType) else (entry_type or "capability")
    if value == EntryType.memory.value:
        return EntryType.memory
    return LEGACY_ENTRY_TYPE_TO_CANONICAL.get(str(value), EntryType.capability)


def legacy_entry_subtype(entry_type: "EntryType | str | None") -> str | None:
    """Return the pre-normalization subtype when it carries extra detail."""
    value = entry_type.value if isinstance(entry_type, EntryType) else (entry_type or "")
    canonical = canonical_entry_type(value)
    if value and value != canonical.value and value != EntryType.memory.value:
        return str(value)
    return None


class SkillLevel(str, Enum):
    """Progressive-disclosure layer of a node in the hierarchical memory.

    L1 — Capability    : reusable high-level ability (planner-friendly)
    L2 — Procedure     : executable workflow / task decomposition
    L3 — Heuristic     : empirical guidance, conditional advice
    L4 — Constraint    : failure modes, instability regions, do-not-use cases

    Stored on ``EntryMetadata.skill_level``. ``None`` means *unclassified*
    (legacy / generic content). The level is **orthogonal** to ``entry_type``
    so that, e.g., a ``procedure`` and a ``workflow`` can both be tagged L2,
    and an L3 ``heuristic`` can be attached to either.
    """

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


# Default mapping from entry_type → skill level, used by the backfill script
# and by progressive retrieval when ``skill_level`` is not set explicitly.
DEFAULT_LEVEL_FOR_TYPE: dict[str, SkillLevel] = {
    "capability": SkillLevel.L1,
    "procedure": SkillLevel.L2,
    "heuristic": SkillLevel.L3,
    "constraint": SkillLevel.L4,
    "memory": SkillLevel.L3,
}


def implied_level(
    entry_type: "EntryType | str | None", explicit: "SkillLevel | None"
) -> "SkillLevel | None":
    """Return the effective skill level for an entry.

    Prefers an explicit metadata tag; otherwise falls back to the default
    mapping for the entry type.
    """
    if explicit is not None:
        return explicit
    et = entry_type.value if hasattr(entry_type, "value") else (entry_type or "")
    return DEFAULT_LEVEL_FOR_TYPE.get(str(et))


class RefinementStatus(str, Enum):
    raw = "raw"
    linked = "linked"
    refined = "refined"
    validated = "validated"


class VerificationStatus(str, Enum):
    """Lifecycle of correctness checking for a node.

    unverified  — created by an agent, never validated.
    self_tested — author/agent reports it works (low confidence).
    peer_reviewed — another agent or human reviewed it.
    community_tested — multiple independent successes recorded.
    bugged       — known broken; needs fix.
    deprecated   — superseded; do not use.
    """

    unverified = "unverified"
    self_tested = "self_tested"
    peer_reviewed = "peer_reviewed"
    community_tested = "community_tested"
    bugged = "bugged"
    deprecated = "deprecated"


class EntryMetadata(BaseModel):
    # Disabled entries remain persisted, but are excluded from ordinary
    # retrieval and the in-memory traversal graph.
    disabled: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_provenance: Optional[str] = None
    extraction_method: Optional[str] = None
    refinement_status: RefinementStatus = RefinementStatus.raw
    usage_count: int = 0
    trust_score: Optional[float] = None
    verification_status: VerificationStatus = VerificationStatus.unverified
    # Set by create_entry when a more-generic existing node is found.
    # MaintenanceAgent uses this to pick candidates for abstraction.
    needs_generalization: bool = False
    # Append-only log of external/internal feedback events.
    # Each item: {timestamp, agent_id, verdict, note, evidence}
    feedback_log: list[dict] = Field(default_factory=list)

    # Hierarchical-memory tagging (progressive disclosure).
    # Explicit override for the L1/L2/L3/L4 level. When None, callers should
    # use ``implied_level(entry_type, skill_level)`` to derive it from the
    # entry_type via DEFAULT_LEVEL_FOR_TYPE.
    skill_level: Optional[SkillLevel] = None
    # Previous or more specific type label when a legacy public type has been
    # collapsed into the four canonical public types.
    subtype: Optional[str] = None
    # Free-form metadata for L3 heuristics / L4 constraints:
    #   {domain: str, confidence: float, papers: [str], notes: str, ...}
    applicability: dict = Field(default_factory=dict)
    # Quick-access list of slugs/ids of L4 constraint nodes attached to this
    # capability/procedure. Kept denormalised so planners can skim risks
    # without traversing edges. Authoritative source is still ``constraint_on``
    # edges in the graph.
    failure_modes: list[str] = Field(default_factory=list)

    @field_validator("verification_status", mode="before")
    @classmethod
    def _default_verification(cls, v):
        # Tolerate legacy rows where verification_status was stored as null.
        return VerificationStatus.unverified if v is None else v

    # Script-specific metadata
    script_language: Optional[str] = None  # e.g. "python", "bash", "julia"
    script_requirements: list[str] = Field(default_factory=list)  # pip/conda packages
    script_filename: Optional[str] = None  # suggested filename for download
    related_environments: list[str] = Field(default_factory=list)
    runtime_requirements: list[str] = Field(default_factory=list)
    external_refs: list[str] = Field(default_factory=list)
    # Review-agent tracking
    review_count: int = 0
    modify_count: int = 0
    last_reviewed_at: Optional[datetime] = None
    # Remote-source mirror (for nodes that wrap an upstream SKILL.md / script).
    remote_source: Optional[RemoteSource] = None
    custom: dict = Field(default_factory=dict)


_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")


def _extract_wikilinks(content: str) -> list[str]:
    return _WIKILINK_RE.findall(content)


class ScriptAttachment(BaseModel):
    """An executable script stored directly on a node, separate from human-readable content.

    Kept for backward compatibility — internally these are mirrored into the
    generalised :class:`NodeAsset` list with ``folder="scripts"``.
    """

    filename: str
    language: str = "python"
    content: str
    requirements: list[str] = Field(default_factory=list)
    description: str = ""


# ── Asset folders (free-form, but these are recognised by the UI) ────────────
ASSET_FOLDER_SCRIPTS = "scripts"
ASSET_FOLDER_REFERENCES = "references"
ASSET_FOLDER_DOCS = "docs"
ASSET_FOLDER_EXAMPLES = "examples"
ASSET_FOLDER_DATA = "data"
ASSET_FOLDER_NOTES = "notes"

KNOWN_ASSET_FOLDERS = (
    ASSET_FOLDER_SCRIPTS,
    ASSET_FOLDER_REFERENCES,
    ASSET_FOLDER_DOCS,
    ASSET_FOLDER_EXAMPLES,
    ASSET_FOLDER_DATA,
    ASSET_FOLDER_NOTES,
)


def _normalise_folder(folder: str) -> str:
    f = (folder or "").strip().strip("/").lower()
    f = re.sub(r"[^a-z0-9_\-]+", "-", f)
    return f or ASSET_FOLDER_NOTES


def _normalise_filename(filename: str) -> str:
    """Strip path traversal and leading slashes; keep simple sub-paths."""
    name = (filename or "").strip().lstrip("/\\")
    # Reject path-traversal segments outright
    parts = [p for p in re.split(r"[\\/]+", name) if p and p != "."]
    if any(p == ".." for p in parts):
        raise ValueError(f"Invalid asset filename (contains '..'): {filename!r}")
    if not parts:
        raise ValueError("Asset filename must not be empty")
    return "/".join(parts)


class NodeAsset(BaseModel):
    """A file-like attachment on an entry.

    Each node behaves like a small folder of typed assets. Folders are free-form
    strings (e.g. ``scripts``, ``references``, ``docs``, ``examples``, ``data``,
    ``notes``); see :data:`KNOWN_ASSET_FOLDERS` for the conventional set.

    External agents can address assets as ``[entry-slug]/[folder]/[filename]``
    via ``GET /entries/{id}/assets/{folder}/{filename}``.
    """

    folder: str = ASSET_FOLDER_NOTES
    filename: str
    kind: str = "file"  # "file" | "link" | "text"
    content: str = ""  # body for file/text; URL for link
    language: Optional[str] = None
    mime_type: Optional[str] = None
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @field_validator("folder", mode="before")
    @classmethod
    def _v_folder(cls, v):
        return _normalise_folder(v if isinstance(v, str) else "")

    @field_validator("filename", mode="before")
    @classmethod
    def _v_filename(cls, v):
        return _normalise_filename(v if isinstance(v, str) else "")

    @field_validator("kind", mode="before")
    @classmethod
    def _v_kind(cls, v):
        v = (v or "file").lower()
        if v not in ("file", "link", "text"):
            v = "file"
        return v

    @property
    def path(self) -> str:
        """Folder/filename path used in asset URLs."""
        return f"{self.folder}/{self.filename}"


class Entry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    slug: str = ""
    # Native Know-Do Graphs use EntryType; custom graph databases may retain
    # their own non-empty type labels.
    entry_type: EntryType | str = EntryType.capability
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    metadata: EntryMetadata = Field(default_factory=EntryMetadata)
    internal_refs: list[str] = Field(default_factory=list)
    scripts: list[ScriptAttachment] = Field(default_factory=list)
    assets: list[NodeAsset] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_public_type(cls, data):
        if not isinstance(data, dict):
            return data
        raw_type = data.get("entry_type", EntryType.capability.value)
        raw_value = raw_type.value if isinstance(raw_type, EntryType) else str(raw_type).strip()
        if raw_value and raw_value not in {entry_type.value for entry_type in EntryType}:
            data = dict(data)
            data["entry_type"] = raw_value
            return data
        subtype = legacy_entry_subtype(raw_type)
        canonical = canonical_entry_type(raw_type)
        data = dict(data)
        data["entry_type"] = canonical
        if subtype:
            metadata = data.get("metadata") or {}
            if isinstance(metadata, EntryMetadata):
                if metadata.subtype is None:
                    metadata = metadata.model_copy(update={"subtype": subtype})
            elif isinstance(metadata, dict):
                metadata = dict(metadata)
                metadata.setdefault("subtype", subtype)
            data["metadata"] = metadata
        return data

    def model_post_init(self, __context: object) -> None:
        if not self.slug:
            self.slug = slug_from_title(self.title)
        extracted = _extract_wikilinks(self.content)
        combined = list(dict.fromkeys(self.internal_refs + extracted))
        self.internal_refs = combined
        # Bidirectional sync between legacy `scripts` and generalised `assets`.
        self._sync_scripts_and_assets()

    def refresh_refs(self) -> None:
        self.internal_refs = list(dict.fromkeys(_extract_wikilinks(self.content)))

    # ------------------------------------------------------------------
    # Assets / scripts sync helpers
    # ------------------------------------------------------------------

    def _sync_scripts_and_assets(self) -> None:
        """Keep ``scripts`` and ``assets[folder='scripts']`` in sync.

        ``assets`` is the canonical store. ``scripts`` is a derived legacy view.

        - **Legacy load** (``assets`` empty, ``scripts`` non-empty): migrate the
          scripts into ``assets`` so future reads see the unified model.
        - Otherwise: any ``scripts=`` passed at construction is **ignored**
          (``assets`` is authoritative).
        - ``scripts`` is then rebuilt strictly from ``assets`` so deletions on
          ``assets`` propagate to the legacy view.
        """
        if not self.assets and self.scripts:
            for s in self.scripts:
                self.assets.append(
                    NodeAsset(
                        folder=ASSET_FOLDER_SCRIPTS,
                        filename=s.filename,
                        kind="file",
                        content=s.content,
                        language=s.language,
                        requirements=list(s.requirements),
                        description=s.description,
                    )
                )
        # Derived view — always rebuilt from canonical assets.
        self.scripts = [
            ScriptAttachment(
                filename=a.filename,
                language=a.language or "python",
                content=a.content,
                requirements=list(a.requirements),
                description=a.description,
            )
            for a in self.assets
            if a.folder == ASSET_FOLDER_SCRIPTS and a.kind != "link"
        ]

    def find_asset(self, folder: str, filename: str) -> Optional[NodeAsset]:
        folder = _normalise_folder(folder)
        filename = _normalise_filename(filename)
        for a in self.assets:
            if a.folder == folder and a.filename == filename:
                return a
        return None

    def assets_by_folder(self) -> dict[str, list[NodeAsset]]:
        out: dict[str, list[NodeAsset]] = {}
        for a in self.assets:
            out.setdefault(a.folder, []).append(a)
        return out


def entry_type_value(entry_type: EntryType | str | None) -> str:
    """Return the stored/displayable type for native and custom graphs."""
    return (
        entry_type.value
        if isinstance(entry_type, EntryType)
        else str(entry_type or EntryType.capability.value)
    )


# Scientific symbols that should become descriptive words, not their Latin
# transliterations. Å (U+00C5/U+00E5) decomposes to 'a' via NFKD, but in
# materials-science titles it is the Ångström unit symbol.
_CHAR_SUBS: dict[str, str] = {
    "Å": "angstrom",
    "å": "angstrom",
    "µ": "micro",
    "μ": "micro",
    "°": "deg",
    "±": "plus-minus",
    "×": "x",
    "·": "-",
}


def _legacy_slug_from_title(title: str) -> str:
    import unicodedata

    # Pre-substitute scientific symbols that have misleading NFKD decompositions.
    for sym, replacement in _CHAR_SUBS.items():
        title = title.replace(sym, f" {replacement} ")
    # Transliterate to ASCII: NFKD decomposes accented letters (é→e);
    # characters with no Latin decomposition (δ, Δ) are replaced char-by-char
    # using the last word of their Unicode name (e.g. "GREEK SMALL LETTER DELTA" → "delta").
    parts: list[str] = []
    for ch in unicodedata.normalize("NFKD", title):
        if ch.isascii():
            parts.append(ch)
        elif unicodedata.combining(ch):
            pass  # drop combining diacritics
        else:
            name = unicodedata.name(ch, "").lower()
            parts.append(name.split()[-1] if name else "")
    slug = "".join(parts).lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
