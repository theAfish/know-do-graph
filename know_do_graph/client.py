"""High-level Python API for embedding Know-Do Graph in agent systems."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

from sqlalchemy.orm import Session, sessionmaker

from core.graph.graph import KnowDoGraph as InMemoryGraph
from core.memory.memgraph import MemGraph
from core.retrieval.progressive import ProgressiveRetriever
from core.retrieval.retrieval import RetrievalEngine
from core.schemas.edge import Edge, EdgeRelation
from core.schemas.entry import Entry, EntryMetadata, EntryType, VerificationStatus
from core.services import edges as edge_service
from core.services import entries as entry_service
from core.storage.database import create_database_engine, initialize_database
from core.storage.repository import EdgeRepository, EntryRepository

if TYPE_CHECKING:
    from .chat import AgentKind, ChatSession, StatusCallback, StepCallback
    from .review import ReviewPolicy, ReviewStrategy


class KnowDoGraph:
    """A self-contained knowledge graph client."""

    def __init__(
        self,
        path: str | Path = "data/know_do_graph.db",
        *,
        memory_dir: str | Path | None = None,
        initialize: bool = True,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.memory_dir = (
            Path(memory_dir).expanduser().resolve()
            if memory_dir is not None
            else self.path.parent / "memory"
        )
        self._engine = create_database_engine(self.path)
        self._session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine,
        )
        self._graph = InMemoryGraph()
        self._auto_reviewers: list[Any] = []
        if initialize:
            initialize_database(self._engine)
        self.refresh()

    def __enter__(self) -> "KnowDoGraph":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Release pooled database connections."""
        for scheduler in list(self._auto_reviewers):
            scheduler.stop()
        self._engine.dispose()

    def refresh(self) -> dict:
        """Reload the traversal graph from persisted entries and edges."""
        with self._session() as db:
            entries = EntryRepository(db).get_all()
            edges = EdgeRepository(db).get_all()
        self._graph.rebuild_from_db(entries, edges)
        return self.stats()

    def stats(self) -> dict:
        return self._graph.stats()

    def add(
        self,
        title: str,
        *,
        content: str = "",
        entry_type: EntryType | str = EntryType.capability,
        tags: Optional[Iterable[str]] = None,
        aliases: Optional[Iterable[str]] = None,
        metadata: EntryMetadata | dict[str, Any] | None = None,
        **fields: Any,
    ) -> Entry:
        """Create and persist an entry."""
        with self._session() as db:
            saved = entry_service.create_entry(
                db,
                self._graph,
                title=title,
                content=content,
                entry_type=entry_type,
                tags=tags,
                aliases=aliases,
                metadata=metadata,
                **fields,
            )
        for scheduler in list(self._auto_reviewers):
            scheduler.notify_node_created(saved)
        return saved

    create_entry = add

    def get(self, identifier: str) -> Entry | None:
        """Resolve an entry by ID, slug, or alias."""
        with self._session() as db:
            return RetrievalEngine(db, self._graph).resolve_identifier(identifier)

    def list(
        self, *, limit: int = 50, offset: int = 0, disabled: bool = False
    ) -> list[Entry]:
        """List enabled entries, or set ``disabled=True`` to list archived ones."""
        with self._session() as db:
            return RetrievalEngine(db, self._graph).list_entries(
                limit=limit, offset=offset, disabled=disabled
            )

    def search(
        self,
        query: str | None = None,
        *,
        tags: Optional[Iterable[str]] = None,
        entry_type: EntryType | str | None = None,
        limit: int = 20,
        mode: str = "hybrid",
        scores: bool = False,
        disabled: bool = False,
    ) -> list[Entry] | list[tuple[Entry, float]]:
        """Search entries using keyword, semantic, or hybrid retrieval."""
        with self._session() as db:
            retrieval = RetrievalEngine(db, self._graph)
            kwargs = {
                "query": query,
                "tags": list(tags) if tags is not None else None,
                "entry_type": entry_type,
                "limit": limit,
                "mode": mode,
                "disabled": disabled,
            }
            if scores:
                return retrieval.search_entries_scored(**kwargs)
            return retrieval.search_entries(**kwargs)

    def set_disabled(self, identifier: str, disabled: bool) -> Entry:
        """Hide or restore an entry without deleting its stored data or edges."""
        with self._session() as db:
            engine = RetrievalEngine(db, self._graph)
            current = engine.resolve_identifier(identifier, disabled=None)
            if current is None:
                raise KeyError(f"Entry not found: {identifier}")
            current.metadata.disabled = disabled
            saved = EntryRepository(db).update(current)
        if saved is None:
            raise KeyError(f"Entry not found: {identifier}")
        self._graph.add_entry(saved)
        if not disabled:
            # Incident edges are persisted, but were removed from the in-memory
            # graph while disabled; reload them when restoring the node.
            self.refresh()
        return saved

    def list_disabled(self, *, limit: int = 50, offset: int = 0) -> list[Entry]:
        """Convenience alias for listing entries hidden by ``set_disabled``."""
        return self.list(limit=limit, offset=offset, disabled=True)

    def update(self, identifier: str, **changes: Any) -> Entry:
        """Update selected fields on an existing entry."""
        with self._session() as db:
            try:
                return entry_service.update_entry(db, self._graph, identifier, **changes)
            except Exception as exc:
                raise KeyError(f"Entry not found: {identifier}") from exc

    def set_verification_status(
        self,
        identifier: str,
        status: VerificationStatus | str,
    ) -> Entry:
        """Manually assign any verification status to a node."""
        with self._session() as db:
            current = entry_service.resolve_required(db, self._graph, identifier)
            current.metadata.verification_status = VerificationStatus(status)
            return entry_service.replace_entry(db, self._graph, current)

    def delete(self, identifier: str) -> bool:
        with self._session() as db:
            return entry_service.delete_entry(db, self._graph, identifier)

    def connect(
        self,
        source: str,
        target: str,
        *,
        relation: EdgeRelation | str = EdgeRelation.related_workflow,
        weight: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Edge:
        """Connect two entries, resolving each by ID, slug, or alias."""
        with self._session() as db:
            return edge_service.connect_entries(
                db,
                self._graph,
                source,
                target,
                relation=relation,
                weight=weight,
                metadata=metadata,
            )

    def related(
        self,
        identifier: str,
        *,
        depth: int = 1,
        relation: EdgeRelation | str | None = None,
    ) -> list[Entry]:
        entry = self._require(identifier)
        normalized_relation = EdgeRelation(relation) if relation is not None else None
        with self._session() as db:
            return RetrievalEngine(db, self._graph).get_related_entries(
                entry.id,
                depth=depth,
                relation=normalized_relation,
            )

    def plan(
        self,
        goal: str,
        *,
        limit: int = 5,
        mode: str = "hybrid",
        include_procedures: bool = True,
    ) -> list[Entry]:
        with self._session() as db:
            return ProgressiveRetriever(db, self._graph).plan(
                goal,
                k=limit,
                mode=mode,
                include_l2=include_procedures,
            )

    def heuristics(self, skill: str, *, limit: int = 5) -> list[Entry]:
        with self._session() as db:
            return ProgressiveRetriever(db, self._graph).heuristics_for(skill, k=limit)

    def constraints(self, skill: str, *, limit: int = 5) -> list[Entry]:
        with self._session() as db:
            return ProgressiveRetriever(db, self._graph).constraints_for(skill, k=limit)

    def count_attached(self, skill: str) -> dict:
        """Count L3/L4 nodes directly attached to an L1/L2 entry."""
        with self._session() as db:
            return ProgressiveRetriever(db, self._graph).count_attached(skill)

    def search_attached(
        self,
        skill: str,
        *,
        kind: str,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> tuple[list[Entry], int]:
        """Search heuristics or constraints attached to one selected entry."""
        with self._session() as db:
            return ProgressiveRetriever(db, self._graph).search_attached(
                skill=skill,
                kind=kind,
                query=query,
                tags=tags,
                limit=limit,
                mode=mode,
            )

    def expand(
        self,
        skill: str,
        *,
        stages: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        with self._session() as db:
            return ProgressiveRetriever(db, self._graph).expand(
                skill,
                stages=stages,
                k=limit,
            )

    def memory(self, session_id: str = "default") -> MemGraph:
        """Return a session-scoped view of memory nodes in this graph."""
        return MemGraph(
            session_id,
            storage_dir=self.memory_dir,
            session_factory=self._session_factory,
            graph=self._graph,
        )

    def chat(
        self,
        *,
        agent: "AgentKind" = "graph",
        model: str | None = None,
        read_only: bool = False,
        on_step: "StepCallback | None" = None,
        on_status: "StatusCallback | None" = None,
        api_key: str | None = None,
        base_url: str | None = None,
        batch_size: int = 5,
        policy: "ReviewPolicy | None" = None,
        strategy: "ReviewStrategy" = "auto",
    ) -> "ChatSession":
        """Create a stateful conversation with a built-in graph agent."""
        from .chat import ChatSession

        return ChatSession(
            self,
            agent=agent,
            model=model,
            read_only=read_only,
            on_step=on_step,
            on_status=on_status,
            api_key=api_key,
            base_url=base_url,
            batch_size=batch_size,
            policy=policy,
            strategy=strategy,
        )

    def ask(self, message: str, **chat_options: Any) -> str:
        """Run a one-shot chat request."""
        return self.chat(**chat_options).send(message)

    def auto_review(
        self,
        *,
        threshold: int = 20,
        policy: "ReviewPolicy | None" = None,
        strategy: "ReviewStrategy" = "auto",
        include_existing: bool = False,
        **chat_options: Any,
    ) -> Any:
        """Schedule a background review after each threshold of eligible nodes."""
        from .review import AutoReviewScheduler

        scheduler = AutoReviewScheduler(
            self,
            threshold=threshold,
            policy=policy,
            strategy=strategy,
            chat_options=chat_options,
        )
        self._auto_reviewers.append(scheduler)
        if include_existing:
            with self._session() as db:
                scheduler.include_existing(EntryRepository(db).get_all())
        return scheduler

    def _session(self) -> Session:
        return self._session_factory()

    def _require(self, identifier: str) -> Entry:
        entry = self.get(identifier)
        if entry is None:
            raise KeyError(f"Entry not found: {identifier}")
        return entry

    @staticmethod
    def _metadata(value: EntryMetadata | dict[str, Any] | None) -> EntryMetadata:
        if value is None:
            return EntryMetadata()
        if isinstance(value, EntryMetadata):
            return value
        return EntryMetadata(**value)


KDG = KnowDoGraph
