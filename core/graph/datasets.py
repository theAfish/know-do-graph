"""Read-only adapters for graph-shaped datasets stored alongside KDG data.

The core application owns the ``entries`` / ``edges`` format.  Some analysis
pipelines, however, write a graph projection directly to SQLite.  Adapters in
this module make those datasets inspectable without pretending they are
editable KDG entries or coupling the API to one analysis implementation.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Mapping, Protocol

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


class GraphDatasetAdapter(Protocol):
    """Stable interface for a graph dataset that is not KDG's native model.

    ``describe`` is a declarative UI/API contract: an adapter can expose
    capabilities, graph controls, and presentation defaults without the core
    server knowing its storage schema. ``graph_view`` receives the control
    values as query parameters, leaving each adapter free to define its own.
    """

    kind: str
    read_only: bool

    @classmethod
    def is_compatible(cls, engine: Engine) -> bool: ...

    def describe(self) -> dict[str, Any]: ...

    def graph_view(self, options: Mapping[str, str]) -> dict[str, Any]: ...

    def hierarchy_view(self, node_id: str, options: Mapping[str, str]) -> dict[str, Any]: ...

    def search_view(self, options: Mapping[str, str]) -> dict[str, Any]: ...


class LrgDataset:
    """Expose a layered graph-reduction SQLite result as a read-only graph.

    The LRG format is identified structurally, not by a filename.  Each level
    contains supernodes and aggregated weighted edges; level zero is the
    source projection, while subsequent levels are coarser reductions.
    """

    kind = "lrg"
    read_only = True
    _required_tables = {"levels", "supernodes", "supernode_members", "coarse_edges"}

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @classmethod
    def is_compatible(cls, engine: Engine) -> bool:
        return cls._required_tables.issubset(inspect(engine).get_table_names())

    def describe(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            levels = [
                {
                    "level": int(row.level),
                    "nodes": int(row.node_count),
                    "edges": int(row.edge_count),
                }
                for row in conn.execute(
                    text("SELECT level, node_count, edge_count FROM levels ORDER BY level")
                )
            ]
            metadata = self._metadata(conn)

        return {
            "kind": self.kind,
            "read_only": self.read_only,
            "label": "LRG hierarchical projection",
            "capabilities": ["graph", "hierarchy", "search"],
            "levels": levels,
            "metadata": metadata,
            "default_level": levels[0]["level"] if levels else 0,
            "default_max_nodes": 600,
            "max_nodes": 1500,
            "graph_defaults": {"level": levels[0]["level"] if levels else 0, "max_nodes": 600},
            "controls": [
                {
                    "parameter": "level",
                    "label": "Resolution",
                    "type": "select",
                    "options": [
                        {
                            "value": item["level"],
                            "label": f"Level {item['level']} · {item['nodes']:,} nodes",
                        }
                        for item in levels
                    ],
                },
                {
                    "parameter": "max_nodes",
                    "label": "Overview",
                    "type": "select",
                    "options": [
                        {"value": value, "label": f"{value:,} nodes"}
                        for value in (300, 600, 1000, 1500)
                    ],
                },
            ],
            "presentation": {"show_labels": False},
        }

    def full_graph(self, *, level: int | None, max_nodes: int | None) -> dict[str, Any]:
        description = self.describe()
        levels = description["levels"]
        available = {item["level"] for item in levels}
        selected_level = description["default_level"] if level is None else level
        if selected_level not in available:
            raise ValueError(
                f"Unknown LRG level {selected_level}; available levels: {sorted(available)}"
            )

        # A force-directed SVG is useful for an overview, but not for thousands
        # of labels and links. Select the highest-connected supernodes first;
        # results are deterministic and retain only induced edges.
        limit = max_nodes if max_nodes is not None else description["default_max_nodes"]
        limit = max(1, min(int(limit), int(description["max_nodes"])))

        with self.engine.connect() as conn:
            nodes = self._nodes(conn, selected_level)
            edges = self._edges(conn, selected_level)

        total_nodes = len(nodes)
        total_edges = len(edges)
        if len(nodes) > limit:
            degree = Counter()
            for edge in edges:
                degree[edge["source"]] += 1
                degree[edge["target"]] += 1
            nodes.sort(
                key=lambda node: (
                    -degree[node["id"]],
                    -int(node.get("member_count", 1)),
                    node["title"].lower(),
                )
            )
            nodes = nodes[:limit]
            selected_ids = {node["id"] for node in nodes}
            edges = [
                edge
                for edge in edges
                if edge["source"] in selected_ids and edge["target"] in selected_ids
            ]

        return {
            "metadata": {
                **description,
                "selected_level": selected_level,
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "displayed_nodes": len(nodes),
                "displayed_edges": len(edges),
                "truncated": len(nodes) < total_nodes,
            },
            "nodes": nodes,
            "edges": edges,
        }

    def graph_view(self, options: Mapping[str, str]) -> dict[str, Any]:
        """Adapt generic query parameters to this format's graph view."""
        return self.full_graph(
            level=self._optional_int(options, "level"),
            max_nodes=self._optional_int(options, "max_nodes"),
        )

    def search_view(self, options: Mapping[str, str]) -> dict[str, Any]:
        """Search every supernode at the selected resolution.

        The normal graph view is a deliberately bounded overview.  Search must
        not inherit that bound: a matching supernode is useful precisely when
        it was not one of the high-degree nodes selected for the overview.
        """
        description = self.describe()
        available = {item["level"] for item in description["levels"]}
        level = self._optional_int(options, "level")
        selected_level = description["default_level"] if level is None else level
        if selected_level not in available:
            raise ValueError(
                f"Unknown LRG level {selected_level}; available levels: {sorted(available)}"
            )

        query = str(options.get("q") or "").strip().lower()
        if not query:
            raise ValueError("Search query cannot be empty")
        tag_query = query[1:].strip() if query.startswith("#") else None
        if tag_query == "":
            raise ValueError("Tag search cannot be empty")
        entry_type = str(options.get("entry_type") or "").strip()

        with self.engine.connect() as conn:
            nodes = self._nodes(conn, selected_level)
            edges = self._edges(conn, selected_level)
            member_matches = (
                {} if tag_query else self._matching_members(conn, selected_level, query)
            )

        matched_nodes = []
        for node in nodes:
            if entry_type and node["entry_type"] != entry_type:
                continue
            if tag_query:
                matches = any(tag_query in str(tag).lower() for tag in node.get("tags", []))
                matched_members = []
            else:
                matches = (
                    query in node["title"].lower()
                    or query in node["slug"].lower()
                    or any(query in str(tag).lower() for tag in node.get("tags", []))
                    or node["id"] in member_matches
                )
                matched_members = member_matches.get(node["id"], [])
            if not matches:
                continue

            # A cluster's title is intentionally generic. Preserve a few of
            # the matching member titles so the result explains why it matched.
            if matched_members:
                node = {
                    **node,
                    "metadata": {
                        **node.get("metadata", {}),
                        "search_matches": matched_members,
                    },
                }
            matched_nodes.append(node)

        matched_ids = {node["id"] for node in matched_nodes}
        matched_edges = [
            edge
            for edge in edges
            if edge["source"] in matched_ids and edge["target"] in matched_ids
        ]
        return {
            "metadata": {
                "kind": "search",
                "label": "Search results",
                "selected_level": selected_level,
                "query": options.get("q"),
                "total_matches": len(matched_nodes),
                "displayed_nodes": len(matched_nodes),
                "displayed_edges": len(matched_edges),
                "truncated": False,
                "read_only": True,
            },
            "nodes": matched_nodes,
            "edges": matched_edges,
        }

    def hierarchy(
        self, *, node_id: str, target_level: int | None, max_nodes: int = 600
    ) -> dict[str, Any]:
        """Return constituent supernodes at a finer resolution.

        LRG stores memberships as original entry IDs at every level. Joining
        those memberships gives a stable containment relation across any two
        levels, without assuming that adjacent-level node IDs are preserved.
        """
        source_level, source_supernode = self._parse_node_id(node_id)
        description = self.describe()
        available = {item["level"] for item in description["levels"]}
        if source_level not in available:
            raise ValueError(f"Unknown LRG level {source_level}")
        if target_level is None:
            target_level = source_level - 1
        if target_level not in available or target_level >= source_level:
            raise ValueError("Choose an existing resolution lower than the selected node's level")
        limit = max(1, min(int(max_nodes), int(description["max_nodes"])))

        with self.engine.connect() as conn:
            nodes_by_id = {
                node["id"]: node
                for node in self._nodes(conn, source_level) + self._nodes(conn, target_level)
            }
            parent = nodes_by_id.get(node_id)
            if parent is None:
                raise ValueError(f"Unknown LRG node {node_id}")
            child_rows = list(
                conn.execute(
                    text(
                        """
                        SELECT m.supernode, COUNT(DISTINCT m.entry_id) AS overlap
                        FROM supernode_members AS parent_members
                        JOIN supernode_members AS m ON m.entry_id = parent_members.entry_id
                        WHERE parent_members.level = :source_level
                          AND parent_members.supernode = :source_supernode
                          AND m.level = :target_level
                        GROUP BY m.supernode
                        ORDER BY overlap DESC, m.supernode
                        """
                    ),
                    {
                        "source_level": source_level,
                        "source_supernode": source_supernode,
                        "target_level": target_level,
                    },
                )
            )

        total_children = len(child_rows)
        child_rows = child_rows[:limit]
        children = []
        edges = []
        for row in child_rows:
            child_id = self._node_id(target_level, int(row.supernode))
            child = nodes_by_id.get(child_id)
            if child is None:
                continue
            child = {**child, "membership_overlap": int(row.overlap)}
            children.append(child)
            edges.append(
                {
                    "id": f"contains:{node_id}:{child_id}",
                    "source": node_id,
                    "target": child_id,
                    "relation": "contains",
                    "weight": float(row.overlap),
                    "read_only": True,
                }
            )

        return {
            "metadata": {
                "kind": "hierarchy",
                "label": f"Resolution {source_level} → {target_level}",
                "source_level": source_level,
                "target_level": target_level,
                "parent_id": node_id,
                "total_children": total_children,
                "displayed_children": len(children),
                "truncated": len(children) < total_children,
                "read_only": True,
            },
            "nodes": [parent, *children],
            "edges": edges,
        }

    def hierarchy_view(self, node_id: str, options: Mapping[str, str]) -> dict[str, Any]:
        """Adapt generic query parameters to this format's hierarchy view."""
        return self.hierarchy(
            node_id=node_id,
            target_level=self._optional_int(options, "target_level"),
            max_nodes=self._optional_int(options, "max_nodes") or 600,
        )

    def _metadata(self, conn) -> dict[str, Any]:
        row = conn.execute(
            text("SELECT value_json FROM metadata WHERE key = 'summary' LIMIT 1")
        ).scalar_one_or_none()
        if not row:
            return {}
        try:
            summary = json.loads(row)
        except (TypeError, json.JSONDecodeError):
            return {}
        return {
            key: summary[key]
            for key in ("created_at", "preset", "preset_description", "final_nodes")
            if key in summary
        }

    def _nodes(self, conn, level: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            text(
                """
                SELECT s.supernode, s.size, s.entry_type_counts_json, s.top_tags_json,
                       m.title AS member_title, m.slug AS member_slug, m.entry_id AS member_id
                FROM supernodes AS s
                LEFT JOIN supernode_members AS m
                  ON m.level = s.level
                 AND m.supernode = s.supernode
                 AND m.member_order = 0
                WHERE s.level = :level
                ORDER BY s.supernode
                """
            ),
            {"level": level},
        )
        nodes = []
        for row in rows:
            size = int(row.size)
            type_counts = self._json_dict(row.entry_type_counts_json)
            tags = self._json_list(row.top_tags_json)
            title = (
                row.member_title if size == 1 and row.member_title else f"Cluster of {size} entries"
            )
            nodes.append(
                {
                    "id": self._node_id(level, int(row.supernode)),
                    "title": title,
                    "slug": row.member_slug or f"lrg-{level}-{row.supernode}",
                    "entry_type": self._primary_type(type_counts),
                    "tags": tags,
                    "member_count": size,
                    "source_entry_id": row.member_id if size == 1 else None,
                    "lrg_level": level,
                    "lrg_supernode": int(row.supernode),
                    "hierarchy": {
                        "level": level,
                        "target_levels": list(range(level)),
                    },
                    "read_only": True,
                    "metadata": {
                        "member_count": size,
                        "entry_type_counts": type_counts,
                        "top_tags": tags,
                        "source_entry_id": row.member_id if size == 1 else None,
                        "lrg_level": level,
                    },
                }
            )
        return nodes

    def _edges(self, conn, level: int) -> list[dict[str, Any]]:
        return [
            {
                "id": f"lrg:{level}:{row.source_supernode}:{row.target_supernode}",
                "source": self._node_id(level, int(row.source_supernode)),
                "target": self._node_id(level, int(row.target_supernode)),
                "weight": float(row.weight),
                "relation": "",
                "read_only": True,
            }
            for row in conn.execute(
                text(
                    """
                    SELECT source_supernode, target_supernode, weight
                    FROM coarse_edges
                    WHERE level = :level
                    ORDER BY source_supernode, target_supernode
                    """
                ),
                {"level": level},
            )
        ]

    def _matching_members(self, conn, level: int, query: str) -> dict[str, list[str]]:
        """Return matching member titles, grouped by their LRG supernode."""
        rows = conn.execute(
            text(
                """
                SELECT supernode, title, slug
                FROM supernode_members
                WHERE level = :level
                  AND (
                    LOWER(COALESCE(title, '')) LIKE :pattern
                    OR LOWER(COALESCE(slug, '')) LIKE :pattern
                    OR LOWER(COALESCE(entry_id, '')) LIKE :pattern
                  )
                ORDER BY supernode, member_order
                """
            ),
            {"level": level, "pattern": f"%{query}%"},
        )
        matches: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            node_id = self._node_id(level, int(row.supernode))
            # Showing a small sample is enough to explain a cluster match and
            # avoids making the graph payload balloon for broad queries.
            if len(matches[node_id]) < 3:
                matches[node_id].append(row.title or row.slug or "Unnamed member")
        return dict(matches)

    @staticmethod
    def _node_id(level: int, supernode: int) -> str:
        return f"lrg:{level}:{supernode}"

    @staticmethod
    def _parse_node_id(node_id: str) -> tuple[int, int]:
        match = re.fullmatch(r"lrg:(\d+):(\d+)", node_id)
        if not match:
            raise ValueError(f"Invalid LRG node ID {node_id}")
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _json_dict(value: str | None) -> dict[str, Any]:
        try:
            result = json.loads(value or "{}")
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        try:
            result = json.loads(value or "[]")
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _primary_type(type_counts: dict[str, Any]) -> str:
        if not type_counts:
            return "generic"
        return max(type_counts, key=lambda key: (type_counts[key], key))

    @staticmethod
    def _optional_int(options: Mapping[str, str], key: str) -> int | None:
        value = options.get(key)
        return int(value) if value not in (None, "") else None


DATASET_ADAPTERS: tuple[type[GraphDatasetAdapter], ...] = (LrgDataset,)


def get_dataset_adapter(engine: Engine, *, entry_count: int) -> GraphDatasetAdapter | None:
    """Return a non-KDG adapter only when the native graph has no entries.

    This preference keeps a database that happens to contain analytical tables
    behaving as a normal editable Know-Do Graph database.
    """
    if entry_count != 0:
        return None
    for adapter_type in DATASET_ADAPTERS:
        if adapter_type.is_compatible(engine):
            return adapter_type(engine)
    return None
