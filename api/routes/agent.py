"""Agent-chat routes (GraphAgent and ReviewAgent)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.app_state import graph as _graph

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ReviewRequest(BaseModel):
    instructions: str = ""
    batch_size: int = 5
    model: str | None = None


@router.post("/graph/chat", tags=["agent"])
def graph_agent_chat(body: ChatRequest) -> dict:
    """Send a message to the GraphAgent and receive its response."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")

    from agents.graph_agent.agent import GraphAgent

    agent = GraphAgent(graph=_graph, model=body.model)
    response = agent.chat(body.message)
    return {"response": response}


@router.post("/review/run", tags=["agent"])
def review_agent_run(body: ReviewRequest) -> dict:
    """Run one review session with the ReviewAgent."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")

    from agents.review_agent.agent import ReviewAgent

    agent = ReviewAgent(graph=_graph, model=body.model, batch_size=body.batch_size)
    response = agent.run_review(instructions=body.instructions)
    return {"response": response}


@router.post("/review/chat", tags=["agent"])
def review_agent_chat(body: ChatRequest) -> dict:
    """Send a single message to the ReviewAgent."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")

    from agents.review_agent.agent import ReviewAgent

    agent = ReviewAgent(graph=_graph, model=body.model)
    response = agent.chat(body.message)
    return {"response": response}
