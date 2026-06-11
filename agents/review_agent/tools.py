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


def _memory_metadata(entry: Any) -> dict:
    data = entry.metadata.custom.get("memory", {})
    return data if isinstance(data, dict) else {}


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
# Memory distillation
# ---------------------------------------------------------------------------


def sample_memory_nodes(
    batch_size: int = 5,
    session_id: str | None = None,
    graph: Any = None,
) -> list[dict]:
    """Return unpromoted memory nodes, optionally restricted to one session."""
    from core.schemas.entry import EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    with SessionLocal() as db:
        entries = EntryRepository(db).get_all()

    candidates = []
    for entry in entries:
        if entry.entry_type != EntryType.memory:
            continue
        memory = _memory_metadata(entry)
        if memory.get("promoted", False) or memory.get("distillation_status") == "skipped":
            continue
        if session_id is not None and memory.get("session_id") != session_id:
            continue
        candidates.append(entry)

    candidates.sort(key=lambda entry: entry.metadata.timestamp)
    return [
        {
            "id": entry.id,
            "session_id": _memory_metadata(entry).get("session_id", "default"),
            "title": entry.title,
            "content": entry.content,
            "tags": entry.tags,
            "success": _memory_metadata(entry).get("success"),
            "source_entry_ids": _memory_metadata(entry).get("source_entry_ids", []),
            "created_at": entry.metadata.timestamp.isoformat(),
        }
        for entry in candidates[: max(0, batch_size)]
    ]


def distill_memory(
    memory_id: str,
    classification: str,
    entry_type: str | None = None,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    target_id: str | None = None,
    reason: str = "",
    graph: Any = None,
) -> dict:
    """Apply one reviewed memory decision.

    L1/L2 create unverified capability/procedure nodes. L3/L4 create
    heuristic/constraint nodes and require an existing L1/L2 target. Noise is
    deleted. ``skip`` retains the memory for a later review.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.schemas.edge import Edge, EdgeRelation
    from core.schemas.entry import (
        Entry,
        EntryMetadata,
        EntryType,
        RefinementStatus,
        SkillLevel,
        VerificationStatus,
        implied_level,
    )
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository, EntryRepository

    normalized = classification.upper()
    if normalized not in {"L1", "L2", "L3", "L4", "NOISE", "SKIP"}:
        return {"error": f"Unsupported classification: {classification}"}

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        memory = engine.get_entry_by_id(memory_id)
        if memory is None or memory.entry_type != EntryType.memory:
            return {"error": f"Memory '{memory_id}' not found."}

        memory_data = _memory_metadata(memory)
        if memory_data.get("promoted", False):
            return {"error": f"Memory '{memory_id}' was already distilled."}

        if normalized == "SKIP":
            memory_data["distillation_status"] = "skipped"
            memory_data["distillation_reason"] = reason
            memory.metadata.custom["memory"] = memory_data
            memory.metadata.review_count += 1
            memory.metadata.last_reviewed_at = datetime.now(timezone.utc)
            updated_memory = EntryRepository(db).update(memory)
            if updated_memory is not None:
                g.add_entry(updated_memory)
            return {
                "memory_id": memory_id,
                "classification": "skip",
                "action": "skipped",
                "reason": reason,
            }

        entry_repo = EntryRepository(db)
        edge_repo = EdgeRepository(db)

        if normalized == "NOISE":
            for edge in EdgeRepository(db).get_all():
                if edge.source_id == memory_id or edge.target_id == memory_id:
                    edge_repo.delete(edge.id)
            entry_repo.delete(memory_id)
            g.remove_entry(memory_id)
            return {
                "memory_id": memory_id,
                "classification": "noise",
                "action": "deleted",
                "reason": reason,
            }

        level = SkillLevel(normalized)
        default_type_for_level = {
            SkillLevel.L1: EntryType.capability,
            SkillLevel.L2: EntryType.procedure,
            SkillLevel.L3: EntryType.heuristic,
            SkillLevel.L4: EntryType.constraint,
        }
        allowed_types = {
            SkillLevel.L1: {EntryType.capability, EntryType.workflow},
            SkillLevel.L2: {EntryType.procedure},
            SkillLevel.L3: {EntryType.heuristic},
            SkillLevel.L4: {EntryType.constraint},
        }
        try:
            distilled_type = (
                EntryType(entry_type)
                if entry_type is not None
                else default_type_for_level[level]
            )
        except ValueError:
            return {"error": f"Unsupported entry_type: {entry_type}"}
        if distilled_type not in allowed_types[level]:
            allowed = ", ".join(sorted(item.value for item in allowed_types[level]))
            return {"error": f"{normalized} entry_type must be one of: {allowed}."}
        target = None
        relation = None
        if level in {SkillLevel.L3, SkillLevel.L4}:
            if not target_id:
                return {"error": f"{normalized} memory requires target_id."}
            target = engine.resolve_identifier(target_id)
            if target is None:
                return {"error": f"Target '{target_id}' not found."}
            if implied_level(target.entry_type, target.metadata.skill_level) not in {
                SkillLevel.L1,
                SkillLevel.L2,
            }:
                return {"error": "L3/L4 memory must target an existing L1 or L2 node."}
            relation = (
                EdgeRelation.heuristic_for
                if level == SkillLevel.L3
                else EdgeRelation.constraint_on
            )

        distilled = Entry(
            title=(title or memory.title).strip(),
            content=(content or memory.content).strip(),
            entry_type=distilled_type,
            tags=list(dict.fromkeys((tags or []) + memory.tags)),
            metadata=EntryMetadata(
                source_provenance=f"memory:{memory_id}",
                extraction_method="review_agent_memory_distillation",
                refinement_status=RefinementStatus.raw,
                verification_status=VerificationStatus.unverified,
                skill_level=level,
                applicability={"distillation_reason": reason} if reason else {},
                custom={
                    "distilled_from_memory": {
                        "memory_id": memory_id,
                        "session_id": memory_data.get("session_id", "default"),
                    }
                },
            ),
        )
        saved = entry_repo.create(distilled)
        g.add_entry(saved)

        created_edges = []
        source_edge = edge_repo.create(
            Edge(
                source_id=memory.id,
                target_id=saved.id,
                relation=EdgeRelation.refinement_of,
                metadata={"source": "review_agent_memory_distillation"},
            )
        )
        g.add_edge(source_edge)
        created_edges.append(source_edge.id)

        if target is not None and relation is not None:
            target_edge = edge_repo.create(
                Edge(
                    source_id=saved.id,
                    target_id=target.id,
                    relation=relation,
                    metadata={"source": "review_agent_memory_distillation"},
                )
            )
            g.add_edge(target_edge)
            created_edges.append(target_edge.id)

            if level == SkillLevel.L4:
                target.metadata.failure_modes = list(
                    dict.fromkeys(target.metadata.failure_modes + [saved.slug])
                )
                updated_target = entry_repo.update(target)
                if updated_target is not None:
                    g.add_entry(updated_target)

        memory_data.update(
            {
                "promoted": True,
                "promotion_target_id": saved.id,
                "distilled_level": normalized,
                "distillation_status": "completed",
                "distillation_reason": reason,
            }
        )
        memory.metadata.custom["memory"] = memory_data
        memory.metadata.review_count += 1
        memory.metadata.last_reviewed_at = datetime.now(timezone.utc)
        updated_memory = entry_repo.update(memory)
        if updated_memory is not None:
            g.add_entry(updated_memory)

    return {
        "memory_id": memory_id,
        "classification": normalized,
        "action": "promoted" if level in {SkillLevel.L1, SkillLevel.L2} else "linked",
        "entry": {
            "id": saved.id,
            "slug": saved.slug,
            "title": saved.title,
            "type": saved.entry_type.value,
            "skill_level": normalized,
            "verification_status": saved.metadata.verification_status.value,
        },
        "target_id": target.id if target is not None else None,
        "edge_ids": created_edges,
        "reason": reason,
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


def search_entries(query: str, limit: int = 10, mode: str = "hybrid", graph: Any = None) -> list[dict]:
    """Hybrid semantic + keyword search — use to find duplicate or related candidates."""
    from agents.graph_agent.tools import search_entries as _search_entries

    return _search_entries(query=query, limit=limit, mode=mode, graph=graph)


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
            "description": (
                "Search for nodes using hybrid semantic + keyword retrieval. "
                "The default 'hybrid' mode combines embedding-based vector similarity with "
                "keyword scoring (RRF fusion). Use 'semantic' to find conceptually related nodes "
                "even when wording differs — ideal for surfacing near-duplicate candidates. "
                "Use 'keyword' for exact title or acronym lookups. "
                "If a search misses, retry with a different mode or a broader/rephrased query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "mode": {
                        "type": "string",
                        "enum": ["hybrid", "semantic", "keyword"],
                        "default": "hybrid",
                        "description": (
                            "hybrid: keyword + embedding ANN fused (default). "
                            "semantic: embedding-only, best for conceptual/paraphrase matching. "
                            "keyword: exact text match, best for known titles or acronyms."
                        ),
                    },
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
                                 "generated_from", "memory_of", "related_memory", "refinement_of", "derived_from",
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

MEMORY_REVIEW_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "sample_memory_nodes",
            "description": (
                "Return only unpromoted memory nodes, optionally restricted to a session. "
                "Use exactly once at the start of a memory review."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "batch_size": {"type": "integer", "default": 5},
                    "session_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entries",
            "description": (
                "Search existing graph nodes. Use this before linking L3/L4 memory so it "
                "targets the best existing L1 capability/workflow or L2 procedure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "mode": {
                        "type": "string",
                        "enum": ["hybrid", "semantic", "keyword"],
                        "default": "hybrid",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "distill_memory",
            "description": (
                "Record the final decision for one memory. L1/L2 create unverified nodes; "
                "L3/L4 create and link a heuristic/constraint to target_id; noise is deleted; "
                "skip leaves uncertain memory untouched."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "classification": {
                        "type": "string",
                        "enum": ["L1", "L2", "L3", "L4", "noise", "skip"],
                    },
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "workflow", "procedure", "heuristic", "constraint"],
                        "description": (
                            "Optional concrete node type. L1 allows capability/workflow; "
                            "other levels have one matching type."
                        ),
                    },
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "target_id": {
                        "type": "string",
                        "description": "Required for L3/L4; existing L1/L2 node id or slug.",
                    },
                    "reason": {"type": "string"},
                },
                "required": ["memory_id", "classification", "reason"],
            },
        },
    },
]

MEMORY_REVIEW_TOOL_DISPATCH: dict[str, Any] = {
    "sample_memory_nodes": sample_memory_nodes,
    "search_entries": search_entries,
    "distill_memory": distill_memory,
}
