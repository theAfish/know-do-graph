from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EntryType(str, Enum):
    capability = "capability"
    procedure = "procedure"
    workflow = "workflow"
    tool = "tool"
    repository = "repository"
    environment = "environment"
    dependency = "dependency"
    data = "data"
    analytical = "analytical"
    memory = "memory"
    generic = "generic"


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

    @field_validator("verification_status", mode="before")
    @classmethod
    def _default_verification(cls, v):
        # Tolerate legacy rows where verification_status was stored as null.
        return VerificationStatus.unverified if v is None else v
    # Script-specific metadata
    script_language: Optional[str] = None      # e.g. "python", "bash", "julia"
    script_requirements: list[str] = Field(default_factory=list)  # pip/conda packages
    script_filename: Optional[str] = None      # suggested filename for download
    related_environments: list[str] = Field(default_factory=list)
    runtime_requirements: list[str] = Field(default_factory=list)
    external_refs: list[str] = Field(default_factory=list)
    # Review-agent tracking
    review_count: int = 0
    modify_count: int = 0
    last_reviewed_at: Optional[datetime] = None
    custom: dict = Field(default_factory=dict)


_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")


def _extract_wikilinks(content: str) -> list[str]:
    return _WIKILINK_RE.findall(content)


class Entry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    slug: str = ""
    entry_type: EntryType = EntryType.generic
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    metadata: EntryMetadata = Field(default_factory=EntryMetadata)
    internal_refs: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if not self.slug:
            self.slug = _slug_from_title(self.title)
        extracted = _extract_wikilinks(self.content)
        combined = list(dict.fromkeys(self.internal_refs + extracted))
        self.internal_refs = combined

    def refresh_refs(self) -> None:
        self.internal_refs = list(dict.fromkeys(_extract_wikilinks(self.content)))


def _slug_from_title(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
