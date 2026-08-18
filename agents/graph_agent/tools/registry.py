"""OpenAI tool schemas and dispatch table."""

from __future__ import annotations

from agents.graph_agent.tools_legacy import TOOL_DISPATCH, TOOL_SCHEMAS
from agents.tooling import ToolRegistry

MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "create_entry",
        "update_entry",
        "delete_entry",
        "create_edge",
        "delete_edge",
        "merge_entries",
        "resolve_wikilinks",
        "remove_dangling_edges",
        "create_script_entry",
        "add_script_to_entry",
        "attach_script_to_entry",
        "add_asset_to_entry",
        "build_material_interface_workflow",
        "create_material_entry",
        "submit_feedback",
        "create_heuristic",
        "create_constraint",
        "decompose_capability",
    }
)

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "get_entry",
        "search_entries",
        "list_entries",
        "get_neighbors",
        "graph_stats",
        "fetch_url",
        "web_search",
        "find_similar_nodes",
        "get_graph_overview",
        "list_nodes_by_type",
        "get_script",
        "list_scripts",
        "list_assets",
        "list_by_verification",
        "list_needs_generalization",
        "retrieve_plan",
        "retrieve_heuristics",
        "retrieve_constraints",
    }
)

GRAPH_TOOL_REGISTRY = ToolRegistry.from_legacy(
    TOOL_SCHEMAS,
    TOOL_DISPATCH,
    mutating_tools=MUTATING_TOOLS,
)

__all__ = [
    "GRAPH_TOOL_REGISTRY",
    "MUTATING_TOOLS",
    "READ_ONLY_TOOLS",
    "TOOL_DISPATCH",
    "TOOL_SCHEMAS",
]
