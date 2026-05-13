from __future__ import annotations

import re

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")
_MDLINK_RE = re.compile(r"\[(?:[^\]]+)\]\((https?://[^\)]+)\)")


def parse_wikilinks(content: str) -> list[str]:
    """Return all [[wikilink]] targets found in *content*."""
    return _WIKILINK_RE.findall(content)


def extract_external_refs(content: str) -> list[str]:
    """Return all markdown [text](url) hrefs found in *content*."""
    return _MDLINK_RE.findall(content)


def slug_from_title(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
