"""Know-Do Graph — FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import os
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
from api.routes import remote_sync as remote_sync_routes
from api.routes import retrieve as retrieve_routes
from core.app_state import graph
from core.storage.database import SessionLocal, init_db
from core.version import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database and rebuild the in-memory graph on startup."""
    init_db()
    from core import events as _events
    _events.set_loop(asyncio.get_running_loop())
    from core.sync.db_watcher import reload_graph_from_db

    reload_graph_from_db(graph)

    sync_task: asyncio.Task | None = None
    if os.environ.get("KDG_REMOTE_SYNC_ENABLED", "").lower() in ("1", "true", "yes", "on"):
        interval = int(os.environ.get("KDG_REMOTE_SYNC_INTERVAL_SECONDS", "900"))
        from core.sync.remote_sync import run_periodic_sync

        sync_task = asyncio.create_task(run_periodic_sync(interval))
        logger.info("remote-sync background loop started (interval=%ss)", interval)

    # DB-change watcher: detects mutations written by out-of-process CLI commands
    # (e.g. `python main.py extract …`) and refreshes the in-memory graph + SSE.
    watcher_task: asyncio.Task | None = None
    watch_interval = int(os.environ.get("KDG_DB_WATCH_INTERVAL_SECONDS", "3"))
    if watch_interval > 0:
        from core.sync.db_watcher import run_db_watcher

        watcher_task = asyncio.create_task(run_db_watcher(graph, watch_interval))
        logger.info("db-watcher started (interval=%ss)", watch_interval)

    try:
        yield
    finally:
        from core import events as _events
        _events.signal_shutdown()
        for task in (sync_task, watcher_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


app = FastAPI(
    title="Know-Do Graph API",
    description=(
        "Agent-facing interface for a wiki-native executable knowledge graph. "
        "Search entries, traverse relations, and navigate operational knowledge."
    ),
    version=__version__,
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
app.include_router(remote_sync_routes.router, prefix="/remote-sync", tags=["remote-sync"])
app.include_router(retrieve_routes.router, prefix="/retrieve", tags=["retrieve"])


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
