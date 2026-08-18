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
    related_memory = "related_memory"
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
    implements = "implements"
    uses = "uses"
    documents = "documents"
    # Hierarchical-memory edges (progressive disclosure).
    # Direction convention is always *from child detail → parent skill*,
    # so that traversal "out of" a planner-level node yields its details.
    decomposes_to = "decomposes_to"  # L1 → L2  (capability decomposed into procedure)
    heuristic_for = "heuristic_for"  # L3 → L1/L2  (heuristic attached to a skill)
    constraint_on = "constraint_on"  # L4 → L1/L2  (failure-mode attached to a skill)


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    relation: EdgeRelation = EdgeRelation.wikilink
    weight: float = 1.0
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
