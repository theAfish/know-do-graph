from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

from core import events
from core.extraction.wikilink_parser import extract_external_refs, parse_wikilinks
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.entry import EntryMetadata, EntryType, RemoteSource
from core.storage.repository import EdgeRepository
from core.sync.autolink import auto_link_entry, build_alias_index, find_mentions
from core.sync.remote_sync import _is_due, parse_github_url, sync_entry
from know_do_graph import KnowDoGraph


class Priority9BehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.graph = KnowDoGraph(root / "graph.db", memory_dir=root / "memory")

    def tearDown(self) -> None:
        self.graph.close()
        self.temp_dir.cleanup()

    def test_slug_uniqueness_and_case_insensitive_alias_resolution(self) -> None:
        first = self.graph.add("Duplicate Title", aliases=["Dupe Alias"])
        second = self.graph.add("Duplicate Title", aliases=["Second Alias"])

        self.assertEqual(first.slug, "duplicate-title")
        self.assertEqual(second.slug, "duplicate-title-1")
        self.assertEqual(self.graph.get("dupe alias").id, first.id)
        self.assertEqual(self.graph.get("SECOND ALIAS").id, second.id)

        updated = self.graph.update(second.id, slug="duplicate-title")
        self.assertEqual(updated.slug, "duplicate-title-1")

    def test_wikilink_parsing_and_autolink_edge_cases(self) -> None:
        self.assertEqual(
            parse_wikilinks("[[ASE Relaxation|the ASE flow]] and [[MACE Calculator]]"),
            ["ASE Relaxation", "MACE Calculator"],
        )
        self.assertEqual(
            extract_external_refs("[docs](https://example.com/docs) and [x](http://x.test)"),
            ["https://example.com/docs", "http://x.test"],
        )

        source = self.graph.add(
            "Remote Skill",
            content=(
                "---\n"
                "metadata:\n"
                "  dependent_skills:\n"
                "    - ase-relaxation\n"
                "---\n"
                "This mentions the MACE calculator but avoids ambiguous aliases."
            ),
        )
        dependency = self.graph.add("ASE Relaxation", entry_type=EntryType.procedure)
        mentioned = self.graph.add(
            "MACE Calculator",
            aliases=["mace calculator"],
            entry_type=EntryType.tool,
        )
        self.graph.add("Ambiguous One", aliases=["shared-alias"])
        self.graph.add("Ambiguous Two", aliases=["shared-alias"])

        all_entries = self.graph.list(limit=20)
        index = build_alias_index(all_entries)
        self.assertEqual(find_mentions("shared-alias appears here", index), set())
        self.assertIn(mentioned.id, find_mentions("Use MACE calculator here", index))

        with self.graph._session_factory() as db:
            result = auto_link_entry(source, all_entries, EdgeRepository(db))

        self.assertEqual(result.frontmatter_edges, 1)
        self.assertEqual(result.mention_edges, 2)
        self.graph.refresh()
        related = {entry.id for entry in self.graph.related(source.id, depth=1)}
        self.assertEqual(related, {dependency.id, mentioned.id})

    def test_delete_updates_edges_vectors_graph_and_events(self) -> None:
        source = self.graph.add("Delete Source")
        target = self.graph.add("Delete Target")
        unrelated = self.graph.add("Unrelated")
        self.graph.connect(source.id, target.id)
        self.graph.connect(unrelated.id, source.id)

        queue = events.subscribe()
        loop = asyncio.new_event_loop()
        try:
            events.set_loop(loop)
            with patch("core.retrieval.vector_store.delete") as vector_delete:
                self.assertTrue(self.graph.delete(source.id))
                vector_delete.assert_called_once()
                self.assertEqual(vector_delete.call_args.args[1], source.id)
            loop.run_until_complete(asyncio.sleep(0))
            emitted = []
            while not queue.empty():
                emitted.append(queue.get_nowait())
        finally:
            events.unsubscribe(queue)
            events.set_loop(None)
            loop.close()

        self.assertIsNone(self.graph.get(source.id))
        self.assertEqual(self.graph.related(target.id), [])
        self.assertFalse(self.graph._graph.has_node(source.id))
        self.assertTrue(any('"type": "node_removed"' in message for message in emitted))
        self.assertEqual(
            sum(1 for message in emitted if '"type": "edge_removed"' in message),
            2,
        )

    def test_keyword_retrieval_fallback_when_embeddings_are_disabled(self) -> None:
        entry = self.graph.add(
            "Keyword Fallback Skill",
            content="This entry should be found without vector embeddings.",
            aliases=["fallback-search"],
        )

        with patch.dict("os.environ", {"KDG_EMBED_PROVIDER": "none"}, clear=False):
            with patch("core.retrieval.embedder._default", None):
                hybrid = self.graph.search("fallback", mode="hybrid")
                semantic = self.graph.search("fallback", mode="semantic")

        self.assertEqual(hybrid[0].id, entry.id)
        self.assertEqual(semantic, [])

    def test_remote_sync_parsing_due_success_and_failure_metadata(self) -> None:
        self.assertEqual(
            parse_github_url("https://github.com/org/repo/blob/main/skills/SKILL.md"),
            {"owner": "org", "repo": "repo", "ref": "main", "path": "skills/SKILL.md"},
        )

        due = RemoteSource(
            kind="http",
            url="https://example.com/skill.md",
            fetched_at=datetime.now(timezone.utc) - timedelta(seconds=4000),
            sync_interval_seconds=120,
        )
        not_due = RemoteSource(
            kind="http",
            url="https://example.com/skill.md",
            fetched_at=datetime.now(timezone.utc),
            sync_interval_seconds=3600,
        )
        self.assertTrue(_is_due(due, datetime.now(timezone.utc)))
        self.assertFalse(_is_due(not_due, datetime.now(timezone.utc)))

        entry = self.graph.add(
            "Remote Synced Skill",
            metadata=EntryMetadata(
                remote_source=RemoteSource(kind="http", url="https://example.com/skill.md")
            ),
        )

        async def fake_fetch_http(_url: str, _etag: str | None):
            return "updated", b"Fresh content with [[ASE Relaxation]].", '"etag-1"', "ok"

        with patch("core.sync.remote_sync._fetch_http", fake_fetch_http):
            result = asyncio.run(sync_entry(entry, force=True))

        self.assertEqual(result.status, "updated")
        self.assertEqual(entry.content, "Fresh content with [[ASE Relaxation]].")
        self.assertEqual(entry.internal_refs, ["ASE Relaxation"])
        self.assertEqual(entry.metadata.remote_source.status, "ok")
        self.assertIsNone(entry.metadata.remote_source.last_error)

        async def failing_fetch_http(_url: str, _etag: str | None):
            return "error", None, None, "http 500"

        with patch("core.sync.remote_sync._fetch_http", failing_fetch_http):
            failed = asyncio.run(sync_entry(entry, force=True))

        self.assertEqual(failed.status, "error")
        self.assertEqual(entry.metadata.remote_source.status, "error")
        self.assertEqual(entry.metadata.remote_source.last_error, "http 500")

    def test_keyword_fallback_works_when_embedding_table_is_empty(self) -> None:
        entry = self.graph.add("Empty Vector Table Lookup", content="keyword-only")
        with self.graph._session_factory() as db:
            db.execute(text("DELETE FROM entry_embeddings"))
            db.commit()
            results = RetrievalEngine(db, self.graph._graph).search_entries(
                "keyword-only",
                mode="hybrid",
            )

        self.assertEqual(results[0].id, entry.id)


if __name__ == "__main__":
    unittest.main()
