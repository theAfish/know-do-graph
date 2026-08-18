# Roadmap

This roadmap captures product direction and longer-term themes. The actionable
engineering checklist remains in [`todo.md`](../todo.md).

## Product Direction

Know-Do Graph aims to become a durable memory substrate for agents: a place
where reusable capabilities, procedures, constraints, and execution experience
can accumulate without turning every run log into planner context.

The core loop is:

```text
capture -> structure -> retrieve -> execute -> verify -> improve
```

## Near-Term Themes

- Stronger retrieval quality around aliases, slugs, wikilinks, and fallback
  behavior when embeddings are unavailable.
- Safer delete and merge workflows that keep storage, vectors, in-memory graph
  state, and emitted events synchronized.
- Better remote-sync parsing, retry metadata, and due-check behavior.
- Packaging smoke tests that install built wheels in clean environments.

## Later Themes

- Richer review workflows for human-in-the-loop approval.
- Background embedding refresh and larger graph indexing strategies.
- Optional graph-database/vector-database backends behind the same public
  contracts.
- More frontend contract tests and accessibility checks.
- Better import/export pathways for team knowledge bases.

## Current Backlog

See [`todo.md`](../todo.md) for the active priority list.
