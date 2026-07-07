"""Extraction agent.

Reads source material (files, raw text) and populates the graph with
structured Entry objects.  After insertion it can resolve [[wikilinks]]
to create typed Edge relations between entries.

Supported extraction meta-skills
---------------------------------
* File reading/writing
* Wikilink parsing
* External reference extraction
* Entry creation
* Edge creation / dependency linking
* Source provenance tracking
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.extraction.wikilink_parser import (
    extract_external_refs,
    slug_from_title,
)
from core.graph.graph import KnowDoGraph
from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus
from core.storage.database import SessionLocal
from core.storage.repository import EdgeRepository, EntryRepository

_TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".yaml", ".yml", ".json"}


class ExtractionAgent:
    """Reads source documents and extracts Entry objects into the graph.

    Parameters
    ----------
    graph:
        The shared in-process KnowDoGraph instance to keep in sync.
    """

    def __init__(self, graph: KnowDoGraph) -> None:
        self._graph = graph

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_from_file(
        self,
        path: Path,
        entry_type: EntryType = EntryType.generic,
        tags: Optional[list[str]] = None,
        source_provenance: Optional[str] = None,
    ) -> Entry:
        """Create an Entry from a single text file."""
        content = path.read_text(encoding="utf-8", errors="replace")
        title = path.stem.replace("-", " ").replace("_", " ").title()
        entry = Entry(
            title=title,
            slug=slug_from_title(title),
            entry_type=entry_type,
            content=content,
            tags=tags or [],
            metadata=EntryMetadata(
                source_provenance=source_provenance or str(path),
                extraction_method="file_read",
                refinement_status=RefinementStatus.raw,
                external_refs=extract_external_refs(content),
            ),
        )
        return self._persist_entry(entry)

    def extract_from_directory(
        self,
        directory: Path,
        entry_type: EntryType = EntryType.generic,
        tags: Optional[list[str]] = None,
        recursive: bool = True,
    ) -> list[Entry]:
        """Extract entries from all text files in *directory*."""
        glob = directory.rglob("*") if recursive else directory.glob("*")
        files = [f for f in glob if f.is_file() and f.suffix.lower() in _TEXT_EXTENSIONS]
        return [self.extract_from_file(f, entry_type=entry_type, tags=tags) for f in files]

    def extract_from_text(
        self,
        title: str,
        content: str,
        entry_type: EntryType = EntryType.generic,
        tags: Optional[list[str]] = None,
        source_provenance: Optional[str] = None,
    ) -> Entry:
        """Create an Entry from raw text."""
        entry = Entry(
            title=title,
            slug=slug_from_title(title),
            entry_type=entry_type,
            content=content,
            tags=tags or [],
            metadata=EntryMetadata(
                source_provenance=source_provenance,
                extraction_method="text_input",
                refinement_status=RefinementStatus.raw,
                external_refs=extract_external_refs(content),
            ),
        )
        return self._persist_entry(entry)

    # ------------------------------------------------------------------
    # Wikilink resolution
    # ------------------------------------------------------------------

    def resolve_wikilinks(self) -> int:
        """Resolve all [[wikilinks]] across entries and create edges.

        Returns the number of new edges created.
        """
        created = 0
        with SessionLocal() as db:
            entry_repo = EntryRepository(db)
            edge_repo = EdgeRepository(db)
            all_entries = entry_repo.get_all()
            slug_map = {e.slug: e.id for e in all_entries}
            title_map = {e.title.lower(): e.id for e in all_entries}
            alias_map: dict[str, str] = {}
            for e in all_entries:
                for a in e.aliases:
                    alias_map.setdefault(a.lower(), e.id)

            for entry in all_entries:
                for ref in entry.internal_refs:
                    ref_slug = slug_from_title(ref)
                    ref_lower = ref.lower()
                    target_id = (
                        slug_map.get(ref_slug)
                        or title_map.get(ref_lower)
                        or alias_map.get(ref_lower)
                    )
                    if target_id and target_id != entry.id:
                        edge = Edge(
                            source_id=entry.id,
                            target_id=target_id,
                            relation=EdgeRelation.wikilink,
                        )
                        saved = edge_repo.create(edge)
                        self._graph.add_edge(saved)
                        created += 1
        return created

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist_entry(self, entry: Entry) -> Entry:
        with SessionLocal() as db:
            repo = EntryRepository(db)
            saved = repo.create(entry)
        self._graph.add_entry(saved)
        return saved
