"""Entry CLI commands."""

from __future__ import annotations

from .legacy import entry_add, entry_app, entry_delete, entry_list, entry_search, entry_show

__all__ = [
    "entry_app",
    "entry_add",
    "entry_delete",
    "entry_list",
    "entry_search",
    "entry_show",
]
