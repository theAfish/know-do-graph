# Know-Do Graph — TODO

> A wiki-native, agent-oriented infrastructure for executable knowledge, operational memory, and capability discovery.

## Vision

Know-Do Graph is a wiki-native infrastructure for executable knowledge.
Rather than enforcing a unified execution runtime, the project focuses on organizing capabilities, workflows, dependencies, operational knowledge, and memory into interconnected knowledge entries that agents can discover, traverse, reconstruct, and evolve over time.

The project should behave less like a rigid database and more like a continuously evolving operational wiki for agents.

Entries are the primary object.
Graphs, edges, and semantic relations are secondary structures extracted from interconnected entries.

The long-term direction is to couple:

* **Know-Do Graph** — structured executable knowledge and capability relations
* **Mem-Graph** — shallow memory traces extracted from sessions and interactions

Mem-Graph nodes may later be refined, merged, distilled, and promoted into deeper long-term Know-Do Graph structures.

---

# Phase 0 — Core Foundations

Establish a lightweight but extensible foundation before large-scale graph construction.

## Initial Technical Stack

### Core Language

* Python 3.11+

### Storage

Start simple and evolvable:

* SQLite / DuckDB for structured storage
* JSON / YAML node definitions
* Optional vector indexing later

Avoid early commitment to heavyweight graph databases unless scaling truly requires it.

### Suggested Libraries

* pydantic — schema validation
* networkx — early graph experimentation
* fastapi — external API layer
* typer — CLI tooling
* sqlalchemy — storage abstraction
* rich — debugging and graph inspection

### Repository Structure

```text
/core
    graph/
    schemas/
    retrieval/
    extraction/
    memory/

/data
    nodes/
    edges/
    metadata/

/agents
    extraction_agent/
    maintenance_agent/

/api

/examples
```

---

# Phase 1 — Wiki-Native Know-Do Graph Construction

The first milestone is not creating new skills from scratch.
The goal is to organize and connect already-existing capabilities distributed across the internet.

## Core Objectives

Build a document-centric graph where entries may represent:

* capabilities
* executable procedures
* workflows
* tools
* repositories
* environments
* dependencies
* data affordances
* analytical operations

Edges should represent relations such as:

* dependency
* compatibility
* transformation
* execution pathway
* prerequisite
* replacement / alternative implementation
* provenance

## Entry Structure

Entries should remain flexible and semi-structured rather than constrained to rigid schemas.

Each entry should resemble a wiki page or operational note that agents can directly read and traverse.

An entry may contain:

* descriptions
* workflows
* dependency information
* runtime assumptions
* implementation notes
* references
* caveats
* compatibility observations
* execution examples
* external repositories
* related entries
* operational memories

Internal references should act as semantic graph connections.

Example:

```text
[[ASE relaxation]]
[[MACE calculator]]
[[phonon workflow]]
```

These internal hyperlinks should automatically create traversable graph relations.

The graph should therefore emerge naturally from interconnected operational documents.

## Semantic Relations

The system should support both explicit and implicit relations.

Potential relation types:

* dependency
* compatible_with
* alternative_to
* related_workflow
* generated_from
* memory_of
* refinement_of
* derived_from
* warning_about
* cited_by

However, early versions should avoid over-constraining edge semantics.
Simple hyperlink-style references are sufficient initially.

## Metadata and Evolution

Every entry should support extensible metadata fields from the beginning.

Examples:

* timestamp
* source provenance
* extraction method
* refinement status
* usage count
* success / failure statistics
* trust score
* verification status
* related environments
* runtime requirements

Not all metadata must be exposed directly to external agents.
Some fields primarily exist to support long-term graph evolution, retrieval ranking, refinement, and maintenance.

The architecture should allow future node hierarchy and refinement systems without requiring large structural redesigns.

## External Knowledge and Capability Linking

Instead of copying external projects into the repository, maintain structured links to:

* GitHub repositories
* MCP servers
* Python packages
* CLI tools
* workflows
* notebooks
* HuggingFace Spaces
* blog implementations
* paper repositories

The graph should function as a capability aggregation and operational routing layer rather than a monolithic tool collection.

The system should preserve provenance and external references instead of absorbing everything into a closed ecosystem.

---

# Phase 2 — Knowledge and Skill Extraction Pipeline

The project should support semi-automatic capability extraction from heterogeneous sources.

## Sources

Potential extraction targets include:

* research papers
* technical blogs
* documentation
* GitHub repositories
* notebooks
* tutorials
* benchmark implementations
* databases
* workflow examples

## Extraction Agent

The extraction system itself should operate as an agent using reusable meta-skills.

Create a dedicated extraction agent with a minimal but reusable meta-skill set.

The extraction agent should initially support:

* file reading/writing
* graph querying
* node insertion
* node modification
* metadata updates
* dependency linking
* source tracking

The extraction pipeline should:

1. Parse source material
2. Identify executable affordances
3. Extract dependencies and runtime assumptions
4. Infer compatible workflows
5. Create or update graph nodes
6. Link provenance and source references
7. Attach confidence / verification metadata
8. Create semantic references and internal hyperlinks

The system should tolerate noisy or incomplete extractions during early stages.
Refinement and graph distillation can occur incrementally over time.

The system should eventually support promotion from:

```text
raw extraction
    -> linked operational note
    -> refined capability entry
    -> validated long-term knowledge
```

---

# Phase 3 — Mem-Graph Integration and Long-Term Distillation

Introduce shallow memory graphs derived from agent sessions and operational traces.

## Mem-Graph Goals

Represent:

* recurring workflows
* successful procedures
* repeated failure patterns
* temporary environment knowledge
* user-specific operational traces

Mem-Graph should remain lightweight and mutable.
Over time, stable and repeatedly validated structures may be distilled into long-term Know-Do Graph nodes.

Mem-Graph entries should remain lightweight, loosely structured, and highly mutable.

Over time, repeated patterns, successful procedures, and stable operational knowledge may be refined into deeper Know-Do Graph entries.

This creates a pathway from:

```text
episodic interaction
    -> shallow memory traces
    -> structured affordances
    -> refined executable knowledge
```

---

# Phase 4 — Agent-Facing Retrieval and Navigation Interface

The project must be easy for external agents to integrate and use.

The interface layer is a core feature, not an afterthought.

## Design Goals

External agents should interact with the system primarily through retrieval and traversal rather than low-level graph manipulation.

External agents should immediately understand:

* how to search the graph
* how to inspect entries
* how to traverse linked references
* how to identify compatible workflows
* how to obtain execution guidance

Avoid overly complex protocols during early development.

## Intended Interaction Pattern

A typical retrieval flow should look like:

```text
1. Agent searches the graph
2. System returns relevant entry summaries
3. Agent selects interesting entries
4. Agent requests detailed entry content
5. Agent traverses internal references and related entries
6. Agent decides execution or composition strategy
```

## API Priorities

The API should prioritize:

* simplicity
* readability
* composability
* schema stability
* low cognitive overhead for agents

The system should expose structured operational knowledge without forcing a specific execution framework.

The interface should feel closer to navigating an interconnected operational wiki than querying a rigid database.

---

# Long-Term Direction

Potential future directions:

* graph distillation and node refinement
* automated capability verification
* workflow synthesis
* dependency reconstruction
* capability recommendation
* execution history modeling
* trust-aware retrieval
* multi-agent collaborative graph evolution
* benchmark-driven capability scoring
* environment reconstruction planning

The project should evolve toward an open, agent-native infrastructure layer for executable knowledge and operational memory.
