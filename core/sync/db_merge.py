"""Database merge & deduplication utilities.

Used by the ``python main.py db merge`` and ``python main.py db dedup`` CLI
commands when consolidating snapshots from multiple environments (e.g. a
laptop dev DB and a server DB).

Design
------
* UUID primary keys mean entry-id collisions are negligible \u2014 we treat the
  ``entries`` table as a set and union it.
* Slug collisions across DBs are common (independent authoring of the same
  page). ``EntryRepository.create`` already calls ``_unique_slug`` which
  suffixes ``-1``, ``-2``, etc., so writes never fail \u2014 the duplicates can
  be merged afterwards by ``db dedup``.
* Edges are de-duplicated by ``(source_id, target_id, relation)`` inside
  ``EdgeRepository.create``.
* After import we re-run wikilink resolution so newly-arrived entries connect
  to existing nodes by slug/title/alias.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.schemas.edge import Edge
from core.schemas.entry import Entry
from core.storage.database import SessionLocal
from core.storage.models import EdgeModel, EntryModel
from core.storage.repository import EdgeRepository, EntryRepository

logger = logging.getLogger(__name__)


# ── Merge ────────────────────────────────────────────────────────────────────


@dataclass
class MergeReport:
    entries_inserted: int = 0
    entries_updated: int = 0
    entries_skipped: int = 0
    edges_inserted: int = 0
    edges_skipped: int = 0
    wikilinks_resolved: int = 0
    slug_renames: list[tuple[str, str]] = field(default_factory=list)  # (incoming, final)


def _open_readonly(db_path: Path):
    """Open a foreign SQLite file as a SQLAlchemy session factory.

    We never write to it, so a plain connection is sufficient. (The previous
    ``mode=ro&uri=true`` query-string form is mis-parsed by SQLAlchemy's URL
    parser and silently opens an empty DB.)
    """
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    eng = create_engine(
        f"sqlite:///{db_path.resolve()}",
        connect_args={"check_same_thread": False},
    )
    return sessionmaker(autocommit=False, autoflush=False, bind=eng)


def merge_database(
    other_db_path: Path,
    *,
    prefer: str = "newer",  # "newer" | "local" | "remote"
    resolve_wikilinks: bool = True,
) -> MergeReport:
    """Additively merge entries+edges from *other_db_path* into the current DB.

    ``prefer`` controls id-conflict resolution:
      * ``newer``  \u2014 keep whichever side has the larger ``updated_at``.
      * ``local``  \u2014 never overwrite existing local entries.
      * ``remote`` \u2014 always overwrite with the incoming entry.
    """
    if prefer not in {"newer", "local", "remote"}:
        raise ValueError(f"invalid prefer={prefer!r}")

    report = MergeReport()
    OtherSession = _open_readonly(Path(other_db_path))
    other_engine = OtherSession.kw.get("bind")

    try:
        with OtherSession() as src_db:
            src_entry_models = src_db.query(EntryModel).all()
            src_edge_models = src_db.query(EdgeModel).all()
            # Capture raw fields up-front so we don't hold the read-only session open.
            src_entries: list[tuple[dict, object, object]] = [
                (m.to_dict(), m.created_at, m.updated_at) for m in src_entry_models
            ]
            src_edges: list[dict] = [m.to_dict() for m in src_edge_models]
    finally:
        if other_engine is not None:
            other_engine.dispose()

    logger.info(
        "db merge: source has %d entries, %d edges",
        len(src_entries),
        len(src_edges),
    )

    with SessionLocal() as dst_db:
        dst_repo = EntryRepository(dst_db)
        existing = {m.id: m for m in dst_db.query(EntryModel).all()}

        for data, src_created, src_updated in src_entries:
            incoming = Entry(**data)
            local = existing.get(incoming.id)

            if local is None:
                pre_slug = incoming.slug
                saved = dst_repo.create(incoming)
                if saved.slug != pre_slug:
                    report.slug_renames.append((pre_slug, saved.slug))
                report.entries_inserted += 1
                continue

            # id collision \u2014 apply preference policy
            if prefer == "local":
                report.entries_skipped += 1
                continue
            if (
                prefer == "newer"
                and (local.updated_at and src_updated)
                and local.updated_at >= src_updated
            ):
                report.entries_skipped += 1
                continue
            dst_repo.update(incoming)
            report.entries_updated += 1

    with SessionLocal() as dst_db:
        edge_repo = EdgeRepository(dst_db)
        # ``EdgeRepository.create`` de-dups on (source, target, relation) and
        # returns the existing edge if one is already present.
        existing_keys = {
            (m.source_id, m.target_id, m.relation) for m in dst_db.query(EdgeModel).all()
        }
        for d in src_edges:
            key = (d["source_id"], d["target_id"], d["relation"])
            if key in existing_keys:
                report.edges_skipped += 1
                continue
            try:
                edge = Edge(**d)
            except Exception as exc:  # noqa: BLE001
                logger.warning("skipping malformed edge %s: %s", d.get("id"), exc)
                report.edges_skipped += 1
                continue
            edge_repo.create(edge)
            existing_keys.add(key)
            report.edges_inserted += 1

    if resolve_wikilinks:
        from agents.extraction_agent.agent import ExtractionAgent
        from core import app_state

        report.wikilinks_resolved = ExtractionAgent(app_state.graph).resolve_wikilinks()

    # Refresh in-memory graph and notify any connected UIs.
    from core import app_state
    from core import events as _events
    from core.sync.db_watcher import reload_graph_from_db

    nodes, edges = reload_graph_from_db(app_state.graph)
    _events.emit("graph_changed", {"source": "db_merge", "nodes": nodes, "edges": edges})

    return report


# ── Dedup ────────────────────────────────────────────────────────────────────


@dataclass
class DedupReport:
    exact_groups: int = 0
    similar_groups: int = 0
    merged_pairs: int = 0
    candidates: list[dict] = field(default_factory=list)


def _slug_stem(slug: str) -> str:
    """Strip a trailing ``-<digits>`` collision suffix (e.g. ``mace-2`` \u2192 ``mace``)."""
    import re

    return re.sub(r"-\d+$", "", slug or "")


def find_exact_duplicate_groups() -> list[list[Entry]]:
    """Group entries that are obviously the same node (same slug-stem or title).

    Returns a list of groups, each containing 2+ entries.
    """
    with SessionLocal() as db:
        entries = EntryRepository(db).get_all()

    by_stem: dict[str, list[Entry]] = defaultdict(list)
    by_title: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        by_stem[_slug_stem(e.slug).lower()].append(e)
        by_title[e.title.strip().lower()].append(e)

    groups: list[list[Entry]] = []
    seen_ids: set[str] = set()

    def _emit(group: list[Entry]) -> None:
        ids = tuple(sorted(e.id for e in group))
        if any(i in seen_ids for i in ids):
            # Already covered by a prior overlapping group.
            return
        seen_ids.update(ids)
        groups.append(group)

    for g in by_stem.values():
        if len(g) > 1:
            _emit(g)
    for g in by_title.values():
        if len(g) > 1:
            _emit(g)
    return groups


def _pick_primary(group: list[Entry]) -> Entry:
    """Choose the survivor: prefer the entry with the most content, then earliest id."""
    return max(group, key=lambda e: (len(e.content or ""), -ord(e.id[0]) if e.id else 0))


def dedup_exact(*, dry_run: bool = True) -> DedupReport:
    """Merge entries that are exact duplicates (same slug-stem or normalized title)."""
    from agents.graph_agent.tools import merge_entries
    from core import app_state
    from core import events as _events
    from core.sync.db_watcher import reload_graph_from_db

    report = DedupReport()
    for group in find_exact_duplicate_groups():
        report.exact_groups += 1
        primary = _pick_primary(group)
        for dup in group:
            if dup.id == primary.id:
                continue
            report.candidates.append(
                {
                    "primary_id": primary.id,
                    "primary_slug": primary.slug,
                    "duplicate_id": dup.id,
                    "duplicate_slug": dup.slug,
                    "reason": "exact",
                }
            )
            if not dry_run:
                res = merge_entries(primary.id, dup.id, graph=app_state.graph)
                if res.get("merged"):
                    report.merged_pairs += 1

    if not dry_run and report.merged_pairs:
        nodes, edges = reload_graph_from_db(app_state.graph)
        _events.emit("graph_changed", {"source": "db_dedup", "nodes": nodes, "edges": edges})
    return report


def find_similar_groups(threshold: float = 0.92, top_k: int = 20) -> list[dict]:
    """Embedding-based near-duplicate candidates.

    Returns a list of ``{"a_id", "b_id", "similarity"}`` dicts. Empty if the
    sqlite-vec index is unavailable.
    """
    import struct

    from sqlalchemy import text as _text

    from core.retrieval.vector_store import _table_available, knn  # type: ignore

    with SessionLocal() as db:
        if not _table_available(db):
            logger.info("sqlite-vec table not available \u2014 similarity dedup skipped")
            return []
        rows = db.execute(_text("SELECT entry_id, embedding FROM entry_embeddings")).all()
        id_to_vec: dict[str, list[float]] = {}
        for entry_id, blob in rows:
            if blob is None:
                continue
            n = len(blob) // 4
            id_to_vec[entry_id] = list(struct.unpack(f"<{n}f", blob))

        pairs: dict[tuple[str, str], float] = {}
        for eid, vec in id_to_vec.items():
            neighbors = knn(db, vec, k=top_k + 1)
            for nbr_id, distance in neighbors:
                if nbr_id == eid:
                    continue
                # sqlite-vec returns L2 distance by default; convert to a
                # bounded similarity. With sentence-transformers L2-normed
                # embeddings, sim = 1 - d**2 / 2 is the exact cosine.
                sim = max(0.0, 1.0 - (distance * distance) / 2.0)
                if sim < threshold:
                    continue
                key = tuple(sorted((eid, nbr_id)))
                if sim > pairs.get(key, 0.0):
                    pairs[key] = sim

    return [
        {"a_id": a, "b_id": b, "similarity": round(s, 4)}
        for (a, b), s in sorted(pairs.items(), key=lambda kv: -kv[1])
    ]
