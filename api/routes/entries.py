from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core import events as _events
from core.app_state import graph as _graph
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.edge import EdgeRelation
from core.schemas.entry import (
    KNOWN_ASSET_FOLDERS,
    Entry,
    EntryType,
    NodeAsset,
)
from core.storage.database import get_db
from core.storage.repository import EntryRepository

router = APIRouter()


def _engine(db: Session = Depends(get_db)) -> RetrievalEngine:
    return RetrievalEngine(db, _graph)


@router.get("/", response_model=list[dict])
def list_entries(
    limit: int = 20,
    offset: int = 0,
    engine: RetrievalEngine = Depends(_engine),
):
    """List entries with pagination."""
    return [e.model_dump(mode="json") for e in engine.list_entries(limit=limit, offset=offset)]


@router.get("/search", response_model=list[dict])
def search_entries(
    q: Optional[str] = None,
    tags: Optional[str] = None,
    entry_type: Optional[EntryType] = None,
    limit: int = 20,
    include_scores: bool = False,
    engine: RetrievalEngine = Depends(_engine),
):
    """Full-text + vector hybrid search.

    Pass ``include_scores=true`` to receive a ``_score`` field (0.0–1.0) on
    each result — useful for rendering relevance coloring in the frontend.
    """
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    if include_scores and q:
        results = engine.search_entries_scored(
            query=q, tags=tag_list, entry_type=entry_type, limit=limit
        )
        return [{**e.model_dump(mode="json"), "_score": round(score, 4)} for e, score in results]
    results = engine.search_entries(query=q, tags=tag_list, entry_type=entry_type, limit=limit)
    return [e.model_dump(mode="json") for e in results]


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """Retrieve a single entry by ID, slug, or alias."""
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry.model_dump(mode="json")


@router.post("/", response_model=dict, status_code=201)
def create_entry(entry: Entry, db: Session = Depends(get_db)):
    """Create a new entry."""
    saved = EntryRepository(db).create(entry)
    _graph.add_entry(saved)
    _events.emit(
        "node_added",
        {
            "id": saved.id,
            "title": saved.title,
            "slug": saved.slug,
            "entry_type": saved.entry_type.value
            if hasattr(saved.entry_type, "value")
            else saved.entry_type,
            "tags": saved.tags,
        },
    )
    return saved.model_dump(mode="json")


@router.put("/{entry_id}", response_model=dict)
def update_entry(entry_id: str, entry: Entry, db: Session = Depends(get_db)):
    """Update an existing entry."""
    entry.id = entry_id
    entry.refresh_refs()
    entry._sync_scripts_and_assets()
    updated = EntryRepository(db).update(entry)
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    _graph.add_entry(updated)
    _events.emit(
        "node_updated",
        {
            "id": updated.id,
            "title": updated.title,
            "slug": updated.slug,
            "entry_type": updated.entry_type.value
            if hasattr(updated.entry_type, "value")
            else updated.entry_type,
            "tags": updated.tags,
        },
    )
    return updated.model_dump(mode="json")


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    """Delete an entry and its node from the in-memory graph."""
    if not EntryRepository(db).delete(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    _graph.remove_entry(entry_id)
    _events.emit("node_removed", {"id": entry_id})


@router.get("/{entry_id}/related", response_model=list[dict])
def get_related(
    entry_id: str,
    depth: int = 1,
    relation: Optional[EdgeRelation] = None,
    engine: RetrievalEngine = Depends(_engine),
):
    """Return entries related to *entry_id* via the graph."""
    related = engine.get_related_entries(entry_id, depth=depth, relation=relation)
    return [e.model_dump(mode="json") for e in related]


@router.get("/{entry_id}/edges", response_model=list[dict])
def get_edges(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """Return all edges incident to *entry_id*."""
    return [e.model_dump(mode="json") for e in engine.get_edges_for_entry(entry_id)]


@router.get("/{entry_id}/scripts")
def list_entry_scripts(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """List all scripts attached to an entry (metadata only — no code bodies)."""
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return [
        {
            "filename": s.filename,
            "language": s.language,
            "requirements": s.requirements,
            "description": s.description,
            "download_url": f"/entries/{entry.id}/scripts/{s.filename}",
        }
        for s in entry.scripts
    ]


@router.get("/{entry_id}/scripts/{filename}")
def download_entry_script(entry_id: str, filename: str, engine: RetrievalEngine = Depends(_engine)):
    """Download the source code of a specific script attached to an entry."""
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    script = next((s for s in entry.scripts if s.filename == filename), None)
    if not script:
        raise HTTPException(status_code=404, detail=f"No script '{filename}' on entry '{entry_id}'")

    safe_filename = filename.replace("/", "_").replace("\\", "_").replace('"', "")
    media_type = _media_type_for_language(script.language)
    return Response(
        content=script.content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get("/{entry_id}/download")
def download_script(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """Download the first attached script of an entry (backward-compatible endpoint).

    Prefer ``GET /{entry_id}/scripts/{filename}`` when the entry has multiple scripts.
    Returns 400 if the entry has no scripts attached.
    """
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not entry.scripts:
        raise HTTPException(
            status_code=400,
            detail=f"Entry '{entry_id}' has no attached scripts.",
        )

    script = entry.scripts[0]
    filename = script.filename.replace("/", "_").replace("\\", "_").replace('"', "")
    media_type = _media_type_for_language(script.language)
    return Response(
        content=script.content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _media_type_for_language(language: str) -> str:
    mapping = {
        "python": "text/x-python",
        "py": "text/x-python",
        "bash": "text/x-sh",
        "shell": "text/x-sh",
        "sh": "text/x-sh",
        "julia": "text/x-julia",
        "javascript": "text/javascript",
        "js": "text/javascript",
        "typescript": "text/typescript",
        "ts": "text/typescript",
        "r": "text/x-r",
    }
    return mapping.get(language.lower(), "text/plain")


# ── Folder-style assets ─────────────────────────────────────────────────────


def _asset_meta(entry_id: str, asset: NodeAsset) -> dict:
    return {
        "folder": asset.folder,
        "filename": asset.filename,
        "path": asset.path,
        "kind": asset.kind,
        "language": asset.language,
        "mime_type": asset.mime_type,
        "description": asset.description,
        "requirements": asset.requirements,
        "size": len(asset.content or ""),
        "download_url": f"/entries/{entry_id}/assets/{asset.folder}/{asset.filename}",
        "metadata": asset.metadata,
    }


@router.get("/{entry_id}/assets")
def list_entry_assets(entry_id: str, engine: RetrievalEngine = Depends(_engine)):
    """List all assets attached to an entry, grouped by folder.

    Returns ``{ folders: { scripts: [...], references: [...], ... } }``.
    Use ``GET /entries/{id}/assets/{folder}/{filename}`` to fetch a body.
    """
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    grouped: dict[str, list[dict]] = {}
    for a in entry.assets:
        grouped.setdefault(a.folder, []).append(_asset_meta(entry.id, a))
    # Stable ordering: known folders first, then any extras alphabetically
    ordered = {}
    for f in KNOWN_ASSET_FOLDERS:
        if f in grouped:
            ordered[f] = grouped.pop(f)
    for f in sorted(grouped.keys()):
        ordered[f] = grouped[f]
    return {
        "entry_id": entry.id,
        "slug": entry.slug,
        "folders": ordered,
        "total": sum(len(v) for v in ordered.values()),
    }


@router.get("/{entry_id}/assets/{folder}")
def list_entry_assets_in_folder(
    entry_id: str, folder: str, engine: RetrievalEngine = Depends(_engine)
):
    """List assets in a single folder of an entry."""
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    items = [_asset_meta(entry.id, a) for a in entry.assets if a.folder == folder.lower()]
    return {"entry_id": entry.id, "folder": folder.lower(), "items": items}


@router.get("/{entry_id}/assets/{folder}/{filename:path}")
def download_entry_asset(
    entry_id: str,
    folder: str,
    filename: str,
    engine: RetrievalEngine = Depends(_engine),
):
    """Fetch the content of an asset.

    - ``kind == "file"``: returns the file body with an ``attachment`` disposition.
    - ``kind == "text"``: returns the body inline as ``text/markdown`` (or stored mime).
    - ``kind == "link"``: 302-redirects to the URL stored in ``content``.
    """
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if ".." in filename.split("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    asset = entry.find_asset(folder, filename)
    if asset is None:
        raise HTTPException(
            status_code=404,
            detail=f"No asset '{folder}/{filename}' on entry '{entry_id}'",
        )

    if asset.kind == "link":
        url = (asset.content or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Link asset has empty URL")
        return RedirectResponse(url=url, status_code=302)

    safe_name = asset.filename.split("/")[-1].replace('"', "")
    media_type = (
        asset.mime_type
        or (_media_type_for_language(asset.language) if asset.language else None)
        or ("text/markdown" if asset.kind == "text" else "application/octet-stream")
    )
    disposition = "inline" if asset.kind == "text" else "attachment"
    return Response(
        content=asset.content,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


class AssetBody(BaseModel):
    folder: str
    filename: str
    kind: str = "file"  # file | link | text
    content: str = ""
    language: Optional[str] = None
    mime_type: Optional[str] = None
    description: str = ""
    requirements: list[str] = []
    metadata: dict = {}


@router.post("/{entry_id}/assets", status_code=201)
def add_entry_asset(entry_id: str, body: AssetBody, db: Session = Depends(get_db)):
    """Add or replace an asset on an entry.

    If an asset with the same ``folder/filename`` exists it is replaced.
    """
    engine = RetrievalEngine(db, _graph)
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    try:
        new_asset = NodeAsset(**body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    entry.assets = [
        a
        for a in entry.assets
        if not (a.folder == new_asset.folder and a.filename == new_asset.filename)
    ]
    entry.assets.append(new_asset)
    updated = EntryRepository(db).update(entry)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update entry")
    _graph.add_entry(updated)
    return _asset_meta(updated.id, new_asset)


@router.delete("/{entry_id}/assets/{folder}/{filename:path}", status_code=204)
def delete_entry_asset(entry_id: str, folder: str, filename: str, db: Session = Depends(get_db)):
    """Delete a single asset from an entry."""
    engine = RetrievalEngine(db, _graph)
    entry = engine.resolve_identifier(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    folder_n = folder.lower()
    before = len(entry.assets)
    entry.assets = [
        a for a in entry.assets if not (a.folder == folder_n and a.filename == filename)
    ]
    if len(entry.assets) == before:
        raise HTTPException(status_code=404, detail="Asset not found")
    updated = EntryRepository(db).update(entry)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update entry")
    _graph.add_entry(updated)


# ── Feedback / verification ──────────────────────────────────────────────────


class FeedbackBody(BaseModel):
    verdict: str  # works | peer_works | bugged | deprecated | unclear
    note: str = ""
    evidence: str = ""
    agent_id: str = "external"


@router.post("/{entry_id}/feedback", status_code=201)
def post_entry_feedback(entry_id: str, body: FeedbackBody, db: Session = Depends(get_db)):
    """Record correctness feedback on an entry.

    Updates ``metadata.verification_status`` according to *verdict* and appends
    the event (timestamp + agent_id + note + evidence) to
    ``metadata.feedback_log``. This is the canonical channel for external
    agents to flag a node as working or bugged.
    """
    from agents.graph_agent.tools import submit_feedback

    result = submit_feedback(
        entry_id=entry_id,
        verdict=body.verdict,
        note=body.note,
        evidence=body.evidence,
        agent_id=body.agent_id,
        graph=_graph,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
