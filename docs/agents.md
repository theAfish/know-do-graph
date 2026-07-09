# Agents

Know-Do Graph provides OpenAI-compatible agent wrappers for graph editing,
review, orchestration, and remote read-only access.

## Configuration

```bash
export OPENAI_API_KEY="..."
export OPENAI_API_BASE="https://your-provider.example/v1"  # optional
export GRAPH_AGENT_MODEL="qwen-plus"                       # optional
export REVIEW_AGENT_MODEL="qwen-plus"                      # optional
```

Credentials can also be passed as `api_key=` and `base_url=` when constructing
chat objects.

## GraphAgent

`GraphAgent` uses tool calls to search, retrieve, create, update, link, and
maintain graph entries.

```python
from know_do_graph import KnowDoGraph

with KnowDoGraph("data/my_agent.db") as graph:
    chat = graph.chat()
    print(chat.send("Create a capability for validating relaxations."))
```

Read-only mode exposes only query tools:

```python
with KnowDoGraph("data/my_agent.db") as graph:
    chat = graph.chat(read_only=True)
    print(chat.send("What constraints apply to ASE relaxation?"))
```

Network-capable tools such as `fetch_url` and `web_search` are hidden unless:

```bash
export KDG_ENABLE_NETWORK_TOOLS=1
```

## Tooling Architecture

Agent tools are exposed through registries under each agent's `tools/registry.py`
module. The registry owns:

- OpenAI function/tool schema lists.
- Dispatch from tool name to implementation.
- Mutating tool classification.
- Network-tool gating.
- JSON argument parsing.
- Normalized dict results with `ok: true` or `ok: false`.

This keeps OpenAI schema definitions separate from tool implementation modules.

## ReviewAgent

`ReviewAgent` incrementally audits graph quality. It samples candidates,
inspects local context, and performs conservative fixes.

```python
with KnowDoGraph("data/my_agent.db") as graph:
    reviewer = graph.chat(agent="reviewer", batch_size=5)
    print(reviewer.review("Focus on duplicate titles and inconsistent tags."))
```

Structured review:

```python
from know_do_graph import EntryType, ReviewPolicy, VerificationStatus

policy = ReviewPolicy(
    exclude_types={EntryType.memory},
    protected_statuses={
        VerificationStatus.peer_reviewed,
        VerificationStatus.community_tested,
    },
    assignable_statuses={
        VerificationStatus.unverified,
        VerificationStatus.self_tested,
        VerificationStatus.bugged,
        VerificationStatus.deprecated,
    },
    allowed_actions={"modify", "delete", "distill", "merge_similar", "link"},
)

with KnowDoGraph("data/my_agent.db") as graph:
    reviewer = graph.chat(
        agent="reviewer",
        policy=policy,
        strategy="auto",
        batch_size=10,
        on_status=lambda status: print(status["progress"]),
    )
    result = reviewer.review_nodes()
```

Policy checks run inside every review mutation tool. Protected nodes may still
be inspected and linked, but cannot be changed, deleted, distilled, merged, or
marked reviewed.

## Memory Review

Memory review samples unpromoted `memory` nodes and classifies each trace as:

- `L1`: capability or workflow.
- `L2`: procedure.
- `L3`: heuristic.
- `L4`: constraint.
- `noise`: delete as non-reusable.
- `skip`: leave for human context.

```python
with KnowDoGraph("data/my_agent.db") as graph:
    reviewer = graph.chat(agent="reviewer", batch_size=10)
    result = reviewer.review_memory(session_id="matcreator")
```

Applications can also use the polling API:

```bash
curl -X POST http://127.0.0.1:8000/agent/review/memory \
  -H "Content-Type: application/json" \
  -d '{"session_id":"matcreator","batch_size":10}'

curl http://127.0.0.1:8000/agent/review/memory/<job-id>
```

## Orchestrator

The orchestrator routes broader graph-improvement tasks across available agent
capabilities.

```python
with KnowDoGraph("data/my_agent.db") as graph:
    orchestrator = graph.chat(agent="orchestrator")
    print(orchestrator.send("Improve weak coverage around phonon workflows."))
```

## Remote Agents

Agents outside the Python process can use `/remote`. See
[API Reference](api.md#remote-agent-interface) for endpoint details.

Start the server for LAN access:

```bash
python main.py serve --host 0.0.0.0 --port 8000
```

## Web Access Tools

| Tool | How it works | When to use |
| --- | --- | --- |
| `web_search` | DuckDuckGo search API, returns titles and snippets. | Discovering URLs and broad topic research. |
| `fetch_url` | HTTP GET via `httpx` or stdlib fallback. | Reading a specific URL the user provides. |

Both tools require `KDG_ENABLE_NETWORK_TOOLS=1`.
