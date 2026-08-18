"""Agent-chat routes (GraphAgent and ReviewAgent)."""

from __future__ import annotations

import copy
import threading
import uuid

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


class MemoryReviewRequest(BaseModel):
    session_id: str | None = None
    instructions: str = ""
    batch_size: int = 5
    model: str | None = None


_memory_review_jobs: dict[str, dict] = {}
_memory_review_jobs_lock = threading.Lock()


def _set_memory_review_job(job_id: str, status: dict) -> None:
    with _memory_review_jobs_lock:
        _memory_review_jobs[job_id] = copy.deepcopy(status)


def _run_memory_review_job(job_id: str, body: MemoryReviewRequest) -> None:
    from agents.review_agent.agent import ReviewAgent

    try:
        agent = ReviewAgent(
            graph=_graph,
            model=body.model,
            batch_size=body.batch_size,
            on_status=lambda status: _set_memory_review_job(job_id, status),
        )
        result = agent.run_memory_review(
            session_id=body.session_id,
            instructions=body.instructions,
        )
        _set_memory_review_job(job_id, result)
    except Exception as exc:  # noqa: BLE001
        _set_memory_review_job(
            job_id,
            {
                "status": "failed",
                "session_id": body.session_id,
                "progress": {"completed": 0, "total": 0, "percent": 0},
                "results": [],
                "errors": [str(exc)],
                "summary": "",
            },
        )


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


@router.post("/review/memory", tags=["agent"], status_code=202)
def start_memory_review(body: MemoryReviewRequest) -> dict:
    """Start a memory-distillation review and return a pollable job."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")
    if body.batch_size < 1:
        raise HTTPException(status_code=422, detail="batch_size must be at least 1.")

    job_id = str(uuid.uuid4())
    initial = {
        "job_id": job_id,
        "status": "running",
        "session_id": body.session_id,
        "progress": {"completed": 0, "total": 0, "percent": 0},
        "results": [],
        "errors": [],
        "summary": "",
    }
    _set_memory_review_job(job_id, initial)
    threading.Thread(
        target=_run_memory_review_job,
        args=(job_id, body),
        daemon=True,
        name=f"kdg-memory-review-{job_id[:8]}",
    ).start()
    return initial


@router.get("/review/memory/{job_id}", tags=["agent"])
def get_memory_review(job_id: str) -> dict:
    """Return running progress, completed results, and errors for a review job."""
    with _memory_review_jobs_lock:
        status = _memory_review_jobs.get(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Memory review job not found.")
        result = copy.deepcopy(status)
    result["job_id"] = job_id
    return result


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


@router.post("/orchestrate", tags=["agent"])
def orchestrate(body: ChatRequest) -> dict:
    """Route a request through the Orchestrator to the appropriate agent(s)."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")

    from agents.orchestrator.agent import OrchestratorAgent

    agent = OrchestratorAgent(graph=_graph, model=body.model)
    response = agent.chat(body.message)
    return {"response": response}
