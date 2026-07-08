from __future__ import annotations

from core.memory.memgraph import MemGraph
from core.schemas.entry import Entry, EntryType


def promote_memory_trace(
    memory: MemGraph,
    mem_id: str,
    *,
    entry_type: EntryType | str = EntryType.generic,
    title: str | None = None,
) -> Entry | None:
    return memory.promote(mem_id, entry_type=EntryType(entry_type), title=title)
