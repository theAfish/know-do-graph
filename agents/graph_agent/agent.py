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
from typing import Any, Iterator

from openai import OpenAI

from core.graph.graph import KnowDoGraph
from agents.graph_agent.tools import TOOL_DISPATCH, TOOL_SCHEMAS

_DEFAULT_MODEL = "qwen-plus"

_SYSTEM_PROMPT = """You are an expert knowledge-graph management assistant for the Know-Do Graph system.

The graph stores structured *entries* (nodes) and typed *edges* between them.
Entries can represent capabilities, procedures, tools, workflows, dependencies, etc.

You can:
- Create, update, delete, and search entries (nodes)
- Create and delete edges (relationships) between entries
- Inspect graph statistics and connectivity
- Resolve [[wikilinks]] in content to graph edges
- Search the web with DuckDuckGo when you need external information to enrich entries

When the user asks you to add knowledge, search the web first if appropriate, then
create or update entries with the gathered information, and wire up meaningful edges.

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
    ) -> None:
        self._graph = graph
        self._model = model or os.environ.get("GRAPH_AGENT_MODEL", _DEFAULT_MODEL)
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_BASE"),
        )
        self._history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

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
        MAX_ITERATIONS = 10
        for _ in range(MAX_ITERATIONS):
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
                result = self._dispatch(tc.function.name, tc.function.arguments)
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
