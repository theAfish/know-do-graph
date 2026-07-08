from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from core.storage.config import DatabaseConfig
from core.storage.database import create_database_engine, initialize_database


class DatabaseMigrationTests(unittest.TestCase):
    def test_database_config_resolves_default_and_env_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            default_config = DatabaseConfig.from_env(cwd=root)
            self.assertEqual(default_config.path, (root / "data" / "know_do_graph.db").resolve())

    def test_initialize_database_records_migrations_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_database_engine(Path(temp_dir) / "graph.db")
            initialize_database(engine)

            with engine.connect() as conn:
                migrations = conn.execute(
                    text("SELECT version FROM schema_migrations ORDER BY version")
                ).all()
                entry_indexes = {
                    row[1] for row in conn.execute(text("PRAGMA index_list(entries)")).all()
                }
                edge_indexes = {
                    row[1] for row in conn.execute(text("PRAGMA index_list(edges)")).all()
                }

            engine.dispose()

        self.assertEqual([row[0] for row in migrations], [1, 2, 3])
        self.assertIn("ix_entries_entry_type", entry_indexes)
        self.assertIn("ix_entries_updated_at", entry_indexes)
        self.assertIn("ix_edges_source_target", edge_indexes)
        self.assertIn("ix_edges_relation", edge_indexes)

    def test_initialize_database_migrates_legacy_entries_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            raw = sqlite3.connect(db_path)
            raw.execute(
                "CREATE TABLE entries ("
                "id TEXT PRIMARY KEY, "
                "title TEXT NOT NULL, "
                "slug TEXT NOT NULL UNIQUE, "
                "entry_type TEXT NOT NULL, "
                "content TEXT, "
                "tags TEXT, "
                "metadata_json TEXT, "
                "internal_refs TEXT, "
                "created_at TIMESTAMP, "
                "updated_at TIMESTAMP"
                ")"
            )
            raw.execute(
                "INSERT INTO entries "
                "(id, title, slug, entry_type, content, tags, metadata_json, internal_refs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-tool",
                    "Legacy Tool",
                    "legacy-tool",
                    "tool",
                    "Legacy tool content.",
                    "[]",
                    "{}",
                    "[]",
                ),
            )
            raw.execute(
                "CREATE TABLE edges ("
                "id TEXT PRIMARY KEY, "
                "source_id TEXT NOT NULL, "
                "target_id TEXT NOT NULL, "
                "relation TEXT NOT NULL, "
                "weight FLOAT, "
                "metadata_json TEXT, "
                "created_at TIMESTAMP"
                ")"
            )
            raw.commit()
            raw.close()

            engine = create_database_engine(db_path)
            initialize_database(engine)

            with engine.connect() as conn:
                columns = {row[1] for row in conn.execute(text("PRAGMA table_info(entries)"))}
                migrations = conn.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar()
                migrated = conn.execute(
                    text("SELECT entry_type, metadata_json FROM entries WHERE id = 'legacy-tool'")
                ).one()

            engine.dispose()

        self.assertTrue({"aliases", "scripts_json", "assets_json", "embedding_hash"} <= columns)
        self.assertEqual(migrations, 3)
        self.assertEqual(migrated[0], "procedure")
        self.assertIn('"subtype": "tool"', migrated[1])


if __name__ == "__main__":
    unittest.main()
