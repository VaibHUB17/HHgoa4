"""Case memory retrieval (RESEARCH.md 6.4/6.5).

Blended score: 0.4*semantic + 0.4*structural + 0.2*pattern_match
  structural = min(1.0, shared_entity_count / 3)
  semantic   = 1 - cosine_distance / 2

CRITICAL, the single most important thing in this module: the two outcome pools are
retrieved SEPARATELY and never merged into one ranked list before truncating.

    confirming    = top_3(score, where outcome == 'confirmed_fraud')
    disconfirming = top_2(score, where outcome == 'cleared')

closed_cases_history.csv is 4,665 confirmed_fraud : 900 cleared. A merged top-K ranked
by score alone buries exonerating precedent under that 5:1 base rate almost every time --
five confirmed-fraud cases will usually out-score two cleared ones on raw blended score
even when the cleared cases are a closer structural match, simply because there are more
confirmed cases competing for the top slots. Since half the exam cases (README) are
legitimate, that failure mode directly damages the false-positive rate. Ranking, then
filtering by outcome AFTER truncation, is the bug this module exists to prevent -- so the
two pools are computed from independently sorted candidate lists, full stop, and the
public API returns them as two distinctly labelled fields rather than one flat list.

policy_for_pattern(pattern_id) is the hybrid graph-filter-then-vector-rank query per
RESEARCH.md 6.3: pull PolicyChunk/Pattern rows connected to the pattern via GOVERNS, then
rank that candidate set by vector similarity to the pattern's own description.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

CONFIRMED = "confirmed_fraud"
CLEARED = "cleared"


@dataclass
class ClosedCaseCandidate:
    """One closed-case row, plus the raw signals needed to score it against a new alert.
    This is what a caller (graph query result, or a synthetic fixture in tests) builds
    before calling retrieve_similar_cases."""

    case_id: str
    outcome: str                 # "confirmed_fraud" | "cleared"
    pattern: str
    cosine_distance: float       # 0 (identical) .. 2 (opposite), from vector search
    shared_entity_count: int     # cards/devices/regions shared with the new alert
    pattern_matches: bool        # same provisional pattern classification
    analyst_notes: str = ""
    exposure_usd: float = 0.0
    opened_at: str = ""


@dataclass
class RetrievalResult:
    """The two pools, kept distinct so the prompt can show them separately and the agent
    must reason about any conflict between them (that reasoning is the point)."""

    confirming: list[ClosedCaseCandidate] = field(default_factory=list)
    disconfirming: list[ClosedCaseCandidate] = field(default_factory=list)

    @property
    def similar_prior_cases(self) -> list[str]:
        """Dedup'd case IDs for the answer file's case.similar_prior_cases field."""
        seen: list[str] = []
        for c in self.confirming + self.disconfirming:
            if c.case_id not in seen:
                seen.append(c.case_id)
        return seen


def semantic_score(cosine_distance: float) -> float:
    """semantic = 1 - cosine_distance / 2, per RESEARCH.md 6.5."""
    return 1.0 - (cosine_distance / 2.0)


def structural_score(shared_entity_count: int) -> float:
    """structural = min(1.0, shared_entity_count / 3), per RESEARCH.md 6.5."""
    return min(1.0, shared_entity_count / 3.0)


def blended_score(candidate: ClosedCaseCandidate) -> float:
    """0.4*semantic + 0.4*structural + 0.2*pattern_match."""
    sem = semantic_score(candidate.cosine_distance)
    struct = structural_score(candidate.shared_entity_count)
    pat = 1.0 if candidate.pattern_matches else 0.0
    return 0.4 * sem + 0.4 * struct + 0.2 * pat


def retrieve_similar_cases(
    candidates: Sequence[ClosedCaseCandidate],
    n_confirming: int = 3,
    n_disconfirming: int = 2,
) -> RetrievalResult:
    """Score every candidate, then split by outcome BEFORE truncating to top-N.

    This is the ordering that matters: split first, sort each pool independently, take
    top-N of each. Never sort the full candidate list once and then filter -- that would
    let a deep bench of confirmed_fraud candidates starve the cleared pool even when a
    cleared case scores well within its own pool.
    """
    confirmed_pool = [c for c in candidates if c.outcome == CONFIRMED]
    cleared_pool = [c for c in candidates if c.outcome == CLEARED]

    confirmed_pool.sort(key=blended_score, reverse=True)
    cleared_pool.sort(key=blended_score, reverse=True)

    return RetrievalResult(
        confirming=confirmed_pool[:n_confirming],
        disconfirming=cleared_pool[:n_disconfirming],
    )


# ---------------------------------------------------------------------------
# Hybrid graph-filter-then-vector-rank: policy_for_pattern (RESEARCH.md 6.3/6.2)
# ---------------------------------------------------------------------------

@dataclass
class PolicyChunkCandidate:
    chunk_id: str
    rule_id: str
    text: str
    cosine_distance: float


def policy_for_pattern(
    pattern_id: str,
    graph_filter: Callable[[str], Sequence[PolicyChunkCandidate]],
    k: int = 5,
) -> list[PolicyChunkCandidate]:
    """Graph-filter-then-vector-rank: `graph_filter(pattern_id)` returns the PolicyChunk
    candidates reachable from this pattern via the GOVERNS edge (RESEARCH.md 6.3) --
    typically a handful of rules, e.g. out_of_region_use -> R2, R3. Rank that small
    candidate set by vector similarity (lowest cosine_distance first) rather than running
    an unrestricted vector search over every PolicyChunk in the graph. Injected as a
    callable so this module has no TigerGraph dependency and stays unit-testable without
    a live connection -- src/graph wires the real GOVERNS traversal in.
    """
    candidates = list(graph_filter(pattern_id))
    candidates.sort(key=lambda c: c.cosine_distance)
    return candidates[:k]


def demo() -> None:
    """Self-check mirroring the imbalance scenario the real dataset has: many
    confirmed_fraud candidates outscoring a couple of cleared ones on raw blended score,
    and proving the cleared pool still comes back non-empty."""
    candidates = [
        ClosedCaseCandidate(f"CC-conf-{i}", CONFIRMED, "card_testing",
                             cosine_distance=0.2, shared_entity_count=3, pattern_matches=True)
        for i in range(10)
    ] + [
        ClosedCaseCandidate("CC-clear-1", CLEARED, "none",
                             cosine_distance=1.0, shared_entity_count=1, pattern_matches=False),
        ClosedCaseCandidate("CC-clear-2", CLEARED, "none",
                             cosine_distance=1.2, shared_entity_count=0, pattern_matches=False),
    ]
    result = retrieve_similar_cases(candidates)
    assert len(result.confirming) == 3
    assert len(result.disconfirming) == 2
    assert {c.case_id for c in result.disconfirming} == {"CC-clear-1", "CC-clear-2"}
    print("retrieve.py demo OK:", result.similar_prior_cases)


if __name__ == "__main__":
    demo()
