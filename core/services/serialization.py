from __future__ import annotations

from core.schemas.entry import KNOWN_ASSET_FOLDERS, Entry, NodeAsset, entry_type_value


def entry_to_dict(entry: Entry) -> dict:
    return entry.model_dump(mode="json")


def entries_to_dict(entries: list[Entry]) -> list[dict]:
    return [entry_to_dict(entry) for entry in entries]


def entry_summary(entry: Entry, *, snippet_words: int = 40) -> dict:
    words = (entry.content or "").split()
    snippet = " ".join(words[:snippet_words])
    if len(words) > snippet_words:
        snippet += "..."
    return {
        "id": entry.id,
        "slug": entry.slug,
        "title": entry.title,
        "entry_type": entry_type_value(entry.entry_type),
        "tags": entry.tags,
        "aliases": entry.aliases,
        "snippet": snippet,
    }


def asset_meta(entry_id: str, asset: NodeAsset) -> dict:
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


def assets_by_folder(entry: Entry) -> dict:
    grouped: dict[str, list[dict]] = {}
    for asset in entry.assets:
        grouped.setdefault(asset.folder, []).append(asset_meta(entry.id, asset))

    ordered = {}
    for folder in KNOWN_ASSET_FOLDERS:
        if folder in grouped:
            ordered[folder] = grouped.pop(folder)
    for folder in sorted(grouped):
        ordered[folder] = grouped[folder]
    return ordered


def clean_entry(entry: Entry) -> dict:
    data = entry_to_dict(entry)
    return _strip_empty(data)


def _strip_empty(value):
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := _strip_empty(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            cleaned for item in value if (cleaned := _strip_empty(item)) not in (None, "", [], {})
        ]
    return value
