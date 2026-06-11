from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from know_do_graph import (
    EdgeRelation,
    EntryMetadata,
    EntryType,
    KnowDoGraph,
    ReviewPolicy,
    VerificationStatus,
)


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
        self.assertEqual(self.graph.get(trace.id).entry_type, EntryType.memory)
        self.assertFalse((self.graph.memory_dir / "agent-run.json").exists())

        follow_up = memory.add("The result reproduced on a second structure.")
        edge = memory.connect(trace.id, follow_up.id)
        self.assertEqual(edge.relation, EdgeRelation.related_memory)
        self.assertEqual(memory.edges(trace.id)[0].target_id, follow_up.id)

    def test_clients_are_isolated_by_database_path(self) -> None:
        other_path = Path(self.temp_dir.name) / "other.db"
        with KnowDoGraph(other_path) as other:
            other.add("Only in other graph")
            self.assertEqual(other.stats()["nodes"], 1)
        self.assertEqual(self.graph.stats()["nodes"], 0)

    def test_review_counts_and_global_unreviewed_metadata(self) -> None:
        from agents.review_agent.tools import mark_reviewed
        from core.storage.database import bind_session_factory

        first = self.graph.add(
            "First review target",
            metadata=EntryMetadata(review_count=7, modify_count=3),
        )
        second = self.graph.add("Second review target")

        self.assertEqual(first.metadata.review_count, 0)
        self.assertEqual(first.metadata.modify_count, 0)
        self.assertEqual(self.graph.stats()["unreviewed_nodes"], 2)

        with bind_session_factory(self.graph._session_factory):
            mark_reviewed(first.id, graph=self.graph._graph)
            mark_reviewed(first.id, graph=self.graph._graph)

        self.assertEqual(self.graph.get(first.id).metadata.review_count, 2)
        self.assertEqual(self.graph.stats()["unreviewed_nodes"], 1)

        self.assertTrue(self.graph.delete(second.id))
        self.assertEqual(self.graph.stats()["unreviewed_nodes"], 0)

    def test_review_agent_status_limits_and_manual_status_api(self) -> None:
        from agents.review_agent.tools import update_entry
        from core.storage.database import bind_session_factory

        entry = self.graph.add("Verification target")
        with bind_session_factory(self.graph._session_factory):
            rejected = update_entry(
                entry.id,
                verification_status="peer_reviewed",
                graph=self.graph._graph,
            )
            accepted = update_entry(
                entry.id,
                verification_status="self_tested",
                graph=self.graph._graph,
            )

        self.assertIn("error", rejected)
        self.assertEqual(accepted["verification_status"], "self_tested")
        reviewed = self.graph.get(entry.id)
        self.assertEqual(reviewed.metadata.review_count, 1)
        self.assertEqual(
            reviewed.metadata.verification_status,
            VerificationStatus.self_tested,
        )
        self.assertEqual(self.graph.stats()["unreviewed_nodes"], 0)

        manually_updated = self.graph.set_verification_status(
            entry.id,
            VerificationStatus.community_tested,
        )
        self.assertEqual(
            manually_updated.metadata.verification_status,
            VerificationStatus.community_tested,
        )
        self.assertEqual(manually_updated.metadata.review_count, 1)

    def test_review_policy_filters_and_enforces_mutations(self) -> None:
        from agents.review_agent.tools import (
            create_edge,
            delete_entry,
            sample_nodes_for_review,
            update_entry,
        )
        from core.storage.database import bind_session_factory

        protected = self.graph.add("Protected Knowledge")
        protected = self.graph.set_verification_status(
            protected.id, VerificationStatus.peer_reviewed
        )
        ordinary = self.graph.add("Ordinary Knowledge")
        memory = self.graph.memory("review-policy").add("Transient trace")
        policy = ReviewPolicy(
            exclude_types={EntryType.memory},
            protected_statuses={VerificationStatus.peer_reviewed},
            assignable_statuses={VerificationStatus.bugged},
            allowed_actions={"modify", "link"},
        )

        with bind_session_factory(self.graph._session_factory):
            sampled = sample_nodes_for_review(
                batch_size=10,
                strategy="global",
                graph=self.graph._graph,
                policy=policy,
            )
            denied = update_entry(
                protected.id,
                title="Changed",
                graph=self.graph._graph,
                policy=policy,
            )
            assigned = update_entry(
                ordinary.id,
                verification_status="bugged",
                graph=self.graph._graph,
                policy=policy,
            )
            deletion = delete_entry(ordinary.id, graph=self.graph._graph, policy=policy)
            linked = create_edge(
                protected.id,
                ordinary.id,
                relation="related_workflow",
                graph=self.graph._graph,
                policy=policy,
            )

        self.assertNotIn(memory.id, {item["id"] for item in sampled})
        self.assertNotIn(protected.id, {item["id"] for item in sampled})
        self.assertIn(ordinary.id, {item["id"] for item in sampled})
        self.assertIn("protected", denied["error"])
        self.assertEqual(assigned["verification_status"], "bugged")
        self.assertIn("not permitted", deletion["error"])
        self.assertNotIn("error", linked)

    def test_structured_review_nodes_progress(self) -> None:
        from agents.review_agent.agent import ReviewAgent
        from core.storage.database import bind_session_factory

        entry = self.graph.add("Structured Review Target")
        statuses = []
        agent = ReviewAgent(
            self.graph._graph,
            api_key="test-key",
            batch_size=1,
            strategy="global",
            on_status=statuses.append,
        )

        def fake_run_loop(_history, *, tools, observe_result):
            self.assertNotIn(
                "sample_nodes_for_review",
                {tool["function"]["name"] for tool in tools},
            )
            outcome = agent._dispatch(
                "mark_reviewed",
                f'{{"entry_id": "{entry.id}"}}',
            )
            observe_result("mark_reviewed", outcome)
            return "Reviewed one node."

        with bind_session_factory(self.graph._session_factory):
            with patch.object(agent, "_run_loop", side_effect=fake_run_loop):
                result = agent.review_nodes()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["strategy"], "global")
        self.assertEqual(result["progress"], {"completed": 1, "total": 1, "percent": 100})
        self.assertEqual(statuses[0]["status"], "running")
        self.assertEqual(statuses[-1]["status"], "completed")

    def test_auto_review_threshold_scheduler(self) -> None:
        with patch("know_do_graph.review.Thread") as thread:
            scheduler = self.graph.auto_review(threshold=2, api_key="test-key")
            self.graph.add("First Scheduled Node")
            thread.assert_not_called()
            self.graph.add("Second Scheduled Node")

        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["name"], "kdg-auto-review")
        self.assertTrue(thread.call_args.kwargs["daemon"])
        scheduler.stop()
        self.assertNotIn(scheduler, self.graph._auto_reviewers)

    def test_auto_review_counts_only_policy_candidates(self) -> None:
        from agents.review_agent.tools import mark_reviewed
        from core.storage.database import bind_session_factory

        policy = ReviewPolicy(
            exclude_types={EntryType.memory},
            protected_statuses={VerificationStatus.peer_reviewed},
        )
        reviewed = self.graph.add("Already reviewed")
        with bind_session_factory(self.graph._session_factory):
            mark_reviewed(reviewed.id, graph=self.graph._graph, policy=policy)

        with patch("know_do_graph.review.Thread") as thread:
            scheduler = self.graph.auto_review(threshold=1, policy=policy)
            self.graph.add("Excluded memory", entry_type=EntryType.memory)
            self.graph.add(
                "Protected node",
                metadata=EntryMetadata(
                    verification_status=VerificationStatus.peer_reviewed
                ),
            )
            scheduler.notify_node_created(self.graph.get(reviewed.id))

            thread.assert_not_called()
            self.graph.add("Eligible node")

        thread.assert_called_once()
        scheduler.stop()

    def test_auto_review_can_include_existing_backlog(self) -> None:
        self.graph.add("Existing candidate one")
        self.graph.add("Existing candidate two")

        with patch("know_do_graph.review.Thread") as thread:
            default_scheduler = self.graph.auto_review(threshold=2)
            thread.assert_not_called()
            backlog_scheduler = self.graph.auto_review(
                threshold=2,
                include_existing=True,
            )

        thread.assert_called_once()
        self.assertEqual(backlog_scheduler.created_since_review, 0)
        default_scheduler.stop()
        backlog_scheduler.stop()

    def test_auto_review_existing_backlog_respects_policy(self) -> None:
        self.graph.add("Existing memory", entry_type=EntryType.memory)
        protected = self.graph.add("Existing protected node")
        self.graph.set_verification_status(
            protected.id, VerificationStatus.peer_reviewed
        )
        self.graph.add("Existing eligible node")
        policy = ReviewPolicy(
            exclude_types={EntryType.memory},
            protected_statuses={VerificationStatus.peer_reviewed},
        )

        with patch("know_do_graph.review.Thread") as thread:
            scheduler = self.graph.auto_review(
                threshold=2,
                policy=policy,
                include_existing=True,
            )

        thread.assert_not_called()
        self.assertEqual(scheduler.created_since_review, 1)
        scheduler.stop()

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

    def test_memory_distillation_tools_enforce_hierarchy(self) -> None:
        from agents.review_agent.tools import distill_memory, sample_memory_nodes
        from core.storage.database import bind_session_factory

        capability = self.graph.add(
            "Validate Relaxation",
            content="Check whether an atomistic relaxation converged.",
            entry_type=EntryType.capability,
        )
        memory = self.graph.memory("matcreator")
        l1_trace = memory.add("Reusable capability: generate coherent interfaces.")
        l3_trace = memory.add("Prefer lower mismatch when two interface matches are available.")
        noise_trace = memory.add("Still running, will report back soon.")
        other_trace = self.graph.memory("other-session").add("Unrelated session memory.")

        with bind_session_factory(self.graph._session_factory):
            sampled = sample_memory_nodes(
                batch_size=10,
                session_id="matcreator",
                graph=self.graph._graph,
            )
            self.assertEqual(
                {item["id"] for item in sampled},
                {l1_trace.id, l3_trace.id, noise_trace.id},
            )
            self.assertNotIn(other_trace.id, {item["id"] for item in sampled})

            promoted = distill_memory(
                l1_trace.id,
                "L1",
                title="Generate Coherent Interfaces",
                reason="Reusable high-level ability",
                graph=self.graph._graph,
            )
            linked = distill_memory(
                l3_trace.id,
                "L3",
                title="Prefer Lower Interface Mismatch",
                target_id=capability.id,
                reason="Conditional operational guidance",
                graph=self.graph._graph,
            )
            deleted = distill_memory(
                noise_trace.id,
                "noise",
                reason="Transient status only",
                graph=self.graph._graph,
            )

        promoted_entry = self.graph.get(promoted["entry"]["id"])
        self.assertEqual(promoted["action"], "promoted")
        self.assertEqual(promoted_entry.entry_type, EntryType.capability)
        self.assertEqual(
            promoted_entry.metadata.verification_status,
            VerificationStatus.unverified,
        )
        self.assertEqual(linked["action"], "linked")
        self.assertEqual(self.graph.get(linked["entry"]["id"]).entry_type, EntryType.heuristic)
        self.assertEqual(
            self.graph.related(
                linked["entry"]["id"],
                relation=EdgeRelation.heuristic_for,
            )[0].id,
            capability.id,
        )
        self.assertEqual(deleted["action"], "deleted")
        self.assertIsNone(self.graph.get(noise_trace.id))
        self.assertTrue(promoted["source_memory_deleted"])
        self.assertTrue(linked["source_memory_deleted"])
        self.assertIsNone(self.graph.get(l1_trace.id))
        self.assertIsNone(self.graph.get(l3_trace.id))
        self.assertEqual(self.graph.memory("matcreator").list(), [])
        self.assertIsNone(promoted_entry.metadata.source_provenance)
        self.assertNotIn("distilled_from_memory", promoted_entry.metadata.custom)

    def test_memory_review_returns_structured_progress(self) -> None:
        from agents.review_agent.agent import ReviewAgent
        from core.storage.database import bind_session_factory

        trace = self.graph.memory("matcreator").add(
            "A reusable procedure for checking force convergence."
        )
        statuses = []
        agent = ReviewAgent(
            self.graph._graph,
            api_key="test-key",
            batch_size=5,
            on_status=statuses.append,
        )

        def fake_run_loop(_history, *, tools, dispatch, observe_result):
            self.assertTrue(tools)
            result = agent._dispatch(
                "distill_memory",
                (
                    '{"memory_id": "%s", "classification": "L2", '
                    '"title": "Check Force Convergence", '
                    '"reason": "Reusable execution procedure"}'
                )
                % trace.id,
                dispatch=dispatch,
            )
            observe_result("distill_memory", result)
            return "Created one L2 procedure."

        with bind_session_factory(self.graph._session_factory):
            with patch.object(agent, "_run_loop", side_effect=fake_run_loop):
                result = agent.run_memory_review(session_id="matcreator")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["progress"], {"completed": 1, "total": 1, "percent": 100})
        self.assertEqual(result["results"][0]["classification"], "L2")
        self.assertEqual(statuses[0]["status"], "running")
        self.assertEqual(statuses[-1]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
