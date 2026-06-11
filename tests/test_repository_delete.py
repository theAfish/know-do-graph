from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from core.schemas.edge import Edge
from core.schemas.entry import Entry
from core.storage.database import create_database_engine, initialize_database
from core.storage.repository import EdgeRepository, EntryRepository


class EntryRepositoryDeleteTests(unittest.TestCase):
    def test_delete_removes_incident_edges_but_keeps_unrelated_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_database_engine(Path(temp_dir) / "graph.db")
            initialize_database(engine)
            session_factory = sessionmaker(bind=engine)

            with session_factory() as db:
                entries = EntryRepository(db)
                edges = EdgeRepository(db)
                deleted_node = entries.create(Entry(title="Delete me"))
                neighbor = entries.create(Entry(title="Neighbor"))
                other_source = entries.create(Entry(title="Other source"))
                other_target = entries.create(Entry(title="Other target"))

                edges.create(Edge(source_id=deleted_node.id, target_id=neighbor.id))
                edges.create(Edge(source_id=neighbor.id, target_id=deleted_node.id))
                unrelated = edges.create(
                    Edge(source_id=other_source.id, target_id=other_target.id)
                )

                self.assertTrue(entries.delete(deleted_node.id))
                remaining = edges.get_all()

            engine.dispose()

        self.assertEqual([edge.id for edge in remaining], [unrelated.id])


if __name__ == "__main__":
    unittest.main()
