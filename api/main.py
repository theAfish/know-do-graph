"""Know-Do Graph — FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import entries, graph as graph_routes, mem as mem_routes
from core.app_state import graph
from core.storage.database import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database and rebuild the in-memory graph on startup."""
    init_db()
    with SessionLocal() as db:
        from core.storage.repository import EdgeRepository, EntryRepository

        entries_list = EntryRepository(db).get_all()
        edges_list = EdgeRepository(db).get_all()
    graph.rebuild_from_db(entries_list, edges_list)
    yield
    # Nothing to clean up on shutdown


app = FastAPI(
    title="Know-Do Graph API",
    description=(
        "Agent-facing interface for a wiki-native executable knowledge graph. "
        "Search entries, traverse relations, and navigate operational knowledge."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entries.router, prefix="/entries", tags=["entries"])
app.include_router(graph_routes.router, prefix="/graph", tags=["graph"])
app.include_router(mem_routes.router, prefix="/mem", tags=["mem"])


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", **graph.stats()}


# ── Frontend ──────────────────────────────────────────────────────────────────
_FRONTEND = Path(__file__).parent.parent / "frontend"

if _FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")

    @app.get("/ui", include_in_schema=False)
    def serve_ui() -> FileResponse:
        return FileResponse(str(_FRONTEND / "index.html"))
