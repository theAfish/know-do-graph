"""GraphAgent — LLM-driven agent for know-do graph management.

Uses the OpenAI function-calling API (compatible with any OpenAI-compatible
endpoint, e.g. Alibaba Cloud DashScope) to let a language model manipulate the
graph through structured tool calls.

Configuration is read from environment variables:
    OPENAI_API_KEY   — API key (required)
    OPENAI_API_BASE  — base URL override (optional, defaults to OpenAI)
    GRAPH_AGENT_MODEL — model name (optional, defaults to openai/glm-5.1)
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterator

from openai import OpenAI

from core.graph.graph import KnowDoGraph
from agents.graph_agent.tools import TOOL_DISPATCH, TOOL_SCHEMAS

_DEFAULT_MODEL = "qwen-plus"

_SYSTEM_PROMPT = """You are an expert knowledge-graph management assistant for the Know-Do Graph system.

The graph stores structured *entries* (nodes) and typed *edges* between them.
Entries can represent capabilities, procedures, tools, workflows, dependencies,
scripts, materials, material interfaces, and more.

## Node naming conventions
- Titles must be short, canonical, and human-readable (3–7 words preferred).
- Do NOT embed abbreviations or acronyms inside parentheses in the title (e.g. avoid
  "Density Functional Theory (DFT)"). Instead put the acronym in `aliases`.
- Tags must be lowercase, hyphenated, and domain-specific.

## Abstraction rule (CRITICAL — read carefully)
Skill nodes should describe a **reusable capability**, not a single concrete
instance. Concrete instances belong in the `content` (as examples) or as a
parameter, NOT as their own node.

  BAD:  "Build H2O molecule", "Build CH4 molecule", "Build NH3 molecule"
        → three near-identical nodes that pollute the graph.
  GOOD: One node "Build molecule from formula" whose content explains the
        general procedure and lists examples (H2O, CH4, NH3).

  BAD:  "TiO2/SrTiO3 Interface", "MgO/Fe Interface", "GaN/AlN Interface"
        → one node per material pair.
  GOOD: One "Material interface construction" capability node + one
        "Slab-stacking procedure" node, parameterised over material formulas.

  Exception: a specific instance is worth its own node ONLY when (a) it has
  unique constraints/data not derivable from the general procedure, OR (b) it
  is a famous/canonical reference that other procedures cite.

Before calling `create_entry`:
  1. Call `find_similar_nodes` with both the specific title AND a generalised
     version (e.g. for "Build H2O", also search "build molecule").
  2. If a generic match exists, do NOT create a new node — either link to the
     existing one or extend its content with the new example.
  3. If no generic match exists, ask yourself: "Could a sibling node for a
     different parameter value exist?" If yes, create the **generic** node, not
     the specific one.

`create_entry` will set a `needs_generalization` flag on any node whose title
overlaps an existing one — treat that as a signal to merge or rename.

## Entry types
- **capability** – what a system/tool can do; also used for material interfaces, known constructs, and runnable scripts (when `script_language` is set in metadata).
- **procedure** – step-by-step instructions.
- **workflow** – higher-level sequence linking multiple procedures.
- **tool** – software library, CLI tool, API, or instrument.
- **repository** – code repository or data repository.
- **environment** – computational or lab environment.
- **dependency** – package, library, or external service required by others.
- **data** – dataset, structural file, computed result, or reference material (crystals, compounds).
- **analytical** – analysis method or metric.
- **memory** – operational memory trace.
- **generic** – catch-all for entries that do not fit above.

## Verification & feedback
Every node carries `verification_status` (unverified | self_tested |
peer_reviewed | community_tested | bugged | deprecated). New nodes default to
`unverified`. When you or an external agent confirms a node works (or fails),
call `submit_feedback` with a verdict — this is how the graph self-evolves.

## Script workflow
Scripts are **capability** entries with `script_language` set in metadata.
1. Use ``create_script_entry`` to add runnable scripts.
2. Link scripts to procedures/capabilities via ``attach_script_to_entry``.
3. Any entry with `script_language` set can be downloaded at ``GET /entries/{id}/download``.

## Workflow for adding new knowledge
1. Call ``get_graph_overview`` to orient yourself.
2. For every concept you intend to create, search for both the specific and
   generalised name with ``find_similar_nodes``.
3. Choose the most appropriate ``entry_type``; write clean lowercase
   hyphenated tags; put abbreviations in ``aliases``.
4. Wire meaningful typed edges. Do not leave nodes isolated.
5. Resolve wikilinks when done.

## Workflow for restructuring / cleaning
- Use ``find_similar_nodes`` to detect near-duplicates before merging.
- Use ``merge_entries`` to consolidate duplicates.
- Use ``list_needs_generalization`` to find nodes flagged as too specific.
- Fix titles that contain parenthetical acronyms by moving the acronym to aliases.

Always confirm actions taken and briefly summarise what you did.
"""


class GraphAgent:
    """LLM-powered agent that manipulates the Know-Do Graph via tool calls.

    Parameters
    ----------
    graph:
        The shared ``KnowDoGraph`` instance.
    model:
        Model identifier forwarded to the OpenAI client.
    """

    def __init__(
        self,
        graph: KnowDoGraph,
        model: str | None = None,
        on_step: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._graph = graph
        self._model = model or os.environ.get("GRAPH_AGENT_MODEL", _DEFAULT_MODEL)
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_BASE"),
        )
        self._history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self._on_step = on_step

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(self, user_message: str) -> str:
        """Send one turn and return the final assistant text response."""
        self._history.append({"role": "user", "content": user_message})
        response_text = self._run_loop()
        self._history.append({"role": "assistant", "content": response_text})
        return response_text

    def reset(self) -> None:
        """Clear conversation history (keeps system prompt)."""
        self._history = [self._history[0]]

    # ------------------------------------------------------------------
    # Internal agentic loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> str:
        """Run the tool-call loop until the model produces a final reply."""
        MAX_ITERATIONS = 20
        for i in range(MAX_ITERATIONS):
            if self._on_step:
                self._on_step("thinking", {"iteration": i + 1})

            response = self._client.chat.completions.create(
                model=self._model,
                messages=self._history,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
            message = response.choices[0].message

            # No tool calls — model is done
            if not message.tool_calls:
                return message.content or ""

            # Append assistant message with tool_calls
            self._history.append(message.model_dump(exclude_unset=True))

            # Execute each tool call and collect results
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

                self._history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

        return "Agent reached maximum iterations without a final answer."

    def _dispatch(self, name: str, arguments_json: str) -> Any:
        """Call the named tool with the provided JSON arguments."""
        func = TOOL_DISPATCH.get(name)
        if func is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            kwargs = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            return {"error": f"Bad arguments JSON: {exc}"}

        # Inject the live graph instance into every call
        kwargs["graph"] = self._graph
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
