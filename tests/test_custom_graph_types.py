import unittest

from sqlalchemy import create_engine, text

from core.graph.graph import KnowDoGraph
from core.graph.kinds import GraphKind, detected_graph_kind, uses_know_do_semantics
from core.schemas.entry import Entry, EntryType, entry_type_value


class CustomGraphTypeTests(unittest.TestCase):
    def test_custom_entry_type_is_preserved_in_graph(self) -> None:
        entry = Entry(title="INCAR tag", entry_type="category")
        graph = KnowDoGraph()
        graph.add_entry(entry)

        self.assertEqual(entry.entry_type, "category")
        self.assertEqual(graph._g.nodes[entry.id]["entry_type"], "category")
        self.assertIsNone(graph._g.nodes[entry.id]["skill_level"])

    def test_native_entry_type_remains_an_enum(self) -> None:
        entry = Entry(title="Relax structure", entry_type="capability")

        self.assertIs(entry.entry_type, EntryType.capability)
        self.assertEqual(entry_type_value(entry.entry_type), "capability")

    def test_unknown_database_type_selects_custom_graph(self) -> None:
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE entries (entry_type TEXT)"))
            conn.execute(text("INSERT INTO entries VALUES ('parameter')"))

        self.assertIs(detected_graph_kind(engine), GraphKind.CUSTOM)
        self.assertFalse(uses_know_do_semantics(engine))

    def test_database_declaration_resolves_ambiguous_custom_graph(self) -> None:
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE entries (entry_type TEXT)"))
            conn.execute(text("INSERT INTO entries VALUES ('capability')"))
            conn.execute(text("CREATE TABLE graph_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
            conn.execute(text("INSERT INTO graph_metadata VALUES ('graph_kind', 'custom')"))

        self.assertIs(detected_graph_kind(engine), GraphKind.CUSTOM)
