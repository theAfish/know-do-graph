# Know-Do Graph

A wiki-native, agent-oriented infrastructure for executable knowledge,
operational memory, and capability discovery.

Entries are wiki-style pages that agents can read, traverse, update, and
validate. The graph emerges from typed edges plus `[[wikilink]]` references
between entries.

## Quick Start

Install from PyPI:

```bash
pip install know-do-graph

# Create an empty ./data/know_do_graph.db
know-do-graph init

# Or start from the database bundled with the package
know-do-graph init --starter

know-do-graph serve
```

The server prints the local URLs:

```text
Know-Do Graph API  ->  http://127.0.0.1:8000
  Graph UI         ->  http://127.0.0.1:8000/ui
  Swagger          ->  http://127.0.0.1:8000/docs
```

Set `KDG_DB_PATH` to use a different database path:

```bash
KDG_DB_PATH=./my-data/my-memory.db
```

Relative paths are resolved from the current working directory.

## Optional Embeddings

The default install does not download a local embedding model stack. Keyword
search works out of the box; `hybrid` and `semantic` retrieval fall back
gracefully when no embedding provider is enabled.

Local embeddings:

```bash
pip install "know-do-graph[local-embeddings]"
export KDG_EMBED_PROVIDER=local
export KDG_EMBED_MODEL="sentence-transformers/all-MiniLM-L6-v2"
```

OpenAI-compatible embeddings:

```bash
export KDG_EMBED_PROVIDER=openai
export KDG_EMBED_MODEL="text-embedding-3-small"
export KDG_EMBED_DIM=384
export KDG_EMBED_API_KEY="..."                      # or OPENAI_API_KEY
export KDG_EMBED_BASE_URL="https://example.com/v1"  # optional
```

`KDG_EMBED_DIM` defaults to `384`, matching the bundled SQLite vector table.

## Python API

Use the high-level client directly inside an agent process:

```python
from know_do_graph import EdgeRelation, EntryType, KnowDoGraph

with KnowDoGraph("data/my_agent.db") as graph:
    skill = graph.add(
        "Relax an atomic structure",
        entry_type=EntryType.capability,
        content="Choose a calculator, then run [[ASE Relaxation]].",
        tags=["atomistic"],
    )
    procedure = graph.add(
        "ASE Relaxation",
        entry_type=EntryType.procedure,
        content="Attach a calculator and run an ASE optimizer.",
    )
    graph.connect(skill.id, procedure.id, relation=EdgeRelation.decomposes_to)

    planner_context = graph.plan("relax this crystal")
    execution_context = graph.expand(skill.slug, stages=["decomposition"])
```

Main client methods include `add`, `get`, `list`, `search`, `update`, `delete`,
`connect`, `related`, `plan`, `heuristics`, `constraints`, `expand`, and
`memory`. IDs, slugs, and aliases are accepted anywhere an entry identifier is
required.

### Disabled entries and custom graph types

Set `metadata.disabled` when creating an entry, or call `set_disabled()` to
hide an existing entry without deleting its content or edges. Disabled entries
are excluded from normal retrieval and graph traversal; pass `disabled=True`
to `list()` or `search()` to audit them, then re-enable the entry to restore
its persisted connections.

The shared storage schema also supports custom graph type labels such as
`category` or `parameter`. Those labels remain intact, while progressive
L1--L4 retrieval is available only for Know-Do Graph type semantics.

## Chat API

Configure an OpenAI or OpenAI-compatible provider:

```bash
export OPENAI_API_KEY="..."
export OPENAI_API_BASE="https://your-provider.example/v1"  # optional
export GRAPH_AGENT_MODEL="qwen-plus"                       # optional
```

Read-only Q&A:

```python
from know_do_graph import KnowDoGraph

with KnowDoGraph("data/my_agent.db") as graph:
    chat = graph.chat(read_only=True)
    print(chat.send("Which skills can construct a material interface?"))
```

Graph-editing agent:

```python
with KnowDoGraph("data/my_agent.db") as graph:
    chat = graph.chat()
    reply = chat.send(
        "Add a reusable capability for validating atomistic relaxations. "
        "Search for duplicates and connect it to relevant procedures."
    )
    print(reply)
```

Review agent:

```python
with KnowDoGraph("data/my_agent.db") as graph:
    reviewer = graph.chat(agent="reviewer", batch_size=3)
    print(reviewer.review("Focus on duplicate titles and inconsistent tags."))
```

## CLI Examples

```bash
# Add an entry
know-do-graph entry add "My Tool" \
  --content "Useful for [[ASE Relaxation]]." \
  --type tool \
  --tags "python,simulation"

# Search and inspect
know-do-graph entry search "relaxation"
know-do-graph entry show ase-relaxation

# Graph inspection
know-do-graph graph stats
know-do-graph graph neighbors <entry-id> --depth 2

# Memory traces
know-do-graph mem add "MACE worked for bulk Fe relaxation" \
  --session my-session --tags "success,atomistic"
know-do-graph mem promote <mem-id> --session my-session --type capability
```

## REST Examples

Interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

```bash
curl http://127.0.0.1:8000/graph/full
curl "http://127.0.0.1:8000/entries/search?q=relaxation&limit=5"

curl -X POST http://127.0.0.1:8000/entries/ \
  -H "Content-Type: application/json" \
  -d '{"title":"ASE Relaxation","entry_type":"procedure","tags":["ase"]}'
```

## From Source

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

bash install.sh
python examples/example_entries.py
python main.py serve
```

Frontend hot reload:

```bash
# Terminal 1
python main.py serve

# Terminal 2
cd frontend && npm run dev
```

## Documentation

- [Architecture](docs/architecture.md)
- [API Reference](docs/api.md)
- [Agent Behavior](docs/agents.md)
- [Memory and Retrieval](docs/memory-and-retrieval.md)
- [Module Map](docs/module-map.md)
- [Roadmap](docs/roadmap.md)
- [Release Checklist](docs/release-checklist.md)
- [Contributing](CONTRIBUTING.md)

## Entry Format

Entries are wiki-style documents. Internal `[[wikilinks]]` can be resolved into
graph edges during extraction or maintenance.

```markdown
# ASE Relaxation

Geometry optimisation workflow using [[ASE]].

## Prerequisites
- [[ASE]]
- A [[MACE Calculator]] or other calculator
```

Common entry types are `capability`, `procedure`, `workflow`, `tool`,
`repository`, `environment`, `dependency`, `data`, `analytical`, `memory`,
`heuristic`, `constraint`, and `generic`.
