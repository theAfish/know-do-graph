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
