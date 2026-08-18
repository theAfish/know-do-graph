from __future__ import annotations

from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.retrieval import vector_store
from core.retrieval.embedder import build_embedding_text, get_default_embedder
from core.retrieval.fusion import reciprocal_rank_fusion, trust_multiplier, usage_bump
from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, EntryType, entry_type_value
from core.storage.models import EdgeModel, EntryModel

_STOP_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "be",
}

# Bidirectional synonym groups — each list is a set of interchangeable terms.
# When any member appears as a query token the others are added automatically.
_SYNONYM_GROUPS: list[list[str]] = [
    ["cnt", "nanotube", "carbon-nanotube", "carbon nanotube"],
    ["cnt", "carbon tube", "tube"],
    ["filled tube", "filled cnt", "filled nanotube", "confined"],
    ["ase", "atomic simulation environment"],
    ["slab", "surface slab", "surface"],
    ["interface", "heterostructure", "film substrate"],
    ["supercell", "super cell", "expansion"],
    ["lattice matching", "zsl", "coherent interface"],
    ["methane", "ch4"],
    ["dft", "density functional theory"],
    ["md", "molecular dynamics"],
    ["mlip", "mace", "machine learning potential", "interatomic potential"],
    ["crystal", "bulk crystal", "bulk structure"],
    ["nanoparticle", "nano particle", "nanostructure"],
]

# Build a fast lookup: token → set of synonym tokens (excluding itself)
_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _SYNONYM_GROUPS:
    for _term in _group:
        others = {t for t in _group if t != _term}
        _SYNONYM_MAP.setdefault(_term, set()).update(others)


def _expand_tokens(tokens: list[str]) -> list[str]:
    """Return *tokens* plus any synonyms, deduped, preserving order."""
    seen: set[str] = set(tokens)
    expanded = list(tokens)
    for tok in tokens:
        for syn in _SYNONYM_MAP.get(tok, ()):
            if syn not in seen:
                seen.add(syn)
                expanded.append(syn)
    return expanded


class RetrievalEngine:
    """Search and graph-traversal interface over the persisted graph."""

    def __init__(self, db: Session, graph: KnowDoGraph) -> None:
        self._db = db
        self._graph = graph

    # ------------------------------------------------------------------
    # Entry lookups
    # ------------------------------------------------------------------

    @staticmethod
    def _is_disabled(entry: Entry) -> bool:
        return entry.metadata.disabled

    @classmethod
    def _matches_disabled_filter(cls, entry: Entry, disabled: Optional[bool]) -> bool:
        """Return whether *entry* matches a visibility/filter request.

        ``False`` is the public default: only enabled entries are visible.
        ``True`` is the explicit administrative search for disabled entries.
        ``None`` is reserved for trusted internal maintenance callers that
        need both kinds of persisted rows.
        """
        return disabled is None or cls._is_disabled(entry) is disabled

    def get_entry_by_id(self, entry_id: str, *, disabled: Optional[bool] = False) -> Optional[Entry]:
        row = self._db.get(EntryModel, entry_id)
        if row is None:
            return None
        entry = Entry(**row.to_dict())
        return entry if self._matches_disabled_filter(entry, disabled) else None

    def get_entry_by_slug(self, slug: str, *, disabled: Optional[bool] = False) -> Optional[Entry]:
        row = self._db.query(EntryModel).filter_by(slug=slug).first()
        if row is None:
            return None
        entry = Entry(**row.to_dict())
        return entry if self._matches_disabled_filter(entry, disabled) else None

    def get_entry_by_alias(self, alias: str, *, disabled: Optional[bool] = False) -> Optional[Entry]:
        """Return the first entry whose aliases list contains *alias* (case-insensitive)."""
        alias_lower = alias.lower()
        rows = (
            self._db.query(EntryModel)
            .filter(EntryModel.aliases.ilike(f"%{alias_lower}%"))
            .all()
        )
        for row in rows:
            entry = Entry(**row.to_dict())
            if (
                any(a.lower() == alias_lower for a in entry.aliases)
                and self._matches_disabled_filter(entry, disabled)
            ):
                return entry
        return None

    def resolve_identifier(self, identifier: str, *, disabled: Optional[bool] = False) -> Optional[Entry]:
        """Try ID → slug → alias in order and return the first match."""
        return (
            self.get_entry_by_id(identifier, disabled=disabled)
            or self.get_entry_by_slug(identifier, disabled=disabled)
            or self.get_entry_by_alias(identifier, disabled=disabled)
        )

    def list_entries(
        self, limit: int = 50, offset: int = 0, *, disabled: Optional[bool] = False
    ) -> list[Entry]:
        # Filter after deserialising metadata because metadata is stored in a
        # portable JSON text column (SQLite and PostgreSQL compatible).
        rows = self._db.query(EntryModel).all()
        entries = [Entry(**row.to_dict()) for row in rows]
        visible = [e for e in entries if self._matches_disabled_filter(e, disabled)]
        return visible[offset : offset + limit]

    # ------------------------------------------------------------------
    # Hybrid search
    # ------------------------------------------------------------------

    def search_entries(
        self,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        entry_type: Optional[EntryType | str] = None,
        limit: int = 20,
        mode: str = "hybrid",
        disabled: Optional[bool] = False,
    ) -> list[Entry]:
        return [e for _, e in self._search_impl(query, tags, entry_type, limit, mode, disabled)]

    def search_entries_scored(
        self,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        entry_type: Optional[EntryType | str] = None,
        limit: int = 20,
        mode: str = "hybrid",
        disabled: Optional[bool] = False,
    ) -> list[tuple[Entry, float]]:
        """Like search_entries but returns (entry, score) with scores normalized 0.0–1.0."""
        raw = self._search_impl(query, tags, entry_type, limit, mode, disabled)
        if not raw:
            return []
        max_score = max(s for s, _ in raw) or 1.0
        return [(e, s / max_score) for s, e in raw]

    def _search_impl(
        self,
        query: Optional[str],
        tags: Optional[list[str]],
        entry_type: Optional[EntryType | str],
        limit: int,
        mode: str = "hybrid",
        disabled: Optional[bool] = False,
    ) -> list[tuple[Entry, float]]:
        """Retrieval with three modes:
          - "hybrid": keyword + vector ANN fused with RRF (default)
          - "semantic": vector-only ANN (best for conceptually similar queries)
          - "keyword": keyword-only (best for exact title/tag/acronym lookups)

        Falls back gracefully:
          - No query → filter-only listing, scores all 0.
          - No embedder / no vec index → pure keyword path regardless of mode.
        """
        if not query:
            return [
                (0.0, e)
                for e in self._filter_only(
                    tags=tags, entry_type=entry_type, limit=limit, disabled=disabled
                )
            ]

        entries_by_id: dict[str, Entry] = {}

        # Channel A — keyword scorer (skipped in semantic mode).
        keyword_ranked: list[str] = []
        if mode != "semantic":
            keyword_hits = self._keyword_search(
                query=query, tags=tags, entry_type=entry_type, limit=200, disabled=disabled
            )
            keyword_ranked = [eid for eid, _ in keyword_hits]
            entries_by_id.update(
                {eid: e for eid, _, e in self._with_entries(keyword_hits, disabled=disabled)}
            )

        # Channel B — vector ANN (skipped in keyword mode).
        vector_ranked: list[str] = []
        embedder = get_default_embedder()
        if mode != "keyword" and embedder.available:
            qvec = embedder.embed([query])[0]
            for eid, _dist in vector_store.knn(self._db, qvec, k=50):
                if eid in entries_by_id:
                    vector_ranked.append(eid)
                    continue
                row = self._db.get(EntryModel, eid)
                if row is None:
                    continue
                d = row.to_dict()
                if entry_type and d.get("entry_type") != entry_type_value(entry_type):
                    continue
                if tags and not any(t in d["tags"] for t in tags):
                    continue
                entry = Entry(**d)
                if not self._matches_disabled_filter(entry, disabled):
                    continue
                entries_by_id[eid] = entry
                vector_ranked.append(eid)

        # Fuse + rerank.
        fused = reciprocal_rank_fusion([keyword_ranked, vector_ranked])
        if not fused:
            return []

        scored: list[tuple[float, Entry]] = []
        for eid, base in fused.items():
            entry = entries_by_id.get(eid)
            if entry is None:
                continue
            meta = entry.metadata
            mult = trust_multiplier(
                meta.verification_status.value,
                trust_score_override=meta.trust_score,
            ) * usage_bump(meta.usage_count or 0)
            scored.append((base * mult, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:limit]

    # ------------------------------------------------------------------
    # Channel implementations
    # ------------------------------------------------------------------

    def _filter_only(
        self,
        tags: Optional[list[str]],
        entry_type: Optional[EntryType | str],
        limit: int,
        disabled: Optional[bool],
    ) -> list[Entry]:
        q = self._db.query(EntryModel)
        if entry_type:
            q = q.filter(EntryModel.entry_type == entry_type_value(entry_type))
        rows = q.limit(500).all()
        out: list[Entry] = []
        for row in rows:
            d = row.to_dict()
            entry = Entry(**d)
            if not self._matches_disabled_filter(entry, disabled):
                continue
            if tags and not any(t in d["tags"] for t in tags):
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    def _keyword_search(
        self,
        query: str,
        tags: Optional[list[str]],
        entry_type: Optional[EntryType | str],
        limit: int,
        disabled: Optional[bool],
    ) -> list[tuple[str, int]]:
        """Returns ``[(entry_id, raw_score), ...]`` sorted by descending score.

        Same scoring formula as before — title 10 / alias 5 / tag 3 / content 1.
        """
        q = self._db.query(EntryModel)
        if entry_type:
            q = q.filter(EntryModel.entry_type == entry_type_value(entry_type))

        tokens = [
            t for t in query.lower().split()
            if len(t) > 2 and t not in _STOP_WORDS
        ]
        if not tokens:
            tokens = [query.lower()]

        # Expand tokens with domain synonyms so e.g. "CNT" also finds "nanotube"
        tokens = _expand_tokens(tokens)

        token_filters = []
        for token in tokens:
            tl = f"%{token}%"
            token_filters.append(
                or_(
                    EntryModel.title.ilike(tl),
                    EntryModel.content.ilike(tl),
                    EntryModel.aliases.ilike(tl),
                )
            )
        q = q.filter(or_(*token_filters))

        rows = q.limit(500).all()

        scored: list[tuple[int, str]] = []
        for row in rows:
            d = row.to_dict()
            if not self._matches_disabled_filter(Entry(**d), disabled):
                continue
            if tags and not any(t in d["tags"] for t in tags):
                continue
            title = (d.get("title") or "").lower()
            aliases = str(d.get("aliases") or "").lower()
            tags_str = str(d.get("tags") or "").lower()
            content = (d.get("content") or "").lower()
            score = 0
            for token in tokens:
                if token in title:
                    score += 10
                if token in aliases:
                    score += 5
                if token in tags_str:
                    score += 3
                if token in content and token not in title:
                    score += 1
            scored.append((score, d["id"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(eid, s) for s, eid in scored[:limit]]

    def _with_entries(
        self, hits: list[tuple[str, int]], disabled: Optional[bool] = False
    ) -> list[tuple[str, int, Entry]]:
        out: list[tuple[str, int, Entry]] = []
        for eid, score in hits:
            row = self._db.get(EntryModel, eid)
            if row is None:
                continue
            entry = Entry(**row.to_dict())
            if self._matches_disabled_filter(entry, disabled):
                out.append((eid, score, entry))
        return out

    # ------------------------------------------------------------------
    # Edge lookups
    # ------------------------------------------------------------------

    def get_edges_for_entry(self, entry_id: str) -> list[Edge]:
        if self.get_entry_by_id(entry_id) is None:
            return []
        rows = (
            self._db.query(EdgeModel)
            .filter(
                (EdgeModel.source_id == entry_id)
                | (EdgeModel.target_id == entry_id)
            )
            .all()
        )
        return [
            Edge(**row.to_dict())
            for row in rows
            if self.get_entry_by_id(row.source_id) is not None
            and self.get_entry_by_id(row.target_id) is not None
        ]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_related_entries(
        self,
        entry_id: str,
        depth: int = 1,
        relation: Optional[EdgeRelation] = None,
    ) -> list[Entry]:
        related_ids = self._graph.get_related_ids(entry_id, depth=depth, relation=relation)
        entries: list[Entry] = []
        for rid in related_ids:
            entry = self.get_entry_by_id(rid)
            if entry:
                entries.append(entry)
        return entries

    # ------------------------------------------------------------------
    # Embedding maintenance — used by the backfill CLI
    # ------------------------------------------------------------------

    @staticmethod
    def embedding_text_for(entry: Entry) -> str:
        return build_embedding_text(
            title=entry.title,
            aliases=entry.aliases,
            tags=entry.tags,
            content=entry.content,
        )
