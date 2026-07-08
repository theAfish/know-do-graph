from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.graph.graph import KnowDoGraph
from core.schemas.entry import VerificationStatus
from core.services.entries import replace_entry, resolve_required
from core.services.errors import ValidationServiceError

_VERDICT_TO_STATUS = {
    "works": VerificationStatus.self_tested,
    "peer_works": VerificationStatus.peer_reviewed,
    "bugged": VerificationStatus.bugged,
    "deprecated": VerificationStatus.deprecated,
    "unclear": None,
}


def record_feedback(
    db: Session,
    graph: KnowDoGraph,
    identifier: str,
    *,
    verdict: str,
    note: str = "",
    evidence: str = "",
    agent_id: str = "external",
) -> dict:
    if verdict not in _VERDICT_TO_STATUS:
        raise ValidationServiceError(
            f"Unknown verdict: {verdict}",
            code="invalid_verdict",
        )
    entry = resolve_required(db, graph, identifier)
    new_status = _VERDICT_TO_STATUS[verdict]
    if new_status is not None:
        entry.metadata.verification_status = new_status
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "verdict": verdict,
        "note": note,
        "evidence": evidence,
    }
    entry.metadata.feedback_log.append(event)
    entry.metadata.last_reviewed_at = datetime.now(timezone.utc)
    entry.metadata.review_count += 1
    saved = replace_entry(db, graph, entry)
    return {
        "id": saved.id,
        "slug": saved.slug,
        "title": saved.title,
        "verification_status": saved.metadata.verification_status.value,
        "feedback": event,
        "feedback_count": len(saved.metadata.feedback_log),
    }
