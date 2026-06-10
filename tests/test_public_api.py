from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from know_do_graph import EdgeRelation, EntryType, KnowDoGraph


class PublicApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.graph = KnowDoGraph(root / "graph.db", memory_dir=root / "memory")

    def tearDown(self) -> None:
        self.graph.close()
        self.temp_dir.cleanup()

    def test_entry_lifecycle_search_and_relations(self) -> None:
        capability = self.graph.add(
            "Structure Relaxation",
            content="Relax a crystal structure.",
            entry_type="capability",
            tags=["atomistic"],
            aliases=["relax"],
        )
        procedure = self.graph.add(
            "ASE FIRE Procedure",
            content="Execute FIRE optimization.",
            entry_type=EntryType.procedure,
            tags=["atomistic"],
        )

        self.assertEqual(self.graph.get("relax").id, capability.id)
        self.assertEqual(self.graph.search("crystal", mode="keyword")[0].id, capability.id)

        edge = self.graph.connect(
            capability.slug,
            procedure.slug,
            relation=EdgeRelation.decomposes_to,
        )
        self.assertEqual(edge.source_id, capability.id)
        self.assertEqual(self.graph.related(capability.id)[0].id, procedure.id)

        updated = self.graph.update(capability.id, content="Updated [[ASE FIRE Procedure]].")
        self.assertEqual(updated.internal_refs, ["ASE FIRE Procedure"])
        self.assertTrue(self.graph.delete(procedure.slug))
        self.assertIsNone(self.graph.get(procedure.id))

    def test_progressive_retrieval_and_memory(self) -> None:
        capability = self.graph.add(
            "Generate Interface",
            content="Build a coherent materials interface.",
            entry_type=EntryType.capability,
        )
        heuristic = self.graph.add(
            "Prefer low mismatch",
            content="Choose the match with lower strain.",
            entry_type=EntryType.heuristic,
        )
        self.graph.connect(
            heuristic.id,
            capability.id,
            relation=EdgeRelation.heuristic_for,
        )

        planned = self.graph.plan("materials interface", mode="keyword")
        self.assertEqual(planned[0].id, capability.id)
        self.assertEqual(self.graph.heuristics(capability.slug)[0].id, heuristic.id)

        memory = self.graph.memory("agent-run")
        trace = memory.add("The low-strain match succeeded.", success=True)
        self.assertEqual(memory.get(trace.id).content, trace.content)
        self.assertTrue((self.graph.memory_dir / "agent-run.json").is_file())

    def test_clients_are_isolated_by_database_path(self) -> None:
        other_path = Path(self.temp_dir.name) / "other.db"
        with KnowDoGraph(other_path) as other:
            other.add("Only in other graph")
            self.assertEqual(other.stats()["nodes"], 1)
        self.assertEqual(self.graph.stats()["nodes"], 0)

    def test_chat_tools_are_bound_to_the_client_database(self) -> None:
        self.graph.add("Client-owned entry")
        fake_module = ModuleType("agents.graph_agent.agent")

        class FakeGraphAgent:
            def __init__(self, **_kwargs) -> None:
                self.messages: list[str] = []

            def chat(self, message: str) -> str:
                from core.storage.database import SessionLocal
                from core.storage.models import EntryModel

                self.messages.append(message)
                with SessionLocal() as db:
                    count = db.query(EntryModel).count()
                return f"{message}:{count}:{len(self.messages)}"

            def reset(self) -> None:
                self.messages.clear()

        fake_module.GraphAgent = FakeGraphAgent
        with patch.dict("sys.modules", {"agents.graph_agent.agent": fake_module}):
            chat = self.graph.chat(api_key="test-key")
            self.assertEqual(chat.send("first"), "first:1:1")
            self.assertEqual(chat.send("second"), "second:1:2")
            chat.reset()
            self.assertEqual(chat.send("again"), "again:1:1")


if __name__ == "__main__":
    unittest.main()
