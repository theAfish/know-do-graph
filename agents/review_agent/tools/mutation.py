"""Review mutation tools."""

from __future__ import annotations

from agents.review_agent.tools_legacy import (
    create_edge,
    delete_edge,
    delete_entry,
    mark_reviewed,
    update_entry,
)

__all__ = ["create_edge", "delete_edge", "delete_entry", "mark_reviewed", "update_entry"]
