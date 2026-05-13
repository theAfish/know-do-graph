"""Tools for the ReviewAgent.

The review agent uses these tools to examine the graph incrementally —
it never receives the full graph dump at once.  Instead it:
  - picks under-reviewed nodes (weighted toward low review_count)
  - inspects a node's full details and its local neighbourhood
  - updates review/modify counters after each inspection
  - proposes and applies targeted fixes (title, tags, aliases)
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Sampling / overview
# ---------------------------------------------------------------------------


def sample_nodes_for_review(batch_size: int = 5, graph: Any = None) -> list[dict]:
    """Return a weighted-random sample of nodes, preferring those with low review_count.

    Nodes with fewer reviews are much more likely to be selected so the agent
    makes forward progress on unchecked parts of the graph.

    Returns id, slug, title, type, tags, aliases, review_count, modify_count.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        all_entries = engine.list_entries(limit=5000)

    if not all_entries:
        return []

    # Weight = 1 / (review_count + 1)  → unseen nodes are most likely
    weights = [1.0 / (e.metadata.review_count + 1) for e in all_entries]
    k = min(batch_size, len(all_entries))
    selected = random.choices(all_entries, weights=weights, k=k)
    # Deduplicate while preserving order
    seen_ids: set[str] = set()
    unique: list = []
    for e in selected:
        if e.id not in seen_ids:
            seen_ids.add(e.id)
            unique.append(e)

    return [
        {
            "id": e.id,
            "slug": e.slug,
            "title": e.title,
            "type": e.entry_type.value,
            "tags": e.tags,
            "aliases": e.aliases,
            "review_count": e.metadata.review_count,
            "modify_count": e.metadata.modify_count,
        }
        for e in unique
    ]


def get_graph_summary(graph: Any = None) -> dict:
    """Return aggregate statistics useful for high-level review.

    Includes node/edge counts, type distribution, and review coverage
    (how many nodes have been reviewed at least once).
    """
    from collections import Counter

    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    stats = g.stats()

    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        all_entries = engine.list_entries(limit=5000)

    type_dist = dict(Counter(e.entry_type.value for e in all_entries))
    reviewed = sum(1 for e in all_entries if e.metadata.review_count > 0)
    total = len(all_entries)

    return {
        "stats": stats,
        "type_distribution": type_dist,
        "total_nodes": total,
        "reviewed_nodes": reviewed,
        "unreviewed_nodes": total - reviewed,
        "review_coverage_pct": round(100 * reviewed / total, 1) if total else 0,
    }


# ---------------------------------------------------------------------------
# Node inspection
# ---------------------------------------------------------------------------


def inspect_node(identifier: str, graph: Any = None) -> dict:
    """Retrieve full details of a node including review metadata and local edges.

    Returns title, type, tags, aliases, content (first 800 chars), refs,
    review_count, modify_count, and a list of neighbouring node titles.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.resolve_identifier(identifier)
        if entry is None:
            return {"error": f"Entry '{identifier}' not found."}

        neighbors_raw = g.get_neighbors(entry.id, direction="both")
        neighbor_details = []
        for nbr in neighbors_raw:
            nbr_entry = engine.get_entry_by_id(nbr["id"])
            neighbor_details.append(
                {
                    "id": nbr["id"],
                    "title": nbr_entry.title if nbr_entry else "?",
                    "relation": nbr.get("relation"),
                    "direction": nbr.get("direction"),
                }
            )

    return {
        "id": entry.id,
        "slug": entry.slug,
        "title": entry.title,
        "type": entry.entry_type.value,
        "tags": entry.tags,
        "aliases": entry.aliases,
        "content_preview": entry.content[:800],
        "refs": entry.internal_refs,
        "source": entry.metadata.source_provenance,
        "status": entry.metadata.refinement_status.value,
        "review_count": entry.metadata.review_count,
        "modify_count": entry.metadata.modify_count,
        "last_reviewed_at": entry.metadata.last_reviewed_at.isoformat() if entry.metadata.last_reviewed_at else None,
        "neighbors": neighbor_details,
    }


# ---------------------------------------------------------------------------
# Review tracking
# ---------------------------------------------------------------------------


def mark_reviewed(entry_id: str, was_modified: bool = False, graph: Any = None) -> dict:
    """Increment review_count (and optionally modify_count) on an entry.

    Call this after inspecting a node, regardless of whether changes were made.
    Pass was_modified=True if you also edited the node in this review pass.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.get_entry_by_id(entry_id)
        if entry is None:
            return {"error": f"Entry '{entry_id}' not found."}

        entry.metadata.review_count += 1
        entry.metadata.last_reviewed_at = datetime.now(timezone.utc)
        if was_modified:
            entry.metadata.modify_count += 1

        EntryRepository(db).update(entry)

    return {
        "entry_id": entry_id,
        "review_count": entry.metadata.review_count,
        "modify_count": entry.metadata.modify_count,
    }


# ---------------------------------------------------------------------------
# Cleaning helpers (re-exported from graph_agent.tools for convenience)
# ---------------------------------------------------------------------------


def update_entry(
    entry_id: str,
    title: str | None = None,
    content: str | None = None,
    entry_type: str | None = None,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    graph: Any = None,
) -> dict:
    """Update fields on an existing entry and bump modify_count."""
    from agents.graph_agent.tools import update_entry as _update_entry

    result = _update_entry(
        entry_id=entry_id,
        title=title,
        content=content,
        entry_type=entry_type,
        tags=tags,
        aliases=aliases,
        graph=graph,
    )
    if "error" not in result:
        mark_reviewed(result["id"], was_modified=True, graph=graph)
    return result


def merge_entries(
    primary_id: str,
    duplicate_id: str,
    merge_aliases: bool = True,
    merge_tags: bool = True,
    graph: Any = None,
) -> dict:
    """Merge duplicate into primary, then mark primary as modified."""
    from agents.graph_agent.tools import merge_entries as _merge_entries

    result = _merge_entries(
        primary_id=primary_id,
        duplicate_id=duplicate_id,
        merge_aliases=merge_aliases,
        merge_tags=merge_tags,
        graph=graph,
    )
    if result.get("merged"):
        mark_reviewed(result["primary_id"], was_modified=True, graph=graph)
    return result


def search_entries(query: str, limit: int = 10, graph: Any = None) -> list[dict]:
    """Full-text search — use this to find candidates for merging or cross-linking."""
    from agents.graph_agent.tools import search_entries as _search_entries

    return _search_entries(query=query, limit=limit, graph=graph)


def create_edge(
    source_id: str,
    target_id: str,
    relation: str = "related_to",
    weight: float = 1.0,
    graph: Any = None,
) -> dict:
    """Create an edge between two entries."""
    from agents.graph_agent.tools import create_edge as _create_edge

    return _create_edge(source_id=source_id, target_id=target_id, relation=relation, weight=weight, graph=graph)


def delete_edge(edge_id: str, graph: Any = None) -> dict:
    """Delete an edge by ID."""
    from agents.graph_agent.tools import delete_edge as _delete_edge

    return _delete_edge(edge_id=edge_id, graph=graph)


# ---------------------------------------------------------------------------
# OpenAI tool schemas
# ---------------------------------------------------------------------------

REVIEW_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_graph_summary",
            "description": (
                "Get high-level graph statistics including node count, type distribution, "
                "and review coverage. Use at the start of each review session."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sample_nodes_for_review",
            "description": (
                "Return a weighted-random batch of nodes to review. "
                "Nodes with fewer prior reviews are selected more often. "
                "Use this to pick the next set of nodes to inspect."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "batch_size": {"type": "integer", "default": 5, "description": "Number of nodes to sample"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_node",
            "description": (
                "Get full details of a node: title, type, tags, aliases, content preview, "
                "review history, and neighbouring nodes with relation types. "
                "Always inspect a node before deciding to modify it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Node ID or slug"},
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_reviewed",
            "description": (
                "Record that you have reviewed a node. "
                "Must be called for every node you inspect, even if no changes were made. "
                "Set was_modified=True if you also edited the node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "was_modified": {"type": "boolean", "default": False},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_entry",
            "description": (
                "Update title, tags, aliases, content, or type of a node. "
                "Use to: fix titles containing parenthetical acronyms (move acronym to aliases), "
                "normalise tags to lowercase-hyphenated, remove redundant prefixes from titles, "
                "or correct the entry_type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Node ID or slug"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "procedure", "workflow", "tool", "repository",
                                 "environment", "dependency", "data", "analytical", "memory", "generic"],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entries",
            "description": "Search for nodes by keyword — useful to find duplicate candidates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_entries",
            "description": (
                "Merge a duplicate node into a primary node. "
                "Re-targets edges, merges aliases/tags, deletes the duplicate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "primary_id": {"type": "string"},
                    "duplicate_id": {"type": "string"},
                    "merge_aliases": {"type": "boolean", "default": True},
                    "merge_tags": {"type": "boolean", "default": True},
                },
                "required": ["primary_id", "duplicate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": "Add a typed edge between two nodes when a relationship is missing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": ["dependency", "compatible_with", "alternative_to", "related_workflow",
                                 "generated_from", "memory_of", "refinement_of", "derived_from",
                                 "warning_about", "cited_by", "wikilink", "prerequisite", "replacement",
                                 "execution_pathway", "transformation", "provenance", "compatibility"],
                    },
                    "weight": {"type": "number", "default": 1.0},
                },
                "required": ["source_id", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_edge",
            "description": "Delete a redundant or incorrect edge by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "edge_id": {"type": "string"},
                },
                "required": ["edge_id"],
            },
        },
    },
]

REVIEW_TOOL_DISPATCH: dict[str, Any] = {
    "get_graph_summary": get_graph_summary,
    "sample_nodes_for_review": sample_nodes_for_review,
    "inspect_node": inspect_node,
    "mark_reviewed": mark_reviewed,
    "update_entry": update_entry,
    "search_entries": search_entries,
    "merge_entries": merge_entries,
    "create_edge": create_edge,
    "delete_edge": delete_edge,
}
