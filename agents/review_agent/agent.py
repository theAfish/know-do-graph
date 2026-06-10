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

import json
import os
from typing import Any, Callable

from openai import OpenAI

from core.graph.graph import KnowDoGraph
from agents.review_agent.tools import REVIEW_TOOL_DISPATCH, REVIEW_TOOL_SCHEMAS

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

## Your workflow each session
1. Call `get_graph_summary` to see overall health and review coverage.
2. Call `sample_nodes_for_review` to get a batch (default 5).
3. For each sampled node: call `inspect_node`, assess quality, apply fixes if needed.
4. After inspecting (and optionally fixing) each node, call `mark_reviewed`.
5. Summarise what you found and fixed.

Keep changes conservative — prefer targeted fixes over large rewrites.
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
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._graph = graph
        self._batch_size = batch_size
        self._on_step = on_step
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
        user_msg = (
            f"Please review a batch of {self._batch_size} nodes. "
            + (instructions if instructions else "Apply all quality criteria from your instructions.")
        )
        history: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        return self._run_loop(history)

    def chat(self, user_message: str) -> str:
        """Single-turn interactive review conversation (stateless)."""
        history: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        return self._run_loop(history)

    # ------------------------------------------------------------------
    # Internal agentic loop
    # ------------------------------------------------------------------

    def _run_loop(self, history: list[dict]) -> str:
        MAX_ITERATIONS = 30
        for i in range(MAX_ITERATIONS):
            if self._on_step:
                self._on_step("thinking", {"iteration": i + 1})

            response = self._client.chat.completions.create(
                model=self._model,
                messages=history,
                tools=REVIEW_TOOL_SCHEMAS,
                tool_choice="auto",
            )
            message = response.choices[0].message

            if not message.tool_calls:
                return message.content or ""

            history.append(message.model_dump(exclude_unset=True))

            for tc in message.tool_calls:
                try:
                    display_args = {k: v for k, v in json.loads(tc.function.arguments or "{}").items() if k != "graph"}
                except Exception:
                    display_args = {}
                if self._on_step:
                    self._on_step("tool_call", {"name": tc.function.name, "args": display_args})

                result = self._dispatch(tc.function.name, tc.function.arguments)

                if self._on_step:
                    self._on_step("tool_result", {"name": tc.function.name, "result": result})

                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

        return "Review agent reached maximum iterations without a final answer."

    def _dispatch(self, name: str, arguments_json: str) -> Any:
        func = REVIEW_TOOL_DISPATCH.get(name)
        if func is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            kwargs = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            return {"error": f"Bad arguments JSON: {exc}"}
        kwargs["graph"] = self._graph
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
