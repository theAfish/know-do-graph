from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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


class EntryMetadata(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_provenance: Optional[str] = None
    extraction_method: Optional[str] = None
    refinement_status: RefinementStatus = RefinementStatus.raw
    usage_count: int = 0
    trust_score: Optional[float] = None
    verification_status: Optional[str] = None
    related_environments: list[str] = Field(default_factory=list)
    runtime_requirements: list[str] = Field(default_factory=list)
    external_refs: list[str] = Field(default_factory=list)
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
