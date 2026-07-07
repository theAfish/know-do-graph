"""Entry CRUD and search tools."""

from __future__ import annotations

from agents.graph_agent.tools_legacy import (
    create_entry,
    delete_entry,
    find_similar_nodes,
    get_entry,
    list_entries,
    list_needs_generalization,
    list_nodes_by_type,
    search_entries,
    update_entry,
)

__all__ = [
    "create_entry",
    "delete_entry",
    "find_similar_nodes",
    "get_entry",
    "list_entries",
    "list_needs_generalization",
    "list_nodes_by_type",
    "search_entries",
    "update_entry",
]
