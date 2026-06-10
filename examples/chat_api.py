"""Python chat API examples.

Set OPENAI_API_KEY and, for an OpenAI-compatible provider, OPENAI_API_BASE.
The model can be supplied directly or through GRAPH_AGENT_MODEL.
"""

from __future__ import annotations

import asyncio

from know_do_graph import KnowDoGraph


def print_step(event: str, data: dict) -> None:
    """Receive model/tool progress without parsing console output."""
    if event == "tool_call":
        print(f"calling {data['name']}: {data['args']}")
    elif event == "tool_result":
        print(f"finished {data['name']}: {data['result']}")


def read_only_chat(graph: KnowDoGraph) -> None:
    chat = graph.chat(
        read_only=True,
        model="qwen-plus",
    )
    print(chat.send("Which capabilities can help relax an atomic structure?"))
    print(chat.send("Expand on the most relevant one and list its constraints."))
    chat.reset()


def graph_management_chat(graph: KnowDoGraph) -> None:
    chat = graph.chat(
        model="qwen-plus",
        on_step=print_step,
    )
    reply = chat.send(
        "Add a reusable capability for validating an atomistic relaxation, "
        "but search for duplicates first and connect it to relevant procedures."
    )
    print(reply)


def orchestrator_and_reviewer(graph: KnowDoGraph) -> None:
    orchestrator = graph.chat(agent="orchestrator", model="qwen-plus")
    print(orchestrator.send("Find weak coverage around phonon workflows and improve it."))

    reviewer = graph.chat(agent="reviewer", model="qwen-plus", batch_size=3)
    print(reviewer.review("Focus on duplicate titles and inconsistent tags."))


async def async_agent_runtime(graph: KnowDoGraph) -> str:
    """Run the synchronous chat loop without blocking an async agent runtime."""
    chat = graph.chat(read_only=True, model="qwen-plus")
    return await asyncio.to_thread(chat.send, "Summarize the graph's interface-building skills.")


def main() -> None:
    with KnowDoGraph("data/agent_memory.db") as graph:
        read_only_chat(graph)
        graph_management_chat(graph)
        orchestrator_and_reviewer(graph)
        print(asyncio.run(async_agent_runtime(graph)))


if __name__ == "__main__":
    main()
