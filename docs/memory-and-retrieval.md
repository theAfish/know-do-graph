# Memory and Retrieval

Know-Do Graph separates raw operational memory from stable reusable knowledge.
Raw traces can be stored quickly, connected to other traces, reviewed later, and
promoted or distilled into normal graph entries.

## Memory Sessions

Memory traces are stored in the same SQLite database as graph entries with
`entry_type="memory"`. Session IDs and ingestion metadata live in entry
metadata.

CLI:

```bash
know-do-graph mem add "MACE worked for bulk Fe relaxation" \
  --session my-session --tags "success,atomistic"

know-do-graph mem list --session my-session
know-do-graph mem promote <mem-id> --session my-session --type capability
```

Python:

```python
from core.memory.memgraph import MemGraph

mg = MemGraph("custom-session")
mg.add("Summarised finding from the session.", tags=["finding"], success=True)
```

## Framework Adapters

OpenAI-style messages:

```python
mg.ingest_openai_messages(
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
    tags=["openai"],
)
```

LangChain messages:

```python
mg.ingest_langchain_messages(chain.memory.chat_memory.messages)
```

AutoGen conversations:

```python
mg.ingest_autogen_messages(groupchat.messages, tags=["autogen"])
```

Files:

```python
from pathlib import Path

mg.ingest_file(Path("session_export.json"))
mg.ingest_text_file(Path("agent.log"), chunk_by="paragraph")
```

Accepted JSON shapes are a message array, an object containing `messages`,
`history`, `conversation`, or `turns`, or any other object stored as one trace.

## Promotion

Promote a stable trace into a normal graph entry:

```bash
curl -X POST http://localhost:8000/mem/my-session/<mem-id>/promote \
  -H "Content-Type: application/json" \
  -d '{"entry_type": "capability", "tags": ["promoted"]}'
```

Promotion path:

```text
raw memory trace -> linked note -> refined capability entry -> validated knowledge
```

## Progressive Retrieval

The graph uses four skill levels so planner context stays compact:

| Level | Stored as | Purpose |
| --- | --- | --- |
| L1 Capability | `capability` or `workflow` | Reusable high-level ability. |
| L2 Procedure | `procedure` | Executable decomposition. |
| L3 Heuristic | `heuristic` | Conditional guidance or rule of thumb. |
| L4 Constraint | `constraint` | Known limitation, failure mode, or risk. |

Typed edges connect the levels:

- `decomposes_to`: L1 -> L2.
- `heuristic_for`: L3 -> L1/L2.
- `constraint_on`: L4 -> L1/L2.

Planner flow:

```text
goal -> plan(goal)
     -> pick candidate skill
     -> execute
     -> retrieve heuristics/constraints when uncertainty or verifier feedback appears
```

Python:

```python
with KnowDoGraph("data/my_agent.db") as graph:
    candidates = graph.plan("relax this crystal")
    heuristics = graph.heuristics(candidates[0].id)
    constraints = graph.constraints(candidates[0].id)
    expanded = graph.expand(candidates[0].id, stages=["heuristics", "constraints"])
```

HTTP:

```bash
curl "http://127.0.0.1:8000/retrieve/plan?goal=relax%20this%20crystal&k=5"
curl "http://127.0.0.1:8000/retrieve/heuristics?skill=ase-relaxation&k=5"
curl "http://127.0.0.1:8000/retrieve/constraints?skill=ase-relaxation&k=5"
```

GraphAgent exposes `retrieve_plan`, `retrieve_heuristics`,
`retrieve_constraints`, `create_heuristic`, `create_constraint`, and
`decompose_capability` so operational knowledge is attached as L3/L4 entries
instead of being dumped into capability content.

## Review Distillation

The review agent can distill raw memory into the L1-L4 hierarchy:

- L1/L2 become unverified capability/procedure nodes.
- L3/L4 become heuristic/constraint nodes linked to existing L1/L2 nodes.
- Noise is deleted.
- Ambiguous traces can be skipped.

See [Agent Behavior](agents.md#memory-review) for review-agent usage.
