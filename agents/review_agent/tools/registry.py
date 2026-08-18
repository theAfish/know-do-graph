"""ReviewAgent tool schemas and dispatch tables."""

from __future__ import annotations

from agents.review_agent.tools_legacy import (
    MEMORY_REVIEW_TOOL_DISPATCH,
    MEMORY_REVIEW_TOOL_SCHEMAS,
    REVIEW_TOOL_DISPATCH,
    REVIEW_TOOL_SCHEMAS,
)
from agents.tooling import ToolRegistry

REVIEW_MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "mark_reviewed",
        "update_entry",
        "distill_entry",
        "merge_entries",
        "delete_entry",
        "create_edge",
        "delete_edge",
    }
)

MEMORY_REVIEW_MUTATING_TOOLS: frozenset[str] = frozenset({"distill_memory"})

REVIEW_TOOL_REGISTRY = ToolRegistry.from_legacy(
    REVIEW_TOOL_SCHEMAS,
    REVIEW_TOOL_DISPATCH,
    mutating_tools=REVIEW_MUTATING_TOOLS,
)

MEMORY_REVIEW_TOOL_REGISTRY = ToolRegistry.from_legacy(
    MEMORY_REVIEW_TOOL_SCHEMAS,
    MEMORY_REVIEW_TOOL_DISPATCH,
    mutating_tools=MEMORY_REVIEW_MUTATING_TOOLS,
)

__all__ = [
    "MEMORY_REVIEW_TOOL_DISPATCH",
    "MEMORY_REVIEW_TOOL_SCHEMAS",
    "MEMORY_REVIEW_TOOL_REGISTRY",
    "REVIEW_TOOL_DISPATCH",
    "REVIEW_TOOL_SCHEMAS",
    "REVIEW_TOOL_REGISTRY",
]
