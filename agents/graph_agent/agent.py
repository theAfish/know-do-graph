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
- Do NOT prefix every RDKit capability with "RDKit "; use the `tags` field and a
  `dependency` edge to the RDKit tool node instead.
- Tags must be lowercase, hyphenated, and domain-specific. Avoid capitalised tags
  (e.g. use "rdkit" not "RDKit", "machine-learning" not "Machine Learning").
- Prefer broad, reusable titles over highly specific ones.

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

## Script workflow
Scripts are **capability** entries with `script_language` set in metadata.
1. Use ``create_script_entry`` to add runnable scripts (Python, bash, Julia, etc.).
2. Link scripts to the procedures/capabilities they implement via ``attach_script_to_entry``.
3. Any entry with `script_language` set can be downloaded at ``GET /entries/{id}/download``.

## Material interface workflow
Materials are **data** entries; interfaces are **capability** entries.
1. Create material (data) entries with ``create_material_entry``.
2. Use ``build_material_interface_workflow`` to scaffold: interface (capability) + procedure + data nodes.
3. Attach relevant scripts (relaxation, lattice-matching, etc.) to the procedure node.

## Workflow for adding new knowledge
1. Call ``get_graph_overview`` to orient yourself.
2. Call ``find_similar_nodes`` for every concept you intend to create.
3. Choose the most appropriate ``entry_type``; write clean lowercase hyphenated tags;
   put all abbreviations in ``aliases``.
4. Wire meaningful typed edges. Do not leave nodes isolated.
5. Resolve wikilinks when done.

## Workflow for restructuring / cleaning
- Use ``find_similar_nodes`` to detect near-duplicates before merging.
- Use ``merge_entries`` to consolidate duplicates.
- Fix titles that contain parenthetical acronyms by moving the acronym to aliases.
- Normalise tags to lowercase on every node you touch.

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
