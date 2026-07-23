import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from core.graph.datasets import LrgDataset, get_dataset_adapter


class LrgDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp_dir.name) / 'lrg.db'}")
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE entries (id TEXT)"))
            conn.execute(text("CREATE TABLE levels (level INTEGER, node_count INTEGER, edge_count INTEGER)"))
            conn.execute(text("CREATE TABLE metadata (key TEXT, value_json TEXT)"))
            conn.execute(
                text(
                    "CREATE TABLE supernodes (level INTEGER, supernode INTEGER, size INTEGER, "
                    "entry_type_counts_json TEXT, top_tags_json TEXT)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE supernode_members (level INTEGER, supernode INTEGER, member_order INTEGER, "
                    "entry_id TEXT, slug TEXT, title TEXT)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE coarse_edges (level INTEGER, source_supernode INTEGER, "
                    "target_supernode INTEGER, weight REAL)"
                )
            )
            conn.execute(text("INSERT INTO levels VALUES (0, 3, 2)"))
            conn.execute(text("INSERT INTO levels VALUES (1, 1, 0)"))
            conn.execute(
                text("INSERT INTO metadata VALUES ('summary', :summary)"),
                {"summary": json.dumps({"preset": "demo", "final_nodes": 3})},
            )
            conn.execute(
                text("INSERT INTO supernodes VALUES (0, 1, 1, :types, :tags)"),
                {"types": '{"capability": 1}', "tags": '["science"]'},
            )
            conn.execute(
                text("INSERT INTO supernodes VALUES (0, 2, 2, :types, :tags)"),
                {"types": '{"procedure": 2}', "tags": '["lab"]'},
            )
            conn.execute(
                text("INSERT INTO supernodes VALUES (0, 3, 1, :types, :tags)"),
                {"types": '{"tool": 1}', "tags": '[]'},
            )
            conn.execute(
                text("INSERT INTO supernode_members VALUES (0, 1, 0, 'entry-a', 'alpha', 'Alpha')")
            )
            conn.execute(
                text("INSERT INTO supernode_members VALUES (0, 2, 0, 'entry-b', 'beta', 'Beta')")
            )
            conn.execute(
                text("INSERT INTO supernode_members VALUES (0, 3, 0, 'entry-c', 'gamma', 'Gamma')")
            )
            conn.execute(text("INSERT INTO coarse_edges VALUES (0, 1, 2, 0.8)"))
            conn.execute(text("INSERT INTO coarse_edges VALUES (0, 2, 3, 0.6)"))
            conn.execute(
                text("INSERT INTO supernodes VALUES (1, 10, 3, :types, :tags)"),
                {"types": '{"capability": 1, "procedure": 2}', "tags": '["science", "lab"]'},
            )
            for member_order, (entry_id, slug, title) in enumerate((
                ("entry-a", "alpha", "Alpha"),
                ("entry-b", "beta", "Beta"),
                ("entry-c", "gamma", "Gamma"),
            )):
                conn.execute(
                    text("INSERT INTO supernode_members VALUES (1, 10, :order, :id, :slug, :title)"),
                    {"order": member_order, "id": entry_id, "slug": slug, "title": title},
                )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_adapts_lrg_rows_to_read_only_graph_nodes(self) -> None:
        graph = LrgDataset(self.engine).full_graph(level=0, max_nodes=10)

        self.assertEqual(graph["metadata"]["kind"], "lrg")
        self.assertEqual(graph["metadata"]["total_nodes"], 3)
        self.assertEqual(graph["nodes"][0]["title"], "Alpha")
        self.assertEqual(graph["nodes"][1]["title"], "Cluster of 2 entries")
        self.assertEqual(graph["edges"][0]["source"], "lrg:0:1")
        self.assertTrue(graph["nodes"][0]["read_only"])

    def test_limits_to_highest_connected_induced_subgraph(self) -> None:
        graph = LrgDataset(self.engine).full_graph(level=0, max_nodes=2)

        self.assertTrue(graph["metadata"]["truncated"])
        self.assertEqual(graph["metadata"]["displayed_nodes"], 2)
        self.assertEqual(len(graph["edges"]), 1)

    def test_searches_all_nodes_and_cluster_members_not_just_an_overview(self) -> None:
        graph = LrgDataset(self.engine).search_view({"level": "0", "q": "beta"})

        self.assertEqual(graph["metadata"]["kind"], "search")
        self.assertEqual(graph["metadata"]["total_matches"], 1)
        self.assertEqual([node["id"] for node in graph["nodes"]], ["lrg:0:2"])
        self.assertEqual(graph["nodes"][0]["metadata"]["search_matches"], ["Beta"])

    def test_only_selects_lrg_adapter_when_native_entries_are_empty(self) -> None:
        self.assertIsInstance(get_dataset_adapter(self.engine, entry_count=0), LrgDataset)
        self.assertIsNone(get_dataset_adapter(self.engine, entry_count=1))

    def test_hierarchy_links_a_cluster_to_its_finer_constituents(self) -> None:
        hierarchy = LrgDataset(self.engine).hierarchy(
            node_id="lrg:1:10", target_level=0, max_nodes=10
        )

        self.assertEqual(hierarchy["metadata"]["total_children"], 3)
        self.assertEqual(hierarchy["metadata"]["label"], "Resolution 1 → 0")
        self.assertEqual({node["id"] for node in hierarchy["nodes"]}, {
            "lrg:1:10", "lrg:0:1", "lrg:0:2", "lrg:0:3",
        })
        self.assertEqual(len(hierarchy["edges"]), 3)
