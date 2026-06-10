"""Maintenance agent.

Performs routine graph health and consistency tasks:
- Remove dangling edges pointing to deleted entries
- Rebuild the in-memory graph from the database
- Export entries to YAML node files
- Promote Mem-Graph traces into full Know-Do Graph entries
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.graph.graph import KnowDoGraph
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus
from core.storage.database import SessionLocal
from core.storage.repository import EdgeRepository, EntryRepository


class MaintenanceAgent:
    def __init__(self, graph: KnowDoGraph) -> None:
        self._graph = graph

    def remove_dangling_edges(self) -> int:
        """Delete edges whose source or target entry no longer exists."""
        removed = 0
        with SessionLocal() as db:
            entry_repo = EntryRepository(db)
            edge_repo = EdgeRepository(db)
            entry_ids = {e.id for e in entry_repo.get_all()}
            for edge in edge_repo.get_all():
                if edge.source_id not in entry_ids or edge.target_id not in entry_ids:
                    edge_repo.delete(edge.id)
                    self._graph.remove_edge(edge.source_id, edge.target_id)
                    removed += 1
        return removed

    def rebuild_graph(self) -> None:
        """Rebuild the in-memory graph from the current database state."""
        with SessionLocal() as db:
            entries = EntryRepository(db).get_all()
            edges = EdgeRepository(db).get_all()
        self._graph.rebuild_from_db(entries, edges)

    def export_to_yaml(self, output_dir: Path) -> int:
        """Write each entry as a YAML file under *output_dir*.

        Returns the number of files written.
        """
        import yaml  # pyyaml

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        with SessionLocal() as db:
            entries = EntryRepository(db).get_all()
        for entry in entries:
            data = entry.model_dump(mode="json")
            file_path = output_dir / f"{entry.slug}.yaml"
            file_path.write_text(
                yaml.dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        return len(entries)

    def promote_mem_entry(
        self,
        mem_id: str,
        session_id: str = "default",
        entry_type: EntryType = EntryType.memory,
        tags: Optional[list[str]] = None,
    ) -> Optional[Entry]:
        """Promote a Mem-Graph trace into a full Know-Do Graph entry."""
        from core.memory.memgraph import MemGraph
        from core.storage.repository import EntryRepository

        mg = MemGraph(session_id)
        mem_entry = mg.get(mem_id)
        if not mem_entry:
            return None

        entry = Entry(
            title=f"Memory: {mem_entry.content[:60]}",
            entry_type=entry_type,
            content=mem_entry.content,
            tags=(tags or []) + mem_entry.tags,
            metadata=EntryMetadata(
                source_provenance=f"mem-graph:{session_id}:{mem_id}",
                extraction_method="mem_promotion",
                refinement_status=RefinementStatus.raw,
            ),
        )

        with SessionLocal() as db:
            saved = EntryRepository(db).create(entry)
        self._graph.add_entry(saved)
        mg.mark_promoted(mem_id, saved.id)
        return saved

    # ------------------------------------------------------------------
    # Query helpers — surface entries that need attention
    # ------------------------------------------------------------------

    def list_unverified(self, limit: int = 100) -> list[Entry]:
        """Return entries whose verification_status is 'unverified'."""
        from core.schemas.entry import VerificationStatus

        with SessionLocal() as db:
            entries = EntryRepository(db).get_all()
        return [
            e for e in entries
            if e.metadata.verification_status == VerificationStatus.unverified
        ][:limit]

    def list_bugged(self, limit: int = 100) -> list[Entry]:
        """Return entries flagged as bugged via feedback."""
        from core.schemas.entry import VerificationStatus

        with SessionLocal() as db:
            entries = EntryRepository(db).get_all()
        return [
            e for e in entries
            if e.metadata.verification_status == VerificationStatus.bugged
        ][:limit]

    def list_needs_generalization(self, limit: int = 100) -> list[Entry]:
        """Return entries flagged by the abstraction check."""
        with SessionLocal() as db:
            entries = EntryRepository(db).get_all()
        return [e for e in entries if e.metadata.needs_generalization][:limit]

    # ------------------------------------------------------------------
    # Hierarchical-memory maintenance
    # ------------------------------------------------------------------

    def extract_heuristics_from_node(
        self,
        entry_id: str,
        dry_run: bool = True,
    ) -> dict:
        """Best-effort split of a flat skill blob into L3 / L4 child nodes.

        Scans the body of *entry_id* for headed sections whose titles match
        common heuristic / constraint patterns (case-insensitive substrings):

        ============================ ===============
        Heading contains             Maps to
        ============================ ===============
        "heuristic", "rule of thumb" L3 heuristic
        "tips", "best practice"      L3 heuristic
        "limitation", "failure"      L4 constraint
        "caveat", "warning", "pitfall" L4 constraint
        "do not use", "not suitable" L4 constraint
        ============================ ===============

        Non-destructive: the source node is not modified; child nodes are only
        created when ``dry_run=False``. Returns a summary dict describing what
        was (or would be) extracted.
        """
        import re

        from core.retrieval.retrieval import RetrievalEngine
        from core.schemas.edge import Edge, EdgeRelation
        from core.schemas.entry import (
            Entry,
            EntryMetadata,
            EntryType,
            SkillLevel,
        )

        l3_keywords = ("heuristic", "rule of thumb", "tips", "best practice", "tip:", "guideline")
        l4_keywords = (
            "limitation", "failure", "caveat", "warning", "pitfall",
            "do not use", "not suitable", "unsuitable", "instability", "known issue",
        )

        with SessionLocal() as db:
            engine = RetrievalEngine(db, self._graph)
            entry = engine.resolve_identifier(entry_id)
            if entry is None:
                return {"error": f"Entry '{entry_id}' not found."}

            sections = _split_markdown_sections(entry.content)
            heuristics: list[dict] = []
            constraints: list[dict] = []
            for heading, body in sections:
                lower = heading.lower()
                if any(k in lower for k in l4_keywords):
                    constraints.append({"title": heading.strip(), "content": body.strip()})
                elif any(k in lower for k in l3_keywords):
                    heuristics.append({"title": heading.strip(), "content": body.strip()})

            created_h: list[dict] = []
            created_c: list[dict] = []
            if not dry_run:
                edge_repo = EdgeRepository(db)
                repo = EntryRepository(db)
                for item in heuristics:
                    child = Entry(
                        title=f"{entry.title} — {item['title']}"[:200],
                        content=item["content"],
                        entry_type=EntryType.heuristic,
                        tags=list(dict.fromkeys(entry.tags + ["heuristic"])),
                        metadata=EntryMetadata(
                            skill_level=SkillLevel.L3,
                            source_provenance=f"extracted_from:{entry.slug}",
                            applicability={"parent": entry.slug},
                        ),
                    )
                    saved = repo.create(child)
                    edge = Edge(
                        source_id=saved.id,
                        target_id=entry.id,
                        relation=EdgeRelation.heuristic_for,
                    )
                    edge_repo.create(edge)
                    self._graph.add_entry(saved)
                    self._graph.add_edge(edge)
                    created_h.append({"id": saved.id, "slug": saved.slug, "title": saved.title})

                for item in constraints:
                    child = Entry(
                        title=f"{entry.title} — {item['title']}"[:200],
                        content=item["content"],
                        entry_type=EntryType.constraint,
                        tags=list(dict.fromkeys(entry.tags + ["constraint", "failure-mode"])),
                        metadata=EntryMetadata(
                            skill_level=SkillLevel.L4,
                            source_provenance=f"extracted_from:{entry.slug}",
                            applicability={"parent": entry.slug},
                        ),
                    )
                    saved = repo.create(child)
                    edge = Edge(
                        source_id=saved.id,
                        target_id=entry.id,
                        relation=EdgeRelation.constraint_on,
                    )
                    edge_repo.create(edge)
                    self._graph.add_entry(saved)
                    self._graph.add_edge(edge)
                    created_c.append({"id": saved.id, "slug": saved.slug, "title": saved.title})

                # Denormalise constraint slugs on parent.
                if created_c:
                    entry.metadata.failure_modes = list(
                        dict.fromkeys(
                            entry.metadata.failure_modes + [c["slug"] for c in created_c]
                        )
                    )
                    repo.update(entry)

        return {
            "entry": entry.slug,
            "dry_run": dry_run,
            "candidate_heuristics": heuristics,
            "candidate_constraints": constraints,
            "created_heuristics": created_h,
            "created_constraints": created_c,
        }


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Naive markdown splitter: returns list of (heading, body) pairs.

    Recognises ``#``-style headings (any level). Text before the first heading
    is associated with heading ``""``.
    """
    import re

    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if m:
            sections.append((current_heading, "\n".join(current_body)))
            current_heading = m.group(1)
            current_body = []
        else:
            current_body.append(line)
    sections.append((current_heading, "\n".join(current_body)))
    return sections
