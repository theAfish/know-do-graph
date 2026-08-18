from __future__ import annotations

import re

from core.utils.slug import slug_from_title

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")
_MDLINK_RE = re.compile(r"\[(?:[^\]]+)\]\((https?://[^\)]+)\)")


def parse_wikilinks(content: str) -> list[str]:
    """Return all [[wikilink]] targets found in *content*."""
    return _WIKILINK_RE.findall(content)


def extract_external_refs(content: str) -> list[str]:
    """Return all markdown [text](url) hrefs found in *content*."""
    return _MDLINK_RE.findall(content)


_CHAR_SUBS: dict[str, str] = {
    "Å": "angstrom",
    "å": "angstrom",
    "µ": "micro",
    "μ": "micro",
    "°": "deg",
    "±": "plus-minus",
    "×": "x",
    "·": "-",
}


def _legacy_slug_from_title(title: str) -> str:
    import unicodedata

    for sym, replacement in _CHAR_SUBS.items():
        title = title.replace(sym, f" {replacement} ")
    parts: list[str] = []
    for ch in unicodedata.normalize("NFKD", title):
        if ch.isascii():
            parts.append(ch)
        elif unicodedata.combining(ch):
            pass
        else:
            name = unicodedata.name(ch, "").lower()
            parts.append(name.split()[-1] if name else "")
    slug = "".join(parts).lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


__all__ = ["extract_external_refs", "parse_wikilinks", "slug_from_title"]
