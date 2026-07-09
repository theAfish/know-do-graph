# API Reference

Start the server with:

```bash
know-do-graph serve
```

Interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

## Entries

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/entries/` | List entries with pagination metadata. |
| `GET` | `/entries/search?q=...&tags=...&entry_type=...` | Search entries. |
| `GET` | `/entries/{id}` | Get entry by ID, slug, or alias. |
| `POST` | `/entries/` | Create an entry. |
| `PUT` | `/entries/{id}` | Update an entry. |
| `DELETE` | `/entries/{id}` | Delete an entry and incident edges. |
| `GET` | `/entries/{id}/related?depth=1&relation=...` | Traverse related entries. |
| `GET` | `/entries/{id}/edges` | List edges incident to an entry. |
| `GET` | `/entries/{id}/download` | Download script content for script entries. |
| `POST` | `/entries/{id}/feedback` | Record verification feedback. |

Create an entry:

```bash
curl -X POST http://127.0.0.1:8000/entries/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "ASE Relaxation",
    "entry_type": "procedure",
    "content": "Attach a calculator and run an ASE optimizer.",
    "tags": ["ase", "atomistic"]
  }'
```

Search:

```bash
curl "http://127.0.0.1:8000/entries/search?q=relaxation&limit=5&include_scores=true"
```

## Graph

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/graph/stats` | Node and edge counts. |
| `GET` | `/graph/full` | Full graph payload used by the UI. |
| `GET` | `/graph/neighbors/{id}?direction=both` | Immediate neighbors. |
| `GET` | `/graph/subgraph/{id}?depth=2` | Ego-subgraph around an entry. |
| `GET` | `/graph/path?source=...&target=...` | Simple paths between two entries. |
| `GET` | `/graph/events` | Server-sent graph refresh events. |

## Assets and Scripts

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/entries/{id}/assets` | List assets attached to an entry. |
| `GET` | `/entries/{id}/assets/{folder}/{filename}` | Fetch an asset. |
| `GET` | `/entries/{id}/scripts/{filename}` | Download a legacy script asset. |

## Memory

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/mem/sessions` | List memory session IDs. |
| `GET` | `/mem/{session}` | List traces for a session. |
| `POST` | `/mem/{session}/add` | Add a plain-text trace. |
| `POST` | `/mem/{session}/ingest/openai` | Ingest OpenAI-style messages. |
| `POST` | `/mem/{session}/ingest/langchain` | Ingest LangChain messages. |
| `POST` | `/mem/{session}/ingest/autogen` | Ingest AutoGen conversation data. |
| `POST` | `/mem/{session}/ingest/raw` | Ingest arbitrary JSON. |
| `DELETE` | `/mem/{session}/{mem_id}` | Delete a memory trace. |
| `POST` | `/mem/{session}/{mem_id}/promote` | Promote a trace into a graph entry. |

Promote a trace:

```bash
curl -X POST http://127.0.0.1:8000/mem/my-session/<mem-id>/promote \
  -H "Content-Type: application/json" \
  -d '{"entry_type": "capability", "tags": ["promoted"]}'
```

## Progressive Retrieval

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/retrieve/plan?goal=...&k=5&include_l2=true` | L1/L2 planning context. |
| `GET` | `/retrieve/heuristics?skill=<id-or-slug>&k=5` | L3 heuristics for a skill. |
| `GET` | `/retrieve/constraints?skill=<id-or-slug>&k=5` | L4 constraints for a skill. |
| `GET` | `/retrieve/expand/{skill}?stages=heuristics,constraints,decomposition` | Bundle context for verifier/debug loops. |

Recommended flow:

```text
goal -> /retrieve/plan
     -> choose skill and execute
     -> on uncertainty or verifier feedback
     -> /retrieve/heuristics + /retrieve/constraints
     -> refine or debug
```

## Remote Agent Interface

The `/remote` interface is intended for agents on other machines or in other
runtimes. It uses plain HTTP and returns an instruction sheet from `/` or
`/remote`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Plain-text instruction sheet. |
| `GET` | `/remote` | Same instruction sheet. |
| `POST` | `/remote/chat` | Read-only chat with the orchestrator. |
| `GET` | `/remote/search` | Search entries. |
| `GET` | `/remote/graph` | Stats plus full node/edge dump. |
| `GET` | `/remote/entry/{id}` | Entry with attached L3/L4 counts. |
| `GET` | `/remote/entry/{id}/heuristics` | Attached heuristics. |
| `GET` | `/remote/entry/{id}/constraints` | Attached constraints. |
| `GET` | `/remote/entry/{id}/related` | Related entries via BFS. |
| `POST` | `/remote/feedback` | Free-form feedback trace. |
| `DELETE` | `/remote/session/{id}` | Clear chat history. |
| `POST` | `/remote/submit` | Submit raw knowledge to the inbox. |
| `GET` | `/remote/inbox` | List pending inbox submissions. |
| `POST` | `/remote/distill` | Distill inbox items into graph nodes. |

One-shot chat:

```bash
curl -X POST http://127.0.0.1:8000/remote/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What entries exist in the graph?"}'
```

Feedback:

```bash
curl -X POST http://127.0.0.1:8000/entries/<id-or-slug>/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "verdict": "works",
    "note": "Ran on H2O, energy converged in 12 steps",
    "agent_id": "runner-1"
  }'
```

Inbox distillation:

```bash
curl -X POST http://127.0.0.1:8000/remote/submit \
  -H "Content-Type: application/json" \
  -d '{"title": "ASE session", "content": "Reusable finding...", "agent_id": "agent-1"}'

curl -X POST http://127.0.0.1:8000/remote/distill \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```
