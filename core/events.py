"""Lightweight SSE event bus for broadcasting graph mutations to connected clients.

Usage (from sync FastAPI route handlers):
    from core import events
    events.emit("node_added", {"id": ..., "title": ...})

Usage (SSE endpoint):
    q = events.subscribe()
    try:
        msg = await asyncio.wait_for(q.get(), timeout=25)
        if msg is events.SHUTDOWN_SENTINEL:
            return  # server shutting down
    finally:
        events.unsubscribe(q)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

# Sentinel put into every subscriber queue on server shutdown
SHUTDOWN_SENTINEL: object = object()

# Active subscriber queues (one per SSE connection)
_subscribers: set[asyncio.Queue] = set()

# The asyncio loop FastAPI runs on. Captured during app startup so that
# `emit()` works when invoked from worker threads (sync route handlers and
# background threads have no `get_running_loop()`).
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Remember the main event loop so `emit()` can dispatch from any thread."""
    global _loop
    _loop = loop


def signal_shutdown() -> None:
    """Push the shutdown sentinel into every subscriber queue so generators exit cleanly."""
    for q in list(_subscribers):
        try:
            q.put_nowait(SHUTDOWN_SENTINEL)
        except asyncio.QueueFull:
            pass


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber and return its queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a subscriber queue (called when the SSE connection closes)."""
    _subscribers.discard(q)


def emit(event_type: str, data: Any = None) -> None:
    """Broadcast a graph-change event to all connected SSE clients.

    Safe to call from sync FastAPI route handlers (which run in a thread pool)
    and from background threads — delivery is scheduled on the main asyncio
    event loop captured at startup via :func:`set_loop`.
    """
    msg = json.dumps({"type": event_type, "data": data or {}})
    loop = _loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No event loop available — nothing to broadcast
    for q in list(_subscribers):
        loop.call_soon_threadsafe(_try_put, q, msg)


def _try_put(q: asyncio.Queue, msg: str) -> None:
    try:
        q.put_nowait(msg)
    except asyncio.QueueFull:
        pass  # Slow consumer — drop the event rather than blocking
