"""Remote-source sync routes.

These endpoints expose the :mod:`core.sync.remote_sync` machinery so that
operators (and the UI) can:

  * list all entries that mirror an upstream file,
  * trigger a one-shot resync (one entry or all due),
  * attach / detach a remote source on an existing entry.

Mounted at ``/remote-sync`` from :mod:`api.main`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.schemas import (
    RemoteLinkedEntry,
    RemoteSourceDetachResponse,
    RemoteSourceUpdateResponse,
    RemoteSyncAllResponse,
    RemoteSyncOneResponse,
)
from core import events as _events
from core.app_state import graph as _graph
from core.schemas.entry import RemoteSource
from core.storage.database import get_db
from core.storage.repository import EntryRepository
from core.sync.remote_sync import (
    SyncResult,
    parse_github_url,
    sync_all_due,
    sync_entry,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _result_to_dict(r: SyncResult) -> dict:
    return {
        "entry_id": r.entry_id,
        "title": r.title,
        "status": r.status,
        "detail": r.detail,
        "bytes_fetched": r.bytes_fetched,
        "new_hash": r.new_hash,
        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
    }


def _source_to_dict(src: RemoteSource) -> dict:
    d = src.model_dump(mode="json")
    if isinstance(d.get("fetched_at"), datetime):
        d["fetched_at"] = d["fetched_at"].isoformat()
    return d


def _resolve_entry(db: Session, id_or_slug: str):
    """Look up an entry by id, slug, or alias via EntryRepository.get_all().

    Cheap because get_all() is O(n) over a small node set; if this gets hot,
    add an explicit get_by_slug method on the repo.
    """
    repo = EntryRepository(db)
    for e in repo.get_all():
        if e.id == id_or_slug or e.slug == id_or_slug or id_or_slug in e.aliases:
            return repo, e
    raise HTTPException(status_code=404, detail=f"entry not found: {id_or_slug}")


# ── Request models ────────────────────────────────────────────────────────────


class AttachSourceRequest(BaseModel):
    url: str
    ref: Optional[str] = None
    path: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    auto_sync: bool = True
    sync_interval_seconds: int = 3600
    sync_now: bool = True


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[RemoteLinkedEntry])
def list_linked_entries(db: Session = Depends(get_db)) -> list[dict]:
    """List every entry that mirrors an upstream source."""
    out: list[dict] = []
    for e in EntryRepository(db).get_all():
        src = e.metadata.remote_source
        if src is None:
            continue
        out.append(
            {
                "entry_id": e.id,
                "slug": e.slug,
                "title": e.title,
                "remote_source": _source_to_dict(src),
            }
        )
    return out


@router.post("/all", response_model=RemoteSyncAllResponse)
async def sync_all_endpoint(force: bool = False) -> dict:
    """Sync every entry whose remote source is due (or all when ``force=true``)."""
    results = await sync_all_due(force=force)
    summary = {
        "checked": len(results),
        "updated": sum(1 for r in results if r.status == "updated"),
        "unchanged": sum(1 for r in results if r.status == "unchanged"),
        "errors": sum(1 for r in results if r.status == "error"),
        "results": [_result_to_dict(r) for r in results],
    }
    return summary


@router.post("/{id_or_slug}", response_model=RemoteSyncOneResponse)
async def sync_one_endpoint(
    id_or_slug: str,
    force: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    """Sync a single entry now."""
    repo, entry = _resolve_entry(db, id_or_slug)
    if entry.metadata.remote_source is None:
        raise HTTPException(status_code=400, detail="entry has no remote_source")
    result = await sync_entry(entry, force=force)
    updated = repo.update(entry)
    autolink_summary: dict | None = None
    if result.status == "updated" and updated is not None:
        try:
            _graph.add_entry(updated)
        except Exception:
            pass
        # Refresh derived edges from the new content.
        try:
            from core.storage.repository import EdgeRepository
            from core.sync.autolink import auto_link_entry

            al = auto_link_entry(updated, repo.get_all(), EdgeRepository(db))
            autolink_summary = {
                "frontmatter_edges": al.frontmatter_edges,
                "mention_edges": al.mention_edges,
            }
        except Exception:  # pragma: no cover
            pass
        _events.emit(
            "node_updated",
            {"id": entry.id, "slug": entry.slug, "title": entry.title, "source": "remote_sync"},
        )
    return {
        "result": _result_to_dict(result),
        "remote_source": _source_to_dict(entry.metadata.remote_source),
        "autolink": autolink_summary,
    }


@router.put("/{id_or_slug}/source", response_model=RemoteSourceUpdateResponse)
async def attach_source(
    id_or_slug: str,
    body: AttachSourceRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Attach or replace the remote source on an entry."""
    repo, entry = _resolve_entry(db, id_or_slug)

    owner = body.owner
    repo_name = body.repo
    path = body.path
    ref = body.ref
    kind = "github"

    parsed = parse_github_url(body.url)
    if parsed:
        owner = owner or parsed.get("owner")
        repo_name = repo_name or parsed.get("repo")
        path = path or parsed.get("path")
        ref = ref or parsed.get("ref") or "main"
    else:
        kind = "http"

    if kind == "github" and not (owner and repo_name and path):
        raise HTTPException(
            status_code=400,
            detail="GitHub source needs owner/repo/path (parsed from URL or supplied explicitly)",
        )

    src = RemoteSource(
        kind=kind,
        url=body.url,
        owner=owner,
        repo=repo_name,
        ref=ref or "main",
        path=path,
        auto_sync=body.auto_sync,
        sync_interval_seconds=body.sync_interval_seconds,
    )
    entry.metadata.remote_source = src
    repo.update(entry)

    result_dict = None
    if body.sync_now:
        result = await sync_entry(entry, force=True)
        updated = repo.update(entry)
        if result.status == "updated" and updated is not None:
            try:
                _graph.add_entry(updated)
            except Exception:
                pass
            _events.emit(
                "node_updated",
                {"id": entry.id, "slug": entry.slug, "title": entry.title, "source": "remote_sync"},
            )
        result_dict = _result_to_dict(result)

    return {
        "remote_source": _source_to_dict(entry.metadata.remote_source),
        "result": result_dict,
    }


@router.delete("/{id_or_slug}/source", response_model=RemoteSourceDetachResponse)
def detach_source(id_or_slug: str, db: Session = Depends(get_db)) -> dict:
    """Remove the remote source link from an entry (content is preserved)."""
    repo, entry = _resolve_entry(db, id_or_slug)
    entry.metadata.remote_source = None
    repo.update(entry)
    return {"detached": True, "entry_id": entry.id}
