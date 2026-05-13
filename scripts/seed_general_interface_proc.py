"""One-off script: add the generalised interface procedure node to the DB."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage.database import SessionLocal, init_db
from core.storage.repository import EntryRepository, EdgeRepository
from core.storage.models import EdgeModel
from core.schemas.entry import Entry, EntryMetadata, EntryType, RefinementStatus
from core.schemas.edge import Edge, EdgeRelation
from core import app_state

PROC_TITLE = "Build Material Interface via Slab Stacking"

GENERAL_PROC = {
    "title": PROC_TITLE,
    "entry_type": EntryType.procedure,
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
- Vacuum layer thickness: >= 15 Å to suppress image interactions.

### Expected outputs
- Interface POSCAR / CIF file
- Interface energy in J/m²
- Band offsets (from DFT or model calculations)
""",
    "metadata": EntryMetadata(refinement_status=RefinementStatus.linked),
}

init_db()

with SessionLocal() as db:
    repo = EntryRepository(db)
    title_to_id = {e.title: e.id for e in repo.get_all()}

    if PROC_TITLE in title_to_id:
        print(f"Already exists: {PROC_TITLE}")
        proc_id = title_to_id[PROC_TITLE]
    else:
        saved = repo.create(Entry(**GENERAL_PROC))
        app_state.graph.add_entry(saved)
        proc_id = saved.id
        title_to_id[PROC_TITLE] = proc_id
        print(f"Created: {saved.title}  id={proc_id}")

    edge_repo = EdgeRepository(db)
    existing_pairs = {(e.source_id, e.target_id) for e in db.query(EdgeModel).all()}

    def wire(src_title, tgt_title, rel):
        src_id = title_to_id.get(src_title)
        tgt_id = title_to_id.get(tgt_title)
        if not src_id or not tgt_id:
            print(f"  WARN: missing node  {src_title!r} or {tgt_title!r}")
            return
        if (src_id, tgt_id) in existing_pairs:
            return
        e = edge_repo.create(Edge(source_id=src_id, target_id=tgt_id, relation=rel))
        app_state.graph.add_edge(e)
        existing_pairs.add((src_id, tgt_id))
        print(f"  edge: {src_title} --{rel.value}--> {tgt_title}")

    wire("Substrate Analysis Script",           PROC_TITLE, EdgeRelation.implements)
    wire("Slab Generation Script",              PROC_TITLE, EdgeRelation.implements)
    wire("Interface Builder Script",            PROC_TITLE, EdgeRelation.implements)
    wire("Interface Energy Calculation Script", PROC_TITLE, EdgeRelation.documents)
    wire("Band Alignment Calculation Script",   PROC_TITLE, EdgeRelation.documents)

    wire(PROC_TITLE, "Lattice Matching via ZSL Algorithm", EdgeRelation.execution_pathway)
    wire(PROC_TITLE, "Slab Surface Generation",            EdgeRelation.execution_pathway)
    wire(PROC_TITLE, "Coherent Interface Construction",    EdgeRelation.execution_pathway)
    wire(PROC_TITLE, "Download Bulk Structure from Materials Project", EdgeRelation.execution_pathway)

    db.commit()
    print("Done.")
