"""Know-Do Graph — CLI entry point.

Usage
-----
    python main.py --help
    python main.py entry add "My Entry" --content "..." --type tool
    python main.py entry list
    python main.py entry show <id-or-slug>
    python main.py entry search <query>
    python main.py extract file path/to/notes/
    python main.py graph stats
    python main.py graph neighbors <entry-id>
    python main.py mem add "remembered something"
    python main.py agent chat          # interactive REPL
    python main.py agent run "task"    # one-shot task
    python main.py serve
"""

from __future__ import annotations

import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Load .env so OPENAI_API_KEY / OPENAI_API_BASE are available without manual export
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment

app = typer.Typer(
    name="know-do-graph",
    help="Wiki-native executable knowledge graph — CLI",
    no_args_is_help=True,
)
console = Console()


def _init() -> None:
    from core.storage.database import init_db

    init_db()


def _rebuild_graph() -> None:
    from core import app_state
    from core.storage.database import SessionLocal
    from core.storage.repository import EdgeRepository, EntryRepository

    with SessionLocal() as db:
        entries = EntryRepository(db).get_all()
        edges = EdgeRepository(db).get_all()
    app_state.graph.rebuild_from_db(entries, edges)


# ===========================================================================
# entry sub-commands
# ===========================================================================

entry_app = typer.Typer(help="Manage knowledge entries", no_args_is_help=True)
app.add_typer(entry_app, name="entry")


@entry_app.command("add")
def entry_add(
    title: str = typer.Argument(..., help="Entry title"),
    content: str = typer.Option("", "--content", "-c", help="Entry body (wiki text)"),
    entry_type: str = typer.Option("generic", "--type", "-t", help="Entry type"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags"),
    source: str = typer.Option(None, "--source", "-s", help="Source provenance URL/path"),
) -> None:
    """Add a new knowledge entry."""
    _init()
    from core import app_state
    from core.schemas.entry import Entry, EntryMetadata, EntryType
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    entry = Entry(
        title=title,
        content=content,
        entry_type=EntryType(entry_type),
        tags=tag_list,
        metadata=EntryMetadata(source_provenance=source),
    )
    with SessionLocal() as db:
        saved = EntryRepository(db).create(entry)
    app_state.graph.add_entry(saved)
    console.print(f"[green]Created:[/green] {saved.title}  [dim]({saved.id})[/dim]")


@entry_app.command("list")
def entry_list(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List knowledge entries."""
    _init()
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    with SessionLocal() as db:
        entries = EntryRepository(db).get_all()

    table = Table("Short ID", "Title", "Type", "Tags", "Refs", show_header=True)
    for e in entries[:limit]:
        table.add_row(
            e.id[:8],
            e.title,
            e.entry_type.value,
            ", ".join(e.tags),
            str(len(e.internal_refs)),
        )
    console.print(table)
    if len(entries) > limit:
        console.print(f"[dim]… {len(entries) - limit} more entries not shown[/dim]")


@entry_app.command("show")
def entry_show(
    identifier: str = typer.Argument(..., help="Entry ID or slug"),
) -> None:
    """Show full details of an entry."""
    _init()
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    with SessionLocal() as db:
        engine = RetrievalEngine(db, app_state.graph)
        entry = engine.get_entry_by_id(identifier) or engine.get_entry_by_slug(identifier)

    if not entry:
        console.print(f"[red]Not found:[/red] {identifier}")
        raise typer.Exit(1)

    console.rule(f"[bold]{entry.title}[/bold]")
    console.print(f"[dim]ID       :[/dim] {entry.id}")
    console.print(f"[dim]Slug     :[/dim] {entry.slug}")
    console.print(f"[dim]Type     :[/dim] {entry.entry_type.value}")
    console.print(f"[dim]Tags     :[/dim] {', '.join(entry.tags) or '—'}")
    console.print(f"[dim]Refs     :[/dim] {', '.join(entry.internal_refs) or '—'}")
    console.print(
        f"[dim]Source   :[/dim] {entry.metadata.source_provenance or '—'}"
    )
    console.print(
        f"[dim]Status   :[/dim] {entry.metadata.refinement_status.value}"
    )
    console.rule()
    console.print(entry.content)


@entry_app.command("search")
def entry_search(
    query: str = typer.Argument(...),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Full-text search across entries."""
    _init()
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    with SessionLocal() as db:
        engine = RetrievalEngine(db, app_state.graph)
        results = engine.search_entries(query=query, limit=limit)

    table = Table("Short ID", "Title", "Type", "Tags")
    for e in results:
        table.add_row(e.id[:8], e.title, e.entry_type.value, ", ".join(e.tags))
    console.print(table)


@entry_app.command("delete")
def entry_delete(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an entry."""
    if not yes:
        typer.confirm(f"Delete entry {entry_id}?", abort=True)
    _init()
    from core import app_state
    from core.storage.database import SessionLocal
    from core.storage.repository import EntryRepository

    with SessionLocal() as db:
        deleted = EntryRepository(db).delete(entry_id)
    if deleted:
        app_state.graph.remove_entry(entry_id)
        console.print(f"[green]Deleted:[/green] {entry_id}")
    else:
        console.print(f"[red]Not found:[/red] {entry_id}")
        raise typer.Exit(1)


# ===========================================================================
# extract sub-commands
# ===========================================================================

extract_app = typer.Typer(help="Extract entries from files or directories", no_args_is_help=True)
app.add_typer(extract_app, name="extract")


@extract_app.command("file")
def extract_file(
    path: str = typer.Argument(..., help="File or directory to extract from"),
    entry_type: str = typer.Option("generic", "--type", "-t"),
    tags: str = typer.Option("", "--tags"),
    resolve: bool = typer.Option(
        True, "--resolve/--no-resolve", help="Resolve [[wikilinks]] after extraction"
    ),
) -> None:
    """Extract entries from a file or directory of text/markdown files."""
    _init()
    from pathlib import Path as P

    from core import app_state
    from core.schemas.entry import EntryType
    from agents.extraction_agent.agent import ExtractionAgent

    agent = ExtractionAgent(app_state.graph)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    target = P(path)

    with console.status(f"Extracting from [bold]{target}[/bold]…"):
        if target.is_dir():
            extracted = agent.extract_from_directory(
                target, entry_type=EntryType(entry_type), tags=tag_list
            )
        else:
            extracted = [
                agent.extract_from_file(target, EntryType(entry_type), tags=tag_list)
            ]

    for e in extracted:
        console.print(f"  [green]+[/green] {e.title}")

    if resolve:
        count = agent.resolve_wikilinks()
        console.print(f"[blue]Resolved {count} wikilink edge(s)[/blue]")


# ===========================================================================
# graph sub-commands
# ===========================================================================

graph_app = typer.Typer(help="Graph inspection and traversal", no_args_is_help=True)
app.add_typer(graph_app, name="graph")


@graph_app.command("stats")
def graph_stats() -> None:
    """Print graph statistics."""
    _init()
    _rebuild_graph()
    from core import app_state

    s = app_state.graph.stats()
    console.print(f"Nodes : [bold]{s['nodes']}[/bold]")
    console.print(f"Edges : [bold]{s['edges']}[/bold]")
    console.print(f"Is DAG: [bold]{s['is_dag']}[/bold]")


@graph_app.command("neighbors")
def graph_neighbors(
    entry_id: str = typer.Argument(...),
    depth: int = typer.Option(1, "--depth", "-d"),
) -> None:
    """Show entries related to *entry_id*."""
    _init()
    _rebuild_graph()
    from core import app_state
    from core.retrieval.retrieval import RetrievalEngine
    from core.storage.database import SessionLocal

    with SessionLocal() as db:
        engine = RetrievalEngine(db, app_state.graph)
        related = engine.get_related_entries(entry_id, depth=depth)

    table = Table("Short ID", "Title", "Type")
    for e in related:
        table.add_row(e.id[:8], e.title, e.entry_type.value)
    console.print(table)


@graph_app.command("export")
def graph_export(
    output: str = typer.Option("data/nodes", "--output", "-o", help="Output directory"),
) -> None:
    """Export all entries to YAML files."""
    _init()
    from pathlib import Path as P

    from core import app_state
    from agents.maintenance_agent.agent import MaintenanceAgent

    agent = MaintenanceAgent(app_state.graph)
    count = agent.export_to_yaml(P(output))
    console.print(f"[green]Exported {count} entries to {output}[/green]")


# ===========================================================================
# mem sub-commands
# ===========================================================================

mem_app = typer.Typer(help="Manage Mem-Graph session traces", no_args_is_help=True)
app.add_typer(mem_app, name="mem")


@mem_app.command("add")
def mem_add(
    content: str = typer.Argument(...),
    session: str = typer.Option("default", "--session"),
    tags: str = typer.Option("", "--tags"),
    success: bool = typer.Option(None, "--success/--failure"),
) -> None:
    """Record a memory trace."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    entry = mg.add(content, tags=tag_list, success=success)
    console.print(f"[green]Recorded:[/green] {entry.id[:8]}")


@mem_app.command("list")
def mem_list(
    session: str = typer.Option("default", "--session"),
) -> None:
    """List memory traces for a session."""
    from core.memory.memgraph import MemGraph

    mg = MemGraph(session)
    table = Table("Short ID", "Content", "Tags", "Success", "Promoted")
    for e in mg.list():
        table.add_row(
            e.id[:8],
            e.content[:60] + ("…" if len(e.content) > 60 else ""),
            ", ".join(e.tags),
            str(e.success) if e.success is not None else "—",
            "yes" if e.promoted else "no",
        )
    console.print(table)


@mem_app.command("promote")
def mem_promote(
    mem_id: str = typer.Argument(..., help="Memory trace ID"),
    session: str = typer.Option("default", "--session"),
    entry_type: str = typer.Option("memory", "--type", "-t"),
) -> None:
    """Promote a Mem-Graph trace into a full Know-Do Graph entry."""
    _init()
    from core import app_state
    from core.schemas.entry import EntryType
    from agents.maintenance_agent.agent import MaintenanceAgent

    agent = MaintenanceAgent(app_state.graph)
    entry = agent.promote_mem_entry(mem_id, session_id=session, entry_type=EntryType(entry_type))
    if entry:
        console.print(f"[green]Promoted to entry:[/green] {entry.title}  [dim]({entry.id})[/dim]")
    else:
        console.print(f"[red]Memory trace not found:[/red] {mem_id}")
        raise typer.Exit(1)


# ===========================================================================
# agent sub-commands
# ===========================================================================

agent_app = typer.Typer(help="LLM-driven graph management agent", no_args_is_help=True)
app.add_typer(agent_app, name="agent")


@agent_app.command("chat")
def agent_chat(
    message: str = typer.Argument(None, help="Single message (omit for interactive REPL)"),
    model: str = typer.Option(None, "--model", "-m", help="Override model (e.g. openai/glm-5.1)"),
    session: bool = typer.Option(True, "--session/--no-session", help="Keep conversation history"),
) -> None:
    """Chat with the graph agent.  Omit MESSAGE to start an interactive session."""
    import os

    _init()
    _rebuild_graph()

    if "OPENAI_API_KEY" not in os.environ:
        console.print("[red]OPENAI_API_KEY is not set.[/red]  Add it to your .env or environment.")
        raise typer.Exit(1)

    import json as _json

    from core import app_state
    from agents.graph_agent.agent import GraphAgent

    def _step_handler(event: str, data: dict) -> None:
        if event == "thinking":
            console.print(f"[dim]↻  iteration {data['iteration']} — calling model…[/dim]")
        elif event == "tool_call":
            args_preview = _json.dumps(data["args"], default=str, ensure_ascii=False)
            if len(args_preview) > 160:
                args_preview = args_preview[:160] + "…"
            console.print(f"  [cyan]→ {data['name']}[/cyan]  [dim]{args_preview}[/dim]")
        elif event == "tool_result":
            result_preview = _json.dumps(data["result"], default=str, ensure_ascii=False)
            if len(result_preview) > 240:
                result_preview = result_preview[:240] + "…"
            console.print(f"  [yellow]← {data['name']}[/yellow]  [dim]{result_preview}[/dim]")

    graph_agent = GraphAgent(app_state.graph, model=model, on_step=_step_handler)

    def _run(msg: str) -> None:
        reply = graph_agent.chat(msg)
        console.rule("[dim]Agent[/dim]")
        console.print(reply)
        console.rule()

    if message:
        _run(message)
        return

    # Interactive REPL
    from prompt_toolkit import PromptSession as _PS
    _session = _PS()
    console.print("[bold]Know-Do Graph Agent[/bold]  (type [dim]exit[/dim] or [dim]quit[/dim] to stop, [dim]reset[/dim] to clear history)")
    while True:
        try:
            user_input = _session.prompt("You: ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            console.print("[dim]Goodbye.[/dim]")
            break
        if user_input.strip().lower() == "reset":
            graph_agent.reset()
            console.print("[dim]Conversation history cleared.[/dim]")
            continue
        if not user_input.strip():
            continue
        _run(user_input)


@agent_app.command("run")
def agent_run(
    task: str = typer.Argument(..., help="Natural-language task for the agent to perform"),
    model: str = typer.Option(None, "--model", "-m"),
) -> None:
    """Run a one-shot agentic task and print the result."""
    import os

    _init()
    _rebuild_graph()

    if "OPENAI_API_KEY" not in os.environ:
        console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(1)

    from core import app_state
    from agents.graph_agent.agent import GraphAgent

    graph_agent = GraphAgent(app_state.graph, model=model)
    with console.status("[bold green]Agent running…[/bold green]"):
        reply = graph_agent.chat(task)
    console.rule("[dim]Agent result[/dim]")
    console.print(reply)
    console.rule()


# ===========================================================================
# review sub-commands
# ===========================================================================

review_app = typer.Typer(help="ReviewAgent — audit and clean the graph", no_args_is_help=True)
app.add_typer(review_app, name="review")


def _make_step_handler():
    import json as _json

    def _step_handler(event: str, data: dict) -> None:
        if event == "thinking":
            console.print(f"[dim]↻  iteration {data['iteration']}…[/dim]")
        elif event == "orchestrator_thinking":
            console.print(f"[dim bold magenta]◈  orchestrator iteration {data['iteration']}…[/dim bold magenta]")
        elif event == "route":
            console.print(f"[bold magenta]→  routing to:[/bold magenta] [cyan]{data['agent']}[/cyan]  [dim]{data.get('args', {})}[/dim]")
        elif event == "tool_call":
            args_preview = _json.dumps(data["args"], default=str, ensure_ascii=False)
            if len(args_preview) > 160:
                args_preview = args_preview[:160] + "…"
            console.print(f"  [cyan]→ {data['name']}[/cyan]  [dim]{args_preview}[/dim]")
        elif event == "tool_result":
            result_preview = _json.dumps(data["result"], default=str, ensure_ascii=False)
            if len(result_preview) > 240:
                result_preview = result_preview[:240] + "…"
            console.print(f"  [yellow]← {data['name']}[/yellow]  [dim]{result_preview}[/dim]")

    return _step_handler


@review_app.command("run")
def review_run(
    instructions: str = typer.Argument("", help="Optional focus for this review session"),
    batch_size: int = typer.Option(5, "--batch", "-b", help="Nodes to review per session"),
    model: str = typer.Option(None, "--model", "-m"),
) -> None:
    """Run one review session (sample nodes, inspect, fix, mark reviewed)."""
    import os

    _init()
    _rebuild_graph()

    if "OPENAI_API_KEY" not in os.environ:
        console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(1)

    from core import app_state
    from agents.review_agent.agent import ReviewAgent

    agent = ReviewAgent(app_state.graph, model=model, batch_size=batch_size, on_step=_make_step_handler())
    console.print(f"[bold]ReviewAgent[/bold]  batch={batch_size}" + (f"  focus: {instructions}" if instructions else ""))
    reply = agent.run_review(instructions=instructions)
    console.rule("[dim]Review summary[/dim]")
    console.print(reply)
    console.rule()


@review_app.command("chat")
def review_chat(
    message: str = typer.Argument(None, help="Single message (omit for interactive REPL)"),
    model: str = typer.Option(None, "--model", "-m"),
) -> None:
    """Chat interactively with the ReviewAgent."""
    import os

    _init()
    _rebuild_graph()

    if "OPENAI_API_KEY" not in os.environ:
        console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(1)

    from core import app_state
    from agents.review_agent.agent import ReviewAgent

    agent = ReviewAgent(app_state.graph, model=model, on_step=_make_step_handler())

    def _run(msg: str) -> None:
        reply = agent.chat(msg)
        console.rule("[dim]ReviewAgent[/dim]")
        console.print(reply)
        console.rule()

    if message:
        _run(message)
        return

    from prompt_toolkit import PromptSession as _PS
    _session = _PS()
    console.print("[bold]Know-Do Graph ReviewAgent[/bold]  (type [dim]exit[/dim] to stop)")
    while True:
        try:
            user_input = _session.prompt("You: ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            console.print("[dim]Goodbye.[/dim]")
            break
        if not user_input.strip():
            continue
        _run(user_input)


@review_app.command("stats")
def review_stats() -> None:
    """Show review coverage statistics across all nodes."""
    _init()
    from core.storage.database import SessionLocal
    from core.storage.models import EntryModel
    import json as _json

    with SessionLocal() as db:
        rows = db.query(EntryModel).all()

    total = len(rows)
    reviewed = 0
    unreviewed_titles = []
    table = Table("Title", "Type", "Reviews", "Modifications", "Last Reviewed")
    for row in rows:
        meta = _json.loads(row.metadata_json or "{}")
        rc = meta.get("review_count", 0)
        mc = meta.get("modify_count", 0)
        lr = meta.get("last_reviewed_at") or "—"
        if isinstance(lr, str) and len(lr) > 19:
            lr = lr[:19]
        if rc > 0:
            reviewed += 1
        else:
            unreviewed_titles.append(row.title)
        table.add_row(row.title, row.entry_type, str(rc), str(mc), lr)

    console.print(table)
    console.print(f"\n[bold]Coverage:[/bold] {reviewed}/{total} nodes reviewed "
                  f"([green]{100*reviewed//total if total else 0}%[/green])")


# ===========================================================================
# orchestrate command
# ===========================================================================

orchestrate_app = typer.Typer(help="Orchestrator — routes tasks to the right agent", no_args_is_help=True)
app.add_typer(orchestrate_app, name="orchestrate")


@orchestrate_app.command("chat")
def orchestrate_chat(
    message: str = typer.Argument(None, help="Single message (omit for interactive REPL)"),
    model: str = typer.Option(None, "--model", "-m"),
) -> None:
    """Route a request through the orchestrator to the appropriate agent(s)."""
    import os

    _init()
    _rebuild_graph()

    if "OPENAI_API_KEY" not in os.environ:
        console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(1)

    from core import app_state
    from agents.orchestrator.agent import OrchestratorAgent

    orchestrator = OrchestratorAgent(app_state.graph, model=model, on_step=_make_step_handler())

    def _run(msg: str) -> None:
        reply = orchestrator.chat(msg)
        console.rule("[dim]Result[/dim]")
        console.print(reply)
        console.rule()

    if message:
        _run(message)
        return

    from prompt_toolkit import PromptSession as _PS
    _session = _PS()
    console.print(
        "[bold]Know-Do Graph Orchestrator[/bold]  "
        "(type [dim]exit[/dim] to stop, [dim]reset[/dim] to clear history)"
    )
    while True:
        try:
            user_input = _session.prompt("You: ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            console.print("[dim]Goodbye.[/dim]")
            break
        if user_input.strip().lower() == "reset":
            orchestrator.reset()
            console.print("[dim]History cleared.[/dim]")
            continue
        if not user_input.strip():
            continue
        _run(user_input)


@orchestrate_app.command("run")
def orchestrate_run(
    task: str = typer.Argument(..., help="Natural-language task"),
    model: str = typer.Option(None, "--model", "-m"),
) -> None:
    """Run a one-shot task through the orchestrator."""
    import os

    _init()
    _rebuild_graph()

    if "OPENAI_API_KEY" not in os.environ:
        console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(1)

    from core import app_state
    from agents.orchestrator.agent import OrchestratorAgent

    orchestrator = OrchestratorAgent(app_state.graph, model=model, on_step=_make_step_handler())
    reply = orchestrator.chat(task)
    console.rule("[dim]Result[/dim]")
    console.print(reply)
    console.rule()


# ===========================================================================
# embeddings sub-commands
# ===========================================================================

embeddings_app = typer.Typer(help="Manage vector embeddings for hybrid retrieval", no_args_is_help=True)
app.add_typer(embeddings_app, name="embeddings")


@embeddings_app.command("backfill")
def embeddings_backfill(
    batch: int = typer.Option(32, "--batch", "-b", help="Embedding batch size"),
    force: bool = typer.Option(False, "--force", help="Re-embed even if hash matches"),
) -> None:
    """Compute and store embeddings for every entry that lacks one (or all, with --force)."""
    _init()
    from core.retrieval import vector_store
    from core.retrieval.embedder import build_embedding_text, get_default_embedder, text_hash
    from core.storage.database import SessionLocal
    from core.storage.models import EntryModel

    embedder = get_default_embedder()
    if not embedder.available:
        console.print(
            "[red]No embedder available.[/red] Install with: "
            "[cyan]pip install 'know-do-graph[embeddings]'[/cyan]"
        )
        raise typer.Exit(1)

    with SessionLocal() as db:
        rows = db.query(EntryModel).all()
        pending: list[tuple[EntryModel, str, str]] = []
        for row in rows:
            d = row.to_dict()
            text_in = build_embedding_text(
                title=d["title"], aliases=d["aliases"], tags=d["tags"], content=d["content"]
            )
            new_hash = text_hash(text_in)
            if not force and row.embedding_hash == new_hash:
                continue
            pending.append((row, text_in, new_hash))

        total = len(pending)
        console.print(f"[bold]{total}[/bold] entries to embed (of {len(rows)} total).")
        if total == 0:
            return

        done = 0
        for i in range(0, total, batch):
            chunk = pending[i:i + batch]
            vecs = embedder.embed([t for _, t, _ in chunk])
            for (row, _t, h), vec in zip(chunk, vecs):
                if not vec:
                    continue
                if vector_store.upsert(db, row.id, vec):
                    row.embedding_hash = h
                    done += 1
            db.commit()
            console.print(f"  [dim]…{min(i + len(chunk), total)}/{total}[/dim]")

        index_count = vector_store.count(db)
        console.print(
            f"[green]Embedded {done} entries.[/green] "
            f"Vector index now holds {index_count if index_count is not None else '?'} rows."
        )


# ===========================================================================
# db (merge / dedup across multiple SQLite snapshots)
# ===========================================================================

db_app = typer.Typer(help="Cross-environment DB maintenance (merge, dedup)", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("merge")
def db_merge(
    other: Path = typer.Argument(..., help="Path to the other SQLite DB to merge into this one"),
    prefer: str = typer.Option(
        "newer", "--prefer",
        help="Conflict policy on id collision: newer | local | remote",
    ),
    no_resolve: bool = typer.Option(False, "--no-resolve", help="Skip wikilink re-resolution"),
    notify: bool = typer.Option(
        False, "--notify",
        help="POST /graph/reload to a running server after merge (KDG_API_URL or --api-url)",
    ),
    api_url: str = typer.Option(
        None, "--api-url", help="Base URL of the running API (default: $KDG_API_URL)",
    ),
) -> None:
    """Additively merge entries+edges from another know-do-graph SQLite file.

    UUID ids make union safe; slug collisions are auto-suffixed by the writer.
    Run [bold]python main.py db dedup[/bold] afterwards to consolidate duplicates.
    """
    _init()
    from core.sync.db_merge import merge_database

    report = merge_database(other, prefer=prefer, resolve_wikilinks=not no_resolve)

    console.print(f"\n[bold green]Merge complete[/bold green] (from [cyan]{other}[/cyan])")
    console.print(f"  entries  inserted={report.entries_inserted}  updated={report.entries_updated}  skipped={report.entries_skipped}")
    console.print(f"  edges    inserted={report.edges_inserted}    skipped={report.edges_skipped}")
    console.print(f"  wikilinks_resolved={report.wikilinks_resolved}")
    if report.slug_renames:
        console.print(f"  [yellow]slug renames ({len(report.slug_renames)}):[/yellow]")
        for old, new in report.slug_renames[:10]:
            console.print(f"    {old} \u2192 {new}")
        if len(report.slug_renames) > 10:
            console.print(f"    \u2026 and {len(report.slug_renames) - 10} more")

    if notify:
        import os, httpx
        url = (api_url or os.environ.get("KDG_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        try:
            r = httpx.post(f"{url}/graph/reload", timeout=10.0)
            r.raise_for_status()
            console.print(f"  [dim]reloaded running server at {url}: {r.json()}[/dim]")
        except Exception as exc:
            console.print(f"  [red]server reload failed:[/red] {exc}")


@db_app.command("dedup")
def db_dedup(
    apply: bool = typer.Option(False, "--apply", help="Actually merge (default: dry-run report)"),
    similar: float = typer.Option(
        0.0, "--similar",
        help="Also list embedding-similar pairs with cosine \u2265 THRESHOLD (e.g. 0.92). "
             "Similar pairs are reported only \u2014 review before merging.",
    ),
) -> None:
    """Consolidate exact-duplicate entries; report near-duplicates by embedding similarity."""
    _init()
    from core.sync.db_merge import dedup_exact, find_similar_groups

    report = dedup_exact(dry_run=not apply)
    mode = "APPLIED" if apply else "DRY-RUN"
    console.print(f"\n[bold]{mode} exact dedup:[/bold] {report.exact_groups} duplicate groups, {len(report.candidates)} pairs")
    for c in report.candidates[:20]:
        marker = "[green]merged[/green]" if apply else "[yellow]would merge[/yellow]"
        console.print(f"  {marker}  {c['duplicate_slug']} \u2192 {c['primary_slug']}  ({c['reason']})")
    if len(report.candidates) > 20:
        console.print(f"  \u2026 and {len(report.candidates) - 20} more")
    if apply:
        console.print(f"  [bold green]merged_pairs={report.merged_pairs}[/bold green]")

    if similar > 0:
        sims = find_similar_groups(threshold=similar)
        console.print(f"\n[bold]Near-duplicate candidates[/bold] (cosine \u2265 {similar}): {len(sims)} pairs")
        for s in sims[:30]:
            console.print(f"  sim={s['similarity']:.3f}  {s['a_id'][:8]}\u2026  \u2194  {s['b_id'][:8]}\u2026")
        if len(sims) > 30:
            console.print(f"  \u2026 and {len(sims) - 30} more")
        console.print(
            "[dim]Review and merge with[/dim] "
            "[cyan]python main.py agent run \"merge_entries(primary_id=\u2026, duplicate_id=\u2026)\"[/cyan]"
        )


@db_app.command("reload")
def db_reload(
    api_url: str = typer.Option(None, "--api-url", help="Default: $KDG_API_URL or http://127.0.0.1:8000"),
) -> None:
    """Tell a running API server to rebuild its in-memory graph from the DB."""
    import os, httpx
    url = (api_url or os.environ.get("KDG_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    try:
        r = httpx.post(f"{url}/graph/reload", timeout=10.0)
        r.raise_for_status()
        console.print(f"[green]reloaded:[/green] {r.json()}")
    except Exception as exc:
        console.print(f"[red]reload failed:[/red] {exc}")
        raise typer.Exit(1)


# ===========================================================================
# serve
# ===========================================================================

@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the FastAPI HTTP server."""
    import uvicorn

    base = f"http://{host}:{port}"
    console.print(f"\n[bold green]Know-Do Graph API[/bold green] → [link={base}]{base}[/link]")
    console.print(f"  [cyan]Graph UI  [/cyan] → [link={base}/ui]{base}/ui[/link]")
    console.print(f"  [cyan]Swagger   [/cyan] → [link={base}/docs]{base}/docs[/link]\n")

    # `timeout_graceful_shutdown` ensures Ctrl+C doesn't hang on long-lived
    # SSE connections (Windows in particular). Combined with the per-second
    # disconnect-check in /graph/events, shutdown completes in <2 s.
    config = uvicorn.Config(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        timeout_graceful_shutdown=2,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    app()
