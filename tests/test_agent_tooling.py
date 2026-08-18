from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.graph_agent.agent import GraphAgent
from agents.graph_agent.tools.registry import GRAPH_TOOL_REGISTRY, MUTATING_TOOLS
from agents.review_agent.agent import ReviewAgent
from agents.review_agent.tools.registry import REVIEW_TOOL_REGISTRY
from agents.tooling import normalize_tool_result
from core.schemas.entry import EntryType, VerificationStatus
from core.storage.database import bind_session_factory
from know_do_graph import KnowDoGraph, ReviewPolicy


class AgentToolingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.graph = KnowDoGraph(root / "graph.db", memory_dir=root / "memory")

    def tearDown(self) -> None:
        self.graph.close()
        self.temp_dir.cleanup()

    def test_tool_result_normalization_preserves_payload(self) -> None:
        self.assertEqual(normalize_tool_result({"id": "1"}), {"ok": True, "id": "1"})
        self.assertEqual(
            normalize_tool_result({"error": "bad"}),
            {"ok": False, "error": "bad"},
        )
        self.assertEqual(normalize_tool_result([{"id": "1"}]), [{"id": "1"}])

    def test_graph_registry_mutating_tools_use_bound_database(self) -> None:
        with bind_session_factory(self.graph._session_factory):
            created = GRAPH_TOOL_REGISTRY.call(
                "create_entry",
                json.dumps(
                    {
                        "title": "Agent Tool Node",
                        "content": "Created through the registry.",
                        "entry_type": "capability",
                    }
                ),
                extra_kwargs={"graph": self.graph._graph},
            )
            updated = GRAPH_TOOL_REGISTRY.call(
                "update_entry",
                json.dumps({"entry_id": created["id"], "tags": ["agent-tooling"]}),
                extra_kwargs={"graph": self.graph._graph},
            )
            asset = GRAPH_TOOL_REGISTRY.call(
                "add_asset_to_entry",
                json.dumps(
                    {
                        "entry_id": created["id"],
                        "folder": "docs",
                        "filename": "note.md",
                        "content": "Tool registry asset.",
                        "kind": "text",
                    }
                ),
                extra_kwargs={"graph": self.graph._graph},
            )
            feedback = GRAPH_TOOL_REGISTRY.call(
                "submit_feedback",
                json.dumps({"entry_id": created["id"], "verdict": "works"}),
                extra_kwargs={"graph": self.graph._graph},
            )

        saved = self.graph.get(created["id"])
        self.assertTrue(created["ok"])
        self.assertTrue(updated["ok"])
        self.assertTrue(asset["ok"])
        self.assertTrue(feedback["ok"])
        self.assertEqual(saved.tags, ["agent-tooling"])
        self.assertEqual(saved.assets[0].filename, "note.md")
        self.assertEqual(saved.metadata.verification_status, VerificationStatus.self_tested)

    def test_graph_registry_edge_mutations_use_bound_database(self) -> None:
        source = self.graph.add("Source Capability", entry_type=EntryType.capability)
        target = self.graph.add("Target Procedure", entry_type=EntryType.procedure)
        with bind_session_factory(self.graph._session_factory):
            created = GRAPH_TOOL_REGISTRY.call(
                "create_edge",
                json.dumps(
                    {
                        "source_id": source.id,
                        "target_id": target.id,
                        "relation": "decomposes_to",
                    }
                ),
                extra_kwargs={"graph": self.graph._graph},
            )
            deleted = GRAPH_TOOL_REGISTRY.call(
                "delete_edge",
                json.dumps({"edge_id": created["id"]}),
                extra_kwargs={"graph": self.graph._graph},
            )

        self.assertTrue(created["ok"])
        self.assertTrue(deleted["ok"])
        self.assertEqual(self.graph.related(source.id), [])

    def test_graph_registry_exercises_every_mutating_tool(self) -> None:
        base = self.graph.add("Registry Base Capability", entry_type=EntryType.capability)
        procedure = self.graph.add("Registry Base Procedure", entry_type=EntryType.procedure)
        duplicate = self.graph.add(
            "Registry Duplicate Capability",
            entry_type=EntryType.capability,
            tags=["duplicate"],
            aliases=["registry-duplicate"],
        )
        delete_target = self.graph.add("Registry Delete Target", entry_type=EntryType.capability)
        self.graph.add("Registry Wikilink Target", entry_type=EntryType.tool)
        self.graph.add(
            "Registry Wikilink Source",
            content="Uses [[Registry Wikilink Target]].",
            entry_type=EntryType.procedure,
        )

        results: dict[str, dict] = {}

        def call_tool(name: str, payload: dict | None = None) -> dict:
            result = GRAPH_TOOL_REGISTRY.call(
                name,
                json.dumps(payload or {}),
                extra_kwargs={"graph": self.graph._graph},
            )
            self.assertIsInstance(result, dict)
            self.assertIn("ok", result)
            results[name] = result
            return result

        with bind_session_factory(self.graph._session_factory):
            created = call_tool(
                "create_entry",
                {
                    "title": "Registry Created Capability",
                    "content": "Created by the all-mutating-tools coverage test.",
                    "entry_type": "capability",
                },
            )
            call_tool("update_entry", {"entry_id": base.id, "tags": ["registry-base"]})
            edge = call_tool(
                "create_edge",
                {
                    "source_id": base.id,
                    "target_id": procedure.id,
                    "relation": "decomposes_to",
                },
            )
            call_tool("delete_edge", {"edge_id": edge["id"]})
            call_tool(
                "merge_entries",
                {"primary_id": base.id, "duplicate_id": duplicate.id},
            )
            call_tool("delete_entry", {"entry_id": delete_target.id})
            call_tool("resolve_wikilinks")
            call_tool("remove_dangling_edges")
            call_tool(
                "create_script_entry",
                {
                    "title": "Deprecated Registry Script",
                    "code": "print('deprecated')",
                },
            )
            call_tool(
                "add_script_to_entry",
                {
                    "entry_id": created["id"],
                    "code": "print('registry')",
                    "filename": "registry.py",
                },
            )
            call_tool(
                "attach_script_to_entry",
                {"entry_id": base.id, "script_id": created["id"]},
            )
            call_tool(
                "add_asset_to_entry",
                {
                    "entry_id": created["id"],
                    "folder": "docs",
                    "filename": "registry.md",
                    "content": "Registry asset coverage.",
                    "kind": "text",
                },
            )
            call_tool(
                "build_material_interface_workflow",
                {"material_a": "Si", "material_b": "Ge"},
            )
            call_tool(
                "create_material_entry",
                {
                    "formula": "Si",
                    "crystal_system": "cubic",
                    "space_group": "Fd-3m",
                },
            )
            call_tool("submit_feedback", {"entry_id": base.id, "verdict": "works"})
            call_tool(
                "create_heuristic",
                {
                    "skill": base.id,
                    "title": "Registry Heuristic",
                    "content": "Use small batches when validating registry behavior.",
                },
            )
            call_tool(
                "create_constraint",
                {
                    "skill": base.id,
                    "title": "Registry Constraint",
                    "content": "Deprecated registry tools intentionally return errors.",
                },
            )
            call_tool(
                "decompose_capability",
                {"capability": base.id, "procedure": procedure.id},
            )

        self.assertEqual(set(results), set(MUTATING_TOOLS))
        expected_deprecated = {
            "attach_script_to_entry",
            "build_material_interface_workflow",
            "create_script_entry",
        }
        for name, result in results.items():
            if name in expected_deprecated:
                self.assertFalse(result["ok"], name)
                self.assertIn("deprecated", result["error"])
            else:
                self.assertTrue(result["ok"], name)

    def test_graph_agent_read_only_blocks_mutation_and_network_tools(self) -> None:
        with patch.dict("os.environ", {"KDG_ENABLE_NETWORK_TOOLS": ""}, clear=False):
            agent = GraphAgent(self.graph._graph, api_key="test-key", read_only=True)

        schema_names = {schema["function"]["name"] for schema in agent._tool_schemas}
        self.assertNotIn("create_entry", schema_names)
        self.assertNotIn("fetch_url", schema_names)

        denied = agent._dispatch("create_entry", '{"title": "Should Not Write"}')
        network = agent._dispatch("fetch_url", '{"url": "https://example.com"}')
        self.assertFalse(denied["ok"])
        self.assertIn("read-only", denied["error"])
        self.assertFalse(network["ok"])
        self.assertIn("KDG_ENABLE_NETWORK_TOOLS", network["error"])

    def test_review_registry_enforces_policy(self) -> None:
        protected = self.graph.add(
            "Protected Entry",
            entry_type=EntryType.capability,
            metadata={"verification_status": "peer_reviewed"},
        )
        removable = self.graph.add("Removable Entry", entry_type=EntryType.capability)
        policy = ReviewPolicy(
            protected_statuses={VerificationStatus.peer_reviewed},
            allowed_actions={"modify"},
        )
        agent = ReviewAgent(self.graph._graph, api_key="test-key", policy=policy)

        with bind_session_factory(self.graph._session_factory):
            protected_result = agent._dispatch(
                "update_entry",
                json.dumps({"entry_id": protected.id, "title": "Changed"}),
                dispatch=REVIEW_TOOL_REGISTRY,
            )
            denied_delete = agent._dispatch(
                "delete_entry",
                json.dumps({"entry_id": removable.id}),
                dispatch=REVIEW_TOOL_REGISTRY,
            )

        self.assertFalse(protected_result["ok"])
        self.assertIn("protected verification status", protected_result["error"])
        self.assertFalse(denied_delete["ok"])
        self.assertIn("not permitted", denied_delete["error"])


if __name__ == "__main__":
    unittest.main()
