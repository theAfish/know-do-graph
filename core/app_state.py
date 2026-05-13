"""Application-level shared state.

Import `graph` from here wherever a single in-process graph instance is needed.
The API startup handler calls `graph.rebuild_from_db(...)` after init_db().
"""

from core.graph.graph import KnowDoGraph

graph = KnowDoGraph()
