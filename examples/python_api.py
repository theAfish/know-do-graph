"""Minimal embedding example for an agent application."""

from know_do_graph import EdgeRelation, EntryType, KnowDoGraph


def main() -> None:
    with KnowDoGraph("data/agent_memory.db") as graph:
        capability = graph.add(
            "Relax an atomic structure",
            entry_type=EntryType.capability,
            content="Choose a calculator, then run [[ASE Relaxation]].",
            tags=["atomistic", "planning"],
        )
        procedure = graph.add(
            "ASE Relaxation",
            entry_type=EntryType.procedure,
            content="Attach a calculator and run an ASE optimizer.",
            tags=["atomistic", "execution"],
        )
        heuristic = graph.add(
            "Prefer FIRE for noisy forces",
            entry_type=EntryType.heuristic,
            content="FIRE is often robust when force convergence is noisy.",
            tags=["atomistic", "optimizer"],
        )
        graph.connect(
            capability.id,
            procedure.id,
            relation=EdgeRelation.decomposes_to,
        )
        graph.connect(
            heuristic.id,
            capability.id,
            relation=EdgeRelation.heuristic_for,
        )

        candidates = graph.plan("relax this crystal")
        selected = candidates[0]
        attached = graph.count_attached(selected.id)
        sidecars = []
        if attached["heuristics"]:
            sidecars, total = graph.search_attached(
                selected.id,
                kind="heuristics",
                query="force convergence",
            )
            print(f"Showing {len(sidecars)} of {total} attached heuristics")

        graph.memory("run-42").add(
            "Relaxation converged with FIRE at fmax=0.03.",
            tags=["success"],
            success=True,
        )

        print([entry.title for entry in candidates])
        print([entry.title for entry in sidecars])


if __name__ == "__main__":
    main()
