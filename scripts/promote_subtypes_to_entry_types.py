#!/usr/bin/env python3
"""Promote custom-graph ``metadata.subtype`` values to ``entries.entry_type``.

This is intended for imports where the source taxonomy was temporarily packed
into KDG's capability/procedure field.  It removes ``subtype`` after promotion
so that ``entry_type`` becomes the single authoritative type field.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


def promote(database: Path, *, dry_run: bool = False) -> tuple[int, Counter[tuple[str, str]]]:
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute("SELECT id, entry_type, metadata_json FROM entries").fetchall()
        updates: list[tuple[str, str, str]] = []
        transitions: Counter[tuple[str, str]] = Counter()
        for entry_id, old_type, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Entry {entry_id} has invalid metadata_json") from exc
            subtype = metadata.get("subtype")
            if not isinstance(subtype, str) or not subtype.strip():
                continue
            new_type = subtype.strip()
            metadata.pop("subtype", None)
            updates.append((new_type, json.dumps(metadata, ensure_ascii=False), entry_id))
            transitions[(str(old_type), new_type)] += 1

        if not dry_run:
            with connection:
                if updates:
                    connection.executemany(
                        "UPDATE entries SET entry_type = ?, metadata_json = ? WHERE id = ?",
                        updates,
                    )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS graph_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO graph_metadata(key, value) VALUES ('graph_kind', 'custom') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
        return len(updates), transitions
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="SQLite database to normalize")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing them")
    args = parser.parse_args()

    if not args.database.is_file():
        parser.error(f"database does not exist: {args.database}")
    count, transitions = promote(args.database, dry_run=args.dry_run)
    action = "Would promote" if args.dry_run else "Promoted"
    print(f"{action} {count} entries in {args.database}")
    for (old_type, new_type), total in sorted(transitions.items()):
        print(f"  {old_type} -> {new_type}: {total}")
    if not args.dry_run:
        print("  graph kind: custom")


if __name__ == "__main__":
    main()
