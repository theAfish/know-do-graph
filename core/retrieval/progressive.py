"""Progressive (staged) retrieval over the hierarchical skill memory.

Layers (see :class:`core.schemas.entry.SkillLevel`):
    L1 — Capability    (entry_type ∈ {capability, workflow})
    L2 — Procedure     (entry_type = procedure)
    L3 — Heuristic     (entry_type = heuristic)
    L4 — Constraint    (entry_type = constraint)

The motivation is to avoid dumping all paper knowledge as a single flat blob
into the agent's context. Typical flow::

    goal
      → ProgressiveRetriever.plan(goal)                # L1 / L2 only
      → execution
      → verifier feedback or uncertainty
      → ProgressiveRetriever.heuristics_for(skill)     # L3 on demand
      → ProgressiveRetriever.constraints_for(skill)    # L4 on demand

This module is a thin layer on top of :class:`RetrievalEngine` — it reuses the
hybrid keyword+vector ranking and adds level/edge filters.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.edge import EdgeRelation
from core.schemas.entry import (
    DEFAULT_LEVEL_FOR_TYPE,
    Entry,
    EntryType,
    SkillLevel,
    implied_level,
)
from core.storage.models import EdgeModel, EntryModel

# Levels considered "planner context" (cheap to load up front).
_PLAN_LEVELS = {SkillLevel.L1, SkillLevel.L2}


class ProgressiveRetriever:
    """Staged retrieval interface for the hierarchical operational memory."""

    def __init__(self, db: Session, graph: KnowDoGraph) -> None:
        self._db = db
        self._graph = graph
        self._engine = RetrievalEngine(db, graph)

    # ------------------------------------------------------------------
    # Stage 1 — planning context (L1 + L2)
    # ------------------------------------------------------------------

    def plan(
        self,
        goal: str,
        k: int = 5,
        mode: str = "hybrid",
        include_l2: bool = True,
    ) -> list[Entry]:
        """Return planner-level candidates (L1 capabilities, optionally L2 procedures).

        Heuristics (L3) and constraints (L4) are deliberately excluded — call
        :meth:`heuristics_for` / :meth:`constraints_for` once a candidate is
        selected.
        """
        allowed = {SkillLevel.L1, SkillLevel.L2} if include_l2 else {SkillLevel.L1}
        # Pull a generous superset, then level-filter; we don't push the filter
        # into SQL because skill_level lives in the metadata JSON blob.
        candidates = self._engine.search_entries(query=goal, limit=max(k * 4, 20), mode=mode)
        out: list[Entry] = []
        for e in candidates:
            if implied_level(e.entry_type, e.metadata.skill_level) in allowed:
                out.append(e)
                if len(out) >= k:
                    break
        return out

    # ------------------------------------------------------------------
    # Stage 2 — heuristics (L3)
    # ------------------------------------------------------------------

    def heuristics_for(
        self,
        skill: str,
        k: int = 5,
        include_semantic_fallback: bool = True,
    ) -> list[Entry]:
        """Return L3 heuristics attached to *skill* (id, slug, or alias).

        Resolution order:
          1. Nodes connected to *skill* by an inbound ``heuristic_for`` edge.
          2. (Fallback, optional) Semantic search restricted to L3 entries.
        """
        return self._sidecar_for(
            skill=skill,
            edge_relation=EdgeRelation.heuristic_for,
            target_level=SkillLevel.L3,
            target_entry_type=EntryType.heuristic,
            k=k,
            include_semantic_fallback=include_semantic_fallback,
        )

    # ------------------------------------------------------------------
    # Stage 3 — constraints / failure modes (L4)
    # ------------------------------------------------------------------

    def constraints_for(
        self,
        skill: str,
        k: int = 5,
        include_semantic_fallback: bool = True,
    ) -> list[Entry]:
        """Return L4 constraints / failure modes attached to *skill*.

        Resolution order:
          1. Nodes connected to *skill* by an inbound ``constraint_on`` or
             ``warning_about`` edge.
          2. (Fallback, optional) Semantic search restricted to L4 entries.
        """
        return self._sidecar_for(
            skill=skill,
            edge_relation=EdgeRelation.constraint_on,
            extra_edge_relations=(EdgeRelation.warning_about,),
            target_level=SkillLevel.L4,
            target_entry_type=EntryType.constraint,
            k=k,
            include_semantic_fallback=include_semantic_fallback,
        )

    # ------------------------------------------------------------------
    # Stage 4 — bundle for verifier / debugging loop
    # ------------------------------------------------------------------

    def expand(
        self,
        skill: str,
        stages: Optional[list[str]] = None,
        k: int = 5,
    ) -> dict:
        """Return a bundle of additional context for an already-selected skill.

        ``stages`` is a subset of {"heuristics", "constraints", "decomposition"}.
        Defaults to ``["heuristics", "constraints"]``.
        """
        stages = stages or ["heuristics", "constraints"]
        anchor = self._engine.resolve_identifier(skill)
        if anchor is None:
            return {"error": f"Skill '{skill}' not found.", "skill": skill}

        bundle: dict = {
            "skill": {
                "id": anchor.id,
                "slug": anchor.slug,
                "title": anchor.title,
                "level": (implied_level(anchor.entry_type, anchor.metadata.skill_level) or SkillLevel.L1).value,
            },
        }
        if "heuristics" in stages:
            bundle["heuristics"] = [self._summarize(e) for e in self.heuristics_for(anchor.id, k=k)]
        if "constraints" in stages:
            bundle["constraints"] = [self._summarize(e) for e in self.constraints_for(anchor.id, k=k)]
        if "decomposition" in stages:
            bundle["decomposition"] = [
                self._summarize(e) for e in self._decomposition_for(anchor.id, k=k * 2)
            ]
        return bundle

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _sidecar_for(
        self,
        skill: str,
        edge_relation: EdgeRelation,
        target_level: SkillLevel,
        target_entry_type: EntryType,
        k: int,
        include_semantic_fallback: bool,
        extra_edge_relations: tuple[EdgeRelation, ...] = (),
    ) -> list[Entry]:
        anchor = self._engine.resolve_identifier(skill)
        if anchor is None:
            return []

        # 1) Graph-attached sidecar nodes (authoritative).
        seen: set[str] = set()
        out: list[Entry] = []
        relations = (edge_relation, *extra_edge_relations)
        for source_id in self._inbound_sources(anchor.id, relations):
            if source_id in seen:
                continue
            seen.add(source_id)
            entry = self._engine.get_entry_by_id(source_id)
            if entry is None:
                continue
            out.append(entry)

        # 2) Semantic fallback restricted to the right level / type.
        if include_semantic_fallback and len(out) < k:
            need = k - len(out)
            query = f"{anchor.title} {' '.join(anchor.tags)}".strip()
            candidates = self._engine.search_entries(
                query=query,
                entry_type=target_entry_type,
                limit=max(need * 4, 10),
                mode="semantic",
            )
            for e in candidates:
                if e.id in seen or e.id == anchor.id:
                    continue
                if implied_level(e.entry_type, e.metadata.skill_level) != target_level:
                    continue
                out.append(e)
                seen.add(e.id)
                if len(out) >= k:
                    break

        return out[:k]

    def _decomposition_for(self, skill_id: str, k: int) -> list[Entry]:
        """Return L2 nodes connected via ``decomposes_to`` from *skill_id*.

        Note: ``decomposes_to`` is recorded as source=L1, target=L2 (the
        capability decomposes into procedure).
        """
        out: list[Entry] = []
        seen: set[str] = set()
        for edge in (
            self._db.query(EdgeModel)
            .filter(EdgeModel.source_id == skill_id, EdgeModel.relation == EdgeRelation.decomposes_to.value)
            .limit(k * 4)
            .all()
        ):
            if edge.target_id in seen:
                continue
            seen.add(edge.target_id)
            entry = self._engine.get_entry_by_id(edge.target_id)
            if entry is not None:
                out.append(entry)
                if len(out) >= k:
                    break
        return out

    def _inbound_sources(
        self,
        target_id: str,
        relations: tuple[EdgeRelation, ...],
    ) -> list[str]:
        rel_values = [r.value for r in relations]
        rows = (
            self._db.query(EdgeModel)
            .filter(EdgeModel.target_id == target_id, EdgeModel.relation.in_(rel_values))
            .all()
        )
        return [r.source_id for r in rows]

    @staticmethod
    def _summarize(entry: Entry) -> dict:
        level = implied_level(entry.entry_type, entry.metadata.skill_level)
        return {
            "id": entry.id,
            "slug": entry.slug,
            "title": entry.title,
            "entry_type": entry.entry_type.value,
            "level": level.value if level else None,
            "tags": entry.tags,
            "content": entry.content,
            "applicability": entry.metadata.applicability,
        }


__all__ = ["ProgressiveRetriever"]
