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
        graph.connect(
            capability.id,
            procedure.id,
            relation=EdgeRelation.decomposes_to,
        )

        candidates = graph.plan("relax this crystal")
        context = graph.expand(capability.slug, stages=["decomposition"])
        graph.memory("run-42").add(
            "Relaxation converged with FIRE at fmax=0.03.",
            tags=["success"],
            success=True,
        )

        print([entry.title for entry in candidates])
        print(context)


if __name__ == "__main__":
    main()
