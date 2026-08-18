"""Generic auto-linker: derives edges from raw text content.

Why this exists
---------------
Live-mirrored content (SKILL.md, README.md, web pages) is written in prose,
not in our ``[[wikilink]]`` syntax — so the internal_refs extractor never fires
on it. Without help, those nodes look like isolated islands in the graph.

What this module does
---------------------
1. **Generic mention scan** (``find_mentions``) — given a content string and an
   index of {alias_lower: entry_id}, finds word-boundary, case-insensitive
   matches. Aliases of length < 3 are skipped to avoid noise.

2. **YAML frontmatter enricher** (``parse_frontmatter`` +
   ``enrich_from_frontmatter``) — for SKILL.md-style files that declare
   structured metadata like::

       ---
       name: vasp
       dependent_skills:
         - dpdisp
       ---

   we promote those declarations into typed edges (``dependency``, etc.).

3. **Public entry point** (``auto_link_entry``) — runs both scanners against
   one entry, persists new edges via the supplied ``EdgeRepository`` (which
   already dedups), and returns the list of newly-created edges.

Design notes
------------
* The mirrored ``content`` is NEVER mutated — the upstream text stays pristine.
  We only add edges. This avoids spurious diffs on every sync.
* Edges from generic mentions use ``relation=documents`` with ``weight=0.4``
  so they visually rank below user-curated edges.
* Frontmatter-derived edges use the strongest matching relation
  (``dependency`` for ``dependent_skills``, ``alternative_to`` for
  ``alternatives``, etc.) at ``weight=0.9``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry
from core.storage.repository import EdgeRepository

log = logging.getLogger(__name__)

# Aliases shorter than this are too noisy ("ml", "md", "io" …).
_MIN_ALIAS_LEN = 3

# Very generic words we should NEVER treat as entry mentions, even if some
# entry happens to be titled that way.
_STOPWORDS = {
    "agent",
    "agents",
    "tool",
    "tools",
    "skill",
    "skills",
    "workflow",
    "workflows",
    "script",
    "scripts",
    "data",
    "model",
    "models",
    "code",
    "file",
    "files",
    "task",
    "tasks",
    "input",
    "output",
    "result",
    "results",
    "test",
    "tests",
    "main",
    "default",
    "config",
    "configuration",
    "setup",
    "example",
    "examples",
    "readme",
    "guide",
    "doc",
    "docs",
    "documentation",
    "notes",
    "summary",
    "user",
    "users",
    "system",
    "project",
    "repo",
    "repository",
    "package",
}

# Frontmatter keys → (EdgeRelation, weight). Keys are matched on their YAML name.
_FRONTMATTER_RELATIONS: dict[str, tuple[EdgeRelation, float]] = {
    "dependent_skills": (EdgeRelation.dependency, 0.9),
    "dependencies": (EdgeRelation.dependency, 0.9),
    "depends_on": (EdgeRelation.dependency, 0.9),
    "requires": (EdgeRelation.prerequisite, 0.9),
    "prerequisites": (EdgeRelation.prerequisite, 0.9),
    "uses": (EdgeRelation.uses, 0.8),
    "alternatives": (EdgeRelation.alternative_to, 0.7),
    "alternative_to": (EdgeRelation.alternative_to, 0.7),
    "compatible_with": (EdgeRelation.compatible_with, 0.7),
    "related": (EdgeRelation.related_workflow, 0.5),
}


# ──────────────────────────────────────────────────────────────────────────────
# Alias index
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class AliasIndex:
    """Maps lowercase-alias → set of entry ids. One alias may resolve to many."""

    by_alias: dict[str, set[str]] = field(default_factory=dict)
    # Also keep slug → id for direct frontmatter lookups.
    by_slug: dict[str, str] = field(default_factory=dict)

    def add(self, alias: str, entry_id: str) -> None:
        a = alias.strip().lower()
        if len(a) < _MIN_ALIAS_LEN or a in _STOPWORDS:
            return
        self.by_alias.setdefault(a, set()).add(entry_id)


def build_alias_index(entries: Iterable[Entry]) -> AliasIndex:
    """Build a lookup index over all entries' titles/aliases/slugs.

    For mirrored skills with prefixed slugs (e.g. ``pfd-vasp``), we also index
    the prefix-stripped variant (``vasp``) so the body of *other* sources can
    point at the canonical mirror.
    """
    idx = AliasIndex()
    for e in entries:
        idx.by_slug[e.slug] = e.id
        idx.add(e.title, e.id)
        idx.add(e.slug, e.id)
        for alias in e.aliases or []:
            idx.add(alias, e.id)
        # Strip common namespace prefixes so "pfd-vasp" also matches "vasp".
        for prefix in ("pfd-", "lammps-", "vasp-"):
            if e.slug.startswith(prefix):
                idx.add(e.slug[len(prefix) :], e.id)
    return idx


# ──────────────────────────────────────────────────────────────────────────────
# Generic mention scan
# ──────────────────────────────────────────────────────────────────────────────


def find_mentions(content: str, idx: AliasIndex, *, self_id: str | None = None) -> set[str]:
    """Return ids of entries whose alias appears in ``content``.

    Self-mentions are filtered out so an entry doesn't link to itself.
    Ambiguous aliases (resolving to >1 id) are dropped — better to skip than
    to create a wrong edge.
    """
    if not content:
        return set()
    text = content.lower()
    hits: set[str] = set()
    for alias, ids in idx.by_alias.items():
        if len(ids) > 1:
            continue  # ambiguous — skip
        # Word boundary that also treats '-' and '_' as separators.
        if re.search(rf"(?<![\w\-]){re.escape(alias)}(?![\w\-])", text):
            (target_id,) = tuple(ids)
            if target_id != self_id:
                hits.add(target_id)
    return hits


# ──────────────────────────────────────────────────────────────────────────────
# YAML frontmatter
# ──────────────────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def parse_frontmatter(content: str) -> dict | None:
    """Return parsed YAML frontmatter dict, or None.

    Uses PyYAML if available, otherwise a small hand-rolled subset that handles
    the shape we actually see in SKILL.md (``key: scalar`` and ``key:`` followed
    by ``  - item`` lists, plus nested ``metadata:`` block).

    The nested ``metadata`` sub-dict — used by SKILL.md to hold structured
    fields like ``dependent_skills`` — is flattened into the returned mapping
    so callers don't have to special-case it.
    """
    m = _FRONTMATTER_RE.match(content or "")
    if not m:
        return None
    body = m.group(1)
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(body)
        data = loaded if isinstance(loaded, dict) else None
    except Exception:
        data = _mini_yaml(body)
    if data is None:
        return None
    # Promote nested metadata:{...} keys to the top level (parent wins on conflict
    # so we never clobber an explicit top-level field).
    nested = data.get("metadata")
    if isinstance(nested, dict):
        for k, v in nested.items():
            data.setdefault(k, v)
    return data


def _mini_yaml(text: str) -> dict:
    """Tiny YAML subset parser for ``key: value`` and ``key:\\n  - item`` lists.

    Tracks indentation depth so nested dicts (``metadata:`` block) flatten into
    the top-level result alongside their parent — good enough for our scan,
    which only inspects known keys.
    """
    out: dict[str, object] = {}
    current_list: list[str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip(" ")
        if stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip().strip("'\""))
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if not val:
                current_list = []
                out[key] = current_list
            else:
                out[key] = val.strip("'\"")
                current_list = None
        # nested dicts under metadata: are intentionally flattened.
    # Drop empty list entries we never populated.
    return {k: v for k, v in out.items() if v not in ([], "", None)}


def enrich_from_frontmatter(
    fm: dict, idx: AliasIndex, *, self_id: str | None
) -> list[tuple[str, EdgeRelation, float]]:
    """Translate frontmatter list-keys into (target_id, relation, weight) tuples."""
    out: list[tuple[str, EdgeRelation, float]] = []
    for key, (relation, weight) in _FRONTMATTER_RELATIONS.items():
        raw = fm.get(key)
        if not raw:
            continue
        values = raw if isinstance(raw, list) else [raw]
        for v in values:
            if not isinstance(v, str):
                continue
            name = v.strip().lower()
            if not name:
                continue
            target = idx.by_slug.get(name)
            if target is None:
                # Try alias index for namespaced variants.
                ids = idx.by_alias.get(name, set())
                if len(ids) == 1:
                    (target,) = tuple(ids)
            if target and target != self_id:
                out.append((target, relation, weight))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class AutoLinkResult:
    entry_id: str
    mention_edges: int = 0
    frontmatter_edges: int = 0

    @property
    def total(self) -> int:
        return self.mention_edges + self.frontmatter_edges


def auto_link_entry(
    entry: Entry,
    all_entries: list[Entry],
    edge_repo: EdgeRepository,
    *,
    enable_mentions: bool = True,
    enable_frontmatter: bool = True,
) -> AutoLinkResult:
    """Run all enrichers against one entry and persist resulting edges."""
    idx = build_alias_index(all_entries)
    result = AutoLinkResult(entry_id=entry.id)

    if enable_frontmatter:
        fm = parse_frontmatter(entry.content or "")
        if fm:
            for target_id, relation, weight in enrich_from_frontmatter(fm, idx, self_id=entry.id):
                edge_repo.create(
                    Edge(
                        source_id=entry.id,
                        target_id=target_id,
                        relation=relation,
                        weight=weight,
                        metadata={"derived_by": "autolink.frontmatter"},
                    )
                )
                result.frontmatter_edges += 1

    if enable_mentions:
        mentions = find_mentions(entry.content or "", idx, self_id=entry.id)
        for target_id in mentions:
            edge_repo.create(
                Edge(
                    source_id=entry.id,
                    target_id=target_id,
                    relation=EdgeRelation.documents,
                    weight=0.4,
                    metadata={"derived_by": "autolink.mention"},
                )
            )
            result.mention_edges += 1

    return result
