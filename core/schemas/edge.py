from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class EdgeRelation(str, Enum):
    dependency = "dependency"
    compatible_with = "compatible_with"
    alternative_to = "alternative_to"
    related_workflow = "related_workflow"
    generated_from = "generated_from"
    memory_of = "memory_of"
    refinement_of = "refinement_of"
    derived_from = "derived_from"
    warning_about = "warning_about"
    cited_by = "cited_by"
    wikilink = "wikilink"
    prerequisite = "prerequisite"
    replacement = "replacement"
    execution_pathway = "execution_pathway"
    transformation = "transformation"
    provenance = "provenance"
    compatibility = "compatibility"


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    relation: EdgeRelation = EdgeRelation.wikilink
    weight: float = 1.0
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
