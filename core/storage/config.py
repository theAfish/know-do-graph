from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatabaseConfig:
    """Resolved database locations for a Know-Do Graph runtime."""

    path: Path

    @classmethod
    def from_env(cls, *, cwd: Path | None = None) -> "DatabaseConfig":
        configured_path = os.environ.get("KDG_DB_PATH")
        if configured_path:
            path = Path(configured_path).expanduser()
        else:
            path = (cwd or Path.cwd()) / "data" / "know_do_graph.db"
        return cls(path=path.resolve())
