from __future__ import annotations

from typing import Optional

import networkx as nx

from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry


class KnowDoGraph:
    """In-memory directed graph backed by networkx.

    Entries are nodes; edges represent semantic relations between them.
    This is rebuilt from the database on startup and kept in sync during
    the process lifetime.
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_entry(self, entry: Entry) -> None:
        self._g.add_node(
            entry.id,
            title=entry.title,
            slug=entry.slug,
            entry_type=entry.entry_type.value,
            tags=entry.tags,
        )

    def remove_entry(self, entry_id: str) -> None:
        if self._g.has_node(entry_id):
            self._g.remove_node(entry_id)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(self, edge: Edge) -> None:
        self._g.add_edge(
            edge.source_id,
            edge.target_id,
            id=edge.id,
            relation=edge.relation.value if hasattr(edge.relation, "value") else edge.relation,
            weight=edge.weight,
        )

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
                    neighbors.append({"id": nbr, "direction": "out", **data})

        if direction in ("in", "both"):
            for nbr in self._g.predecessors(entry_id):
                data = dict(self._g.edges[nbr, entry_id])
                if _matches(data):
                    neighbors.append({"id": nbr, "direction": "in", **data})

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

    def get_subgraph(self, entry_id: str, depth: int = 2) -> nx.DiGraph:
        """Return an ego-subgraph centred on entry_id up to *depth* hops."""
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
        }

    def rebuild_from_db(self, entries: list[Entry], edges: list[Edge]) -> None:
        """Clear and rebuild the graph from persisted entries and edges."""
        self._g.clear()
        for entry in entries:
            self.add_entry(entry)
        for edge in edges:
            self.add_edge(edge)
