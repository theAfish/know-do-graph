"""Seed the graph with nodes derived from the LAMMPS skill.

Source: https://github.com/Chenghao-Wu/skill_lammps
        (Chenghao-Wu / Claude Code, archived Mar 2026, CC-BY via GitHub public archive)

Usage
-----
    python scripts/seed_lammps_skill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import app_state
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus, VerificationStatus
from core.storage.database import SessionLocal, init_db
from core.storage.repository import EdgeRepository, EntryRepository
from core.schemas.edge import Edge, EdgeRelation

SOURCE = "https://github.com/Chenghao-Wu/skill_lammps"

ENTRIES: list[dict] = [
    # ── 1. Root tool node ───────────────────────────────────────────────────
    {
        "title": "LAMMPS",
        "entry_type": EntryType.tool,
        "tags": ["molecular-dynamics", "atomistic", "simulation", "lammps"],
        "aliases": ["Large-scale Atomic/Molecular Massively Parallel Simulator"],
        "content": """\
# LAMMPS

LAMMPS (Large-scale Atomic/Molecular Massively Parallel Simulator) is an open-source
classical molecular-dynamics code for large-scale atomic and molecular simulations.

## Key Features
- Runs on single processors or in parallel via MPI
- Supports a wide variety of interatomic potentials (force fields)
- Produces outputs: thermodynamic data, per-atom quantities, trajectory files
- Extensive package ecosystem (KOKKOS, GPU, REPLICA, etc.)

## Related nodes
- [[LAMMPS Input Script Structure]]
- [[LAMMPS Simulation Phases]]
- [[LAMMPS Unit Styles]]
- [[LAMMPS Atom Styles]]
- [[LAMMPS Force Fields]]
- [[LAMMPS Thermostats and Barostats]]
- [[LAMMPS DOF Validation]]
- [[LAMMPS Best Practices]]
- [[LAMMPS Deformation Methods]]

## External References
- https://lammps.sandia.gov/
- https://docs.lammps.org/
- https://github.com/lammps/lammps
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/", "https://github.com/lammps/lammps"],
        ),
    },

    # ── 2. Input script structure ────────────────────────────────────────────
    {
        "title": "LAMMPS Input Script Structure",
        "entry_type": EntryType.procedure,
        "tags": ["lammps", "molecular-dynamics", "script", "input"],
        "content": """\
# LAMMPS Input Script Structure

Source: https://github.com/Chenghao-Wu/skill_lammps

A well-structured [[LAMMPS]] input script follows a 4-section pattern.

## Section 1 — Initialization
Defines global settings before the system is read in.

```lammps
units    real          # Unit system: real | metal | lj | si | cgs | electron | micro | nano
atom_style full        # Atom attributes (full = bonds + angles + dihedrals + charge)
boundary  p p p        # Periodic boundaries (p=periodic, f=fixed, s=shrink-wrap)
```

## Section 2 — System Definition
Reads or creates the atomic system and sets up force-field parameters.

```lammps
read_data    system.data      # Read atom coordinates and topology
pair_style   lj/cut 10.0      # Force field style + cutoff
pair_coeff   * * 0.155 3.166  # LJ parameters (ε, σ) for each pair type
```

## Section 3 — Settings
Configures neighbor lists, output, and time integration parameters.

```lammps
neighbor     2.0 bin          # Neighbor-list skin distance
timestep     1.0              # Time step (fs for real units)
thermo_style custom step temp pe ke etotal press
```

## Section 4 — Simulation
Runs minimizations, equilibrations, and production dynamics.

```lammps
minimize     1.0e-4 1.0e-6 100 1000   # Energy minimisation before dynamics
fix    1 all nvt temp 300 300 100     # NVT thermostat (Nose-Hoover)
run    10000                           # Production run
```

## Related
- [[LAMMPS Unit Styles]]
- [[LAMMPS Simulation Phases]]
- [[LAMMPS Best Practices]]

## External References
- https://docs.lammps.org/Commands_input.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/Commands_input.html"],
        ),
    },

    # ── 3. Unit Styles ───────────────────────────────────────────────────────
    {
        "title": "LAMMPS Unit Styles",
        "entry_type": EntryType.data,
        "tags": ["lammps", "units", "reference", "molecular-dynamics"],
        "content": """\
# LAMMPS Unit Styles

Source: https://github.com/Chenghao-Wu/skill_lammps

The `units` command in [[LAMMPS]] determines the physical units used in the simulation.
All other values (timestep, cutoff, temperature, …) must be consistent with the chosen style.

## Reference Table

| Style  | Time | Length    | Energy      | Recommended timestep |
|--------|------|-----------|-------------|----------------------|
| real   | fs   | Ångström  | kcal/mol    | < 2 fs (1 fs typical)|
| metal  | ps   | Ångström  | eV          | < 0.005 ps           |
| lj     | τ    | σ         | ε           | 0.002–0.005 τ        |
| si     | s    | m         | J           | ~1 × 10⁻¹⁴ s         |
| cgs    | s    | cm        | erg         | –                    |
| electron | fs | Bohr      | Hartree     | –                    |

## Commonly Used Styles
- **real** — biomolecules, CHARMM/AMBER force fields
- **metal** — metals with EAM; consistent with eV and ps
- **lj** — reduced (dimensionless) units; common for coarse-grained models

## Rule: Unit Consistency
The `fix` thermostat/barostat arguments must use the same units:
```lammps
units real
fix 1 all nvt temp 300 300 100   # 100 fs damping
```
vs.
```lammps
units metal
fix 1 all nvt temp 300 300 0.1   # 0.1 ps = 100 fs damping
```

## External References
- https://docs.lammps.org/units.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/units.html"],
        ),
    },

    # ── 4. Atom Styles ───────────────────────────────────────────────────────
    {
        "title": "LAMMPS Atom Styles",
        "entry_type": EntryType.data,
        "tags": ["lammps", "atom-style", "reference", "molecular-dynamics"],
        "content": """\
# LAMMPS Atom Styles

Source: https://github.com/Chenghao-Wu/skill_lammps

The `atom_style` command in [[LAMMPS]] determines which per-atom attributes are stored.
Choose the simplest style that covers your needs (avoids memory overhead).

## Common Styles

| Style     | Per-atom data stored                                      | Typical use |
|-----------|-----------------------------------------------------------|-------------|
| atomic    | Position, velocity, force, type, id                      | Simple LJ / Lennard-Jones fluids, metals |
| charge    | + partial charge                                          | Coulombic systems |
| bond      | + bond topology                                           | Simple bonded models |
| molecular | + bonds, angles, dihedrals, impropers                    | Neutral molecules |
| full      | + bonds, angles, dihedrals, impropers, charge            | CHARMM / AMBER / OPLS biopolymers |

## Less Common Styles
- `ellipsoid` — rigid aspherical particles (Gay-Berne)
- `sphere` — granular particles with radius and angular velocity
- `dipole` — point dipoles
- `hybrid` — combine multiple styles

## Example
```lammps
atom_style full    # Needed for CHARMM force field
```

## External References
- https://docs.lammps.org/atom_style.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/atom_style.html"],
        ),
    },

    # ── 5. Force Fields ──────────────────────────────────────────────────────
    {
        "title": "LAMMPS Force Fields",
        "entry_type": EntryType.data,
        "tags": ["lammps", "force-field", "potential", "molecular-dynamics"],
        "content": """\
# LAMMPS Force Fields

Source: https://github.com/Chenghao-Wu/skill_lammps

Interatomic potentials (force fields) in [[LAMMPS]] are set with `pair_style`.

## Common Force Field Styles

| Style              | Description                                           | Use case |
|--------------------|-------------------------------------------------------|----------|
| `lj/cut`           | Lennard-Jones with a hard cutoff                      | Simple fluids, argon |
| `lj/cut/coul/long` | LJ + long-range Coulombics via PPPM/Ewald             | Charged molecules, ionic liquids |
| `eam`              | Embedded Atom Method                                  | Metals (Al, Cu, Fe…) |
| `eam/alloy`        | EAM for alloys                                        | Multi-component metals |
| `reax/c`           | ReaxFF reactive force field                           | Bond-breaking chemistry |
| `airebo`           | AIREBO for carbon (graphene, CNTs)                    | Carbon systems |
| `charmm`           | CHARMM pair style with switching functions            | Biomolecules |
| `sw`               | Stillinger-Weber                                      | Silicon |
| `tersoff`          | Tersoff covalent potential                            | Si, Ge, C |

## Example: LJ Fluid
```lammps
pair_style   lj/cut 10.0
pair_coeff   * * 0.155 3.166      # ε (kcal/mol), σ (Å)
```

## Example: EAM Metal
```lammps
pair_style   eam/alloy
pair_coeff   * * Cu_mishin1.eam.alloy Cu
```

## External References
- https://docs.lammps.org/pair_style.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/pair_style.html"],
        ),
    },

    # ── 6. Simulation Phases ─────────────────────────────────────────────────
    {
        "title": "LAMMPS Simulation Phases",
        "entry_type": EntryType.workflow,
        "tags": ["lammps", "molecular-dynamics", "workflow", "equilibration", "minimization"],
        "content": """\
# LAMMPS Simulation Phases

Source: https://github.com/Chenghao-Wu/skill_lammps

A standard [[LAMMPS]] simulation progresses through three phases.
Always follow this order to avoid unphysical behavior.

## Phase 1 — Energy Minimization
Required before dynamics to relax high-energy atomic overlaps.

```lammps
minimize    1.0e-4 1.0e-6 100 1000
# Arguments: etol ftol maxiter maxeval
```

- `etol` — relative energy tolerance (1e-4 is typical)
- `ftol` — max force tolerance (1e-6 Å-kcal/mol for real units)
- Run minimization even if structure looks clean — always helps.

## Phase 2 — Equilibration (NVT → NPT)
Bring system to target temperature and/or pressure.

**Recommended staged approach:**
```lammps
# Stage 1: NVT — fix volume, control temperature
fix 1 all nvt temp 300 300 100
timestep 1.0
run 10000

# Stage 2: NPT — also relax pressure
unfix 1
fix 1 all npt temp 300 300 100 iso 0 0 1000
run 10000
```

Convergence checks: temperature std/mean < 1%, volume std/mean < 1%, energy stable.

## Phase 3 — Production
Collect data with a minimal ensemble (usually NVE or NVT).

```lammps
unfix 1
fix 1 all nve          # Constant energy; use after NPT equilibration
run 100000             # At least 10× equilibration length
```

Minimum run lengths:

| Property            | Min steps | Notes |
|---------------------|-----------|-------|
| Structure           | 10 000    | Basic sampling |
| Diffusion           | 100 000   | MSD / VACF convergence |
| Viscosity           | 500 000   | Long-time correlations |
| Thermal conductivity| 200 000   | Heat flux averaging |

## Related
- [[LAMMPS Best Practices]]
- [[LAMMPS Thermostats and Barostats]]
- [[LAMMPS DOF Validation]]

## External References
- https://docs.lammps.org/minimize.html
- https://docs.lammps.org/fix_nvt.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/minimize.html"],
        ),
    },

    # ── 7. Thermostats and Barostats ─────────────────────────────────────────
    {
        "title": "LAMMPS Thermostats and Barostats",
        "entry_type": EntryType.capability,
        "tags": ["lammps", "thermostat", "barostat", "nvt", "npt", "molecular-dynamics"],
        "content": """\
# LAMMPS Thermostats and Barostats

Source: https://github.com/Chenghao-Wu/skill_lammps

Temperature and pressure are controlled through `fix` commands in [[LAMMPS]].

## Thermostat Comparison

| Fix | Ensemble | Recommended? | Notes |
|-----|----------|--------------|-------|
| `fix nvt` (Nose-Hoover) | NVT | ✅ Yes — production | Correct canonical ensemble |
| `fix langevin` | NVT + NVE | ✅ For coarse-grained | Stochastic; damps dynamics |
| `fix temp/berendsen` | NVT (approx.) | ⚠️ Equilibration only | Does NOT produce correct ensemble |

### Nose-Hoover (recommended default)
```lammps
fix 1 all nvt temp 300 300 100
#                  Tstart Tstop Tdamp(fs)
```
Typical `Tdamp`: 100 fs for real units, 0.1 ps for metal units.

### Langevin (implicit solvent / CG models)
```lammps
fix 1 all langevin 300 300 100 12345
#                  Tstart Tstop Tdamp seed
fix 2 all nve                            # also needed for integration
```

## Barostat Comparison

| Coupling | Axes controlled | Use for |
|----------|-----------------|---------|
| `iso`    | X=Y=Z together  | Isotropic liquids |
| `aniso`  | X, Y, Z independently | Solids, crystals |
| `x y z`  | Explicit per axis | Custom deformation workflows |

### NPT — isotropic (liquids)
```lammps
fix 1 all npt temp 300 300 100 iso 0 0 1000
#                               Pdamp(fs)
```

### NPT — anisotropic (crystals)
```lammps
fix 1 all npt temp 300 300 100 x 0 0 1000 y 0 0 1000 z 0 0 1000
```

Typical `Pdamp`: 1000 fs for liquids, 2000–5000 fs for solids.

## Critical Rules
1. **Never use more than one temperature controller** at a time — causes DOF conflicts → crash.
2. When using `fix deform`, avoid `iso` coupling on the deforming axis.

## Related
- [[LAMMPS DOF Validation]]
- [[LAMMPS Simulation Phases]]

## External References
- https://docs.lammps.org/fix_nh.html
- https://docs.lammps.org/fix_langevin.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/fix_nh.html"],
        ),
    },

    # ── 8. DOF Validation ────────────────────────────────────────────────────
    {
        "title": "LAMMPS DOF Validation",
        "entry_type": EntryType.procedure,
        "tags": ["lammps", "validation", "dof", "debugging", "molecular-dynamics"],
        "content": """\
# LAMMPS DOF Validation

Source: https://github.com/Chenghao-Wu/skill_lammps (.claude/skills/lammps/references/dof-validation.md)

## What Are DOF Conflicts?
In [[LAMMPS]], a **degrees-of-freedom (DOF) conflict** occurs when multiple `fix` commands
attempt to control the same simulation axis (X, Y, or Z) simultaneously.
LAMMPS will immediately crash:
```
ERROR: Multiple fixes control X axis
```

## Common Conflict Patterns

### ❌ Pattern 1 — Deform + Isotropic NPT
```lammps
fix 2 all deform 1 z erate 1.0e-5          # controls Z
fix 3 all npt temp 300 300 100 iso 0 0 1000 # controls X, Y, Z → CONFLICT on Z
```
✅ Fix: use explicit axes for npt
```lammps
fix 3 all npt temp 300 300 100 x 0 0 1000 y 0 0 1000  # leaves Z free
```

### ❌ Pattern 2 — Multiple Temperature Controllers
```lammps
fix 1 all npt temp 300 300 100 iso 0 0 1000
fix 2 all nvt temp 300 300 100               # CONFLICT — two T controllers
```
✅ Fix: remove one.

### ❌ Pattern 3 — Shear + Individual Axis NPT
```lammps
fix 2 all deform 1 xy erate 1.0e-5  # controls XY
fix 3 all npt temp 300 300 100 x 0 0 1000  # controls X → CONFLICT
```
✅ Fix:
```lammps
fix 3 all npt temp 300 300 100 z 0 0 1000   # control Z only
```

## Fix Axis Control Reference

| Fix command | Axes controlled |
|-------------|-----------------|
| `fix deform … x/y/z` | Named axis |
| `fix npt iso` | X, Y, Z |
| `fix npt aniso` | X, Y, Z (independently) |
| `fix npt x … y …` | Explicit axes only |
| `fix nvt` | Temperature only (no box DOF) |
| `fix nve` | None (pure integrator) |

## Validation Best Practice
Always validate scripts before submitting long jobs:
```bash
python scripts/validate_syntax.py input.in
python scripts/validate_physics.py input.in
python scripts/validate_protocol.py input.in
```

## Related
- [[LAMMPS Thermostats and Barostats]]
- [[LAMMPS Deformation Methods]]
- [[LAMMPS Best Practices]]

## External References
- https://docs.lammps.org/fix_deform.html
- https://docs.lammps.org/fix_nh.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/fix_deform.html"],
        ),
    },

    # ── 9. Deformation Methods ───────────────────────────────────────────────
    {
        "title": "LAMMPS Deformation Methods",
        "entry_type": EntryType.analytical,
        "tags": ["lammps", "deformation", "rheology", "tensile", "shear", "molecular-dynamics"],
        "content": """\
# LAMMPS Deformation Methods

Source: https://github.com/Chenghao-Wu/skill_lammps

Decision guide for choosing the correct deformation approach in [[LAMMPS]].

## Decision Tree

```
Need to deform your system?
│
├─ Studying flow/rheology (polymer melts, extensional flow)?
│  └─ Use UEF  (examples/uef/)
│     - Volume-preserving (traceless strain rate: ε_xx + ε_yy + ε_zz = 0)
│     - Requires triclinic box and periodic boundaries
│     - Thermostat: fix nvt/uef
│
├─ Mechanical deformation/tension?
│  ├─ Need volume control (Poisson effect)?
│  │  └─ Use fix deform + fix npt  (examples/deformation/)
│  │     - Transverse directions free to contract
│  │     - Volume can change (Poisson)
│  │     - Tensile testing, fracture studies
│  │
│  └─ Fixed transverse dimensions?
│     └─ Use fix deform + fix nvt
│
└─ Shear deformation?
   └─ Use SLLOD  (examples/shear/)
      - fix deform with erate
      - Thermostat: fix nvt/sllod
```

## UEF vs Mechanical Tension

| Property          | UEF (Rheology)              | fix deform (Mechanics) |
|-------------------|-----------------------------|------------------------|
| Purpose           | Flow behavior               | Mechanical deformation |
| Volume            | Preserved (traceless)       | Changes (Poisson) |
| Box type          | Triclinic required          | Orthogonal OK |
| Thermostat        | fix nvt/uef                 | fix npt or fix nvt |
| Primary use       | Polymer melts in flow       | Tensile/fracture |

## Strain Rate Guidelines (real units)

| Rate (τ⁻¹)    | Regime                       |
|----------------|------------------------------|
| 1e-8 – 1e-7   | Quasi-static (near-equilib.) |
| 1e-6 – 1e-5   | Standard testing             |
| 1e-4 – 1e-3   | High rate / non-equilibrium  |

Recommended starting point: **1e-6 τ⁻¹** — adjust for convergence.

## Example: Tensile Test (z-axis)
```lammps
fix 2 all deform 1 z erate 1.0e-5 remap x units box
fix 3 all npt temp 300 300 100 x 0 0 1000 y 0 0 1000  # NOT iso — leaves Z free
```

## Property Extraction
```python
import numpy as np
stress = np.loadtxt('stress.dat')
strain = np.loadtxt('strain.dat')
mask = (strain > 0) & (strain < 0.02)   # linear region
E, _ = np.polyfit(strain[mask], stress[mask], 1)
print(f"Young's Modulus: {E:.3f} GPa")
```

## Related
- [[LAMMPS DOF Validation]]
- [[LAMMPS Thermostats and Barostats]]
- [[LAMMPS Best Practices]]

## External References
- https://docs.lammps.org/fix_deform.html
- https://docs.lammps.org/fix_nvt_uef.html
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/fix_deform.html"],
            script_language="python",
        ),
    },

    # ── 10. Best Practices ───────────────────────────────────────────────────
    {
        "title": "LAMMPS Best Practices",
        "entry_type": EntryType.procedure,
        "tags": ["lammps", "molecular-dynamics", "best-practices", "checklist"],
        "content": """\
# LAMMPS Best Practices

Source: https://github.com/Chenghao-Wu/skill_lammps (.claude/skills/lammps/references/best-practices.md)

## Pre-Run Checklist
1. **Minimize before dynamics** — always relax high-energy contacts first
2. **Check timestep** — real: < 2 fs; metal: < 0.005 ps; lj: 0.001–0.005 τ
3. **Use appropriate ensemble** — NVT (const. V), NPT (const. P), NVE (const. E)
4. **One temperature controller only** — see [[LAMMPS DOF Validation]]
5. **Validate DOF conflicts** before submitting long jobs

## Timestep Selection
```lammps
timestep 1.0    # fs; conservative for most real-unit systems
```
Test: Run 10 000 steps NVE and check total energy conserves to ±1%.

## Thermostat Parameters
- `Tdamp`: 100 fs (real units) — standard; too small → oscillations, too large → poor control
- `Pdamp`: 1000 fs for liquids, 2000–5000 fs for solids

## Equilibration Strategy
1. NVT equilibration (temp only, ~10 000–50 000 steps)
2. NPT equilibration (relax volume, ~10 000–50 000 steps)
3. Check temperature, volume, and energy convergence: std/mean < 1%

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Insufficient equilibration | Drifting properties | Extend phase 2 |
| Timestep too large | Energy drift in NVE | Reduce to 1 fs |
| DOF conflict | LAMMPS crash | See [[LAMMPS DOF Validation]] |
| Wrong ensemble | Incorrect statistics | Match fix to target ensemble |
| Production too short | Large statistical error | Rule: ≥ 10× equilibration |

## Convergence Monitoring
```python
import numpy as np
# Block-average error estimator
def block_average(data, block_size=1000):
    blocks = [np.mean(data[i:i+block_size]) for i in range(0, len(data), block_size)]
    return np.mean(blocks), np.std(blocks) / np.sqrt(len(blocks))
```

## Neighbor List
```lammps
neighbor 2.0 bin    # skin = 2 Å (or 0.3 × cutoff)
```

## References (literature)
- Frenkel & Smit, *Understanding Molecular Simulation* (2002)
- Allen & Tildesley, *Computer Simulation of Liquids* (2017)
- Thompson et al. (2022) *Comput. Phys. Commun.*

## Related
- [[LAMMPS Simulation Phases]]
- [[LAMMPS DOF Validation]]
- [[LAMMPS Thermostats and Barostats]]

## External References
- https://docs.lammps.org/
- Source skill: https://github.com/Chenghao-Wu/skill_lammps
""",
        "metadata": EntryMetadata(
            source_provenance=SOURCE,
            extraction_method="manual-from-skill",
            refinement_status=RefinementStatus.linked,
            verification_status=VerificationStatus.community_tested,
            external_refs=[SOURCE, "https://docs.lammps.org/"],
        ),
    },
]

# ── Edges to create after all entries are inserted ───────────────────────────
# (source_title, target_title, relation)
EDGES: list[tuple[str, str, EdgeRelation]] = [
    ("LAMMPS", "LAMMPS Input Script Structure", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS Simulation Phases", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS Unit Styles", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS Atom Styles", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS Force Fields", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS Thermostats and Barostats", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS DOF Validation", EdgeRelation.uses),
    ("LAMMPS", "LAMMPS Best Practices", EdgeRelation.documents),
    ("LAMMPS", "LAMMPS Deformation Methods", EdgeRelation.uses),
    ("LAMMPS Input Script Structure", "LAMMPS Unit Styles", EdgeRelation.prerequisite),
    ("LAMMPS Input Script Structure", "LAMMPS Atom Styles", EdgeRelation.prerequisite),
    ("LAMMPS Input Script Structure", "LAMMPS Force Fields", EdgeRelation.uses),
    ("LAMMPS Simulation Phases", "LAMMPS Thermostats and Barostats", EdgeRelation.uses),
    ("LAMMPS Simulation Phases", "LAMMPS DOF Validation", EdgeRelation.related_workflow),
    ("LAMMPS Deformation Methods", "LAMMPS DOF Validation", EdgeRelation.prerequisite),
    ("LAMMPS Deformation Methods", "LAMMPS Thermostats and Barostats", EdgeRelation.uses),
    ("LAMMPS Best Practices", "LAMMPS DOF Validation", EdgeRelation.related_workflow),
    ("LAMMPS Best Practices", "LAMMPS Simulation Phases", EdgeRelation.related_workflow),
    ("LAMMPS DOF Validation", "LAMMPS Thermostats and Barostats", EdgeRelation.related_workflow),
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        entry_repo = EntryRepository(db)
        edge_repo = EdgeRepository(db)

        title_to_id: dict[str, str] = {}

        for data in ENTRIES:
            meta = data.pop("metadata")
            entry = Entry(**data, metadata=meta)
            saved = entry_repo.create(entry)
            title_to_id[saved.title] = saved.id
            app_state.graph.add_entry(saved)
            print(f"  ✓ Created: {saved.title}  [{saved.id[:8]}]")

        print(f"\nAdding {len(EDGES)} edges …")
        for src_title, dst_title, rel in EDGES:
            src_id = title_to_id.get(src_title)
            dst_id = title_to_id.get(dst_title)
            if not src_id or not dst_id:
                print(f"  ⚠ Skipping edge {src_title} → {dst_title}: ID not found")
                continue
            edge = Edge(source_id=src_id, target_id=dst_id, relation=rel)
            edge_repo.create(edge)
            app_state.graph.add_edge(edge)
            print(f"  ✓ Edge: {src_title} –[{rel.value}]→ {dst_title}")

        print(f"\nDone — {len(ENTRIES)} nodes, {len(EDGES)} edges added.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
