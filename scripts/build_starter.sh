#!/usr/bin/env bash
# Checkpoint the development DB, build the package, and verify the starter DB.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$ROOT_DIR/data/know_do_graph.db"
STARTER_PATH="$ROOT_DIR/assets/starter.db"
DIST_DIR="$ROOT_DIR/dist"

if [[ ! -f "$DB_PATH" ]]; then
    echo "Starter source database not found: $DB_PATH" >&2
    exit 1
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "Python 3 is required." >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it from https://docs.astral.sh/uv/" >&2
    exit 1
fi

echo "==> Checkpointing data/know_do_graph.db"
"$PYTHON" -c '
import sqlite3
import sys

db_path = sys.argv[1]
with sqlite3.connect(db_path, timeout=5) as connection:
    busy, log_pages, checkpointed_pages = connection.execute(
        "PRAGMA wal_checkpoint(TRUNCATE)"
    ).fetchone()

if busy:
    raise SystemExit(
        f"Database is busy; stop the API server and try again "
        f"(log pages={log_pages}, checkpointed={checkpointed_pages})."
    )
' "$DB_PATH"

echo "==> Updating assets/starter.db"
mkdir -p "$(dirname "$STARTER_PATH")"
cp "$DB_PATH" "$STARTER_PATH"

echo "==> Building source distribution and wheel"
mkdir -p "$DIST_DIR"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/know-do-graph-uv-cache}"
(
    cd "$ROOT_DIR"
    uv build --out-dir "$DIST_DIR"
)

WHEEL="$(
    find "$DIST_DIR" -maxdepth 1 -type f -name 'know_do_graph-*.whl' \
        -printf '%T@ %p\n' |
        sort -nr |
        head -n 1 |
        cut -d' ' -f2-
)"

if [[ -z "$WHEEL" ]]; then
    echo "No wheel was produced in $DIST_DIR" >&2
    exit 1
fi

echo "==> Verifying packaged starter database"
"$PYTHON" -c '
import sys
import zipfile

wheel_path = sys.argv[1]
resource = "core/resources/starter.db"
with zipfile.ZipFile(wheel_path) as wheel:
    try:
        packaged_size = wheel.getinfo(resource).file_size
    except KeyError:
        raise SystemExit(f"{resource} is missing from {wheel_path}")

source_size = int(sys.argv[2])
if packaged_size != source_size:
    raise SystemExit(
        f"Starter size mismatch: source={source_size}, packaged={packaged_size}"
    )

print(f"Verified {resource} ({packaged_size} bytes)")
' "$WHEEL" "$(stat -c %s "$STARTER_PATH")"

echo ""
echo "Starter package is ready:"
echo "  $WHEEL"
