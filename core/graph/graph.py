from __future__ import annotations

import logging
from typing import Optional

import networkx as nx

from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, entry_type_value

logger = logging.getLogger(__name__)


class KnowDoGraph:
    """In-memory directed graph backed by networkx.

    Entries are nodes; edges represent semantic relations between them.
    This is rebuilt from the database on startup and kept in sync during
    the process lifetime.
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        self._g.graph["unreviewed_nodes"] = 0

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_entry(self, entry: Entry) -> None:
        md = entry.metadata
        existed = self._g.has_node(entry.id)
        was_unreviewed = (
            existed and self._g.nodes[entry.id].get("review_count", 0) == 0
        )
        is_unreviewed = md.review_count == 0
        if not existed and is_unreviewed:
            self._g.graph["unreviewed_nodes"] += 1
        elif existed and was_unreviewed != is_unreviewed:
            self._g.graph["unreviewed_nodes"] += 1 if is_unreviewed else -1
        timestamp = md.timestamp.isoformat() if getattr(md, "timestamp", None) else None
        verification = (
            md.verification_status.value
            if hasattr(md.verification_status, "value")
            else md.verification_status
        )
        # Effective hierarchical-memory level (explicit override > entry_type default).
        from core.schemas.entry import implied_level

        level_obj = implied_level(entry.entry_type, md.skill_level)
        level_value = level_obj.value if level_obj else None
        self._g.add_node(
            entry.id,
            title=entry.title,
            slug=entry.slug,
            entry_type=entry_type_value(entry.entry_type),
            tags=entry.tags,
            timestamp=timestamp,
            usage_count=md.usage_count,
            trust_score=md.trust_score,
            verification_status=verification,
            review_count=md.review_count,
            skill_level=level_value,
        )

    def remove_entry(self, entry_id: str) -> None:
        if self._g.has_node(entry_id):
            if self._g.nodes[entry_id].get("review_count", 0) == 0:
                self._g.graph["unreviewed_nodes"] -= 1
            self._g.remove_node(entry_id)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(self, edge: Edge) -> bool:
        """Add an edge to the in-memory graph.

        Returns ``False`` (and logs a warning) if either endpoint is unknown,
        instead of silently letting networkx auto-create a typeless ghost node.
        """
        if not self._g.has_node(edge.source_id) or not self._g.has_node(edge.target_id):
            logger.warning(
                "skipping edge %s → %s (%s): endpoint missing from graph",
                edge.source_id,
                edge.target_id,
                edge.relation.value if hasattr(edge.relation, "value") else edge.relation,
            )
            return False
        self._g.add_edge(
            edge.source_id,
            edge.target_id,
            id=edge.id,
            relation=edge.relation.value if hasattr(edge.relation, "value") else edge.relation,
            weight=edge.weight,
        )
        return True

    def remove_edge(self, source_id: str, target_id: str) -> None:
        if self._g.has_edge(source_id, target_id):
            self._g.remove_edge(source_id, target_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_neighbors(
        self,
        entry_id: str,
        relation: Optional[EdgeRelation] = None,
        direction: str = "both",
    ) -> list[dict]:
        """Return neighboring node IDs with edge metadata.

        direction: "out" (successors), "in" (predecessors), "both"
        """
        if entry_id not in self._g:
            return []

        neighbors: list[dict] = []

        def _matches(data: dict) -> bool:
            if relation is None:
                return True
            rel_val = relation.value if hasattr(relation, "value") else relation
            return data.get("relation") == rel_val

        if direction in ("out", "both"):
            for nbr in self._g.successors(entry_id):
                data = dict(self._g.edges[entry_id, nbr])
                if _matches(data):
                    neighbors.append({
                        **data,
                        "edge_id": data.get("id"),
                        "id": nbr,
                        "direction": "out",
                    })

        if direction in ("in", "both"):
            for nbr in self._g.predecessors(entry_id):
                data = dict(self._g.edges[nbr, entry_id])
                if _matches(data):
                    neighbors.append({
                        **data,
                        "edge_id": data.get("id"),
                        "id": nbr,
                        "direction": "in",
                    })

        return neighbors

    def get_related_ids(
        self,
        entry_id: str,
        depth: int = 1,
        relation: Optional[EdgeRelation] = None,
    ) -> list[str]:
        """BFS from *entry_id* up to *depth* hops, optionally filtered by relation type.

        Returns IDs of all reachable nodes (excluding the start node).
        """
        visited: set[str] = {entry_id}
        frontier: set[str] = {entry_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in frontier:
                for nbr_info in self.get_neighbors(node, relation=relation):
                    nbr_id = nbr_info["id"]
                    if nbr_id not in visited:
                        next_frontier.add(nbr_id)
            frontier = next_frontier
            visited.update(frontier)
        visited.discard(entry_id)
        return list(visited)

    def has_node(self, entry_id: str) -> bool:
        return self._g.has_node(entry_id)

    def get_subgraph(self, entry_id: str, depth: int = 2) -> nx.DiGraph:
        """Return an ego-subgraph centred on entry_id up to *depth* hops."""
        if entry_id not in self._g:
            return nx.DiGraph()
        nodes = {entry_id}
        frontier = {entry_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in frontier:
                next_frontier.update(self._g.successors(node))
                next_frontier.update(self._g.predecessors(node))
            frontier = next_frontier - nodes
            nodes.update(frontier)
        return self._g.subgraph(nodes).copy()

    def find_paths(
        self, source_id: str, target_id: str, cutoff: int = 6
    ) -> list[list[str]]:
        try:
            return list(
                nx.all_simple_paths(self._g, source_id, target_id, cutoff=cutoff)
            )
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            return []

    def stats(self) -> dict:
        return {
            "nodes": self._g.number_of_nodes(),
            "edges": self._g.number_of_edges(),
            "is_dag": nx.is_directed_acyclic_graph(self._g),
            "unreviewed_nodes": self._g.graph["unreviewed_nodes"],
        }

    def rebuild_from_db(self, entries: list[Entry], edges: list[Edge]) -> None:
        """Clear and rebuild the graph from persisted entries and edges.

        Edges whose endpoints are not present in *entries* are skipped (with a
        warning). They survive in the database — the maintenance agent's
        ``remove_dangling_edges`` is responsible for pruning them — but they
        are never allowed to materialise ghost nodes in the in-memory graph.
        """
        self._g.clear()
        self._g.graph["unreviewed_nodes"] = 0
        for entry in entries:
            self.add_entry(entry)
        skipped = 0
        for edge in edges:
            if not self.add_edge(edge):
                skipped += 1
        if skipped:
            logger.warning("rebuild_from_db: skipped %d dangling edge(s)", skipped)
