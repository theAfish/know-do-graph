from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import app_state
from core.schemas.edge import Edge as EntryEdge
from core.schemas.edge import EdgeRelation
from core.schemas.entry import Entry
from core.storage.database import bind_session_factory
from core.storage.repository import EdgeRepository, EntryRepository
from core.sync.db_merge import dedup_exact, find_exact_duplicate_groups, merge_database
from know_do_graph import KnowDoGraph


class Priority9SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.graph = KnowDoGraph(self.root / "local.db", memory_dir=self.root / "memory")
        self._app_graph = app_state.graph
        app_state.graph = self.graph._graph

    def tearDown(self) -> None:
        app_state.graph = self._app_graph
        self.graph.close()
        self.temp_dir.cleanup()

    def _make_remote_db(self) -> Path:
        remote = KnowDoGraph(self.root / "remote.db", memory_dir=self.root / "remote-memory")
        remote.add("Local Skill", content="Remote copy", aliases=["remote-local"])
        remote.add("Remote Wikilink Source", content="See [[Local Skill]].")
        remote_path = remote.path
        remote.close()
        return remote_path

    def test_database_merge_reports_slug_renames_and_resolves_wikilinks(self) -> None:
        local = self.graph.add("Local Skill", content="Local copy")
        remote_path = self._make_remote_db()

        with bind_session_factory(self.graph._session_factory):
            report = merge_database(remote_path, resolve_wikilinks=True)

        self.assertEqual(report.entries_inserted, 2)
        self.assertIn(("local-skill", "local-skill-1"), report.slug_renames)
        self.assertGreaterEqual(report.wikilinks_resolved, 1)
        self.graph.refresh()
        source = self.graph.get("remote-wikilink-source")
        related = {entry.id for entry in self.graph.related(source.id)}
        self.assertIn(local.id, related)

    def test_dedup_exact_dry_run_and_apply_merge_duplicates(self) -> None:
        primary = self.graph.add("Duplicate Merge", content="longer canonical content")
        duplicate = self.graph.add("Duplicate Merge", content="short")
        target = self.graph.add("Merge Target")
        self.graph.connect(duplicate.id, target.id, relation=EdgeRelation.dependency)

        with bind_session_factory(self.graph._session_factory):
            groups = find_exact_duplicate_groups()
            dry = dedup_exact(dry_run=True)
            applied = dedup_exact(dry_run=False)

        self.assertTrue(
            any({primary.id, duplicate.id} <= {entry.id for entry in group} for group in groups)
        )
        self.assertEqual(dry.merged_pairs, 0)
        self.assertEqual(len(dry.candidates), 1)
        self.assertEqual(applied.merged_pairs, 1)
        self.graph.refresh()
        self.assertIsNone(self.graph.get(duplicate.id))
        self.assertIn(target.id, {entry.id for entry in self.graph.related(primary.id)})

    def test_merge_database_skips_duplicate_edges(self) -> None:
        source = self.graph.add("Shared Source")
        target = self.graph.add("Shared Target")
        self.graph.connect(source.id, target.id, relation=EdgeRelation.dependency)

        remote_path = self.root / "edge-remote.db"
        remote = KnowDoGraph(remote_path, memory_dir=self.root / "edge-remote-memory")
        try:
            with remote._session_factory() as db:
                entries = EntryRepository(db)
                edges = EdgeRepository(db)
                entries.create(Entry(id=source.id, title=source.title, slug=source.slug))
                entries.create(Entry(id=target.id, title=target.title, slug=target.slug))
                edges.create(
                    EntryEdge(
                        source_id=source.id,
                        target_id=target.id,
                        relation=EdgeRelation.dependency,
                    )
                )
        finally:
            remote.close()

        with bind_session_factory(self.graph._session_factory):
            report = merge_database(remote_path, resolve_wikilinks=False)

        self.assertEqual(report.edges_skipped, 1)


if __name__ == "__main__":
    unittest.main()
