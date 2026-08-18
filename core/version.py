"""Version helpers shared across runtime surfaces."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

try:
    from core._version import version as __version__
except ImportError:
    try:
        __version__ = package_version("know-do-graph")
    except PackageNotFoundError:
        __version__ = "0.0.0.dev0"
