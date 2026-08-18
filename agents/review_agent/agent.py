"""ReviewAgent — LLM-driven agent that incrementally audits and cleans the graph.

The agent never receives the full graph at once. Instead it:
1. Checks overall graph health via ``get_graph_summary``.
2. Samples a small batch of under-reviewed nodes via ``sample_nodes_for_review``.
3. Inspects each node and its local neighbourhood with ``inspect_node``.
4. Applies targeted fixes: normalise titles, move acronyms to aliases,
   fix tags, merge near-duplicates, add missing edges.
5. Marks each reviewed node with ``mark_reviewed`` so the next session
   continues where this one left off.

Configuration:
    OPENAI_API_KEY     — required
    OPENAI_API_BASE    — optional base URL override
    REVIEW_AGENT_MODEL — model name (defaults to GRAPH_AGENT_MODEL or "qwen-plus")
"""

from __future__ import annotations

import inspect
import json
import os
from copy import deepcopy
from typing import Any, Callable

from openai import OpenAI

from agents.review_agent.tools import (
    MEMORY_REVIEW_TOOL_SCHEMAS,
    REVIEW_TOOL_SCHEMAS,
)
from agents.review_agent.tools.registry import (
    MEMORY_REVIEW_TOOL_REGISTRY,
    REVIEW_TOOL_REGISTRY,
)
from agents.tooling import ToolRegistry, normalize_tool_result
from core.graph.graph import KnowDoGraph
from know_do_graph.review import ReviewPolicy

_DEFAULT_MODEL = "qwen-plus"

_SYSTEM_PROMPT = """You are a knowledge-graph quality reviewer for the Know-Do Graph system.

Your role is to incrementally audit existing nodes (entries) for quality issues and
fix them. You work in focused batches — you do NOT need to review the entire graph
in one session.

## Quality criteria
1. **Title hygiene**
   - Titles must be concise (3–7 words).
   - Remove parenthetical acronyms/aliases from titles — put them in `aliases` instead.
     Example: "Density Functional Theory (DFT)" → title "Density Functional Theory",
     aliases ["DFT", "ab initio DFT"].
   - Remove redundant tool-name prefixes from capability titles.
     Example: "RDKit Molecular Fingerprint Generation" → "Molecular Fingerprint Generation"
     (keep "rdkit" as a tag and ensure a `dependency` edge to the RDKit tool node).

2. **Tag normalisation**
   - All tags must be lowercase and hyphenated (e.g. "machine-learning", "rdkit").
   - Remove capitalised duplicates (e.g. "RDKit" when "rdkit" already present).
   - Tags should be domain-specific and meaningful — remove generic filler tags.

3. **Duplicate / alias detection**
   - If two nodes represent the same concept, merge them with `merge_entries`.
   - If one node is a more specific variant of another, add a `derived_from` or
     `refinement_of` edge rather than merging.

4. **Edge completeness**
   - If a node uses a tool or library, ensure a `dependency` edge exists to that
     tool's node.
   - If a node is a specific application of a broader capability, add a
     `derived_from` or `prerequisite` edge.

5. **Verification limits**
   - You may only set `verification_status` to `unverified` or `self_tested`.
   - `peer_reviewed` and `community_tested` are reserved for explicit human edits.

## Your workflow each session
1. Call `get_graph_summary` to see overall health and review coverage.
2. Call `sample_nodes_for_review` to get a batch (default 5).
3. For each sampled node: call `inspect_node`, assess quality, apply fixes if needed.
4. For each unchanged node, call `mark_reviewed`. Update and merge tools record
   the review automatically, so do not call `mark_reviewed` after using them.
5. Summarise what you found and fixed.

Keep changes conservative — prefer targeted fixes over large rewrites.
"""

_MEMORY_REVIEW_PROMPT = """You distil raw operational memory into the Know-Do Graph hierarchy.

Classify every supplied memory exactly once:
- L1: a reusable high-level capability or workflow.
- L2: an executable procedure or task decomposition.
- L3: conditional empirical guidance or a rule of thumb.
- L4: a failure mode, limitation, warning, or hard constraint.
- noise: chatter, repetition, transient status, or content with no reusable value.
- skip: genuinely ambiguous content that needs human context.

For L1/L2, call `distill_memory` with a concise reusable title, cleaned content,
and the concrete entry_type (L1 capability/workflow; L2 procedure).
For L3/L4, first call `search_entries` to find the best existing L1/L2 parent, then
call `distill_memory` with that target. Never invent a target. If no defensible
target exists, use `skip`.
For noise, call `distill_memory` with classification `noise`.

Do not turn a one-off task, result, material, filename, or parameter set into an
overly specific capability. Preserve useful conditions and evidence in L3/L4
content. After all supplied memories have one decision, provide a brief summary.
"""


class ReviewAgent:
    """LLM-powered agent that reviews and cleans the Know-Do Graph incrementally.

    Parameters
    ----------
    graph:
        The shared ``KnowDoGraph`` instance.
    model:
        Model identifier forwarded to the OpenAI client.
    batch_size:
        Number of nodes to review per ``run_review`` call.
    """

    def __init__(
        self,
        graph: KnowDoGraph,
        model: str | None = None,
        batch_size: int = 5,
        on_step: Callable[[str, dict], None] | None = None,
        on_status: Callable[[dict], None] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        policy: ReviewPolicy | None = None,
        strategy: str = "auto",
    ) -> None:
        self._graph = graph
        self._batch_size = batch_size
        self._on_step = on_step
        self._on_status = on_status
        self._policy = policy or ReviewPolicy()
        self._strategy = strategy
        self._model = model or os.environ.get(
            "REVIEW_AGENT_MODEL",
            os.environ.get("GRAPH_AGENT_MODEL", _DEFAULT_MODEL),
        )
        self._client = OpenAI(
            api_key=api_key or os.environ["OPENAI_API_KEY"],
            base_url=base_url if base_url is not None else os.environ.get("OPENAI_API_BASE"),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_review(self, instructions: str = "") -> str:
        """Run one review session and return a summary of findings and fixes."""
        user_msg = f"Please review a batch of {self._batch_size} nodes. " + (
            instructions if instructions else "Apply all quality criteria from your instructions."
        )
        history: list[dict] = [
            {"role": "system", "content": self._policy_prompt()},
            {"role": "user", "content": user_msg},
        ]
        return self._run_loop(history, tools=self._review_tools(), dispatch=REVIEW_TOOL_REGISTRY)

    def review_nodes(self, instructions: str = "") -> dict:
        """Run a policy-controlled review and return structured progress/results."""
        candidates = self._dispatch(
            "sample_nodes_for_review",
            json.dumps({"batch_size": self._batch_size, "strategy": self._strategy}),
        )
        if isinstance(candidates, dict) and candidates.get("error"):
            result = {
                "status": "failed",
                "strategy": self._strategy,
                "progress": {"completed": 0, "total": 0, "percent": 0},
                "candidates": [],
                "results": [],
                "errors": [candidates["error"]],
                "summary": "",
            }
            self._emit_review_status(result)
            return result

        selected = candidates if isinstance(candidates, list) else []
        result = {
            "status": "running",
            "strategy": self._strategy,
            "progress": {"completed": 0, "total": len(selected), "percent": 0},
            "candidates": selected,
            "results": [],
            "errors": [],
            "summary": "",
        }
        self._emit_review_status(result)
        if not selected:
            result["status"] = "completed"
            result["summary"] = "No eligible nodes found."
            self._emit_review_status(result)
            return result

        user_msg = (
            f"Review exactly these {len(selected)} candidates selected with strategy "
            f"'{self._strategy}':\n{json.dumps(selected, default=str)}"
        )
        if instructions:
            user_msg += f"\nAdditional instructions: {instructions}"
        history = [
            {"role": "system", "content": self._policy_prompt()},
            {"role": "user", "content": user_msg},
        ]
        candidate_ids = {item["id"] for item in selected}
        completed_ids: set[str] = set()

        def observe(name: str, outcome: Any) -> None:
            record = {"action": name, "result": outcome}
            result["results"].append(record)
            if isinstance(outcome, dict) and outcome.get("error"):
                result["errors"].append(outcome["error"])
            ids = set()
            if isinstance(outcome, dict):
                ids.update(
                    value
                    for key, value in outcome.items()
                    if key in {"id", "entry_id", "primary_id", "removed_duplicate_id"}
                    and isinstance(value, str)
                )
            completed_ids.update(ids & candidate_ids)
            completed = len(completed_ids)
            total = len(selected)
            result["progress"] = {
                "completed": completed,
                "total": total,
                "percent": round(100 * completed / total),
            }
            self._emit_review_status(result)

        tools = [
            schema
            for schema in self._review_tools()
            if schema["function"]["name"] != "sample_nodes_for_review"
        ]
        result["summary"] = self._run_loop(
            history,
            tools=tools,
            observe_result=observe,
        )
        result["status"] = "completed" if not result["errors"] else "completed_with_errors"
        self._emit_review_status(result)
        return result

    def chat(self, user_message: str) -> str:
        """Single-turn interactive review conversation (stateless)."""
        history: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        return self._run_loop(history)

    def run_memory_review(
        self,
        *,
        session_id: str | None = None,
        instructions: str = "",
    ) -> dict:
        """Distil one batch of memory nodes and return structured status/results."""
        sampled = self._dispatch(
            "sample_memory_nodes",
            json.dumps({"batch_size": self._batch_size, "session_id": session_id}),
            dispatch=MEMORY_REVIEW_TOOL_REGISTRY,
        )
        if isinstance(sampled, dict) and sampled.get("error"):
            status = {
                "status": "failed",
                "progress": {"completed": 0, "total": 0, "percent": 0},
                "results": [],
                "errors": [sampled["error"]],
                "summary": "",
            }
            self._emit_status(status)
            return status

        memories = sampled if isinstance(sampled, list) else []
        status = {
            "status": "running",
            "session_id": session_id,
            "progress": {"completed": 0, "total": len(memories), "percent": 0},
            "results": [],
            "errors": [],
            "summary": "",
        }
        self._emit_status(status)
        if not memories:
            status["status"] = "completed"
            status["summary"] = "No unreviewed memory nodes found."
            self._emit_status(status)
            return status

        user_msg = (
            f"Review these {len(memories)} memory nodes:\n"
            f"{json.dumps(memories, default=str, ensure_ascii=False)}"
        )
        if instructions:
            user_msg += f"\nAdditional instructions: {instructions}"
        history: list[dict] = [
            {"role": "system", "content": _MEMORY_REVIEW_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        def observe(name: str, result: Any) -> None:
            if name != "distill_memory":
                return
            if isinstance(result, dict) and result.get("error"):
                status["errors"].append(result["error"])
            else:
                status["results"].append(result)
            completed = len(status["results"])
            total = status["progress"]["total"]
            status["progress"] = {
                "completed": completed,
                "total": total,
                "percent": round(100 * completed / total) if total else 100,
            }
            self._emit_status(status)

        memory_tools = [
            schema
            for schema in MEMORY_REVIEW_TOOL_SCHEMAS
            if schema["function"]["name"] != "sample_memory_nodes"
        ]
        summary = self._run_loop(
            history,
            tools=memory_tools,
            dispatch=MEMORY_REVIEW_TOOL_REGISTRY,
            observe_result=observe,
        )
        status["summary"] = summary
        if status["progress"]["completed"] < status["progress"]["total"]:
            status["errors"].append("Review ended before every sampled memory received a decision.")
        status["status"] = "completed" if not status["errors"] else "completed_with_errors"
        self._emit_status(status)
        return status

    # ------------------------------------------------------------------
    # Internal agentic loop
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        history: list[dict],
        *,
        tools: list[dict] = REVIEW_TOOL_SCHEMAS,
        dispatch: dict[str, Any] | ToolRegistry = REVIEW_TOOL_REGISTRY,
        observe_result: Callable[[str, Any], None] | None = None,
    ) -> str:
        MAX_ITERATIONS = 30
        for i in range(MAX_ITERATIONS):
            if self._on_step:
                self._on_step("thinking", {"iteration": i + 1})

            response = self._client.chat.completions.create(
                model=self._model,
                messages=history,
                tools=tools,
                tool_choice="auto",
            )
            message = response.choices[0].message

            if not message.tool_calls:
                return message.content or ""

            history.append(message.model_dump(exclude_unset=True))

            for tc in message.tool_calls:
                try:
                    display_args = {
                        k: v
                        for k, v in json.loads(tc.function.arguments or "{}").items()
                        if k != "graph"
                    }
                except Exception:
                    display_args = {}
                if self._on_step:
                    self._on_step("tool_call", {"name": tc.function.name, "args": display_args})

                result = self._dispatch(
                    tc.function.name,
                    tc.function.arguments,
                    dispatch=dispatch,
                )

                if self._on_step:
                    self._on_step("tool_result", {"name": tc.function.name, "result": result})
                if observe_result:
                    observe_result(tc.function.name, result)

                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

        return "Review agent reached maximum iterations without a final answer."

    def _dispatch(
        self,
        name: str,
        arguments_json: str,
        *,
        dispatch: dict[str, Any] | ToolRegistry = REVIEW_TOOL_REGISTRY,
    ) -> Any:
        dispatch_map = dispatch.dispatch if isinstance(dispatch, ToolRegistry) else dispatch
        func = dispatch_map.get(name)
        if func is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            if isinstance(dispatch, ToolRegistry):
                kwargs = dispatch.parse_arguments(arguments_json)
            else:
                kwargs = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"Bad arguments JSON: {exc}"}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        kwargs["graph"] = self._graph
        if "policy" in inspect.signature(func).parameters:
            kwargs["policy"] = self._policy
        try:
            return normalize_tool_result(func(**kwargs))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _emit_status(self, status: dict) -> None:
        snapshot = json.loads(json.dumps(status, default=str))
        if self._on_status:
            self._on_status(snapshot)
        if self._on_step:
            self._on_step("memory_review_status", snapshot)

    def _emit_review_status(self, status: dict) -> None:
        snapshot = json.loads(json.dumps(status, default=str))
        if self._on_status:
            self._on_status(snapshot)
        if self._on_step:
            self._on_step("review_status", snapshot)

    def _review_tools(self) -> list[dict]:
        action_for_tool = {
            "update_entry": "modify",
            "mark_reviewed": "modify",
            "delete_entry": "delete",
            "distill_entry": "distill",
            "merge_entries": "merge_similar",
            "create_edge": "link",
            "delete_edge": "link",
        }
        tools = [
            deepcopy(schema)
            for schema in REVIEW_TOOL_SCHEMAS
            if action_for_tool.get(schema["function"]["name"]) in self._policy.allowed_actions
            or schema["function"]["name"] not in action_for_tool
        ]
        for schema in tools:
            if schema["function"]["name"] == "update_entry":
                properties = schema["function"]["parameters"]["properties"]
                properties["verification_status"]["enum"] = sorted(
                    status.value for status in self._policy.assignable_statuses
                )
        return tools

    def _policy_prompt(self) -> str:
        return (
            _SYSTEM_PROMPT
            + "\n## Enforced policy\n"
            + f"Allowed actions: {sorted(self._policy.allowed_actions)}.\n"
            + "Protected verification statuses may be inspected and linked, but never "
            + f"mutated: {sorted(status.value for status in self._policy.protected_statuses)}.\n"
            + "Assignable verification statuses: "
            + f"{sorted(status.value for status in self._policy.assignable_statuses)}.\n"
            + "The candidate list is already selected. Do not call the sampling tool."
        )
