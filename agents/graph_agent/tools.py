"""Tool definitions for the GraphAgent.

Each function corresponds to an OpenAI function-calling tool.  All functions
receive the live ``KnowDoGraph`` instance via the module-level ``_graph``
variable which is set once by ``GraphAgent.__init__``.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


# ---------------------------------------------------------------------------
# Node / Entry tools
# ---------------------------------------------------------------------------


def create_entry(
    title: str,
    content: str = "",
    entry_type: str = "generic",
    tags: list[str] | None = None,
    source_provenance: str | None = None,
    graph: Any = None,
) -> dict:
    """Create a new knowledge entry (node) in the graph."""
    from core.schemas.entry import Entry, EntryMetadata, EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    entry = Entry(
        title=title,
        content=content,
        entry_type=EntryType(entry_type),
        tags=tags or [],
        metadata=EntryMetadata(source_provenance=source_provenance),
    )
    with SessionLocal() as db:
        saved = EntryRepository(db).create(entry)
    if graph is not None:
        graph.add_entry(saved)
    return {"id": saved.id, "slug": saved.slug, "title": saved.title}


def update_entry(
    entry_id: str,
    title: str | None = None,
    content: str | None = None,
    entry_type: str | None = None,
    tags: list[str] | None = None,
    graph: Any = None,
) -> dict:
    """Update fields on an existing entry."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.schemas.entry import EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.get_entry_by_id(entry_id) or engine.get_entry_by_slug(entry_id)
        if entry is None:
            return {"error": f"Entry '{entry_id}' not found."}
        if title is not None:
            entry.title = title
        if content is not None:
            entry.content = content
            entry.refresh_refs()
        if entry_type is not None:
            entry.entry_type = EntryType(entry_type)
        if tags is not None:
            entry.tags = tags
        saved = EntryRepository(db).update(entry)
    if graph is not None and saved:
        graph.add_entry(saved)  # upsert node attributes
    return {"id": saved.id, "slug": saved.slug, "title": saved.title} if saved else {"error": "Update failed."}


def delete_entry(entry_id: str, graph: Any = None) -> dict:
    """Delete an entry (node) and its associated edges."""
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    with SessionLocal() as db:
        deleted = EntryRepository(db).delete(entry_id)
    if deleted and graph is not None:
        graph.remove_entry(entry_id)
    return {"deleted": deleted, "entry_id": entry_id}


def search_entries(query: str, limit: int = 10, graph: Any = None) -> list[dict]:
    """Full-text search over entry titles and content."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        results = engine.search_entries(query=query, limit=limit)
    return [
        {"id": e.id, "slug": e.slug, "title": e.title, "type": e.entry_type.value, "tags": e.tags}
        for e in results
    ]


def get_entry(identifier: str, graph: Any = None) -> dict:
    """Retrieve a single entry by ID or slug."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.get_entry_by_id(identifier) or engine.get_entry_by_slug(identifier)
    if entry is None:
        return {"error": f"Entry '{identifier}' not found."}
    return {
        "id": entry.id,
        "slug": entry.slug,
        "title": entry.title,
        "type": entry.entry_type.value,
        "tags": entry.tags,
        "content": entry.content,
        "refs": entry.internal_refs,
        "source": entry.metadata.source_provenance,
        "status": entry.metadata.refinement_status.value,
    }


def list_entries(limit: int = 20, graph: Any = None) -> list[dict]:
    """List entries in the graph."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entries = engine.list_entries(limit=limit)
    return [
        {"id": e.id, "slug": e.slug, "title": e.title, "type": e.entry_type.value}
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Edge tools
# ---------------------------------------------------------------------------


def create_edge(
    source_id: str,
    target_id: str,
    relation: str = "related_to",
    weight: float = 1.0,
    graph: Any = None,
) -> dict:
    """Create a directed edge between two entries."""
    from core.schemas.edge import Edge, EdgeRelation
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository

    try:
        rel = EdgeRelation(relation)
    except ValueError:
        rel = EdgeRelation.wikilink

    edge = Edge(source_id=source_id, target_id=target_id, relation=rel, weight=weight)
    with SessionLocal() as db:
        saved = EdgeRepository(db).create(edge)
    if graph is not None:
        graph.add_edge(saved)
    return {"id": saved.id, "source_id": saved.source_id, "target_id": saved.target_id, "relation": saved.relation.value}


def delete_edge(edge_id: str, graph: Any = None) -> dict:
    """Delete an edge by its ID."""
    from core.storage.database import SessionLocal
    from core.storage.models import EdgeModel
    from core.storage.repository import EdgeRepository
    from core.schemas.edge import Edge

    with SessionLocal() as db:
        model = db.get(EdgeModel, edge_id)
        if model is None:
            return {"error": f"Edge '{edge_id}' not found."}
        src_id, tgt_id = model.source_id, model.target_id
        deleted = EdgeRepository(db).delete(edge_id)
        if deleted and graph is not None:
            graph.remove_edge(src_id, tgt_id)
    return {"deleted": deleted, "edge_id": edge_id}


def get_neighbors(entry_id: str, direction: str = "both", graph: Any = None) -> list[dict]:
    """Get neighboring entries connected by edges."""
    from core import app_state

    g = graph or app_state.graph
    neighbors = g.get_neighbors(entry_id, direction=direction)
    return neighbors


# ---------------------------------------------------------------------------
# Graph-level tools
# ---------------------------------------------------------------------------


def graph_stats(graph: Any = None) -> dict:
    """Return high-level statistics about the graph."""
    from core import app_state

    g = graph or app_state.graph
    return g.stats()


def resolve_wikilinks(graph: Any = None) -> dict:
    """Scan all entries for [[wikilinks]] and create edges for matches."""
    from core import app_state
    from agents.extraction_agent.agent import ExtractionAgent

    g = graph or app_state.graph
    agent = ExtractionAgent(g)
    count = agent.resolve_wikilinks()
    return {"edges_created": count}


def remove_dangling_edges(graph: Any = None) -> dict:
    """Remove edges pointing to deleted entries."""
    from core import app_state
    from agents.maintenance_agent.agent import MaintenanceAgent

    g = graph or app_state.graph
    agent = MaintenanceAgent(g)
    count = agent.remove_dangling_edges()
    return {"edges_removed": count}


# ---------------------------------------------------------------------------
# Web / URL tools
# ---------------------------------------------------------------------------


def fetch_url(url: str, timeout: int = 15) -> dict:
    """Fetch the text content of a URL and return it so the agent can read it.

    Uses ``httpx`` if available, falls back to ``urllib``.
    Returns a dict with keys ``url``, ``status_code``, and ``text``.
    """
    try:
        try:
            import httpx
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                resp = client.get(url, headers={"User-Agent": "KnowDoGraph/1.0"})
                return {"url": url, "status_code": resp.status_code, "text": resp.text[:20000]}
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "KnowDoGraph/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return {"url": url, "status_code": resp.status, "text": resp.read(20000).decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo and return result snippets."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# OpenAI tool schema definitions
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_entry",
            "description": "Create a new knowledge entry (node) in the graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Entry title"},
                    "content": {"type": "string", "description": "Entry body (wiki text, markdown)"},
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "procedure", "workflow", "tool", "repository",
                                 "environment", "dependency", "data", "analytical", "memory", "generic"],
                        "description": "Semantic type of this entry",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tags"},
                    "source_provenance": {"type": "string", "description": "URL or path this entry was sourced from"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_entry",
            "description": "Update fields on an existing entry by its ID or slug.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Entry ID or slug"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "procedure", "workflow", "tool", "repository",
                                 "environment", "dependency", "data", "analytical", "memory", "generic"],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_entry",
            "description": "Delete an entry (node) and all its edges by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Entry ID"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entry",
            "description": "Retrieve full details of a single entry by ID or slug.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Entry ID or slug"},
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entries",
            "description": "Full-text search for entries matching a query string.",
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
            "name": "list_entries",
            "description": "List entries in the graph (returns id, slug, title, type).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": "Create a directed edge (relationship) between two entries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "Source entry ID"},
                    "target_id": {"type": "string", "description": "Target entry ID"},
                    "relation": {
                        "type": "string",
                        "enum": ["dependency", "compatible_with", "alternative_to", "related_workflow",
                                 "generated_from", "memory_of", "refinement_of", "derived_from",
                                 "warning_about", "cited_by", "wikilink", "prerequisite", "replacement",
                                 "execution_pathway", "transformation", "provenance", "compatibility"],
                        "description": "Semantic relation type",
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
            "description": "Delete an edge by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "edge_id": {"type": "string"},
                },
                "required": ["edge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_neighbors",
            "description": "Get entries directly connected to a given entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["out", "in", "both"],
                        "default": "both",
                    },
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_stats",
            "description": "Return node count, edge count, and DAG status of the graph.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_wikilinks",
            "description": "Scan all entry content for [[wikilinks]] and create edges for resolved matches.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_dangling_edges",
            "description": "Remove edges whose source or target entry no longer exists.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and return the text content of any URL (web page, API endpoint, documentation site, etc.). Use this when the user provides a specific URL or when you need to read a page in full rather than just search snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "timeout": {"type": "integer", "default": 15, "description": "Request timeout in seconds"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via DuckDuckGo and return titles, URLs and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
]

# Map function name → callable
TOOL_DISPATCH: dict[str, Any] = {
    "create_entry": create_entry,
    "update_entry": update_entry,
    "delete_entry": delete_entry,
    "get_entry": get_entry,
    "search_entries": search_entries,
    "list_entries": list_entries,
    "create_edge": create_edge,
    "delete_edge": delete_edge,
    "get_neighbors": get_neighbors,
    "graph_stats": graph_stats,
    "resolve_wikilinks": resolve_wikilinks,
    "remove_dangling_edges": remove_dangling_edges,
    "fetch_url": fetch_url,
    "web_search": web_search,
}
