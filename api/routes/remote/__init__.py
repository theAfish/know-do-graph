"""Remote API route facade."""

from __future__ import annotations

from api.routes.remote_instructions import _render_instructions
from api.routes.remote_legacy import router

__all__ = ["_render_instructions", "router"]
