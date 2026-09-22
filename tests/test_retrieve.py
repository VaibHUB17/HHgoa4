"""Tests for src/rag/retrieve.py.

The test that matters most: two-pool separation actually returns cleared cases even
when many more confirmed-fraud cases outscore them on raw blended score. Constructs the
4,665:900 imbalance synthetically (proportionally) and proves exonerating precedent
still surfaces in `disconfirming`, never merged away by a shared top-K.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.retrieve import (
    CLEARED,
    CONFIRMED,
    ClosedCaseCandidate,
    PolicyChunkCandidate,
    RetrievalResult,
    blended_score,
    policy_for_pattern,
    retrieve_similar_cases,
    semantic_score,
    structural_score,
)


def _confirmed(case_id: str, cosine_distance: float, shared: int, pattern_match: bool) -> ClosedCaseCandidate:
    return ClosedCaseCandidate(case_id, CONFIRMED, "card_testing", cosine_distance, shared, pattern_match)


def _cleared(case_id: str, cosine_distance: float, shared: int, pattern_match: bool) -> ClosedCaseCandidate:
    return ClosedCaseCandidate(case_id, CLEARED, "none", cosine_distance, shared, pattern_match)


class TestScoringFormula:
    def test_semantic_score_formula(self):
        assert semantic_score(0.0) == 1.0
        assert semantic_score(2.0) == 0.0
        assert semantic_score(1.0) == 0.5

    def test_structural_score_formula(self):
        assert structural_score(0) == 0.0
        assert structural_score(3) == 1.0
        assert structural_score(6) == 1.0  # capped at 1.0
        assert structural_score(1) == pytest.approx(1 / 3)

    def test_blended_score_weights(self):
        # semantic=1.0 (dist=0), structural=1.0 (shared>=3), pattern_match=True
        c = ClosedCaseCandidate("CC-1", CONFIRMED, "p", cosine_distance=0.0, shared_entity_count=3, pattern_matches=True)
        assert blended_score(c) == pytest.approx(0.4 * 1.0 + 0.4 * 1.0 + 0.2 * 1.0)

    def test_blended_score_all_zero(self):
        c = ClosedCaseCandidate("CC-1", CONFIRMED, "p", cosine_distance=2.0, shared_entity_count=0, pattern_matches=False)
        assert blended_score(c) == pytest.approx(0.0)


class TestTwoPoolSeparation:
    """The critical test: exonerating precedent must survive the base-rate imbalance."""

    def test_cleared_cases_surface_even_when_outscored_by_many_confirmed(self):
        # 10 confirmed_fraud candidates, all scoring HIGHER than the 2 cleared ones.
        # A naive merge-then-rank top-5 would return zero cleared cases here.
        confirmed = [_confirmed(f"CC-conf-{i}", cosine_distance=0.1, shared=3, pattern_match=True) for i in range(10)]
        cleared = [
            _cleared("CC-clear-1", cosine_distance=1.5, shared=1, pattern_match=False),
            _cleared("CC-clear-2", cosine_distance=1.8, shared=0, pattern_match=False),
        ]
        candidates = confirmed + cleared

        # sanity: every confirmed candidate really does outscore every cleared one
        assert min(blended_score(c) for c in confirmed) > max(blended_score(c) for c in cleared)

        result = retrieve_similar_cases(candidates)

        assert len(result.confirming) == 3
        assert len(result.disconfirming) == 2
        assert {c.case_id for c in result.disconfirming} == {"CC-clear-1", "CC-clear-2"}

    def test_proportional_4665_to_900_imbalance(self):
        # Build the real base rate proportionally (scaled down): ~52 confirmed : 10 cleared,
        # confirmed all scoring higher than cleared, mirroring the dataset's actual skew.
        n_confirmed, n_cleared = 4665 // 90, 900 // 90  # 51 : 10
        confirmed = [_confirmed(f"CC-conf-{i}", cosine_distance=0.05, shared=3, pattern_match=True)
                     for i in range(n_confirmed)]
        cleared = [_cleared(f"CC-clear-{i}", cosine_distance=1.9, shared=0, pattern_match=False)
                   for i in range(n_cleared)]
        candidates = confirmed + cleared

        result = retrieve_similar_cases(candidates)

        assert len(result.disconfirming) == 2, "disconfirming pool must be non-empty despite 5:1 base rate"
        assert all(c.outcome == CLEARED for c in result.disconfirming)
        assert all(c.outcome == CONFIRMED for c in result.confirming)

    def test_never_merge_then_rank_fewer_cleared_than_requested(self):
        # Only one cleared case exists at all -- disconfirming pool should return it,
        # not pad with a confirmed case.
        confirmed = [_confirmed(f"CC-conf-{i}", 0.1, 3, True) for i in range(5)]
        cleared = [_cleared("CC-only-clear", 0.1, 3, True)]  # even scores as well as confirmed
        result = retrieve_similar_cases(confirmed + cleared)
        assert len(result.disconfirming) == 1
        assert result.disconfirming[0].case_id == "CC-only-clear"
        assert all(c.outcome == CONFIRMED for c in result.confirming)

    def test_pools_are_sorted_by_score_within_each_pool(self):
        confirmed = [
            _confirmed("CC-low", cosine_distance=1.0, shared=0, pattern_match=False),
            _confirmed("CC-high", cosine_distance=0.0, shared=3, pattern_match=True),
            _confirmed("CC-mid", cosine_distance=0.5, shared=1, pattern_match=True),
        ]
        result = retrieve_similar_cases(confirmed, n_confirming=3)
        assert [c.case_id for c in result.confirming] == ["CC-high", "CC-mid", "CC-low"]

    def test_empty_cleared_pool_does_not_crash(self):
        confirmed = [_confirmed(f"CC-{i}", 0.1, 3, True) for i in range(5)]
        result = retrieve_similar_cases(confirmed)
        assert result.disconfirming == []
        assert len(result.confirming) == 3

    def test_empty_confirmed_pool_does_not_crash(self):
        cleared = [_cleared(f"CC-{i}", 0.1, 3, True) for i in range(3)]
        result = retrieve_similar_cases(cleared)
        assert result.confirming == []
        assert len(result.disconfirming) == 2

    def test_similar_prior_cases_dedupes_and_covers_both_pools(self):
        confirmed = [_confirmed(f"CC-conf-{i}", 0.1, 3, True) for i in range(3)]
        cleared = [_cleared(f"CC-clear-{i}", 0.1, 3, True) for i in range(2)]
        result = retrieve_similar_cases(confirmed + cleared)
        ids = result.similar_prior_cases
        assert set(ids) == {c.case_id for c in confirmed} | {c.case_id for c in cleared}
        assert len(ids) == len(set(ids))

    def test_result_pools_are_distinctly_labelled_fields(self):
        result = RetrievalResult(confirming=[_confirmed("A", 0, 3, True)], disconfirming=[_cleared("B", 0, 3, True)])
        assert result.confirming[0].outcome == CONFIRMED
        assert result.disconfirming[0].outcome == CLEARED
        assert result.confirming is not result.disconfirming


class TestPolicyForPattern:
    def test_graph_filter_then_vector_rank(self):
        pool = {
            "out_of_region_use": [
                PolicyChunkCandidate("policy:R3", "R3", "text3", cosine_distance=0.5),
                PolicyChunkCandidate("policy:R2", "R2", "text2", cosine_distance=0.1),
            ]
        }

        def fake_graph_filter(pattern_id: str):
            return pool.get(pattern_id, [])

        ranked = policy_for_pattern("out_of_region_use", fake_graph_filter, k=5)
        assert [c.rule_id for c in ranked] == ["R2", "R3"]  # lowest distance first

    def test_k_limits_results(self):
        candidates = [PolicyChunkCandidate(f"c{i}", f"R{i}", "t", cosine_distance=i / 10) for i in range(5)]
        ranked = policy_for_pattern("x", lambda pid: candidates, k=2)
        assert len(ranked) == 2

    def test_empty_graph_filter_result(self):
        ranked = policy_for_pattern("unknown_pattern", lambda pid: [], k=5)
        assert ranked == []
