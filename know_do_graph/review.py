"""Public configuration types for policy-driven graph review."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread
from typing import Any, FrozenSet, Literal

from core.schemas.entry import EntryType, VerificationStatus

ReviewAction = Literal["modify", "delete", "distill", "merge_similar", "link"]
ReviewStrategy = Literal["seed", "global", "auto"]

ALL_REVIEW_ACTIONS: FrozenSet[ReviewAction] = frozenset(
    {"modify", "delete", "distill", "merge_similar", "link"}
)
DEFAULT_REVIEW_ACTIONS: FrozenSet[ReviewAction] = frozenset({"modify", "merge_similar", "link"})


@dataclass(frozen=True)
class ReviewPolicy:
    """Permissions and eligibility rules enforced by reviewer tools."""

    exclude_types: FrozenSet[EntryType] = field(
        default_factory=lambda: frozenset({EntryType.memory})
    )
    protected_statuses: FrozenSet[VerificationStatus] = field(
        default_factory=lambda: frozenset(
            {
                VerificationStatus.peer_reviewed,
                VerificationStatus.community_tested,
            }
        )
    )
    assignable_statuses: FrozenSet[VerificationStatus] = field(
        default_factory=lambda: frozenset(
            {
                VerificationStatus.unverified,
                VerificationStatus.self_tested,
            }
        )
    )
    allowed_actions: FrozenSet[ReviewAction] = field(default_factory=lambda: DEFAULT_REVIEW_ACTIONS)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exclude_types", frozenset(EntryType(value) for value in self.exclude_types)
        )
        object.__setattr__(
            self,
            "protected_statuses",
            frozenset(VerificationStatus(value) for value in self.protected_statuses),
        )
        object.__setattr__(
            self,
            "assignable_statuses",
            frozenset(VerificationStatus(value) for value in self.assignable_statuses),
        )
        unknown = set(self.allowed_actions) - set(ALL_REVIEW_ACTIONS)
        if unknown:
            raise ValueError(f"Unknown review actions: {sorted(unknown)}")
        object.__setattr__(self, "allowed_actions", frozenset(self.allowed_actions))


def is_review_candidate(entry: Any, policy: ReviewPolicy) -> bool:
    """Return whether an entry should count toward an automatic review."""
    return (
        entry.entry_type not in policy.exclude_types
        and entry.metadata.verification_status not in policy.protected_statuses
        and entry.metadata.review_count == 0
    )


class AutoReviewScheduler:
    """Threshold scheduler returned by :meth:`KnowDoGraph.auto_review`."""

    def __init__(
        self,
        graph: Any,
        *,
        threshold: int,
        policy: ReviewPolicy | None,
        strategy: ReviewStrategy,
        chat_options: dict[str, Any],
    ) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be greater than zero")
        self.graph = graph
        self.threshold = threshold
        self.policy = policy or ReviewPolicy()
        self.strategy = strategy
        self.chat_options = dict(chat_options)
        self.created_since_review = 0
        self.last_result: dict | None = None
        self.last_error: str | None = None
        self._active = True
        self._running = False
        self._lock = Lock()

    def notify_node_created(self, entry: Any) -> None:
        if not is_review_candidate(entry, self.policy):
            return
        self._add_candidates(1)

    def include_existing(self, entries: Any) -> None:
        """Count existing eligible entries and schedule a review if needed."""
        count = sum(is_review_candidate(entry, self.policy) for entry in entries)
        self._add_candidates(count)

    def _add_candidates(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            if not self._active:
                return
            self.created_since_review += count
            if self.created_since_review < self.threshold or self._running:
                return
            self.created_since_review = 0
            self._running = True
        Thread(target=self._run, name="kdg-auto-review", daemon=True).start()

    def trigger(self) -> dict:
        """Run a review synchronously, regardless of the current count."""
        return self._review()

    def stop(self) -> None:
        self._active = False
        if self in self.graph._auto_reviewers:
            self.graph._auto_reviewers.remove(self)

    def _run(self) -> None:
        try:
            self._review()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
        finally:
            with self._lock:
                self._running = False

    def _review(self) -> dict:
        session = self.graph.chat(
            agent="reviewer",
            policy=self.policy,
            strategy=self.strategy,
            **self.chat_options,
        )
        self.last_result = session.review_nodes()
        self.last_error = None
        return self.last_result
