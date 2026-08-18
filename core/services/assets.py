from __future__ import annotations

from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.schemas.entry import NodeAsset
from core.services.entries import replace_entry, resolve_required
from core.services.errors import NotFoundError


def add_or_replace_asset(
    db: Session,
    graph: KnowDoGraph,
    identifier: str,
    asset: NodeAsset,
) -> tuple[str, NodeAsset]:
    entry = resolve_required(db, graph, identifier)
    entry.assets = [
        item
        for item in entry.assets
        if not (item.folder == asset.folder and item.filename == asset.filename)
    ]
    entry.assets.append(asset)
    saved = replace_entry(db, graph, entry)
    return saved.id, asset


def delete_asset(
    db: Session, graph: KnowDoGraph, identifier: str, folder: str, filename: str
) -> None:
    entry = resolve_required(db, graph, identifier)
    folder_n = folder.lower()
    before = len(entry.assets)
    entry.assets = [
        asset
        for asset in entry.assets
        if not (asset.folder == folder_n and asset.filename == filename)
    ]
    if len(entry.assets) == before:
        raise NotFoundError(f"Asset not found: {folder}/{filename}")
    replace_entry(db, graph, entry)
