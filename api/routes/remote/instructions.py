"""Compatibility exports for remote instruction rendering."""

from __future__ import annotations

from api.routes.remote_instructions import _render_instructions, render_remote_instructions

__all__ = ["_render_instructions", "render_remote_instructions"]
