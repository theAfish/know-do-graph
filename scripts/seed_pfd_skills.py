"""Seed the graph with linked-source nodes mirroring PFD_Agent skills.

Each created node has an empty initial body and a ``remote_source`` pointing at
the upstream SKILL.md in https://github.com/nlz25/PFD_Agent (branch: devel).
The body is then fetched once via ``core.sync.remote_sync.sync_entry``.

After this script runs:
    * Each node's content reflects the current upstream SKILL.md.
    * The periodic loop (KDG_REMOTE_SYNC_ENABLED=1) will keep them fresh.
    * Wikilinks in the body are auto-extracted on every refresh.
    * Inbound wikilinks (e.g. [[pfd-vasp]]) remain stable forever.

Usage
-----
    python scripts/seed_pfd_skills.py
    python scripts/seed_pfd_skills.py --no-fetch     # create nodes, sync later

Then trigger a manual sync via:
    curl -X POST http://localhost:8000/remote-sync/all?force=true
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

REPO_OWNER = "nlz25"
REPO_NAME = "PFD_Agent"
REPO_REF = "devel"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"

# (slug, title, tags, path-in-repo, entry_type)
SKILLS: list[tuple[str, str, list[str], str, EntryType]] = [
    ("pfd-abacus", "PFD ABACUS Skill",
     ["pfd-agent", "abacus", "dft", "simulation"],
     "agents/MatCreator/skills/abacus/SKILL.md", EntryType.tool),
    ("pfd-ase-deepmd", "PFD ASE + DeePMD Skill",
     ["pfd-agent", "ase", "deepmd", "md", "machine-learning-potential"],
     "agents/MatCreator/skills/ase-deepmd/SKILL.md", EntryType.tool),
    ("pfd-atomic-structure", "PFD Atomic Structure Skill",
     ["pfd-agent", "atomic-structure", "crystallography"],
     "agents/MatCreator/skills/atomic-structure/SKILL.md", EntryType.procedure),
    ("pfd-cgcnn-predictor", "PFD CGCNN Predictor Skill",
     ["pfd-agent", "cgcnn", "ml", "materials"],
     "agents/MatCreator/skills/cgcnn-predictor/SKILL.md", EntryType.tool),
    ("pfd-database", "PFD Materials Database Skill",
     ["pfd-agent", "database", "materials"],
     "agents/MatCreator/skills/database/SKILL.md", EntryType.tool),
    ("pfd-deepmd", "PFD DeePMD Skill",
     ["pfd-agent", "deepmd", "machine-learning-potential", "training"],
     "agents/MatCreator/skills/deepmd/SKILL.md", EntryType.tool),
    ("pfd-dpdisp", "PFD dpdispatcher Skill",
     ["pfd-agent", "dpdispatcher", "job-submission", "hpc"],
     "agents/MatCreator/skills/dpdisp/SKILL.md", EntryType.workflow),
    ("pfd-mattergen-evaluation", "PFD MatterGen Evaluation Skill",
     ["pfd-agent", "mattergen", "evaluation", "generative"],
     "agents/MatCreator/skills/mattergen/mattergen-evaluation/SKILL.md", EntryType.tool),
    ("pfd-mattergen-finetune", "PFD MatterGen Fine-tuning Skill",
     ["pfd-agent", "mattergen", "finetune", "generative"],
     "agents/MatCreator/skills/mattergen/mattergen-finetune/SKILL.md", EntryType.workflow),
    ("pfd-mattergen-generation", "PFD MatterGen Generation Skill",
     ["pfd-agent", "mattergen", "generation", "generative"],
     "agents/MatCreator/skills/mattergen/mattergen-generation/SKILL.md", EntryType.workflow),
    ("pfd-mattersim", "PFD MatterSim Skill",
     ["pfd-agent", "mattersim", "md", "foundation-model"],
     "agents/MatCreator/skills/mattersim/SKILL.md", EntryType.tool),
    ("pfd-plot", "PFD Plotting Skill",
     ["pfd-agent", "plot", "visualization"],
     "agents/MatCreator/skills/plot/SKILL.md", EntryType.tool),
    ("pfd-quests", "PFD QUESTS Skill",
     ["pfd-agent", "quests", "active-learning"],
     "agents/MatCreator/skills/quests/SKILL.md", EntryType.workflow),
    ("pfd-structure-conversion", "PFD Structure Conversion Skill",
     ["pfd-agent", "structure", "conversion", "pymatgen", "ase"],
     "agents/MatCreator/skills/structure-conversion/SKILL.md", EntryType.tool),
    ("pfd-tavily-cli", "PFD Tavily CLI Skill",
     ["pfd-agent", "tavily", "search", "web"],
     "agents/MatCreator/skills/tavily/tavily-cli/SKILL.md", EntryType.tool),
    ("pfd-tavily-search", "PFD Tavily Search Skill",
     ["pfd-agent", "tavily", "search", "web"],
     "agents/MatCreator/skills/tavily/tavily-search/SKILL.md", EntryType.tool),
    ("pfd-vasp", "PFD VASP Skill",
     ["pfd-agent", "vasp", "dft", "simulation"],
     "agents/MatCreator/skills/vasp/SKILL.md", EntryType.tool),
]


def _hub_node() -> Entry:
    """A root node that all PFD skill nodes link to via 'part_of'."""
    return Entry(
        title="PFD Agent (MatCreator)",
        slug="pfd-agent",
        entry_type=EntryType.repository,
        tags=["pfd-agent", "matcreator", "materials", "agent-framework"],
        aliases=["PFD_Agent", "MatCreator"],
        content=(
            "# PFD_Agent\n\n"
            "Hub node for skills imported (live-linked) from the PFD_Agent repository.\n\n"
            f"Source: {REPO_URL}  (branch `{REPO_REF}`)\n\n"
            "Each child node mirrors a SKILL.md from `agents/MatCreator/skills/*` and is\n"
            "kept in sync by the `remote_sync` subsystem — no LLM calls are involved in\n"
            "the freshness loop.\n"
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

        hub = existing.get("pfd-agent")
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

            # Link hub → skill  (“the agent uses this skill”).
            # EdgeRepository.create handles dedup itself.
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
                # Reload to ensure metadata.remote_source is hydrated from the DB.
                fresh = next((e for e in erepo.get_all() if e.id == node.id), None)
                if fresh is None or fresh.metadata.remote_source is None:
                    continue
                result = await sync_entry(fresh, force=True)
                erepo.update(fresh)
                print(f"  · {fresh.slug:<32} {result.status:<10} {result.detail}")

            # ── Autolink pass ──────────────────────────────────────────────
            # Derive edges from the freshly-fetched bodies: SKILL.md YAML
            # frontmatter (dependent_skills, …) and generic mention scan.
            from core.sync.autolink import auto_link_entry
            print("\nAuto-linking derived edges…")
            all_entries = erepo.get_all()
            for node in [hub, *created]:
                fresh = next((e for e in all_entries if e.id == node.id), None)
                if fresh is None:
                    continue
                al = auto_link_entry(fresh, all_entries, edrepo)
                if al.total:
                    print(f"  · {fresh.slug:<32} +{al.frontmatter_edges} frontmatter, +{al.mention_edges} mention")

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
