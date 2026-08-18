from __future__ import annotations

import re
import unicodedata

# Scientific symbols that should become descriptive words, not misleading
# Unicode decompositions. These strings are UTF-8 source text; keep this file
# encoded as UTF-8.
_CHAR_SUBS: dict[str, str] = {
    "µ": "micro",
    "μ": "micro",
    "°": "deg",
    "±": "plus-minus",
    "×": "x",
    "·": "-",
}


def slug_from_title(title: str) -> str:
    """Return the canonical slug for a title."""
    title = re.sub(r"(?<![A-Za-z])Å(?![A-Za-z])", " angstrom ", title)
    title = re.sub(r"(?<![A-Za-z])å(?![A-Za-z])", " angstrom ", title)
    for sym, replacement in _CHAR_SUBS.items():
        title = title.replace(sym, f" {replacement} ")

    parts: list[str] = []
    for ch in unicodedata.normalize("NFKD", title):
        if ch.isascii():
            parts.append(ch)
        elif unicodedata.combining(ch):
            continue
        else:
            name = unicodedata.name(ch, "").lower()
            parts.append(name.split()[-1] if name else "")

    slug = "".join(parts).lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
