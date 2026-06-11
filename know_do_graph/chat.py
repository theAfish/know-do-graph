"""Conversation API for the built-in graph agents."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Callable, Literal

from core.storage.database import bind_session_factory

if TYPE_CHECKING:
    from .client import KnowDoGraph

AgentKind = Literal["graph", "orchestrator", "reviewer"]
StepCallback = Callable[[str, dict], None]
StatusCallback = Callable[[dict], None]


class ChatSession:
    """Stateful conversation with a graph-aware agent.

    Use :meth:`send` for normal graph or orchestrator conversations. Reviewer
    sessions also expose :meth:`review` for a structured review batch.
    """

    def __init__(
        self,
        graph: "KnowDoGraph",
        *,
        agent: AgentKind = "graph",
        model: str | None = None,
        read_only: bool = False,
        on_step: StepCallback | None = None,
        on_status: StatusCallback | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        batch_size: int = 5,
    ) -> None:
        if agent not in ("graph", "orchestrator", "reviewer"):
            raise ValueError("agent must be 'graph', 'orchestrator', or 'reviewer'")
        if agent == "reviewer" and read_only:
            raise ValueError("reviewer sessions modify review metadata and cannot be read-only")

        self.graph = graph
        self.agent_kind = agent
        self.read_only = read_only
        self._lock = Lock()

        common = {
            "graph": graph._graph,
            "model": model,
            "on_step": on_step,
            "api_key": api_key,
            "base_url": base_url,
        }
        if agent == "graph":
            from agents.graph_agent.agent import GraphAgent

            self._agent = GraphAgent(**common, read_only=read_only)
        elif agent == "orchestrator":
            from agents.orchestrator.agent import OrchestratorAgent

            self._agent = OrchestratorAgent(**common, read_only=read_only)
        else:
            from agents.review_agent.agent import ReviewAgent

            self._agent = ReviewAgent(
                **common,
                batch_size=batch_size,
                on_status=on_status,
            )

    def send(self, message: str) -> str:
        """Send one message while preserving this session's conversation history."""
        if not message.strip():
            raise ValueError("message must not be empty")
        with self._lock, bind_session_factory(self.graph._session_factory):
            return self._agent.chat(message)

    __call__ = send

    def review(self, instructions: str = "") -> str:
        """Run one review batch. Only available for ``agent='reviewer'``."""
        if self.agent_kind != "reviewer":
            raise TypeError("review() is only available for reviewer sessions")
        with self._lock, bind_session_factory(self.graph._session_factory):
            return self._agent.run_review(instructions=instructions)

    def review_memory(
        self,
        *,
        session_id: str | None = None,
        instructions: str = "",
    ) -> dict:
        """Distil one memory batch. Only available for reviewer sessions."""
        if self.agent_kind != "reviewer":
            raise TypeError("review_memory() is only available for reviewer sessions")
        with self._lock, bind_session_factory(self.graph._session_factory):
            return self._agent.run_memory_review(
                session_id=session_id,
                instructions=instructions,
            )

    def reset(self) -> None:
        """Clear conversation history when supported by the selected agent."""
        reset = getattr(self._agent, "reset", None)
        if reset is None:
            return
        with self._lock:
            reset()
