from __future__ import annotations

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


MIGRATIONS = [
    Migration(1, "entry compatibility columns", _m001_entry_compat_columns),
    Migration(2, "lookup indexes", _m002_indexes),
]
