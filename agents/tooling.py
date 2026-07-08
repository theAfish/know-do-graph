from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

NETWORK_TOOL_NAMES = frozenset({"fetch_url", "web_search"})


def network_tools_enabled() -> bool:
    return os.environ.get("KDG_ENABLE_NETWORK_TOOLS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_tool_result(result: Any) -> Any:
    """Add a lightweight success/error envelope to dict tool results.

    Lists and scalar values are left unchanged to preserve established read-tool
    contracts. Dicts keep their existing fields and gain ``ok`` when absent.
    """
    if not isinstance(result, dict):
        return result
    if "ok" in result:
        return result
    if "error" in result:
        return {"ok": False, **result}
    return {"ok": True, **result}


@dataclass(frozen=True)
class ToolRegistry:
    schemas: tuple[dict, ...]
    dispatch: Mapping[str, Callable[..., Any]]
    mutating_tools: frozenset[str] = frozenset()
    network_tools: frozenset[str] = NETWORK_TOOL_NAMES

    @classmethod
    def from_legacy(
        cls,
        schemas: Iterable[dict],
        dispatch: Mapping[str, Callable[..., Any]],
        *,
        mutating_tools: Iterable[str] = (),
        network_tools: Iterable[str] = NETWORK_TOOL_NAMES,
    ) -> "ToolRegistry":
        return cls(
            schemas=tuple(schemas),
            dispatch=dict(dispatch),
            mutating_tools=frozenset(mutating_tools),
            network_tools=frozenset(network_tools),
        )

    def schema_list(
        self,
        *,
        allowed_tools: Iterable[str] | None = None,
        include_network: bool | None = None,
    ) -> list[dict]:
        allowed = set(allowed_tools) if allowed_tools is not None else None
        network_allowed = network_tools_enabled() if include_network is None else include_network
        schemas: list[dict] = []
        for schema in self.schemas:
            name = schema["function"]["name"]
            if allowed is not None and name not in allowed:
                continue
            if name in self.network_tools and not network_allowed:
                continue
            schemas.append(schema)
        return schemas

    def has_tool(self, name: str) -> bool:
        return name in self.dispatch

    def is_mutating(self, name: str) -> bool:
        return name in self.mutating_tools

    def is_network(self, name: str) -> bool:
        return name in self.network_tools

    def parse_arguments(self, arguments_json: str) -> dict:
        try:
            parsed = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Bad arguments JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must decode to a JSON object.")
        return parsed

    def call(
        self,
        name: str,
        arguments_json: str,
        *,
        extra_kwargs: dict[str, Any] | None = None,
        include_network: bool | None = None,
        normalize: bool = True,
    ) -> Any:
        if self.is_network(name) and not (
            network_tools_enabled() if include_network is None else include_network
        ):
            result = {"error": f"Tool '{name}' requires KDG_ENABLE_NETWORK_TOOLS=1."}
            return normalize_tool_result(result) if normalize else result
        func = self.dispatch.get(name)
        if func is None:
            result = {"error": f"Unknown tool: {name}"}
            return normalize_tool_result(result) if normalize else result
        try:
            kwargs = self.parse_arguments(arguments_json)
        except ValueError as exc:
            result = {"error": str(exc)}
            return normalize_tool_result(result) if normalize else result
        if extra_kwargs:
            kwargs.update(extra_kwargs)
        try:
            result = func(**kwargs)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
        return normalize_tool_result(result) if normalize else result
