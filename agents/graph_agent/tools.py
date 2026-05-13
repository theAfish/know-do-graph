"""Tool definitions for the GraphAgent.

Each function corresponds to an OpenAI function-calling tool.  All functions
receive the live ``KnowDoGraph`` instance via the module-level ``_graph``
variable which is set once by ``GraphAgent.__init__``.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


# ---------------------------------------------------------------------------
# Node / Entry tools
# ---------------------------------------------------------------------------


def create_entry(
    title: str,
    content: str = "",
    entry_type: str = "generic",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    source_provenance: str | None = None,
    graph: Any = None,
) -> dict:
    """Create a new knowledge entry (node) in the graph."""
    from core.schemas.entry import Entry, EntryMetadata, EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    entry = Entry(
        title=title,
        content=content,
        entry_type=EntryType(entry_type),
        tags=tags or [],
        aliases=aliases or [],
        metadata=EntryMetadata(source_provenance=source_provenance),
    )
    with SessionLocal() as db:
        saved = EntryRepository(db).create(entry)
    if graph is not None:
        graph.add_entry(saved)
    return {"id": saved.id, "slug": saved.slug, "title": saved.title}


def update_entry(
    entry_id: str,
    title: str | None = None,
    content: str | None = None,
    entry_type: str | None = None,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    graph: Any = None,
) -> dict:
    """Update fields on an existing entry."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.schemas.entry import EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.resolve_identifier(entry_id)
        if entry is None:
            return {"error": f"Entry '{entry_id}' not found."}
        if title is not None:
            entry.title = title
        if content is not None:
            entry.content = content
            entry.refresh_refs()
        if entry_type is not None:
            entry.entry_type = EntryType(entry_type)
        if tags is not None:
            entry.tags = tags
        if aliases is not None:
            entry.aliases = aliases
        saved = EntryRepository(db).update(entry)
    if graph is not None and saved:
        graph.add_entry(saved)  # upsert node attributes
    return {"id": saved.id, "slug": saved.slug, "title": saved.title} if saved else {"error": "Update failed."}


def delete_entry(entry_id: str, graph: Any = None) -> dict:
    """Delete an entry (node) and its associated edges."""
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    with SessionLocal() as db:
        deleted = EntryRepository(db).delete(entry_id)
    if deleted and graph is not None:
        graph.remove_entry(entry_id)
    return {"deleted": deleted, "entry_id": entry_id}


def search_entries(query: str, limit: int = 10, graph: Any = None) -> list[dict]:
    """Full-text search over entry titles and content."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        results = engine.search_entries(query=query, limit=limit)
    return [
        {"id": e.id, "slug": e.slug, "title": e.title, "type": e.entry_type.value, "tags": e.tags}
        for e in results
    ]


def get_entry(identifier: str, graph: Any = None) -> dict:
    """Retrieve a single entry by ID, slug, or alias."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.resolve_identifier(identifier)
    if entry is None:
        return {"error": f"Entry '{identifier}' not found."}
    return {
        "id": entry.id,
        "slug": entry.slug,
        "title": entry.title,
        "type": entry.entry_type.value,
        "tags": entry.tags,
        "aliases": entry.aliases,
        "content": entry.content,
        "refs": entry.internal_refs,
        "source": entry.metadata.source_provenance,
        "status": entry.metadata.refinement_status.value,
    }


def list_entries(limit: int = 20, graph: Any = None) -> list[dict]:
    """List entries in the graph."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entries = engine.list_entries(limit=limit)
    return [
        {"id": e.id, "slug": e.slug, "title": e.title, "type": e.entry_type.value}
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Edge tools
# ---------------------------------------------------------------------------


def create_edge(
    source_id: str,
    target_id: str,
    relation: str = "related_to",
    weight: float = 1.0,
    graph: Any = None,
) -> dict:
    """Create a directed edge between two entries."""
    from core.schemas.edge import Edge, EdgeRelation
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository

    try:
        rel = EdgeRelation(relation)
    except ValueError:
        rel = EdgeRelation.wikilink

    edge = Edge(source_id=source_id, target_id=target_id, relation=rel, weight=weight)
    with SessionLocal() as db:
        saved = EdgeRepository(db).create(edge)
    if graph is not None:
        graph.add_edge(saved)
    return {"id": saved.id, "source_id": saved.source_id, "target_id": saved.target_id, "relation": saved.relation.value}


def delete_edge(edge_id: str, graph: Any = None) -> dict:
    """Delete an edge by its ID."""
    from core.storage.database import SessionLocal
    from core.storage.models import EdgeModel
    from core.storage.repository import EdgeRepository
    from core.schemas.edge import Edge

    with SessionLocal() as db:
        model = db.get(EdgeModel, edge_id)
        if model is None:
            return {"error": f"Edge '{edge_id}' not found."}
        src_id, tgt_id = model.source_id, model.target_id
        deleted = EdgeRepository(db).delete(edge_id)
        if deleted and graph is not None:
            graph.remove_edge(src_id, tgt_id)
    return {"deleted": deleted, "edge_id": edge_id}


def get_neighbors(entry_id: str, direction: str = "both", graph: Any = None) -> list[dict]:
    """Get neighboring entries connected by edges."""
    from core import app_state

    g = graph or app_state.graph
    neighbors = g.get_neighbors(entry_id, direction=direction)
    return neighbors


# ---------------------------------------------------------------------------
# Graph-level tools
# ---------------------------------------------------------------------------


def graph_stats(graph: Any = None) -> dict:
    """Return high-level statistics about the graph."""
    from core import app_state

    g = graph or app_state.graph
    return g.stats()


def resolve_wikilinks(graph: Any = None) -> dict:
    """Scan all entries for [[wikilinks]] and create edges for matches."""
    from core import app_state
    from agents.extraction_agent.agent import ExtractionAgent

    g = graph or app_state.graph
    agent = ExtractionAgent(g)
    count = agent.resolve_wikilinks()
    return {"edges_created": count}


def remove_dangling_edges(graph: Any = None) -> dict:
    """Remove edges pointing to deleted entries."""
    from core import app_state
    from agents.maintenance_agent.agent import MaintenanceAgent

    g = graph or app_state.graph
    agent = MaintenanceAgent(g)
    count = agent.remove_dangling_edges()
    return {"edges_removed": count}


# ---------------------------------------------------------------------------
# Web / URL tools
# ---------------------------------------------------------------------------


def fetch_url(url: str, timeout: int = 15) -> dict:
    """Fetch the text content of a URL and return it so the agent can read it.

    Uses ``httpx`` if available, falls back to ``urllib``.
    Returns a dict with keys ``url``, ``status_code``, and ``text``.
    """
    try:
        try:
            import httpx
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                resp = client.get(url, headers={"User-Agent": "KnowDoGraph/1.0"})
                return {"url": url, "status_code": resp.status_code, "text": resp.text[:20000]}
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "KnowDoGraph/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return {"url": url, "status_code": resp.status, "text": resp.read(20000).decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo and return result snippets."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Node-discovery / graph-intelligence tools
# ---------------------------------------------------------------------------


def find_similar_nodes(title: str, limit: int = 8, graph: Any = None) -> list[dict]:
    """Search for nodes whose title or aliases closely resemble *title*.

    Use this before creating a new node to avoid duplicates and decide whether
    to reuse an existing entry, add an alias, or create a truly new node.
    Returns id, slug, title, type, tags, and aliases for each candidate.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        results = engine.search_entries(query=title, limit=limit)
    return [
        {
            "id": e.id,
            "slug": e.slug,
            "title": e.title,
            "type": e.entry_type.value,
            "tags": e.tags,
            "aliases": e.aliases,
        }
        for e in results
    ]


def get_graph_overview(sample_size: int = 15, graph: Any = None) -> dict:
    """Return a high-level overview of the graph without dumping every node.

    Includes:
    - Node/edge counts and DAG status
    - Distribution of entry types
    - A random sample of node titles (to check naming conventions)
    - Top-5 most connected nodes

    Use this to orient yourself before deciding how to add or restructure nodes.
    """
    import random
    from collections import Counter

    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    stats = g.stats()

    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        all_entries = engine.list_entries(limit=2000)

    type_dist = dict(Counter(e.entry_type.value for e in all_entries))
    sample = random.sample(all_entries, min(sample_size, len(all_entries)))
    sample_titles = [{"id": e.id, "title": e.title, "type": e.entry_type.value, "tags": e.tags} for e in sample]

    # Top connected nodes (by total degree in the in-memory graph)
    top_nodes: list[dict] = []
    try:
        degree_map = dict(g._g.degree())  # type: ignore[attr-defined]
        top_ids = sorted(degree_map, key=lambda k: degree_map[k], reverse=True)[:5]
        id_to_entry = {e.id: e for e in all_entries}
        top_nodes = [
            {"id": nid, "title": id_to_entry[nid].title if nid in id_to_entry else "?", "degree": degree_map[nid]}
            for nid in top_ids
        ]
    except Exception:
        pass

    return {
        "stats": stats,
        "type_distribution": type_dist,
        "sample_nodes": sample_titles,
        "top_connected": top_nodes,
    }


def list_nodes_by_type(entry_type: str, limit: int = 50, graph: Any = None) -> list[dict]:
    """List all nodes of a given entry type (returns id, slug, title, tags, aliases)."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.schemas.entry import EntryType
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        try:
            et = EntryType(entry_type)
        except ValueError:
            return [{"error": f"Unknown entry_type '{entry_type}'"}]
        results = engine.search_entries(entry_type=et, limit=limit)
    return [
        {"id": e.id, "slug": e.slug, "title": e.title, "tags": e.tags, "aliases": e.aliases}
        for e in results
    ]


def merge_entries(
    primary_id: str,
    duplicate_id: str,
    merge_aliases: bool = True,
    merge_tags: bool = True,
    graph: Any = None,
) -> dict:
    """Merge *duplicate_id* into *primary_id*.

    The duplicate's aliases and tags are optionally merged into the primary.
    All edges pointing to/from the duplicate are re-targeted to the primary.
    The duplicate entry is then deleted.

    Use this to consolidate redundant nodes identified during review.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal
    from core.storage.models import EdgeModel
    from core.storage.repository import EntryRepository

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        primary = engine.resolve_identifier(primary_id)
        duplicate = engine.resolve_identifier(duplicate_id)
        if primary is None:
            return {"error": f"Primary entry '{primary_id}' not found."}
        if duplicate is None:
            return {"error": f"Duplicate entry '{duplicate_id}' not found."}
        if primary.id == duplicate.id:
            return {"error": "primary_id and duplicate_id refer to the same entry."}

        # Re-target edges
        edges_retargeted = 0
        for edge_model in db.query(EdgeModel).filter(EdgeModel.target_id == duplicate.id).all():
            if edge_model.source_id != primary.id:
                edge_model.target_id = primary.id
                edges_retargeted += 1
        for edge_model in db.query(EdgeModel).filter(EdgeModel.source_id == duplicate.id).all():
            if edge_model.target_id != primary.id:
                edge_model.source_id = primary.id
                edges_retargeted += 1

        # Merge metadata into primary
        if merge_aliases:
            new_aliases = list(dict.fromkeys(primary.aliases + duplicate.aliases + [duplicate.title]))
            primary.aliases = new_aliases
        if merge_tags:
            primary.tags = list(dict.fromkeys(primary.tags + duplicate.tags))

        repo = EntryRepository(db)
        repo.update(primary)

        # Delete the duplicate entry model directly
        from core.storage.models import EntryModel
        dup_model = db.get(EntryModel, duplicate.id)
        if dup_model:
            db.delete(dup_model)
        db.commit()

    # Refresh in-memory graph
    if g is not None:
        g.remove_entry(duplicate.id)
        with SessionLocal() as db2:
            from core.retrieval.retrieval import RetrievalEngine as RE
            refreshed = RE(db2, g).get_entry_by_id(primary.id)
            if refreshed:
                g.add_entry(refreshed)

    return {
        "merged": True,
        "primary_id": primary.id,
        "removed_duplicate_id": duplicate.id,
        "edges_retargeted": edges_retargeted,
    }


# ---------------------------------------------------------------------------
# Script entry tools
# ---------------------------------------------------------------------------


def create_script_entry(
    title: str,
    code: str,
    language: str = "python",
    requirements: list[str] | None = None,
    description: str = "",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    filename: str | None = None,
    source_provenance: str | None = None,
    graph: Any = None,
) -> dict:
    """Create a script entry in the graph — stores executable code that external agents/users can download.

    The code is stored in the entry's ``content`` field; language, requirements,
    and suggested filename are saved in the entry metadata so they survive
    serialisation.
    """
    from core.schemas.entry import Entry, EntryMetadata, EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    meta = EntryMetadata(
        source_provenance=source_provenance,
        script_language=language,
        script_requirements=requirements or [],
        script_filename=filename or _slug(title) + _ext_for_language(language),
    )
    # Prepend a header comment to the code for clarity
    header = f"# {title}\n# Language: {language}\n"
    if requirements:
        header += f"# Requirements: {', '.join(requirements)}\n"
    if description:
        header += f"# {description}\n"
    full_content = header + "\n" + code

    entry = Entry(
        title=title,
        content=full_content,
        entry_type=EntryType.capability,
        tags=tags or [],
        aliases=aliases or [],
        metadata=meta,
    )
    with SessionLocal() as db:
        saved = EntryRepository(db).create(entry)
    if graph is not None:
        graph.add_entry(saved)
    return {
        "id": saved.id,
        "slug": saved.slug,
        "title": saved.title,
        "language": language,
        "filename": meta.script_filename,
        "download_url": f"/entries/{saved.id}/download",
    }


def _ext_for_language(language: str) -> str:
    """Map language name to a file extension."""
    mapping = {
        "python": ".py",
        "py": ".py",
        "bash": ".sh",
        "shell": ".sh",
        "sh": ".sh",
        "julia": ".jl",
        "javascript": ".js",
        "js": ".js",
        "typescript": ".ts",
        "ts": ".ts",
        "r": ".r",
        "matlab": ".m",
        "ruby": ".rb",
        "rust": ".rs",
        "go": ".go",
        "c": ".c",
        "cpp": ".cpp",
        "c++": ".cpp",
    }
    return mapping.get(language.lower(), ".txt")


def get_script(identifier: str, graph: Any = None) -> dict:
    """Retrieve a script entry's code, language, and requirements by ID or slug.

    Returns everything needed for a user to download and run the script locally.
    """
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        entry = engine.resolve_identifier(identifier)
    if entry is None:
        return {"error": f"Entry '{identifier}' not found."}
    if not entry.metadata.script_language:
        return {"error": f"Entry '{identifier}' has no script_language in metadata — not a downloadable script."}
    return {
        "id": entry.id,
        "slug": entry.slug,
        "title": entry.title,
        "language": entry.metadata.script_language or "unknown",
        "requirements": entry.metadata.script_requirements,
        "filename": entry.metadata.script_filename or entry.slug + ".txt",
        "code": entry.content,
        "download_url": f"/entries/{entry.id}/download",
    }


def list_scripts(limit: int = 50, graph: Any = None) -> list[dict]:
    """List all capability entries that have runnable scripts attached (have script_language set in metadata)."""
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    g = graph or app_state.graph
    with SessionLocal() as db:
        engine = RetrievalEngine(db, g)
        # Fetch a broad set and filter by presence of script_language in metadata
        candidates = engine.list_entries(limit=max(limit * 5, 500))
    results = [e for e in candidates if e.metadata.script_language]
    return [
        {
            "id": e.id,
            "slug": e.slug,
            "title": e.title,
            "language": e.metadata.script_language or "unknown",
            "filename": e.metadata.script_filename,
            "requirements": e.metadata.script_requirements,
            "tags": e.tags,
            "download_url": f"/entries/{e.id}/download",
        }
        for e in results[:limit]
    ]


# ---------------------------------------------------------------------------
# Material interface tools
# ---------------------------------------------------------------------------


def build_material_interface_workflow(
    material_a: str,
    material_b: str,
    method: str = "slab_stacking",
    description: str = "",
    tags: list[str] | None = None,
    graph: Any = None,
) -> dict:
    """Create a structured workflow chain for building a material interface between two materials.

    Creates three linked entries:
      1. A *material_interface* node representing the interface concept.
      2. A *procedure* node describing the construction method (e.g. slab stacking,
         lattice matching, supercell creation).
      3. A *data* node as a placeholder for resulting interface structure data.

    Edges: workflow → procedure (execution_pathway), procedure → interface (generates),
           interface → data (provenance).

    Returns the IDs of all created nodes.
    """
    import uuid
    from core.schemas.edge import Edge, EdgeRelation
    from core.schemas.entry import Entry, EntryMetadata, EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository, EntryRepository

    base_tags = list(dict.fromkeys(["materials-interface", "computational-materials"] + (tags or [])))
    description_text = description or (
        f"Interface between {material_a} and {material_b} constructed via {method}."
    )

    # 1. Interface node — typed as capability (it IS a known capability/skill)
    interface_entry = Entry(
        title=f"{material_a}/{material_b} Interface",
        content=(
            f"## {material_a}/{material_b} Interface\n\n"
            f"{description_text}\n\n"
            f"Construction method: {method}\n\n"
            f"### Key considerations\n"
            f"- Lattice mismatch between [[{material_a}]] and [[{material_b}]]\n"
            f"- Surface termination and reconstruction\n"
            f"- Charge neutrality and stoichiometry at the interface\n"
            f"- Band alignment and electronic structure\n"
        ),
        entry_type=EntryType.capability,
        tags=base_tags,
        metadata=EntryMetadata(),
    )

    # 2. Procedure node
    procedure_entry = Entry(
        title=f"Build {material_a}/{material_b} Interface via {method.replace('_', ' ').title()}",
        content=(
            f"## Construction Procedure\n\n"
            f"Step-by-step procedure for building a [[{material_a}/{material_b} Interface]] "
            f"using the *{method.replace('_', ' ')}* approach.\n\n"
            f"### Steps\n"
            f"1. Obtain or generate bulk structures for [[{material_a}]] and [[{material_b}]].\n"
            f"2. Select appropriate surface facets and create slab models.\n"
            f"3. Match lattice parameters (strain or supercell expansion).\n"
            f"4. Stack the slabs with appropriate vacuum spacing.\n"
            f"5. Relax the interface geometry.\n"
            f"6. Validate structure and compute interface energy.\n"
        ),
        entry_type=EntryType.procedure,
        tags=base_tags + ["construction"],
        metadata=EntryMetadata(),
    )

    # 3. Data placeholder node
    data_entry = Entry(
        title=f"{material_a}/{material_b} Interface Structure Data",
        content=(
            f"Structural data and calculation results for the "
            f"[[{material_a}/{material_b} Interface]].\n\n"
            f"Expected outputs:\n"
            f"- Interface geometry file (CIF / POSCAR / XYZ)\n"
            f"- Interface energy (J/m²)\n"
            f"- Band alignment (eV)\n"
            f"- Relaxed atomic positions\n"
        ),
        entry_type=EntryType.data,
        tags=base_tags + ["structure-data"],
        metadata=EntryMetadata(),
    )

    with SessionLocal() as db:
        repo = EntryRepository(db)
        edge_repo = EdgeRepository(db)

        saved_interface = repo.create(interface_entry)
        saved_procedure = repo.create(procedure_entry)
        saved_data = repo.create(data_entry)

        # procedure → interface (execution_pathway: running the procedure produces the interface)
        e1 = Edge(source_id=saved_procedure.id, target_id=saved_interface.id, relation=EdgeRelation.execution_pathway)
        # interface → data (provenance: the interface is the source of the data)
        e2 = Edge(source_id=saved_interface.id, target_id=saved_data.id, relation=EdgeRelation.provenance)
        # procedure → data (generated_from perspective: data is generated by procedure)
        e3 = Edge(source_id=saved_data.id, target_id=saved_procedure.id, relation=EdgeRelation.generated_from)

        saved_e1 = edge_repo.create(e1)
        saved_e2 = edge_repo.create(e2)
        saved_e3 = edge_repo.create(e3)

    g = graph
    if g is not None:
        g.add_entry(saved_interface)
        g.add_entry(saved_procedure)
        g.add_entry(saved_data)
        g.add_edge(saved_e1)
        g.add_edge(saved_e2)
        g.add_edge(saved_e3)

    return {
        "interface_id": saved_interface.id,
        "interface_slug": saved_interface.slug,
        "procedure_id": saved_procedure.id,
        "procedure_slug": saved_procedure.slug,
        "data_id": saved_data.id,
        "data_slug": saved_data.slug,
        "edges_created": 3,
    }


def create_material_entry(
    formula: str,
    crystal_system: str = "",
    space_group: str = "",
    description: str = "",
    tags: list[str] | None = None,
    source_provenance: str | None = None,
    graph: Any = None,
) -> dict:
    """Create a structured *material* entry for a crystal or compound.

    Stores formula, crystal system, space group, and description in a standardised
    content template so the entry is immediately useful for downstream interface
    workflows and agent reasoning.
    """
    from core.schemas.entry import Entry, EntryMetadata, EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    content_lines = [f"## {formula}\n"]
    if crystal_system:
        content_lines.append(f"- **Crystal system**: {crystal_system}")
    if space_group:
        content_lines.append(f"- **Space group**: {space_group}")
    if description:
        content_lines.append(f"\n{description}")
    content_lines.append(
        "\n### Usage\n"
        f"This material can be used as a component in [[{formula}/X Interface]] workflows."
    )

    entry = Entry(
        title=formula,
        content="\n".join(content_lines),
        entry_type=EntryType.data,
        tags=list(dict.fromkeys(["material", "crystal"] + (tags or []))),
        metadata=EntryMetadata(source_provenance=source_provenance),
    )
    with SessionLocal() as db:
        saved = EntryRepository(db).create(entry)
    if graph is not None:
        graph.add_entry(saved)
    return {"id": saved.id, "slug": saved.slug, "title": saved.title, "type": "data"}


def attach_script_to_entry(
    entry_id: str,
    script_id: str,
    relation: str = "implements",
    graph: Any = None,
) -> dict:
    """Create a typed edge linking a script to any graph entry.

    Typical usage: link a script that *implements* a procedure, *documents*
    an analytical method, or *uses* a tool/dependency.

    relation must be one of: implements, uses, documents, execution_pathway.
    """
    from core import app_state
    from core.schemas.edge import Edge, EdgeRelation
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository

    allowed = {"implements", "uses", "documents", "execution_pathway", "generated_from", "derived_from"}
    if relation not in allowed:
        return {"error": f"relation must be one of {sorted(allowed)}"}

    try:
        rel = EdgeRelation(relation)
    except ValueError:
        rel = EdgeRelation.implements

    edge = Edge(source_id=script_id, target_id=entry_id, relation=rel, weight=1.0)
    g = graph or app_state.graph
    with SessionLocal() as db:
        saved = EdgeRepository(db).create(edge)
    if g is not None:
        g.add_edge(saved)
    return {"edge_id": saved.id, "script_id": script_id, "entry_id": entry_id, "relation": rel.value}


# ---------------------------------------------------------------------------
# OpenAI tool schema definitions
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_entry",
            "description": "Create a new knowledge entry (node) in the graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Entry title"},
                    "content": {"type": "string", "description": "Entry body (wiki text, markdown)"},
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "procedure", "workflow", "tool", "repository",
                                 "environment", "dependency", "data", "analytical", "memory", "generic"],
                        "description": "Semantic type of this entry",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tags"},
                    "aliases": {"type": "array", "items": {"type": "string"}, "description": "Alternative names / synonyms for this entry"},
                    "source_provenance": {"type": "string", "description": "URL or path this entry was sourced from"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_entry",
            "description": "Update fields on an existing entry by its ID or slug.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Entry ID or slug"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "procedure", "workflow", "tool", "repository",
                                 "environment", "dependency", "data", "analytical", "memory", "generic"],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "aliases": {"type": "array", "items": {"type": "string"}, "description": "Alternative names / synonyms"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_entry",
            "description": "Delete an entry (node) and all its edges by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Entry ID"},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entry",
            "description": "Retrieve full details of a single entry by ID or slug.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Entry ID or slug"},
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entries",
            "description": "Full-text search for entries matching a query string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_entries",
            "description": "List entries in the graph (returns id, slug, title, type).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": "Create a directed edge (relationship) between two entries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "Source entry ID"},
                    "target_id": {"type": "string", "description": "Target entry ID"},
                    "relation": {
                        "type": "string",
                        "enum": ["dependency", "compatible_with", "alternative_to", "related_workflow",
                                 "generated_from", "memory_of", "refinement_of", "derived_from",
                                 "warning_about", "cited_by", "wikilink", "prerequisite", "replacement",
                                 "execution_pathway", "transformation", "provenance", "compatibility",
                                 "implements", "uses", "documents"],
                        "description": "Semantic relation type",
                    },
                    "weight": {"type": "number", "default": 1.0},
                },
                "required": ["source_id", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_edge",
            "description": "Delete an edge by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "edge_id": {"type": "string"},
                },
                "required": ["edge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_neighbors",
            "description": "Get entries directly connected to a given entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["out", "in", "both"],
                        "default": "both",
                    },
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_stats",
            "description": "Return node count, edge count, and DAG status of the graph.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_wikilinks",
            "description": "Scan all entry content for [[wikilinks]] and create edges for resolved matches.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_dangling_edges",
            "description": "Remove edges whose source or target entry no longer exists.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and return the text content of any URL (web page, API endpoint, documentation site, etc.). Use this when the user provides a specific URL or when you need to read a page in full rather than just search snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "timeout": {"type": "integer", "default": 15, "description": "Request timeout in seconds"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via DuckDuckGo and return titles, URLs and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_nodes",
            "description": (
                "Search for existing nodes whose title or aliases resemble a given title. "
                "ALWAYS call this before creating a new node to avoid duplicates. "
                "Returns candidates with id, slug, title, type, tags, and aliases."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The proposed node title or concept to check"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_overview",
            "description": (
                "Get a high-level overview of the graph: stats, type distribution, "
                "a random sample of node titles, and the most connected nodes. "
                "Use this to orient yourself before adding or restructuring content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_size": {"type": "integer", "default": 15, "description": "Number of random nodes to sample"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_nodes_by_type",
            "description": "List all nodes of a specific entry type (capability, tool, procedure, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_type": {
                        "type": "string",
                        "enum": ["capability", "procedure", "workflow", "tool", "repository",
                                 "environment", "dependency", "data", "analytical", "memory", "generic"],
                    },
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["entry_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_entries",
            "description": (
                "Merge a duplicate node into a primary node. "
                "Re-targets all edges, optionally merges aliases and tags, then deletes the duplicate. "
                "Use when two nodes represent the same concept."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "primary_id": {"type": "string", "description": "ID or slug of the entry to keep"},
                    "duplicate_id": {"type": "string", "description": "ID or slug of the entry to remove"},
                    "merge_aliases": {"type": "boolean", "default": True, "description": "Add duplicate's title and aliases to primary's aliases"},
                    "merge_tags": {"type": "boolean", "default": True, "description": "Merge duplicate's tags into primary"},
                },
                "required": ["primary_id", "duplicate_id"],
            },
        },
    },
    # ------------------------------------------------------------------ #
    # Script management tools                                              #
    # ------------------------------------------------------------------ #
    {
        "type": "function",
        "function": {
            "name": "create_script_entry",
            "description": (
                "Create a script entry in the graph, storing executable code that "
                "external agents or users can later download and run locally. "
                "Use for Python, bash, Julia, or any other runnable script."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Human-readable script title"},
                    "code": {"type": "string", "description": "The full source code of the script"},
                    "language": {
                        "type": "string",
                        "description": "Programming language (e.g. python, bash, julia, r)",
                        "default": "python",
                    },
                    "requirements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package dependencies (e.g. ['ase', 'numpy'])",
                    },
                    "description": {"type": "string", "description": "Short description of what the script does"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "filename": {"type": "string", "description": "Suggested filename for download (e.g. relax.py)"},
                    "source_provenance": {"type": "string", "description": "URL or citation this script was derived from"},
                },
                "required": ["title", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_script",
            "description": (
                "Retrieve the full source code, language, requirements, and download URL "
                "of a script entry by its ID or slug."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Script entry ID or slug"},
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scripts",
            "description": "List all script entries in the graph with their language, filename, and download URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attach_script_to_entry",
            "description": (
                "Link a script entry to another entry via a semantic edge. "
                "Use 'implements' when a script implements a procedure, "
                "'documents' when a script demonstrates a capability, "
                "'uses' when a script depends on a tool/library entry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "script_id": {"type": "string", "description": "ID or slug of the script entry"},
                    "entry_id": {"type": "string", "description": "ID or slug of the target entry"},
                    "relation": {
                        "type": "string",
                        "enum": ["implements", "uses", "documents", "execution_pathway", "generated_from", "derived_from"],
                        "default": "implements",
                    },
                },
                "required": ["script_id", "entry_id"],
            },
        },
    },
    # ------------------------------------------------------------------ #
    # Material interface tools                                             #
    # ------------------------------------------------------------------ #
    {
        "type": "function",
        "function": {
            "name": "create_material_entry",
            "description": (
                "Create a structured data entry for a crystal or compound (uses entry_type=data), "
                "recording its formula, crystal system, space group, and description "
                "in a standardised template suitable for downstream interface workflows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "formula": {"type": "string", "description": "Chemical formula or material name (e.g. 'TiO2', 'GaN')"},
                    "crystal_system": {"type": "string", "description": "e.g. cubic, tetragonal, hexagonal"},
                    "space_group": {"type": "string", "description": "Hermann-Mauguin symbol or number (e.g. 'Fm-3m', '225')"},
                    "description": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source_provenance": {"type": "string"},
                },
                "required": ["formula"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_material_interface_workflow",
            "description": (
                "Create a full workflow chain in the graph for building a material interface "
                "between two materials. Produces three linked entries: a capability node for the interface, "
                "a construction procedure node, and a data placeholder node, wired with "
                "appropriate edges."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_a": {"type": "string", "description": "Formula or name of the first material (e.g. 'TiO2')"},
                    "material_b": {"type": "string", "description": "Formula or name of the second material (e.g. 'SrTiO3')"},
                    "method": {
                        "type": "string",
                        "description": "Construction method: slab_stacking, lattice_matching, supercell, epitaxial_growth",
                        "default": "slab_stacking",
                    },
                    "description": {"type": "string", "description": "Additional context or motivation for this interface"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["material_a", "material_b"],
            },
        },
    },
]

# Map function name → callable
TOOL_DISPATCH: dict[str, Any] = {
    "create_entry": create_entry,
    "update_entry": update_entry,
    "delete_entry": delete_entry,
    "get_entry": get_entry,
    "search_entries": search_entries,
    "list_entries": list_entries,
    "create_edge": create_edge,
    "delete_edge": delete_edge,
    "get_neighbors": get_neighbors,
    "graph_stats": graph_stats,
    "resolve_wikilinks": resolve_wikilinks,
    "remove_dangling_edges": remove_dangling_edges,
    "fetch_url": fetch_url,
    "web_search": web_search,
    "find_similar_nodes": find_similar_nodes,
    "get_graph_overview": get_graph_overview,
    "list_nodes_by_type": list_nodes_by_type,
    "merge_entries": merge_entries,
    "create_script_entry": create_script_entry,
    "get_script": get_script,
    "list_scripts": list_scripts,
    "build_material_interface_workflow": build_material_interface_workflow,
    "create_material_entry": create_material_entry,
    "attach_script_to_entry": attach_script_to_entry,
}
