"""Ranking helpers: Reciprocal Rank Fusion and trust-score multipliers.

Kept dependency-free so retrieval works without numpy.
"""

from __future__ import annotations

import math
from typing import Iterable

from core.schemas.entry import VerificationStatus

# Multiplier applied to fused RRF scores based on verification status.
# Trusted entries float up, broken/deprecated ones sink — but nothing is hidden.
_TRUST_MULTIPLIER: dict[str, float] = {
    VerificationStatus.community_tested.value: 1.30,
    VerificationStatus.peer_reviewed.value: 1.15,
    VerificationStatus.self_tested.value: 1.00,
    VerificationStatus.unverified.value: 0.90,
    VerificationStatus.bugged.value: 0.50,
    VerificationStatus.deprecated.value: 0.30,
}


def reciprocal_rank_fusion(
    ranked_lists: Iterable[list[str]],
    k: int = 60,
) -> dict[str, float]:
    """Standard RRF: each list contributes 1/(k + rank) per id (1-indexed)."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, entry_id in enumerate(ranked, start=1):
            scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (k + rank)
    return scores


def trust_multiplier(verification_status: str, trust_score_override: float | None = None) -> float:
    """Pick the multiplier from explicit override (if set) or verification status."""
    if trust_score_override is not None:
        # Treat user-set trust_score as a direct multiplier, clamped to a sane range.
        return max(0.1, min(2.0, float(trust_score_override)))
    return _TRUST_MULTIPLIER.get(verification_status, 1.0)


def usage_bump(usage_count: int) -> float:
    """Small log-scaled multiplier rewarding entries that have actually been used.

    1 use → ×1.02, 10 uses → ×1.06, 100 uses → ×1.10, capped at ×1.15.
    """
    if usage_count <= 0:
        return 1.0
    return min(1.15, 1.0 + 0.02 * math.log10(usage_count + 1) * 2)
