"""Know-Do Graph — FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from fastapi import Request
from fastapi.responses import PlainTextResponse

from api.routes import entries, graph as graph_routes, mem as mem_routes, agent as agent_routes
from api.routes import remote as remote_routes
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
    from core import events as _events
    _events.signal_shutdown()


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
app.include_router(agent_routes.router, prefix="/agent", tags=["agent"])
app.include_router(remote_routes.router, prefix="/remote", tags=["remote"])


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", **graph.stats()}


@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root_instructions(request: Request) -> PlainTextResponse:
    """Return the plain-text instruction sheet for any client that hits the server root."""
    from api.routes.remote import _render_instructions
    return PlainTextResponse(_render_instructions(request))


# ── Frontend ──────────────────────────────────────────────────────────────────
# After `npm run build` in frontend/, Vite emits frontend/dist/ with relative
# asset URLs (vite.config.js: base: './'). We serve dist/index.html at /ui and
# the hashed bundle at /assets. In dev, prefer `npm run dev` (Vite on :5173
# with API proxy) — direct HMR, this mount unused.
_FRONTEND_ROOT = Path(__file__).parent.parent / "frontend"
_FRONTEND_DIST = _FRONTEND_ROOT / "dist"

if _FRONTEND_DIST.is_dir() and (_FRONTEND_DIST / "index.html").is_file():
    if (_FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="ui-assets")

    @app.get("/ui", include_in_schema=False)
    def serve_ui() -> FileResponse:
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

else:
    from fastapi.responses import HTMLResponse

    @app.get("/ui", include_in_schema=False)
    def serve_ui_not_built() -> HTMLResponse:
        return HTMLResponse(
            "<h1 style='font-family:sans-serif'>Frontend not built</h1>"
            "<p style='font-family:sans-serif'>Run the following then restart the server:</p>"
            "<pre style='background:#111;color:#0f0;padding:1em;border-radius:4px'>"
            "cd frontend\nnpm install\nnpm run build</pre>",
            status_code=503,
        )
