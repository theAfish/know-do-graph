from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from api.routes import agent as agent_routes
from api.routes import entries as entries_routes
from api.routes import graph as graph_routes
from api.routes import mem as mem_routes
from api.routes import remote_legacy as remote_routes
from api.routes import remote_sync as remote_sync_routes
from api.routes import retrieve as retrieve_routes
from core.storage.database import bind_session_factory, get_db
from know_do_graph import EdgeRelation, EntryType, KnowDoGraph
from know_do_graph.cli.app import app as cli_app


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.graph = KnowDoGraph(root / "graph.db", memory_dir=root / "memory")
        self._route_graphs = (
            entries_routes._graph,
            graph_routes._graph,
            remote_routes._graph,
            remote_sync_routes._graph,
            retrieve_routes._graph,
        )
        entries_routes._graph = self.graph._graph
        graph_routes._graph = self.graph._graph
        remote_routes._graph = self.graph._graph
        remote_sync_routes._graph = self.graph._graph
        retrieve_routes._graph = self.graph._graph

        app = FastAPI()
        app.include_router(agent_routes.router, prefix="/agent")
        app.include_router(entries_routes.router, prefix="/entries")
        app.include_router(graph_routes.router, prefix="/graph")
        app.include_router(mem_routes.router, prefix="/mem")
        app.include_router(remote_routes.router, prefix="/remote")
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
        remote_routes._graph = self._route_graphs[2]
        remote_sync_routes._graph = self._route_graphs[3]
        retrieve_routes._graph = self._route_graphs[4]
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

    def test_agent_routes_return_declared_contracts_without_llm_calls(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            missing_key = self.client.post("/agent/graph/chat", json={"message": "hello"})
        self.assertEqual(missing_key.status_code, 503)

        job_id = "contract-job"
        status = {
            "job_id": job_id,
            "status": "completed",
            "session_id": "api-session",
            "progress": {"completed": 1, "total": 1, "percent": 100},
            "results": [{"entry_id": "entry-1"}],
            "errors": [],
            "summary": "done",
        }
        with agent_routes._memory_review_jobs_lock:
            agent_routes._memory_review_jobs[job_id] = status
        try:
            response = self.client.get(f"/agent/review/memory/{job_id}")
        finally:
            with agent_routes._memory_review_jobs_lock:
                agent_routes._memory_review_jobs.pop(job_id, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), status)

    def test_remote_routes_return_declared_contracts_without_llm_calls(self) -> None:
        entry = self.graph.add(
            "Remote Search Target",
            content="Remote API contract content.",
            entry_type=EntryType.capability,
        )

        search = self.client.get("/remote/search?q=contract")
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()[0]["id"], entry.id)
        self.assertIn("snippet", search.json()[0])

        overview = self.client.get("/remote/graph")
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(len(overview.json()["nodes"]), 1)
        self.assertEqual(overview.json()["unreviewed_nodes"], 1)

        with bind_session_factory(self.graph._session_factory):
            feedback = self.client.post(
                "/remote/feedback",
                json={
                    "session_id": "remote-contract",
                    "content": "Stored remote feedback.",
                    "tags": ["contract"],
                },
            )
            self.assertEqual(feedback.status_code, 201)
            self.assertTrue(feedback.json()["stored"])

            submitted = self.client.post(
                "/remote/submit",
                json={
                    "session_id": "remote-contract",
                    "title": "Contract Submission",
                    "content": "Reusable submitted knowledge.",
                },
            )
            self.assertEqual(submitted.status_code, 201)
            self.assertEqual(submitted.json()["tag"], "pending-distillation")

            inbox = self.client.get("/remote/inbox?session_id=remote-contract")
            self.assertEqual(inbox.status_code, 200)
            self.assertEqual(inbox.json()[0]["title"], "Contract Submission")

        with patch.dict("os.environ", {}, clear=True):
            chat = self.client.post("/remote/chat", json={"message": "hello"})
            distill = self.client.post("/remote/distill", json={"dry_run": True})
        self.assertEqual(chat.status_code, 503)
        self.assertEqual(distill.status_code, 503)

    def test_rest_and_public_client_support_same_entry_lifecycle(self) -> None:
        rest_created = self.client.post(
            "/entries/",
            json={
                "title": "REST Lifecycle Node",
                "content": "Initial REST lifecycle content.",
                "entry_type": "capability",
                "tags": ["lifecycle"],
                "aliases": ["rest-life"],
            },
        )
        self.assertEqual(rest_created.status_code, 201)
        rest_id = rest_created.json()["id"]

        rest_search = self.client.get("/entries/search?q=lifecycle")
        self.assertEqual(rest_search.status_code, 200)
        self.assertIn(rest_id, {item["id"] for item in rest_search.json()["items"]})

        rest_alias_get = self.client.get("/entries/rest-life")
        self.assertEqual(rest_alias_get.status_code, 200)
        self.assertEqual(rest_alias_get.json()["id"], rest_id)

        rest_asset = self.client.post(
            f"/entries/{rest_id}/assets",
            json={
                "folder": "scripts",
                "filename": "run.py",
                "kind": "file",
                "content": "print('lifecycle')",
                "language": "python",
            },
        )
        self.assertEqual(rest_asset.status_code, 201)
        self.assertEqual(rest_asset.json()["path"], "scripts/run.py")

        rest_scripts = self.client.get(f"/entries/{rest_id}/scripts")
        self.assertEqual(rest_scripts.status_code, 200)
        self.assertEqual(rest_scripts.json()[0]["filename"], "run.py")

        rest_updated = self.client.put(
            f"/entries/{rest_id}",
            json={**rest_created.json(), "content": "Updated REST lifecycle content."},
        )
        self.assertEqual(rest_updated.status_code, 200)
        self.assertEqual(rest_updated.json()["content"], "Updated REST lifecycle content.")

        rest_feedback = self.client.post(
            f"/entries/{rest_id}/feedback",
            json={"verdict": "works", "note": "REST lifecycle verified."},
        )
        self.assertEqual(rest_feedback.status_code, 201)
        self.assertEqual(rest_feedback.json()["verification_status"], "self_tested")

        rest_deleted = self.client.delete(f"/entries/{rest_id}")
        self.assertEqual(rest_deleted.status_code, 204)
        self.assertIsNone(self.graph.get(rest_id))

        reloaded = self.client.post("/graph/reload")
        self.assertEqual(reloaded.status_code, 200)
        self.assertTrue(reloaded.json()["reloaded"])

        client_created = self.graph.add(
            "Client Lifecycle Node",
            content="Initial client lifecycle content.",
            entry_type=EntryType.capability,
            tags=["lifecycle"],
            aliases=["client-life"],
        )
        self.assertEqual(self.graph.get("client-life").id, client_created.id)
        self.assertEqual(
            self.graph.search("client lifecycle", mode="keyword")[0].id, client_created.id
        )

        client_updated = self.graph.update(
            client_created.id,
            content="Updated client lifecycle content.",
        )
        self.assertEqual(client_updated.content, "Updated client lifecycle content.")

        client_status = self.graph.set_verification_status(client_created.id, "self_tested")
        self.assertEqual(client_status.metadata.verification_status.value, "self_tested")

        self.assertTrue(self.graph.delete(client_created.id))
        self.assertIsNone(self.graph.get(client_created.id))

    def test_remote_instruction_renderer_is_extracted_and_preserves_host(self) -> None:
        response = self.client.get("/remote", headers={"host": "example.test"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("http://example.test/remote/search", response.text)

    def test_cli_entry_lifecycle_uses_same_database_contracts(self) -> None:
        runner = CliRunner()
        with bind_session_factory(self.graph._session_factory):
            with patch("know_do_graph.cli.legacy._init", return_value=None):
                added = runner.invoke(
                    cli_app,
                    [
                        "entry",
                        "add",
                        "CLI Lifecycle Node",
                        "--content",
                        "CLI lifecycle content.",
                        "--type",
                        "capability",
                        "--tags",
                        "lifecycle",
                    ],
                )
                self.assertEqual(added.exit_code, 0, added.output)

                self.graph.refresh()
                entry = self.graph.search("CLI lifecycle", mode="keyword")[0]
                self.assertEqual(entry.title, "CLI Lifecycle Node")

                shown = runner.invoke(cli_app, ["entry", "show", entry.slug])
                self.assertEqual(shown.exit_code, 0, shown.output)
                self.assertIn("CLI lifecycle content.", shown.output)

                deleted = runner.invoke(cli_app, ["entry", "delete", entry.id, "--yes"])
                self.assertEqual(deleted.exit_code, 0, deleted.output)

        self.graph.refresh()
        self.assertIsNone(self.graph.get(entry.id))


if __name__ == "__main__":
    unittest.main()
