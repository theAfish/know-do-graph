"""Orchestrator — routes a user request to the right agent or pipeline.

The orchestrator is a thin LLM-driven router that:
1. Reads the user's request (with optional graph context).
2. Decides which agent(s) to invoke and with what parameters.
3. Calls them in sequence or parallel and returns the combined result.

Supported targets:
- ``graph``  — GraphAgent (add/update/link knowledge)
- ``review`` — ReviewAgent (audit & clean existing nodes)

The orchestrator does NOT do graph work itself; it delegates entirely.
"""

from __future__ import annotations

import json
import os
from typing import Callable

from openai import OpenAI

from core.graph.graph import KnowDoGraph

_DEFAULT_MODEL = "qwen-plus"

_SYSTEM_PROMPT = """You are the orchestrator for the Know-Do Graph system.
Your only job is to decide which agent(s) should handle the user's request and
call them with the right parameters.

Available agents / pipelines
-----------------------------
1. ``run_graph_agent(message)``
   Use for: adding new knowledge, searching/updating/linking nodes, enriching
   content from the web, answering questions about graph content.

2. ``run_review_agent(instructions, batch_size)``
   Use for: auditing existing nodes, cleaning titles/tags/aliases, merging
   duplicates, checking graph quality, improving coverage.
   batch_size controls how many nodes are reviewed per session (default 5).

Decision rules
--------------
- If the request is about *adding, updating, or querying* knowledge → graph agent.
- If the request is about *cleaning, reviewing, fixing, auditing* the graph → review agent.
- If both apply (e.g. "add new nodes and then review the related area") → call both in order.
- If the intent is ambiguous, prefer the graph agent for content tasks and the
  review agent for quality/maintenance tasks.

Always call at least one agent. Never answer directly without delegating.
After all agent calls are complete, give a concise summary of what was done.
"""


class OrchestratorAgent:
    """Routes requests to GraphAgent and/or ReviewAgent.

    Parameters
    ----------
    graph:
        Shared KnowDoGraph instance.
    model:
        LLM model for the orchestrator's routing decision.
    on_step:
        Optional callback ``(event, data)`` forwarded to sub-agents for CLI display.
    """

    def __init__(
        self,
        graph: KnowDoGraph,
        model: str | None = None,
        on_step: Callable[[str, dict], None] | None = None,
        read_only: bool = False,
    ) -> None:
        self._graph = graph
        self._model = model or os.environ.get("ORCHESTRATOR_MODEL", os.environ.get("GRAPH_AGENT_MODEL", _DEFAULT_MODEL))
        self._on_step = on_step
        self._read_only = read_only
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_BASE"),
        )
        self._history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def chat(self, user_message: str) -> str:
        """Route a message and return the combined agent response."""
        self._history.append({"role": "user", "content": user_message})
        result = self._run_loop()
        self._history.append({"role": "assistant", "content": result})
        return result

    def reset(self) -> None:
        self._history = [self._history[0]]

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> str:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "run_graph_agent",
                    "description": (
                        "Delegate a task to the GraphAgent. Use for adding, updating, "
                        "searching, linking, or enriching knowledge nodes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Full task description for the graph agent",
                            },
                        },
                        "required": ["message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_review_agent",
                    "description": (
                        "Delegate a quality-review session to the ReviewAgent. "
                        "Use for auditing, cleaning, deduplicating, or fixing existing nodes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "instructions": {
                                "type": "string",
                                "description": "Specific review focus (leave empty for general review)",
                                "default": "",
                            },
                            "batch_size": {
                                "type": "integer",
                                "description": "Number of nodes to review in this session",
                                "default": 5,
                            },
                        },
                    },
                },
            },
        ]

        MAX_ITERATIONS = 8
        for i in range(MAX_ITERATIONS):
            if self._on_step:
                self._on_step("orchestrator_thinking", {"iteration": i + 1})

            response = self._client.chat.completions.create(
                model=self._model,
                messages=self._history,
                tools=tools,
                tool_choice="auto",
            )
            message = response.choices[0].message

            if not message.tool_calls:
                return message.content or ""

            self._history.append(message.model_dump(exclude_unset=True))

            for tc in message.tool_calls:
                name = tc.function.name
                try:
                    kwargs = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    kwargs = {}

                if self._on_step:
                    self._on_step("route", {"agent": name, "args": kwargs})

                result = self._dispatch(name, kwargs)

                self._history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"result": result}, default=str),
                    }
                )

        return "Orchestrator reached maximum iterations."

    def _dispatch(self, name: str, kwargs: dict) -> str:
        if name == "run_graph_agent":
            return self._run_graph_agent(kwargs.get("message", ""))
        if name == "run_review_agent":
            return self._run_review_agent(
                kwargs.get("instructions", ""),
                int(kwargs.get("batch_size", 5)),
            )
        return f"Unknown agent: {name}"

    def _run_graph_agent(self, message: str) -> str:
        from agents.graph_agent.agent import GraphAgent

        agent = GraphAgent(graph=self._graph, model=self._model, on_step=self._on_step, read_only=self._read_only)
        return agent.chat(message)

    def _run_review_agent(self, instructions: str, batch_size: int) -> str:
        from agents.review_agent.agent import ReviewAgent

        agent = ReviewAgent(
            graph=self._graph,
            model=self._model,
            batch_size=batch_size,
            on_step=self._on_step,
        )
        return agent.run_review(instructions=instructions)
