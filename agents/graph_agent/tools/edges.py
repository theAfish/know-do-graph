"""Edge and graph maintenance tools."""

from __future__ import annotations

from agents.graph_agent.tools_legacy import (
    create_edge,
    delete_edge,
    get_graph_overview,
    get_neighbors,
    graph_stats,
    remove_dangling_edges,
    resolve_wikilinks,
)

__all__ = [
    "create_edge",
    "delete_edge",
    "get_graph_overview",
    "get_neighbors",
    "graph_stats",
    "remove_dangling_edges",
    "resolve_wikilinks",
]
