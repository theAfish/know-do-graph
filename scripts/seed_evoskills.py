"""Seed the graph with linked-source nodes mirroring EvoSkills.

Each created node has an empty initial body and a ``remote_source`` pointing at
the upstream SKILL.md in https://github.com/EvoScientist/EvoSkills (branch: main).
The body is then fetched once via ``core.sync.remote_sync.sync_entry``.

After this script runs:
    * Each node's content reflects the current upstream SKILL.md.
    * The periodic loop (KDG_REMOTE_SYNC_ENABLED=1) will keep them fresh.
    * Wikilinks in the body are auto-extracted on every refresh.
    * Inbound wikilinks (e.g. [[evo-memory]]) remain stable forever.

Usage
-----
    python scripts/seed_evoskills.py
    python scripts/seed_evoskills.py --no-fetch     # create nodes, sync later

Then trigger a manual sync via:
    curl -X POST http://localhost:8008/remote-sync/all?force=true
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import app_state
from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import (
    Entry,
    EntryMetadata,
    EntryType,
    RefinementStatus,
    RemoteSource,
    VerificationStatus,
)
from core.storage.database import SessionLocal, init_db
from core.storage.repository import EdgeRepository, EntryRepository
from core.sync.remote_sync import sync_entry

REPO_OWNER = "EvoScientist"
REPO_NAME = "EvoSkills"
REPO_REF = "main"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"

# (slug, title, tags, path-in-repo, entry_type)
SKILLS: list[tuple[str, str, list[str], str, EntryType]] = [
    (
        "evoskill-research-ideation",
        "EvoSkills Research Ideation",
        ["evoskills", "research", "ideation", "literature", "proposal", "ai-science"],
        "skills/research-ideation/SKILL.md",
        EntryType.workflow,
    ),
    (
        "evoskill-paper-planning",
        "EvoSkills Paper Planning",
        ["evoskills", "paper", "planning", "outline", "writing", "ai-science"],
        "skills/paper-planning/SKILL.md",
        EntryType.procedure,
    ),
    (
        "evoskill-experiment-pipeline",
        "EvoSkills Experiment Pipeline",
        ["evoskills", "experiment", "pipeline", "stages", "ai-science"],
        "skills/experiment-pipeline/SKILL.md",
        EntryType.workflow,
    ),
    (
        "evoskill-experiment-craft",
        "EvoSkills Experiment Craft",
        ["evoskills", "experiment", "debugging", "iteration", "ai-science"],
        "skills/experiment-craft/SKILL.md",
        EntryType.procedure,
    ),
    (
        "evoskill-experiment-iterative-coder",
        "EvoSkills Experiment Iterative Coder",
        ["evoskills", "code", "iteration", "refinement", "ai-science"],
        "skills/experiment-iterative-coder/SKILL.md",
        EntryType.workflow,
    ),
    (
        "evoskill-paper-writing",
        "EvoSkills Paper Writing",
        ["evoskills", "paper", "writing", "latex", "ai-science"],
        "skills/paper-writing/SKILL.md",
        EntryType.procedure,
    ),
    (
        "evoskill-paper-review",
        "EvoSkills Paper Review",
        ["evoskills", "paper", "review", "feedback", "ai-science"],
        "skills/paper-review/SKILL.md",
        EntryType.procedure,
    ),
    (
        "evoskill-paper-rebuttal",
        "EvoSkills Paper Rebuttal",
        ["evoskills", "paper", "rebuttal", "peer-review", "ai-science"],
        "skills/paper-rebuttal/SKILL.md",
        EntryType.procedure,
    ),
    (
        "evoskill-academic-slides",
        "EvoSkills Academic Slides",
        ["evoskills", "slides", "presentation", "talk", "ai-science"],
        "skills/academic-slides/SKILL.md",
        EntryType.procedure,
    ),
    (
        "evoskill-evo-memory",
        "EvoSkills Evo Memory",
        ["evoskills", "memory", "self-evolution", "persistent", "ai-science"],
        "skills/evo-memory/SKILL.md",
        EntryType.capability,
    ),
    (
        "evoskill-paper-navigator",
        "EvoSkills Paper Navigator",
        ["evoskills", "paper", "discovery", "semantic-scholar", "arxiv", "ai-science"],
        "skills/paper-navigator/SKILL.md",
        EntryType.workflow,
    ),
    (
        "evoskill-research-survey",
        "EvoSkills Research Survey",
        ["evoskills", "survey", "literature", "synthesis", "ai-science"],
        "skills/research-survey/SKILL.md",
        EntryType.workflow,
    ),
    (
        "evoskill-nano-banana",
        "EvoSkills Nano Banana",
        ["evoskills", "slides", "gemini", "image-generation", "presentation"],
        "skills/nano-banana/SKILL.md",
        EntryType.tool,
    ),
    (
        "evoskill-evomath-tao",
        "EvoSkills EvoMath Tao",
        ["evoskills", "math", "proof", "olympiad", "tao", "formal-verification"],
        "skills/evomath-tao/SKILL.md",
        EntryType.procedure,
    ),
]


def _hub_node() -> Entry:
    """A root node that all EvoSkill nodes link to via 'part_of'."""
    return Entry(
        title="EvoSkills",
        slug="evoskills",
        entry_type=EntryType.repository,
        tags=["evoskills", "evoscientist", "ai-science", "agent-framework", "skills"],
        aliases=["EvoScientist/EvoSkills"],
        content=(
            "# EvoSkills\n\n"
            "Hub node for skills imported (live-linked) from the EvoSkills repository.\n\n"
            f"Source: {REPO_URL}  (branch `{REPO_REF}`)\n\n"
            "EvoSkills is the official skill repository for EvoScientist — an end-to-end\n"
            "multi-agent AI scientist framework. Each child node mirrors a\n"
            "`skills/*/SKILL.md` and is kept in sync by the `remote_sync` subsystem.\n\n"
            "## Available Skills\n"
            "- [[evoskill-research-ideation]]\n"
            "- [[evoskill-paper-planning]]\n"
            "- [[evoskill-experiment-pipeline]]\n"
            "- [[evoskill-experiment-craft]]\n"
            "- [[evoskill-experiment-iterative-coder]]\n"
            "- [[evoskill-paper-writing]]\n"
            "- [[evoskill-paper-review]]\n"
            "- [[evoskill-paper-rebuttal]]\n"
            "- [[evoskill-academic-slides]]\n"
            "- [[evoskill-evo-memory]]\n"
            "- [[evoskill-paper-navigator]]\n"
            "- [[evoskill-research-survey]]\n"
            "- [[evoskill-nano-banana]]\n"
            "- [[evoskill-evomath-tao]]\n"
        ),
        metadata=EntryMetadata(
            source_provenance=REPO_URL,
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[REPO_URL],
            remote_source=RemoteSource(
                kind="github",
                url=f"{REPO_URL}/blob/{REPO_REF}/README.md",
                owner=REPO_OWNER,
                repo=REPO_NAME,
                ref=REPO_REF,
                path="README.md",
                auto_sync=True,
                sync_interval_seconds=3600,
            ),
        ),
    )


def _skill_node(slug: str, title: str, tags: list[str], path: str, entry_type: EntryType) -> Entry:
    src = RemoteSource(
        kind="github",
        url=f"{REPO_URL}/blob/{REPO_REF}/{path}",
        owner=REPO_OWNER,
        repo=REPO_NAME,
        ref=REPO_REF,
        path=path,
        auto_sync=True,
        sync_interval_seconds=3600,
    )
    return Entry(
        title=title,
        slug=slug,
        entry_type=entry_type,
        tags=tags,
        content=f"_Live-mirrored from {src.url}. Body is fetched on first sync._\n",
        metadata=EntryMetadata(
            source_provenance=src.url,
            extraction_method="remote-sync",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[src.url, REPO_URL],
            remote_source=src,
        ),
    )


async def main(do_fetch: bool = True) -> None:
    init_db()

    with SessionLocal() as db:
        erepo = EntryRepository(db)
        edrepo = EdgeRepository(db)

        # Build a slug → existing entry index for idempotency.
        existing = {e.slug: e for e in erepo.get_all()}

        hub = existing.get("evoskills")
        if hub is None:
            hub = erepo.create(_hub_node())
            print(f"+ created hub node {hub.slug}")
        else:
            print(f"= hub node already exists: {hub.slug}")

        created: list[Entry] = []
        for slug, title, tags, path, entry_type in SKILLS:
            if slug in existing:
                print(f"= already exists: {slug}")
                node = existing[slug]
            else:
                node = erepo.create(_skill_node(slug, title, tags, path, entry_type))
                print(f"+ created {slug}")
            created.append(node)

            # Link hub → skill  ("the repository uses this skill").
            edrepo.create(
                Edge(
                    source_id=hub.id,
                    target_id=node.id,
                    relation=EdgeRelation.uses,
                    weight=1.0,
                )
            )

        if do_fetch:
            print("\nFetching upstream bodies (this calls the GitHub API)…")
            for node in [hub, *created]:
                fresh = next((e for e in erepo.get_all() if e.id == node.id), None)
                if fresh is None or fresh.metadata.remote_source is None:
                    continue
                result = await sync_entry(fresh, force=True)
                erepo.update(fresh)
                print(f"  · {fresh.slug:<42} {result.status:<10} {result.detail}")

            # ── Autolink pass ──────────────────────────────────────────────
            from core.sync.autolink import auto_link_entry
            print("\nAuto-linking derived edges…")
            all_entries = erepo.get_all()
            for node in [hub, *created]:
                fresh = next((e for e in all_entries if e.id == node.id), None)
                if fresh is None:
                    continue
                al = auto_link_entry(fresh, all_entries, edrepo)
                if al.total:
                    print(f"  · {fresh.slug:<42} +{al.frontmatter_edges} frontmatter, +{al.mention_edges} mention")

    # Rebuild in-memory graph so a running server picks up changes after restart.
    with SessionLocal() as db:
        entries = EntryRepository(db).get_all()
        edges = EdgeRepository(db).get_all()
    app_state.graph.rebuild_from_db(entries, edges)
    print(f"\nDone. Graph now has {len(entries)} entries, {len(edges)} edges.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="Create nodes but skip the initial pull.")
    args = ap.parse_args()
    asyncio.run(main(do_fetch=not args.no_fetch))
