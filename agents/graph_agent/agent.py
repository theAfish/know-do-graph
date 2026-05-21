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

from core import events as _events
from core.graph.graph import KnowDoGraph
from agents.graph_agent.tools import TOOL_DISPATCH, TOOL_SCHEMAS

_DEFAULT_MODEL = "qwen-plus"

# Tool calls that mutate the graph; the frontend is notified via SSE so it
# can refresh after each such call.
_MUTATING_TOOLS: set[str] = {
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

# Read-only tools exposed when the agent is instantiated in query-only mode.
# Mutating tools are excluded so external agents can query the graph without
# accidentally writing nodes or edges.
_READ_ONLY_TOOLS: set[str] = {
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

_READ_ONLY_SYSTEM_PROMPT = """You are a read-only knowledge-graph query assistant for the Know-Do Graph system.

Your role is to **answer questions** about the graph — searching, retrieving, and
summarising existing entries and relationships. You do NOT add, modify, or delete
any nodes or edges.

## Search strategy
Use ``search_entries`` or ``find_similar_nodes`` for free-text queries.
Use ``get_entry`` to fetch full details of a specific node.
Use ``get_neighbors`` to explore relationships.
Use ``get_graph_overview`` to orient yourself when asked general questions.
Use ``list_nodes_by_type`` to enumerate nodes of a given category.

## Important
- Do NOT attempt to create, update, delete, or merge any entries or edges.
- Do NOT call any write operations; only read/query tools are available.
- Summarise and return what exists in the graph as clearly as possible.
"""

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
- **heuristic** – L3 conditional, empirical guidance attached to a skill (see hierarchical memory below).
- **constraint** – L4 known failure mode or limitation attached to a skill.
- **generic** – catch-all for entries that do not fit above.

## Hierarchical memory (L1–L4) — progressive disclosure
The graph is organised into four orthogonal levels so planners can pull only
the level of detail they need:

  - **L1 — Capability**  (`capability` / `workflow`)
      Reusable high-level ability. Planner-friendly. Stays domain-agnostic
      when possible. Example: "construct amorphous structures".
  - **L2 — Procedure**  (`procedure`)
      Executable workflow decomposition / tool sequencing. Example:
      "initialize random structure → anneal → controlled quench → relax".
  - **L3 — Heuristic**  (`heuristic`)
      Operational experience: conditional, empirical guidance. NOT a universal
      truth. Example: "cooling rate strongly affects sp2/sp3 ratio".
  - **L4 — Constraint / Failure Mode**  (`constraint`)
      Known limitation or failure pattern. Example: "unsuitable for
      bond-breaking processes". Verifier-guided debugging starts here.

**Critical rules**
1. Do NOT embed heuristics or failure modes inside a capability's `content`
   blob. Create them as separate L3 / L4 nodes via `create_heuristic` /
   `create_constraint` so progressive retrieval can surface them on demand.
2. Do NOT encode domain-specific details directly into L1 capability names.
   Prefer "construct amorphous structures" over "construct amorphous carbon
   via Tersoff melt-quench". System-specific knowledge lives in L3/L4.
3. When you create an L2 procedure that implements an existing L1 capability,
   wire the link with `decompose_capability(capability, procedure)`.
4. For retrieval, prefer the staged tools:
   - `retrieve_plan(goal)` for planning (returns L1 + L2 only).
   - `retrieve_heuristics(skill)` once a candidate is chosen.
   - `retrieve_constraints(skill)` when the verifier reports an issue or you
     need to estimate execution risk.
   This avoids polluting the planning context with the full knowledge dump.

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

## Node assets (folder-style)
Every node behaves like a small folder containing typed assets, addressable as
`[entry]/[folder]/[filename]` and served at
``GET /entries/{id}/assets/{folder}/{filename}``.

Conventional folders (free-form names also allowed):
- ``scripts``     — runnable code (Python/bash/…)
- ``references``  — URLs to papers, repos, docs (use ``kind="link"``)
- ``docs``        — markdown/text documentation (``kind="text"``)
- ``examples``    — example input files, configs, notebooks
- ``data``        — small datasets / structural files
- ``notes``       — free-form annotations

Use ``add_asset_to_entry`` for anything beyond a script (URL, doc, example file).
Use ``add_script_to_entry`` for runnable scripts (auto-targets the ``scripts`` folder).
Use ``list_assets`` to inspect a node's folder tree.

## Search strategy
Both ``search_entries`` and ``find_similar_nodes`` support three modes:
- **hybrid** (default) — fuses embedding vector similarity (ANN) with keyword scoring via
  Reciprocal Rank Fusion, then re-ranks by verification trust and usage count. Best general-purpose choice.
- **semantic** — embedding-only. Use when the exact words differ but the concept is the same
  (paraphrases, synonyms, related domains). Good for catching near-duplicates with different wording.
- **keyword** — exact text matching on title, aliases, tags, content. Use for known acronyms,
  formula strings, or when you need precise title lookup.

If an initial search returns poor results, try a different mode or rephrase/broaden the query
before assuming no match exists. For duplicate detection, run at least one semantic pass.

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
        read_only: bool = False,
    ) -> None:
        self._graph = graph
        self._model = model or os.environ.get("GRAPH_AGENT_MODEL", _DEFAULT_MODEL)
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_BASE"),
        )
        self._read_only = read_only
        system_prompt = _READ_ONLY_SYSTEM_PROMPT if read_only else _SYSTEM_PROMPT
        self._history: list[dict] = [{"role": "system", "content": system_prompt}]
        self._on_step = on_step
        # Filter tool schemas to read-only set when in query-only mode
        self._tool_schemas = (
            [s for s in TOOL_SCHEMAS if s["function"]["name"] in _READ_ONLY_TOOLS]
            if read_only
            else TOOL_SCHEMAS
        )

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
                tools=self._tool_schemas,
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
        # Guard: in read-only mode, reject any mutating tool that somehow slips through
        if self._read_only and name in _MUTATING_TOOLS:
            return {"error": f"Tool '{name}' is not available in read-only mode."}

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
            result = func(**kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

        # Broadcast a refresh hint so connected frontends re-fetch the graph.
        if name in _MUTATING_TOOLS:
            is_error = isinstance(result, dict) and "error" in result
            if not is_error:
                try:
                    _events.emit("graph_changed", {"tool": name})
                except Exception:
                    pass
        return result
