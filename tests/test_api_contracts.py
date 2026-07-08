from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import entries as entries_routes
from api.routes import graph as graph_routes
from api.routes import mem as mem_routes
from api.routes import remote_sync as remote_sync_routes
from api.routes import retrieve as retrieve_routes
from core.storage.database import bind_session_factory, get_db
from know_do_graph import EdgeRelation, EntryType, KnowDoGraph


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.graph = KnowDoGraph(root / "graph.db", memory_dir=root / "memory")
        self._route_graphs = (
            entries_routes._graph,
            graph_routes._graph,
            remote_sync_routes._graph,
            retrieve_routes._graph,
        )
        entries_routes._graph = self.graph._graph
        graph_routes._graph = self.graph._graph
        remote_sync_routes._graph = self.graph._graph
        retrieve_routes._graph = self.graph._graph

        app = FastAPI()
        app.include_router(entries_routes.router, prefix="/entries")
        app.include_router(graph_routes.router, prefix="/graph")
        app.include_router(mem_routes.router, prefix="/mem")
        app.include_router(remote_sync_routes.router, prefix="/remote-sync")
        app.include_router(retrieve_routes.router, prefix="/retrieve")

        def override_get_db():
            db = self.graph._session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        entries_routes._graph = self._route_graphs[0]
        graph_routes._graph = self._route_graphs[1]
        remote_sync_routes._graph = self._route_graphs[2]
        retrieve_routes._graph = self._route_graphs[3]
        self.graph.close()
        self.temp_dir.cleanup()

    def test_entries_list_and_search_are_paginated_contracts(self) -> None:
        self.graph.add(
            "Relax Crystal",
            content="Relax an atomistic crystal structure.",
            entry_type=EntryType.capability,
            aliases=["relax"],
        )

        listed = self.client.get("/entries/")
        self.assertEqual(listed.status_code, 200)
        listed_body = listed.json()
        self.assertEqual(listed_body["pagination"]["count"], 1)
        self.assertEqual(listed_body["items"][0]["slug"], "relax-crystal")

        searched = self.client.get("/entries/search?q=crystal&include_scores=true")
        self.assertEqual(searched.status_code, 200)
        searched_body = searched.json()
        self.assertEqual(searched_body["pagination"]["count"], 1)
        self.assertEqual(searched_body["items"][0]["title"], "Relax Crystal")
        self.assertIn("_score", searched_body["items"][0])

    def test_graph_routes_return_declared_contracts(self) -> None:
        source = self.graph.add("Source Skill", entry_type=EntryType.capability)
        target = self.graph.add("Target Procedure", entry_type=EntryType.procedure)
        self.graph.connect(source.id, target.id, relation=EdgeRelation.decomposes_to)

        full_graph = self.client.get("/graph/full")
        self.assertEqual(full_graph.status_code, 200)
        body = full_graph.json()
        self.assertEqual(body["metadata"]["nodes"], 2)
        self.assertEqual(len(body["nodes"]), 2)
        self.assertEqual(len(body["edges"]), 1)

        path = self.client.get(f"/graph/path?source={source.id}&target={target.id}")
        self.assertEqual(path.status_code, 200)
        self.assertEqual(path.json()["paths"], [[source.id, target.id]])

    def test_progressive_retrieve_entries_include_level_alias(self) -> None:
        self.graph.add(
            "Generate Interface",
            content="Build a coherent materials interface.",
            entry_type=EntryType.capability,
        )

        response = self.client.get("/retrieve/plan?goal=materials%20interface&mode=keyword")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["entry_type"], "capability")
        self.assertEqual(body[0]["_level"], "L1")

    def test_memory_routes_return_declared_contracts(self) -> None:
        with bind_session_factory(self.graph._session_factory):
            first = self.client.post(
                "/mem/api-session/add",
                json={"content": "First useful trace", "tags": ["api"]},
            )
            second = self.client.post(
                "/mem/api-session/add",
                json={"content": "Second useful trace", "tags": ["api"]},
            )
            self.assertEqual(first.status_code, 201)
            self.assertEqual(second.status_code, 201)

            listed = self.client.get("/mem/api-session")
            self.assertEqual(listed.status_code, 200)
            listed_body = listed.json()
            self.assertEqual(listed_body["session_id"], "api-session")
            self.assertEqual(listed_body["pagination"]["count"], 2)
            self.assertEqual(len(listed_body["items"]), 2)

            connected = self.client.post(
                "/mem/api-session/edges",
                json={
                    "source_id": first.json()["id"],
                    "target_id": second.json()["id"],
                    "relation": "related_memory",
                },
            )
            self.assertEqual(connected.status_code, 201)
            self.assertEqual(connected.json()["relation"], "related_memory")

            edges = self.client.get("/mem/api-session/edges")
            self.assertEqual(edges.status_code, 200)
            self.assertEqual(edges.json()["pagination"]["count"], 1)

    def test_remote_sync_source_routes_return_declared_contracts(self) -> None:
        entry = self.graph.add("Remote Source Target")

        attached = self.client.put(
            f"/remote-sync/{entry.id}/source",
            json={"url": "https://example.com/source.md", "sync_now": False},
        )
        self.assertEqual(attached.status_code, 200)
        self.assertEqual(attached.json()["remote_source"]["kind"], "http")
        self.assertIsNone(attached.json()["result"])

        linked = self.client.get("/remote-sync/")
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.json()[0]["entry_id"], entry.id)
        self.assertEqual(linked.json()[0]["remote_source"]["url"], "https://example.com/source.md")

        detached = self.client.delete(f"/remote-sync/{entry.slug}/source")
        self.assertEqual(detached.status_code, 200)
        self.assertEqual(detached.json(), {"detached": True, "entry_id": entry.id})


if __name__ == "__main__":
    unittest.main()
