"""Seed the graph with example capability entries.

Demonstrates wiki-native cross-linking via [[wikilinks]].

Usage
-----
    python examples/example_entries.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import app_state
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus
from core.storage.database import SessionLocal, init_db
from core.storage.repository import EntryRepository

EXAMPLE_ENTRIES: list[dict] = [
    {
        "title": "MACE Calculator",
        "entry_type": EntryType.tool,
        "tags": ["atomistic", "machine-learning", "calculator"],
        "content": """\
# MACE Calculator

A machine-learning interatomic potential calculator based on the MACE architecture.

## Dependencies
- [[ASE]]
- [[PyTorch]]

## Usage

```python
from mace.calculators import MACECalculator
calc = MACECalculator(model_paths=['model.pt'], device='cpu')
atoms.calc = calc
```

## Related workflows
- [[ASE Relaxation]]
- [[Phonon Workflow]]

## External References
- https://github.com/ACEsuit/mace
""",
        "metadata": EntryMetadata(
            source_provenance="https://github.com/ACEsuit/mace",
            refinement_status=RefinementStatus.linked,
        ),
    },
    {
        "title": "ASE Relaxation",
        "entry_type": EntryType.workflow,
        "tags": ["atomistic", "relaxation", "ase"],
        "content": """\
# ASE Relaxation

Geometry optimisation workflow using ASE (Atomic Simulation Environment).

## Prerequisites
- [[ASE]]
- A compatible [[MACE Calculator]] or other calculator

## Workflow

1. Load structure
2. Attach calculator
3. Run BFGS or FIRE optimiser
4. Save relaxed structure

```python
from ase.optimize import BFGS
opt = BFGS(atoms, trajectory='relax.traj')
opt.run(fmax=0.05)
```

## Related
- [[Phonon Workflow]]
""",
        "metadata": EntryMetadata(
            source_provenance="https://wiki.fysik.dtu.dk/ase/",
            refinement_status=RefinementStatus.linked,
        ),
    },
    {
        "title": "Phonon Workflow",
        "entry_type": EntryType.workflow,
        "tags": ["atomistic", "phonon", "lattice-dynamics"],
        "content": """\
# Phonon Workflow

Compute phonon dispersion and density of states using finite displacement or DFPT.

## Prerequisites
- [[ASE Relaxation]] (fully relaxed structure required)
- [[MACE Calculator]] or DFT calculator
- phonopy or [[ASE]] phonon module

## Steps
1. Relax the structure (see [[ASE Relaxation]])
2. Generate displaced supercells
3. Compute forces
4. Build force constant matrix
5. Compute phonon bands and DOS

## Caveats
- Requires accurate forces (low fmax in relaxation)
- Supercell size affects accuracy
""",
        "metadata": EntryMetadata(
            source_provenance="https://phonopy.github.io/phonopy/",
            refinement_status=RefinementStatus.raw,
        ),
    },
    {
        "title": "ASE",
        "entry_type": EntryType.dependency,
        "tags": ["atomistic", "python", "library"],
        "content": """\
# ASE — Atomic Simulation Environment

Python library for setting up, running, and analysing atomistic simulations.

## Install

```bash
pip install ase
```

## Key Modules
- `ase.Atoms` — atomic structure representation
- `ase.io` — file I/O
- `ase.optimize` — geometry optimisers
- `ase.phonons` — phonon calculation

## External
- https://wiki.fysik.dtu.dk/ase/
""",
        "metadata": EntryMetadata(
            source_provenance="https://wiki.fysik.dtu.dk/ase/",
            refinement_status=RefinementStatus.validated,
        ),
    },
    {
        "title": "PyTorch",
        "entry_type": EntryType.dependency,
        "tags": ["deep-learning", "python", "library"],
        "content": """\
# PyTorch

Open source machine learning framework.

## Install

```bash
pip install torch
```

## External
- https://pytorch.org/
""",
        "metadata": EntryMetadata(
            source_provenance="https://pytorch.org/",
            refinement_status=RefinementStatus.validated,
        ),
    },
]


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        repo = EntryRepository(db)
        existing_titles = {e.title for e in repo.get_all()}
        created: list[Entry] = []
        for data in EXAMPLE_ENTRIES:
            if data["title"] in existing_titles:
                print(f"  skip (exists): {data['title']}")
                continue
            entry = Entry(**data)
            saved = repo.create(entry)
            app_state.graph.add_entry(saved)
            created.append(saved)
            print(f"  + {saved.title}")

    if not created:
        print("Nothing new to seed.")
        return

    from agents.extraction_agent.agent import ExtractionAgent

    agent = ExtractionAgent(app_state.graph)
    count = agent.resolve_wikilinks()
    print(f"\nResolved {count} wikilink edge(s)")
    stats = app_state.graph.stats()
    print(f"Graph: {stats['nodes']} nodes, {stats['edges']} edges")


if __name__ == "__main__":
    seed()
