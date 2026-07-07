"""Remote-source sync — pull upstream SKILL.md / script files into entry content.

Design
------
* **Zero LLM cost.** Uses GitHub's REST contents API with the blob ``sha`` as a
  cheap change-detector. We additionally hash the decoded body so we can also
  diff against arbitrary HTTP sources.
* **Identity-preserving.** Only ``Entry.content`` (and the ``remote_source``
  metadata block) is touched on a successful pull. The entry's id, slug, title,
  tags, and inbound wikilinks are never modified by sync — so ``[[my-skill]]``
  references remain stable even if the upstream file is renamed.
* **Re-extraction of wikilinks** happens automatically because
  ``Entry.model_post_init`` re-runs the wikilink regex over ``content``.
* **Re-embedding** happens automatically inside ``EntryRepository.update``
  (it stamps ``embedding_hash`` only when the text changes).

The optional periodic loop is started by ``api/main.py`` during lifespan and
controlled by env vars:

    KDG_REMOTE_SYNC_ENABLED          "1" to enable the loop (default off)
    KDG_REMOTE_SYNC_INTERVAL_SECONDS  poll cadence  (default 900 = 15min)
    GITHUB_TOKEN                     optional, raises rate limit 60 → 5000/h
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from core import events as _events
from core.schemas.entry import Entry, RemoteSource

logger = logging.getLogger(__name__)


# ── URL parsing ───────────────────────────────────────────────────────────────

_GH_BLOB_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<ref>[^/]+)/(?P<path>.+?)$"
)
_GH_TREE_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)(/(tree/(?P<ref>[^/]+)(/(?P<path>.*))?)?)?$"
)
_GH_RAW_RE = re.compile(
    r"^https?://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<ref>[^/]+)/(?P<path>.+?)$"
)


def parse_github_url(url: str) -> Optional[dict]:
    """Best-effort parse of a GitHub URL into owner/repo/ref/path."""
    for rx in (_GH_BLOB_RE, _GH_RAW_RE):
        m = rx.match(url.strip())
        if m:
            return {k: m.group(k) for k in ("owner", "repo", "ref", "path")}
    m = _GH_TREE_RE.match(url.strip())
    if m:
        return {
            "owner": m.group("owner"),
            "repo": m.group("repo"),
            "ref": m.group("ref") or "HEAD",
            "path": m.group("path") or "",
        }
    return None


# ── Sync result ───────────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    entry_id: str
    title: str
    status: str  # "updated" | "unchanged" | "error" | "skipped"
    detail: str = ""
    bytes_fetched: int = 0
    new_hash: Optional[str] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Low-level fetchers ────────────────────────────────────────────────────────


def _gh_headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "know-do-graph-remote-sync",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


async def _fetch_github_file(
    owner: str, repo: str, path: str, ref: str, prev_sha: Optional[str]
) -> tuple[str, Optional[bytes], Optional[str], str]:
    """Returns (status, body_bytes, blob_sha, detail).

    status: "updated" | "unchanged" | "missing" | "error"
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": ref}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params=params, headers=_gh_headers())
    except httpx.HTTPError as exc:
        return "error", None, None, f"network: {exc}"

    if r.status_code == 404:
        return "missing", None, None, "404 not found"
    if r.status_code >= 400:
        return "error", None, None, f"http {r.status_code}: {r.text[:200]}"

    payload = r.json()
    if isinstance(payload, list):
        return "error", None, None, "path is a directory, not a file"

    sha = payload.get("sha")
    if prev_sha and sha == prev_sha:
        return "unchanged", None, sha, "blob sha matches"

    enc = payload.get("encoding")
    if enc == "base64" and payload.get("content"):
        try:
            body = base64.b64decode(payload["content"])
        except Exception as exc:
            return "error", None, sha, f"base64 decode: {exc}"
    elif payload.get("download_url"):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r2 = await client.get(payload["download_url"], headers=_gh_headers())
            r2.raise_for_status()
            body = r2.content
        except httpx.HTTPError as exc:
            return "error", None, sha, f"raw fetch: {exc}"
    else:
        return "error", None, sha, "no content / download_url in response"

    return "updated", body, sha, "ok"


async def _fetch_http(
    url: str, prev_etag: Optional[str]
) -> tuple[str, Optional[bytes], Optional[str], str]:
    headers = {"User-Agent": "know-do-graph-remote-sync"}
    if prev_etag:
        headers["If-None-Match"] = prev_etag
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return "error", None, None, f"network: {exc}"
    if r.status_code == 304:
        return "unchanged", None, prev_etag, "304 not modified"
    if r.status_code >= 400:
        return "error", None, None, f"http {r.status_code}"
    return "updated", r.content, r.headers.get("etag"), "ok"


# ── Public sync API ───────────────────────────────────────────────────────────


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


async def sync_entry(entry: Entry, *, force: bool = False) -> SyncResult:
    """Fetch the upstream file for *entry* and return a SyncResult.

    Does NOT persist — the caller is expected to write the (possibly mutated)
    entry back via ``EntryRepository.update``.
    """
    src = entry.metadata.remote_source
    if src is None:
        return SyncResult(entry.id, entry.title, "skipped", "no remote_source")

    prev_etag = None if force else src.etag
    if src.kind == "github":
        owner = src.owner
        repo = src.repo
        path = src.path
        if not (owner and repo and path):
            parsed = parse_github_url(src.url) or {}
            owner = owner or parsed.get("owner")
            repo = repo or parsed.get("repo")
            path = path or parsed.get("path")
            if not (owner and repo and path):
                src.status = "error"
                src.last_error = "cannot resolve owner/repo/path"
                return SyncResult(entry.id, entry.title, "error", src.last_error)
        status, body, sha, detail = await _fetch_github_file(
            owner, repo, path, src.ref or "main", prev_etag
        )
    else:
        status, body, sha, detail = await _fetch_http(src.url, prev_etag)

    now = datetime.now(timezone.utc)

    if status == "unchanged":
        src.fetched_at = now
        src.status = "ok"
        src.last_error = None
        return SyncResult(entry.id, entry.title, "unchanged", detail)

    if status in ("missing", "error"):
        src.status = "stale" if status == "missing" else "error"
        src.last_error = detail
        src.fetched_at = now
        return SyncResult(entry.id, entry.title, "error", detail)

    # status == "updated"
    assert body is not None
    new_hash = _sha256(body)
    if not force and src.content_hash == new_hash:
        src.etag = sha or src.etag
        src.fetched_at = now
        src.status = "ok"
        src.last_error = None
        return SyncResult(entry.id, entry.title, "unchanged", "body hash matches")

    text = body.decode("utf-8", errors="replace")
    entry.content = text
    entry.refresh_refs()  # re-extract wikilinks from new content
    src.content_hash = new_hash
    src.etag = sha or src.etag
    src.fetched_at = now
    src.status = "ok"
    src.last_error = None

    return SyncResult(
        entry.id,
        entry.title,
        "updated",
        detail,
        bytes_fetched=len(body),
        new_hash=new_hash,
        fetched_at=now,
    )


def _is_due(src: RemoteSource, now: datetime) -> bool:
    if not src.auto_sync:
        return False
    if src.fetched_at is None:
        return True
    return (now - src.fetched_at).total_seconds() >= max(60, src.sync_interval_seconds)


async def sync_all_due(*, force: bool = False, autolink: bool = True) -> list[SyncResult]:
    """Sync every entry whose ``remote_source`` is due (or all, if ``force``).

    When ``autolink`` is True, runs :func:`core.sync.autolink.auto_link_entry`
    after each successful update so derived edges (frontmatter + mentions)
    refresh alongside the body.
    """
    # Imported inside to avoid circular imports at module load time.
    from core.app_state import graph as _graph
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository, EntryRepository
    from core.sync.autolink import auto_link_entry

    results: list[SyncResult] = []
    with SessionLocal() as db:
        repo = EntryRepository(db)
        edge_repo = EdgeRepository(db)
        entries = repo.get_all()
        now = datetime.now(timezone.utc)
        for entry in entries:
            src = entry.metadata.remote_source
            if src is None:
                continue
            if not force and not _is_due(src, now):
                continue
            try:
                result = await sync_entry(entry, force=force)
            except Exception as exc:  # pragma: no cover — never crash the loop
                logger.exception("sync_entry crashed for %s", entry.id)
                result = SyncResult(entry.id, entry.title, "error", f"crash: {exc}")
                src.status = "error"
                src.last_error = str(exc)
            results.append(result)

            # Persist regardless (we may have updated fetched_at/status only).
            updated = repo.update(entry)
            if result.status == "updated" and updated is not None:
                # Refresh in-memory graph node so the UI / search sees new content.
                try:
                    _graph.add_entry(updated)  # idempotent — overwrites node attrs
                except Exception:
                    pass
                if autolink:
                    try:
                        al = auto_link_entry(updated, entries, edge_repo)
                        if al.total:
                            logger.info(
                                "autolink %s: +%d frontmatter, +%d mention edges",
                                updated.slug,
                                al.frontmatter_edges,
                                al.mention_edges,
                            )
                    except Exception:  # pragma: no cover
                        logger.exception("autolink failed for %s", updated.slug)
                _events.emit(
                    "node_updated",
                    {
                        "id": entry.id,
                        "slug": entry.slug,
                        "title": entry.title,
                        "source": "remote_sync",
                    },
                )
    return results


async def run_periodic_sync(interval_seconds: int) -> None:
    """Background task: every *interval_seconds*, sync all due remote sources."""
    interval = max(60, int(interval_seconds))
    logger.info("remote_sync loop started (interval=%ss)", interval)
    while True:
        try:
            results = await sync_all_due(force=False)
            updated = [r for r in results if r.status == "updated"]
            errors = [r for r in results if r.status == "error"]
            if results:
                logger.info(
                    "remote_sync tick: %d checked, %d updated, %d errors",
                    len(results),
                    len(updated),
                    len(errors),
                )
        except asyncio.CancelledError:
            logger.info("remote_sync loop cancelled")
            raise
        except Exception:
            logger.exception("remote_sync tick failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
