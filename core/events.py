"""Lightweight SSE event bus for broadcasting graph mutations to connected clients.

Usage (from sync FastAPI route handlers):
    from core import events
    events.emit("node_added", {"id": ..., "title": ...})

Usage (SSE endpoint):
    q = events.subscribe()
    try:
        msg = await asyncio.wait_for(q.get(), timeout=25)
    finally:
        events.unsubscribe(q)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

# Active subscriber queues (one per SSE connection)
_subscribers: set[asyncio.Queue] = set()


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

    Safe to call from sync FastAPI route handlers (which run in a thread pool);
    delivery is scheduled on the running asyncio event loop via
    ``loop.call_soon_threadsafe``.
    """
    msg = json.dumps({"type": event_type, "data": data or {}})
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
