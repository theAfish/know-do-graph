"""Add the agent-skills.cc skill registry node to the graph.

Usage
-----
    python scripts/add_agent_skills_cc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import app_state
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus
from core.storage.database import SessionLocal, init_db
from core.storage.repository import EntryRepository

ENTRY = {
    "title": "Agent Skills CC",
    "entry_type": EntryType.tool,
    "tags": [
        "agent",
        "skill-registry",
        "public",
        "claude-code",
        "codex",
        "cursor",
        "open-standard",
        "skill-md",
    ],
    "content": """\
# Agent Skills CC

A public web catalog of 63,000+ free AI agent skills, browseable by category
and searchable by keyword.  Skills are sourced from GitHub repositories that
follow the open **SKILL.md** format.

- Homepage: https://agent-skills.cc/
- All skills: https://agent-skills.cc/skills
- Claude Code skills: https://agent-skills.cc/claude-skills

## Compatible Platforms

Skills on this site are tagged and filtered for:
- **Claude Code** (Anthropic) — `claude-skills` section
- **OpenAI Codex CLI** — `codex-skills` section
- **Cursor** — `cursor-skills` section
- ChatGPT, Gemini CLI, Antigravity, and others

## Browsing by Category

Category URL pattern: `https://agent-skills.cc/claude-skills/<category>`

| Category | URL slug |
|----------|----------|
| Tools | `tools` |
| Development | `development` |
| Data & AI | `data-ai` |
| Business | `business` |
| DevOps | `devops` |
| Testing & Security | `testing-security` |
| Documentation | `documentation` |
| Content & Media | `content-media` |
| Research | `research` |
| Databases | `databases` |
| Lifestyle | `lifestyle` |
| Blockchain | `blockchain` |

## Curated Listings

- **Hot / Trending** — https://agent-skills.cc/claude-skills/hot
- **Newest** — https://agent-skills.cc/claude-skills/new
- **Top Rated** — https://agent-skills.cc/claude-skills/top
- **Official Anthropic skills** — https://agent-skills.cc/anthropic-skills

## Individual Skill URLs

Each skill maps to a GitHub repo.  URL pattern:

```
https://agent-skills.cc/skills/<owner>-<repo>
```

Examples:
- `https://agent-skills.cc/skills/anthropics-skills` — official Anthropic skill repo
- `https://agent-skills.cc/skills/openclaw-openclaw` — OpenClaw agent (157k stars)
- `https://agent-skills.cc/skills/obra-superpowers` — Superpowers agent framework

## Skill Format (SKILL.md)

Each GitHub skill repo is expected to contain a `SKILL.md` file — a
machine-readable markdown document that describes the skill's purpose,
invocation instructions, and dependencies.  An agent can fetch or clone
the repo and read `SKILL.md` to load the skill directly.

## How an Agent Should Use This Node

1. **Discover** — search this registry by category or keyword to find relevant
   skills you don't yet have locally.
2. **Fetch** — open the skill's detail page, follow the GitHub link, and read
   `SKILL.md` (or the repo README) to understand invocation and install steps.
3. **Install** — copy the `SKILL.md` content into your agent's skill directory,
   or install via the associated CLI (OpenClaw, SkillHub CLI, etc.).
4. **Reference** — link the newly imported skill as a node in [[SkillHub]] or
   this graph so future agents can find it locally.

## Related Nodes

- [[SkillHub]] — self-hosted private skill registry (enterprise, RBAC, versioning)
""",
    "metadata": EntryMetadata(
        source_provenance="https://agent-skills.cc/",
        refinement_status=RefinementStatus.linked,
    ),
}


def main() -> None:
    init_db()

    entry = Entry(
        title=ENTRY["title"],
        entry_type=ENTRY["entry_type"],
        tags=ENTRY["tags"],
        content=ENTRY["content"],
        metadata=ENTRY["metadata"],
    )

    with SessionLocal() as db:
        saved = EntryRepository(db).create(entry)

    app_state.graph.add_entry(saved)
    print(f"Created: {saved.title}  ({saved.id})")
    print(f"  slug : {saved.slug}")
    print(f"  type : {saved.entry_type.value}")
    print(f"  tags : {', '.join(saved.tags)}")


if __name__ == "__main__":
    main()
