from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def apply_migrations(engine: Engine) -> None:
    """Apply all known SQLite migrations idempotently."""
    with engine.begin() as conn:
        _ensure_migration_table(conn)
        applied = {
            int(row[0]) for row in conn.execute(text("SELECT version FROM schema_migrations")).all()
        }
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            migration.apply(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (version, name) VALUES (:version, :name)"),
                {"version": migration.version, "name": migration.name},
            )


def create_vector_table(conn: Connection) -> None:
    """Create the sqlite-vec table when the extension is available."""
    try:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entry_embeddings USING vec0("
                "entry_id TEXT PRIMARY KEY, embedding FLOAT[384])"
            )
        )
    except Exception:
        pass


def _ensure_migration_table(conn: Connection) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
    )


def _add_column_if_missing(conn: Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}
    if column not in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def _m001_entry_compat_columns(conn: Connection) -> None:
    for column, definition in [
        ("aliases", "TEXT DEFAULT '[]'"),
        ("scripts_json", "TEXT DEFAULT '[]'"),
        ("assets_json", "TEXT DEFAULT '[]'"),
        ("embedding_hash", "TEXT DEFAULT NULL"),
    ]:
        _add_column_if_missing(conn, "entries", column, definition)


def _m002_indexes(conn: Connection) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_entries_entry_type ON entries(entry_type)",
        "CREATE INDEX IF NOT EXISTS ix_entries_created_at ON entries(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_entries_updated_at ON entries(updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_entries_aliases_text ON entries(aliases)",
        "CREATE INDEX IF NOT EXISTS ix_edges_source_target ON edges(source_id, target_id)",
        "CREATE INDEX IF NOT EXISTS ix_edges_relation ON edges(relation)",
        "CREATE INDEX IF NOT EXISTS ix_edges_created_at ON edges(created_at)",
    ]
    for statement in statements:
        conn.execute(text(statement))

    try:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_entries_verification_status "
                "ON entries(json_extract(metadata_json, '$.verification_status'))"
            )
        )
    except Exception:
        pass


_LEGACY_ENTRY_TYPE_TO_CANONICAL = {
    "workflow": "capability",
    "tool": "procedure",
    "repository": "procedure",
    "data": "procedure",
    "environment": "constraint",
    "dependency": "constraint",
    "analytical": "heuristic",
    "generic": "capability",
}


def _m003_normalize_public_entry_types(conn: Connection) -> None:
    rows = conn.execute(text("SELECT id, entry_type, metadata_json FROM entries")).all()
    for entry_id, entry_type, metadata_json in rows:
        canonical = _LEGACY_ENTRY_TYPE_TO_CANONICAL.get(entry_type)
        if canonical is None:
            continue
        try:
            metadata = json.loads(metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        metadata.setdefault("subtype", entry_type)
        conn.execute(
            text(
                "UPDATE entries "
                "SET entry_type = :entry_type, metadata_json = :metadata_json "
                "WHERE id = :id"
            ),
            {
                "id": entry_id,
                "entry_type": canonical,
                "metadata_json": json.dumps(metadata),
            },
        )


MIGRATIONS = [
    Migration(1, "entry compatibility columns", _m001_entry_compat_columns),
    Migration(2, "lookup indexes", _m002_indexes),
    Migration(3, "normalize public entry types", _m003_normalize_public_entry_types),
]
