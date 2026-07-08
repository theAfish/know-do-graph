"""Progressive (staged) retrieval API.

Endpoints surface the hierarchical-memory layers so external agents can pull
only the level of detail needed for the current execution stage.

See :mod:`core.retrieval.progressive` for the underlying logic.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.schemas import ProgressiveEntry
from core.app_state import graph as _graph
from core.retrieval.progressive import ProgressiveRetriever
from core.schemas.entry import Entry, implied_level
from core.storage.database import get_db

router = APIRouter()


def _retriever(db: Session = Depends(get_db)) -> ProgressiveRetriever:
    return ProgressiveRetriever(db, _graph)


def _annotate(entry: Entry) -> dict:
    data = entry.model_dump(mode="json")
    level = implied_level(entry.entry_type, entry.metadata.skill_level)
    data["_level"] = level.value if level else None
    return data


@router.get("/plan", response_model=list[ProgressiveEntry])
def plan(
    goal: str = Query(..., description="Free-text description of what you want to do"),
    k: int = Query(5, ge=1, le=50),
    mode: str = Query("hybrid", pattern="^(hybrid|semantic|keyword)$"),
    include_l2: bool = Query(True, description="Include L2 procedures alongside L1 capabilities"),
    retriever: ProgressiveRetriever = Depends(_retriever),
):
    """Return planner-level candidates (L1 capabilities, optionally L2 procedures).

    Heuristics (L3) and constraints (L4) are intentionally excluded — fetch
    them on demand via ``/retrieve/heuristics`` and ``/retrieve/constraints``.
    """
    return [_annotate(e) for e in retriever.plan(goal=goal, k=k, mode=mode, include_l2=include_l2)]


@router.get("/heuristics", response_model=list[ProgressiveEntry])
def heuristics(
    skill: str = Query(..., description="Entry id, slug, or alias of the L1/L2 skill"),
    k: int = Query(5, ge=1, le=50),
    fallback: bool = Query(
        True, description="Include semantic-search L3 fallback if no edges exist"
    ),
    retriever: ProgressiveRetriever = Depends(_retriever),
):
    """Return L3 heuristics attached to a skill."""
    return [
        _annotate(e)
        for e in retriever.heuristics_for(skill, k=k, include_semantic_fallback=fallback)
    ]


@router.get("/constraints", response_model=list[ProgressiveEntry])
def constraints(
    skill: str = Query(..., description="Entry id, slug, or alias of the L1/L2 skill"),
    k: int = Query(5, ge=1, le=50),
    fallback: bool = Query(
        True, description="Include semantic-search L4 fallback if no edges exist"
    ),
    retriever: ProgressiveRetriever = Depends(_retriever),
):
    """Return L4 constraints / failure modes attached to a skill."""
    return [
        _annotate(e)
        for e in retriever.constraints_for(skill, k=k, include_semantic_fallback=fallback)
    ]


@router.get("/expand/{skill}", response_model=dict)
def expand(
    skill: str,
    stages: Optional[str] = Query(
        None,
        description="Comma-separated subset of heuristics,constraints,decomposition (default: heuristics,constraints)",
    ),
    k: int = Query(5, ge=1, le=50),
    retriever: ProgressiveRetriever = Depends(_retriever),
):
    """Bundle additional context for an already-selected skill (verifier loop)."""
    stage_list = [s.strip() for s in stages.split(",")] if stages else None
    result = retriever.expand(skill=skill, stages=stage_list, k=k)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
