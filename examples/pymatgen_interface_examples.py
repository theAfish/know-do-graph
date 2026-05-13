"""Seed the graph with generalised pymatgen interface-building knowledge and runnable scripts.

Populates:
  - Dependency entries (pymatgen, ASE, mp-api, ...)
  - Generalised capability / procedure entries (lattice matching, slab generation, ...)
  - Runnable script entries (downloadable via GET /entries/{id}/download)

Note: Specific material instances (Si, Ge, GaN, ...) and specific material-pair
interface nodes are intentionally excluded — those are examples / instantiations,
not generalised knowledge worth storing in the graph.

Usage
-----
    python examples/pymatgen_interface_examples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import app_state
from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus, VerificationStatus
from core.storage.database import SessionLocal, init_db
from core.storage.repository import EdgeRepository, EntryRepository

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _existing_titles(repo: EntryRepository) -> set[str]:
    return {e.title for e in repo.get_all()}


def _create(repo: EntryRepository, data: dict) -> Entry | None:
    entry = Entry(**data)
    return repo.create(entry)


# ---------------------------------------------------------------------------
# 1. Dependency entries
# ---------------------------------------------------------------------------

DEPS: list[dict] = [
    {
        "title": "pymatgen",
        "entry_type": EntryType.dependency,
        "tags": ["python", "materials-science", "library", "dft"],
        "aliases": ["Python Materials Genomics"],
        "content": """\
# pymatgen — Python Materials Genomics

Core library for materials analysis, structure manipulation, and interface construction.

## Install
```bash
pip install pymatgen
```

## Key modules for interfaces
- `pymatgen.core.surface` — `SlabGenerator`, `ReconstructionGenerator`
- `pymatgen.analysis.interfaces` — `SubstrateAnalyzer`, `InterfaceBuilder`, `CohenValence`
- `pymatgen.core.structure` — `Structure`, `Lattice`
- `pymatgen.io.vasp` — POSCAR / CONTCAR read-write
- `pymatgen.io.ase` — ASE ↔ pymatgen bridge

## External
- https://pymatgen.org/
- https://github.com/materialsproject/pymatgen
""",
        "metadata": EntryMetadata(
            source_provenance="https://pymatgen.org/",
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.community_tested,
        ),
    },
    {
        "title": "ASE",
        "entry_type": EntryType.dependency,
        "tags": ["python", "atomistic", "library"],
        "aliases": ["Atomic Simulation Environment"],
        "content": """\
# ASE — Atomic Simulation Environment

Python library for atomistic simulations.  
Interoperates with [[pymatgen]] via `pymatgen.io.ase`.

## Install
```bash
pip install ase
```

## External
- https://wiki.fysik.dtu.dk/ase/
""",
        "metadata": EntryMetadata(
            source_provenance="https://wiki.fysik.dtu.dk/ase/",
            refinement_status=RefinementStatus.validated,
        ),
    },
    {
        "title": "mp-api",
        "entry_type": EntryType.dependency,
        "tags": ["python", "materials-project", "api", "library"],
        "aliases": ["Materials Project API", "MPRester"],
        "content": """\
# mp-api — Materials Project REST API Client

Download bulk structures, band structures, and properties from the Materials Project database.

## Install
```bash
pip install mp-api
```

## Usage
```python
from mp_api.client import MPRester
with MPRester("YOUR_MP_API_KEY") as mpr:
    structure = mpr.get_structure_by_material_id("mp-149")  # Si
```

## External
- https://api.materialsproject.org/
- https://next-gen.materialsproject.org/
""",
        "metadata": EntryMetadata(
            source_provenance="https://api.materialsproject.org/",
            refinement_status=RefinementStatus.validated,
        ),
    },
]

# ---------------------------------------------------------------------------
# 2. Procedure entries
# ---------------------------------------------------------------------------

# NOTE: MATERIALS and INTERFACES lists removed. Specific material instances
# (Si, Ge, GaN, etc.) and specific material-pair interface nodes are
# instantiations, not generalised knowledge.

MATERIALS: list[dict] = []  # intentionally empty
INTERFACES: list[dict] = []  # intentionally empty

PROCEDURES: list[dict] = [
    {
        "title": "Build Material Interface via Slab Stacking",
        "entry_type": EntryType.data,
        "tags": ["interface-construction", "slab-stacking", "pymatgen", "heterostructure"],
        "content": """\
## Build Material Interface via Slab Stacking

General workflow for constructing a heterointerface between two materials using
the slab-stacking method with [[pymatgen]].

### Prerequisites
- [[pymatgen]]
- Bulk structures for substrate and film (from [[mp-api]] or local CIF files)

### Steps
1. Download bulk structures using [[Download Bulk Structure from Materials Project]].
2. Run [[Substrate Analysis Script]] to find compatible orientations and quantify lattice mismatch.
3. Generate oriented slabs for both materials with [[Slab Generation Script]].
4. Build the interface supercell with [[Interface Builder Script]].
5. Run ionic relaxation (e.g. [[ASE Relaxation]] with a DFT or ML calculator).
6. Compute interface energy with [[Interface Energy Calculation Script]].
7. Optionally compute band alignment with [[Band Alignment Calculation Script]].

### Key considerations
- Lattice mismatch determines strain state; use [[Lattice Matching via ZSL Algorithm]] to
  find the minimum-strain supercell.
- Polar surfaces (e.g. wurtzite nitrides) require termination treatment to
  avoid a diverging electrostatic potential (Tasker Type-III rule).
- Vacuum layer thickness: ≥ 15 Å to suppress image interactions.

### Expected outputs
- Interface POSCAR / CIF file
- Interface energy in J/m²
- Band offsets (from DFT or model calculations)
""",
        "metadata": EntryMetadata(refinement_status=RefinementStatus.linked),
    },
    {
        "title": "Download Bulk Structure from Materials Project",
        "entry_type": EntryType.procedure,
        "tags": ["materials-project", "pymatgen", "data-retrieval", "mp-api"],
        "content": """\
## Download Bulk Structure from Materials Project

Retrieve a relaxed bulk structure using [[mp-api]].

### Prerequisites
- [[mp-api]]  (`pip install mp-api`)
- A valid Materials Project API key (set as `MP_API_KEY` environment variable)

### Steps
1. Look up the material ID (e.g. `mp-149` for Si) on https://materialsproject.org.
2. Run [[Bulk Structure Download Script]] to fetch and save the structure.
3. Verify the structure with `pymatgen.core.structure.Structure.from_file`.

### Outputs
- `{formula}_{mp_id}.cif` or `POSCAR_{formula}` file
""",
        "metadata": EntryMetadata(refinement_status=RefinementStatus.linked),
    },
]

# ---------------------------------------------------------------------------
# 3. Script entries  (actual runnable Python code)
# ---------------------------------------------------------------------------

_BULK_DOWNLOAD_CODE = '''\
"""Download a bulk crystal structure from the Materials Project.

Requirements: mp-api pymatgen
Usage: python download_bulk_structure.py
"""
import os
from pathlib import Path

from mp_api.client import MPRester

# ── Configuration ──────────────────────────────────────────────────────────────
MP_IDS = {
    "Si":         "mp-149",
    "Ge":         "mp-32",
    "GaN":        "mp-804",
    "AlN":        "mp-661",
    "TiO2":       "mp-2657",
    "SrTiO3":     "mp-5229",
}
OUTPUT_DIR = Path("structures")
OUTPUT_DIR.mkdir(exist_ok=True)

api_key = os.environ.get("MP_API_KEY", "")
if not api_key:
    raise EnvironmentError("Set the MP_API_KEY environment variable.")

with MPRester(api_key) as mpr:
    for name, mp_id in MP_IDS.items():
        structure = mpr.get_structure_by_material_id(mp_id)
        out_path = OUTPUT_DIR / f"{name}_{mp_id}.cif"
        structure.to(str(out_path))
        print(f"  Saved {name} → {out_path}")

print("\\nDone. Structures saved to:", OUTPUT_DIR.resolve())
'''

_SUBSTRATE_ANALYSIS_CODE = '''\
"""Substrate / film lattice matching analysis using pymatgen SubstrateAnalyzer.

For a given substrate and film structure, finds all crystallographic orientations
and in-plane supercell combinations that minimise lattice mismatch.

Requirements: pymatgen
Usage: python substrate_analysis.py
"""
from __future__ import annotations

from pathlib import Path

from pymatgen.analysis.interfaces.substrate_analyzer import SubstrateAnalyzer
from pymatgen.core import Structure

# ── Configuration ──────────────────────────────────────────────────────────────
# Update these paths to your local CIF or POSCAR files
SUBSTRATE_FILE = "structures/Si_mp-149.cif"   # e.g. Si
FILM_FILE      = "structures/Ge_mp-32.cif"    # e.g. Ge

MAX_AREA   = 200   # max supercell area (Å²) to search
MAX_MISMATCH = 0.10  # max linear mismatch fraction (10 %)
MAX_ANGLE    = 0.01  # max angle mismatch (rad)

# ── Load structures ────────────────────────────────────────────────────────────
substrate = Structure.from_file(SUBSTRATE_FILE)
film       = Structure.from_file(FILM_FILE)

print(f"Substrate: {substrate.formula}  spacegroup: {substrate.get_space_group_info()}")
print(f"Film:      {film.formula}  spacegroup: {film.get_space_group_info()}")

# ── Run substrate analyzer ────────────────────────────────────────────────────
analyzer = SubstrateAnalyzer(max_area=MAX_AREA)
matches = list(analyzer.calculate(film, substrate, lowest=True))

if not matches:
    print("\\nNo matching orientations found with current search parameters.")
else:
    print(f"\\nFound {len(matches)} orientation match(es):\\n")
    for i, m in enumerate(matches[:10]):  # show top 10
        print(
            f"  [{i+1}] substrate_miller={m.substrate_miller}  "
            f"film_miller={m.film_miller}  "
            f"mismatch={m.mismatch:.4f}  "
            f"strain_energy={m.elastic_energy:.3f} eV/Å²  "
            f"sub_sl_vecs={m.substrate_sl_vectors}"
        )
'''

_SLAB_GENERATION_CODE = '''\
"""Generate oriented slab models from bulk structures using pymatgen SlabGenerator.

Requirements: pymatgen
Usage: python slab_generation.py
"""
from __future__ import annotations

from pathlib import Path

from pymatgen.core import Structure
from pymatgen.core.surface import SlabGenerator

# ── Configuration ──────────────────────────────────────────────────────────────
BULK_FILE    = "structures/Si_mp-149.cif"   # bulk structure
MILLER_INDEX = (0, 0, 1)                    # surface orientation
MIN_SLAB_SIZE     = 10.0   # minimum slab thickness (Å)
MIN_VACUUM_SIZE   = 15.0   # vacuum layer thickness (Å)
IN_UNIT_PLANES    = False  # use Å not unit cells
PRIMITIVE          = False  # keep conventional cell
SYMMETRIZE        = True   # make slab symmetric (equal top/bottom)
MAX_NORMAL_SEARCH = 2      # search depth for non-orthogonal slabs

OUTPUT_DIR = Path("slabs")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Load bulk and generate slabs ──────────────────────────────────────────────
bulk = Structure.from_file(BULK_FILE)
print(f"Bulk: {bulk.formula}  ({bulk.num_sites} atoms)")

gen = SlabGenerator(
    bulk,
    miller_index=MILLER_INDEX,
    min_slab_size=MIN_SLAB_SIZE,
    min_vacuum_size=MIN_VACUUM_SIZE,
    in_unit_planes=IN_UNIT_PLANES,
    primitive=PRIMITIVE,
    max_normal_search=MAX_NORMAL_SEARCH,
)

slabs = gen.get_slabs(symmetrize=SYMMETRIZE)
print(f"\\nGenerated {len(slabs)} slab termination(s) for {bulk.formula}{list(MILLER_INDEX)}:\\n")

for i, slab in enumerate(slabs):
    fname = OUTPUT_DIR / f"{bulk.formula}_{''.join(map(str, MILLER_INDEX))}_term{i}.cif"
    slab.to(str(fname))
    print(
        f"  Termination {i}: {slab.num_sites} atoms  "
        f"thickness={slab.get_orthogonal_c_slab().lattice.c:.2f} Å  → {fname.name}"
    )
'''

_INTERFACE_BUILDER_CODE = '''\
"""Build a heterointerface supercell using pymatgen InterfaceBuilder.

Stacks a film slab on a substrate slab, matching the in-plane lattice vectors.
Produces a POSCAR ready for DFT or ML-IP relaxation.

Requirements: pymatgen
Usage: python interface_builder.py
"""
from __future__ import annotations

from pathlib import Path

from pymatgen.analysis.interfaces.coherent_interfaces import CoherentInterfaceBuilder
from pymatgen.core import Structure

# ── Configuration ──────────────────────────────────────────────────────────────
SUBSTRATE_FILE    = "structures/Si_mp-149.cif"
FILM_FILE         = "structures/Ge_mp-32.cif"

SUBSTRATE_MILLER  = (0, 0, 1)
FILM_MILLER       = (0, 0, 1)

IN_LAYERS_SUBSTRATE = 4    # number of substrate layers
IN_LAYERS_FILM      = 3    # number of film layers
VACUUM              = 20.0 # Å vacuum above the film

OUTPUT_DIR = Path("interfaces")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Load structures ────────────────────────────────────────────────────────────
substrate_bulk = Structure.from_file(SUBSTRATE_FILE)
film_bulk      = Structure.from_file(FILM_FILE)

print(f"Substrate bulk: {substrate_bulk.formula}")
print(f"Film bulk:      {film_bulk.formula}")

# ── Build interface ────────────────────────────────────────────────────────────
builder = CoherentInterfaceBuilder(
    substrate_structure=substrate_bulk,
    film_structure=film_bulk,
    substrate_miller=SUBSTRATE_MILLER,
    film_miller=FILM_MILLER,
    zslgen=None,               # use default ZSL generator settings
)

interfaces = list(
    builder.get_interfaces(
        termination=builder.terminations[0],
        gap=2.5,               # Å gap at interface
        vacuum_over_film=VACUUM,
        film_thickness=IN_LAYERS_FILM,
        substrate_thickness=IN_LAYERS_SUBSTRATE,
        in_layers=True,
    )
)

print(f"\\nBuilt {len(interfaces)} interface structure(s):")
for i, iface in enumerate(interfaces):
    fname = OUTPUT_DIR / (
        f"{substrate_bulk.formula}_{film_bulk.formula}_"
        f"{''.join(map(str,SUBSTRATE_MILLER))}-{''.join(map(str,FILM_MILLER))}"
        f"_v{i}.vasp"
    )
    iface.to(str(fname), fmt="poscar")
    print(
        f"  [{i}] {iface.num_sites} atoms  "
        f"a={iface.lattice.a:.3f} b={iface.lattice.b:.3f} "
        f"c={iface.lattice.c:.3f} Å  → {fname.name}"
    )

if interfaces:
    best = interfaces[0]
    print(f"\\nBest interface: {best.num_sites} sites, saved as {fname.name}")
'''

_INTERFACE_ENERGY_CODE = '''\
"""Compute interface energy from DFT/ML-IP total energies.

Uses the formula:
    E_interface = (E_slab_AB - E_slab_A - E_slab_B) / (2 * A)

where A is the interface cross-sectional area.

Requirements: pymatgen, ase (for energy extraction), numpy
Usage: python interface_energy.py
"""
from __future__ import annotations

import numpy as np

# ── Input total energies (replace with your DFT/MLIP values) ──────────────────
# All energies in eV; structures from files written by interface_builder.py

E_slab_AB = -1234.56   # eV  — total energy of the full interface supercell
E_slab_A  =  -800.00   # eV  — total energy of substrate slab (same cell, no film)
E_slab_B  =  -430.00   # eV  — total energy of film slab (same cell, no substrate)

# Lattice parameters of the interface cell (in Å)
a = 5.431
b = 5.431

# ── Calculation ────────────────────────────────────────────────────────────────
area_ang2  = a * b                          # Å²
area_m2    = area_ang2 * 1e-20              # m²
eV_to_J    = 1.602176634e-19               # J/eV

E_interface_eV     = E_slab_AB - E_slab_A - E_slab_B
# Factor 2: two equivalent interfaces created when periodic slab is cut
E_interface_J_m2   = (E_interface_eV * eV_to_J) / (2 * area_m2)

print(f"Interface energy components:")
print(f"  E(slab_AB) = {E_slab_AB:.4f} eV")
print(f"  E(slab_A)  = {E_slab_A:.4f} eV")
print(f"  E(slab_B)  = {E_slab_B:.4f} eV")
print(f"  ΔE         = {E_interface_eV:.4f} eV")
print(f"  Area       = {area_ang2:.3f} Å² = {area_m2:.4e} m²")
print(f"\\nInterface energy = {E_interface_J_m2:.4f} J/m²")

# Typical ranges:
#   Low energy (stable):   0.0 – 0.5 J/m²
#   Medium energy:         0.5 – 1.5 J/m²
#   High energy (strained):> 1.5 J/m²
if E_interface_J_m2 < 0.5:
    print("Assessment: low-energy (thermodynamically stable) interface")
elif E_interface_J_m2 < 1.5:
    print("Assessment: moderate-energy interface")
else:
    print("Assessment: high-energy interface — consider strain relaxation or reconstruction")
'''

_BAND_ALIGNMENT_CODE = '''\
"""Compute natural band alignment and band offset at a heterointerface.

Uses the branch-point energy (BPE) / charge neutrality level (CNL) method
and the band-gap / VBM values from DFT calculations.

Requirements: numpy
Usage: python band_alignment.py
"""
from __future__ import annotations

import numpy as np

# ── Material parameters (fill in from your DFT results) ───────────────────────
# All energies relative to the average electrostatic potential of the bulk slab.

materials = {
    "Si": {
        "Eg":        1.12,    # eV — band gap
        "VBM_bulk":  0.00,    # eV — VBM (set reference to 0 for first material)
        "BPE_bulk": -4.05,    # eV — branch-point energy w.r.t. VBM
    },
    "Ge": {
        "Eg":        0.67,    # eV
        "VBM_bulk":  0.00,    # eV — will be shifted relative to Si
        "BPE_bulk": -4.00,    # eV
    },
}

# Potential lineup from interface calculation (VBM_Ge - VBM_Si from slab)
delta_V = 0.74   # eV  — valence band offset from DFT interface calc

# ── Compute band offsets ───────────────────────────────────────────────────────
VBO = delta_V                                         # valence band offset
CBO = (materials["Ge"]["Eg"] - materials["Si"]["Eg"]) - VBO  # conduction band offset

print("=" * 50)
print("Band alignment: Si / Ge heterointerface")
print("=" * 50)
print(f"  Valence band offset (VBO)     : {VBO:+.3f} eV")
print(f"  Conduction band offset (CBO)  : {CBO:+.3f} eV")

if VBO * CBO > 0:
    btype = "Type-I (straddling gap)"
elif VBO * CBO < 0:
    btype = "Type-II (staggered gap)"
else:
    btype = "Type-III (broken gap)"
print(f"  Band alignment type           : {btype}")

print()
print("Energy level diagram (eV, Si VBM = 0.00):")
print(f"  Si VBM = 0.00     Si CBM = {materials['Si']['Eg']:.2f}")
print(f"  Ge VBM = {VBO:+.2f}  Ge CBM = {VBO + materials['Ge']['Eg']:.2f}")
'''

SCRIPTS: list[dict] = [
    {
        "title": "Bulk Structure Download Script",
        "entry_type": EntryType.capability,
        "tags": ["pymatgen", "mp-api", "data-retrieval", "python"],
        "aliases": ["download_bulk_structure.py"],
        "content": _BULK_DOWNLOAD_CODE,
        "metadata": EntryMetadata(
            source_provenance="https://api.materialsproject.org/",
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.self_tested,
            script_language="python",
            script_requirements=["pymatgen", "mp-api"],
            script_filename="download_bulk_structure.py",
        ),
    },
    {
        "title": "Substrate Analysis Script",
        "entry_type": EntryType.capability,
        "tags": ["pymatgen", "lattice-matching", "substrate-analysis", "python"],
        "aliases": ["substrate_analysis.py"],
        "content": _SUBSTRATE_ANALYSIS_CODE,
        "metadata": EntryMetadata(
            source_provenance="https://pymatgen.org/pymatgen.analysis.interfaces.html",
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.self_tested,
            script_language="python",
            script_requirements=["pymatgen"],
            script_filename="substrate_analysis.py",
        ),
    },
    {
        "title": "Slab Generation Script",
        "entry_type": EntryType.capability,
        "tags": ["pymatgen", "slab-generation", "surface", "python"],
        "aliases": ["slab_generation.py"],
        "content": _SLAB_GENERATION_CODE,
        "metadata": EntryMetadata(
            source_provenance="https://pymatgen.org/pymatgen.core.surface.html",
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.self_tested,
            script_language="python",
            script_requirements=["pymatgen"],
            script_filename="slab_generation.py",
        ),
    },
    {
        "title": "Interface Builder Script",
        "entry_type": EntryType.capability,
        "tags": ["pymatgen", "interface-builder", "coherent-interface", "python"],
        "aliases": ["interface_builder.py"],
        "content": _INTERFACE_BUILDER_CODE,
        "metadata": EntryMetadata(
            source_provenance="https://pymatgen.org/pymatgen.analysis.interfaces.html",
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.self_tested,
            script_language="python",
            script_requirements=["pymatgen"],
            script_filename="interface_builder.py",
        ),
    },
    {
        "title": "Interface Energy Calculation Script",
        "entry_type": EntryType.capability,
        "tags": ["interface-energy", "thermodynamics", "python", "numpy"],
        "aliases": ["interface_energy.py"],
        "content": _INTERFACE_ENERGY_CODE,
        "metadata": EntryMetadata(
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.self_tested,
            script_language="python",
            script_requirements=["numpy"],
            script_filename="interface_energy.py",
        ),
    },
    {
        "title": "Band Alignment Calculation Script",
        "entry_type": EntryType.capability,
        "tags": ["band-alignment", "band-offset", "heterojunction", "python", "numpy"],
        "aliases": ["band_alignment.py"],
        "content": _BAND_ALIGNMENT_CODE,
        "metadata": EntryMetadata(
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.self_tested,
            script_language="python",
            script_requirements=["numpy"],
            script_filename="band_alignment.py",
        ),
    },
]

# ---------------------------------------------------------------------------
# 6. Capability entries
# ---------------------------------------------------------------------------

CAPABILITIES: list[dict] = [
    {
        "title": "Lattice Matching via ZSL Algorithm",
        "entry_type": EntryType.capability,
        "tags": ["lattice-matching", "substrate-analysis", "pymatgen", "zsl"],
        "aliases": ["ZSL lattice matching", "Zur-McGill lattice matching"],
        "content": """\
## Lattice Matching via ZSL Algorithm

[[pymatgen]] `SubstrateAnalyzer` implements the Zur & McGill (ZSL) algorithm to find
supercell coincidence lattices between two crystal surfaces that minimise area and mismatch.

### Relevant script
Run [[Substrate Analysis Script]] to execute a lattice matching analysis.

### Output
- Substrate and film Miller indices
- Linear mismatch (%)
- Elastic strain energy density
- Coincidence supercell vectors

### Reference
Zur & McGill, J. Appl. Phys. 55, 378 (1984).
""",
        "metadata": EntryMetadata(
            source_provenance="https://doi.org/10.1063/1.333084",
            refinement_status=RefinementStatus.linked,
        ),
    },
    {
        "title": "Coherent Interface Construction",
        "entry_type": EntryType.capability,
        "tags": ["interface-construction", "pymatgen", "coherent-interface"],
        "aliases": ["CoherentInterfaceBuilder"],
        "content": """\
## Coherent Interface Construction

[[pymatgen]] `CoherentInterfaceBuilder` automates the stacking of two slab models into
a periodic interface supercell with a controllable vacuum region.

### Relevant script
Run [[Interface Builder Script]] to construct an interface supercell.

### Key parameters
- `gap` — spacing between slab surfaces at the interface (Å)
- `vacuum_over_film` — vacuum layer above the film slab (Å)
- `film_thickness` / `substrate_thickness` — in layers or Å
- `termination` — choose from available slab terminations

### Reference
Mathew et al., Comput. Mater. Sci. 152, 60 (2018).
""",
        "metadata": EntryMetadata(
            source_provenance="https://doi.org/10.1016/j.commatsci.2018.05.018",
            refinement_status=RefinementStatus.linked,
        ),
    },
    {
        "title": "Slab Surface Generation",
        "entry_type": EntryType.capability,
        "tags": ["slab-generation", "surface-science", "pymatgen"],
        "content": """\
## Slab Surface Generation

[[pymatgen]] `SlabGenerator` creates slab models from bulk crystals for any Miller index,
with controllable thickness, vacuum, and termination symmetry.

### Relevant script
Run [[Slab Generation Script]] to generate slab models.

### Key options
- `symmetrize=True` — force symmetric top/bottom terminations
- `max_normal_search` — controls accuracy for non-orthogonal surface cells
- `in_unit_planes=True` — thickness in unit cells rather than Å
""",
        "metadata": EntryMetadata(
            source_provenance="https://pymatgen.org/pymatgen.core.surface.html",
            refinement_status=RefinementStatus.linked,
        ),
    },
]

# ---------------------------------------------------------------------------
# Edge wiring definitions
# ---------------------------------------------------------------------------

# Each tuple: (source_title, target_title, relation)
EDGE_WIRING: list[tuple[str, str, EdgeRelation]] = [
    # Scripts implement generalised capabilities
    ("Substrate Analysis Script",          "Lattice Matching via ZSL Algorithm",                 EdgeRelation.implements),
    ("Substrate Analysis Script",          "Build Material Interface via Slab Stacking",         EdgeRelation.implements),
    ("Slab Generation Script",             "Slab Surface Generation",                            EdgeRelation.implements),
    ("Slab Generation Script",             "Build Material Interface via Slab Stacking",         EdgeRelation.implements),
    ("Interface Builder Script",           "Coherent Interface Construction",                    EdgeRelation.implements),
    ("Interface Builder Script",           "Build Material Interface via Slab Stacking",         EdgeRelation.implements),
    ("Interface Energy Calculation Script","Build Material Interface via Slab Stacking",         EdgeRelation.documents),
    ("Band Alignment Calculation Script",  "Build Material Interface via Slab Stacking",         EdgeRelation.documents),
    ("Bulk Structure Download Script",     "Download Bulk Structure from Materials Project",     EdgeRelation.implements),
    # Scripts use dependencies
    ("Substrate Analysis Script",          "pymatgen",   EdgeRelation.uses),
    ("Slab Generation Script",             "pymatgen",   EdgeRelation.uses),
    ("Interface Builder Script",           "pymatgen",   EdgeRelation.uses),
    ("Interface Energy Calculation Script","pymatgen",   EdgeRelation.uses),
    ("Band Alignment Calculation Script",  "pymatgen",   EdgeRelation.uses),
    ("Bulk Structure Download Script",     "pymatgen",   EdgeRelation.uses),
    ("Bulk Structure Download Script",     "mp-api",     EdgeRelation.uses),
    # Procedure uses generalised capabilities
    ("Build Material Interface via Slab Stacking", "Lattice Matching via ZSL Algorithm",  EdgeRelation.execution_pathway),
    ("Build Material Interface via Slab Stacking", "Slab Surface Generation",             EdgeRelation.execution_pathway),
    ("Build Material Interface via Slab Stacking", "Coherent Interface Construction",     EdgeRelation.execution_pathway),
    # Download procedure uses mp-api
    ("Download Bulk Structure from Materials Project", "mp-api", EdgeRelation.dependency),
]

# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------

def seed() -> None:
    init_db()
    all_data = DEPS + PROCEDURES + CAPABILITIES + SCRIPTS

    title_to_id: dict[str, str] = {}

    with SessionLocal() as db:
        repo = EntryRepository(db)
        existing = {e.title: e.id for e in repo.get_all()}
        title_to_id.update(existing)

        for data in all_data:
            title = data["title"]
            if title in existing:
                print(f"  skip (exists): {title}")
                title_to_id[title] = existing[title]
                continue
            entry = Entry(**data)
            saved = repo.create(entry)
            app_state.graph.add_entry(saved)
            title_to_id[saved.title] = saved.id
            print(f"  + {saved.title}  [{saved.entry_type.value}]")

    # Wire edges
    edges_created = 0
    with SessionLocal() as db:
        edge_repo = EdgeRepository(db)
        # Check existing edges to avoid dupes
        from core.storage.models import EdgeModel
        existing_pairs = {
            (e.source_id, e.target_id) for e in db.query(EdgeModel).all()
        }
        for src_title, tgt_title, relation in EDGE_WIRING:
            src_id = title_to_id.get(src_title)
            tgt_id = title_to_id.get(tgt_title)
            if not src_id or not tgt_id:
                print(f"  WARN: skipping edge {src_title!r} → {tgt_title!r} (missing node)")
                continue
            if (src_id, tgt_id) in existing_pairs:
                continue
            edge = Edge(source_id=src_id, target_id=tgt_id, relation=relation)
            saved_edge = edge_repo.create(edge)
            app_state.graph.add_edge(saved_edge)
            existing_pairs.add((src_id, tgt_id))
            edges_created += 1

    print(f"\nEdges created: {edges_created}")

    # Resolve wikilinks
    from agents.extraction_agent.agent import ExtractionAgent
    agent = ExtractionAgent(app_state.graph)
    wl_count = agent.resolve_wikilinks()
    print(f"Resolved {wl_count} wikilink edge(s)")
    print("\nPymatgen interface entries seeded successfully.")


if __name__ == "__main__":
    seed()
