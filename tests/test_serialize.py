"""Tests for src/rag/serialize.py.

Covers the three hard requirements from the task spec:
1. A block without a ref raises.
2. Token-budget trimming keeps the highest-risk rows and drops the lowest.
3. entity_ids round-trip so they can populate evidence[].
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.serialize import (
    FULL_DETAIL_ROW_LIMIT,
    MissingRefError,
    QueryResult,
    count_tokens,
    fit_to_budget,
    render_block,
    render_context,
)


def _rows(n: int) -> list[dict]:
    return [{"txn_id": f"T{i}", "risk_score": i / max(n - 1, 1), "amount": 10.0 + i} for i in range(n)]


class TestRefRequirement:
    def test_missing_ref_raises_on_construction(self):
        with pytest.raises(MissingRefError):
            QueryResult(ref="", rows=[{"a": 1}])

    def test_whitespace_only_ref_raises(self):
        with pytest.raises(MissingRefError):
            QueryResult(ref="   ", rows=[{"a": 1}])

    def test_valid_ref_constructs_fine(self):
        qr = QueryResult(ref="query:card_window(card_id=C1, hours=2)", rows=[{"a": 1}], entity_ids=["a"])
        assert qr.ref

    def test_render_block_refuses_result_with_blanked_ref(self):
        qr = QueryResult(ref="query:x()", rows=[{"a": 1}], entity_ids=["a"])
        qr.ref = ""  # simulate a caller mutating it after construction
        with pytest.raises(MissingRefError):
            render_block(qr)

    def test_render_block_includes_ref_in_heading(self):
        qr = QueryResult(ref="query:card_window(card_id=C04570-K1, hours=2)", rows=_rows(3),
                          entity_ids=["T0", "T1", "T2"], title="Card window")
        text = render_block(qr)
        assert "ref: `query:card_window(card_id=C04570-K1, hours=2)`" in text
        assert text.startswith("### Card window")


class TestTokenBudgetTrimming:
    def test_full_detail_under_row_limit(self):
        qr = QueryResult(ref="query:x()", rows=_rows(5), entity_ids=[f"T{i}" for i in range(5)])
        text = render_block(qr)
        for i in range(5):
            assert f"T{i}" in text
        assert "omitted" not in text

    def test_over_row_limit_shows_topn_plus_aggregate(self):
        n = FULL_DETAIL_ROW_LIMIT + 5
        qr = QueryResult(ref="query:x()", rows=_rows(n), entity_ids=[f"T{i}" for i in range(n)])
        text = render_block(qr)
        assert "omitted" in text
        # highest-risk row (last index, risk_score=1.0) must be present in the shown table
        assert "T" + str(n - 1) in text

    def test_fit_to_budget_keeps_highest_risk_drops_lowest(self):
        rows = _rows(20)
        qr = QueryResult(ref="query:card_window(card_id=C1, hours=2)", rows=rows,
                          entity_ids=[r["txn_id"] for r in rows], title="Card window")
        text, trimmed = fit_to_budget("Case narrative header.", [qr], max_tokens=40)
        remaining_ids = [row["txn_id"] for row in trimmed[0].rows]

        assert "T19" in remaining_ids, "highest-risk row must survive trimming"
        assert "T0" not in remaining_ids, "lowest-risk row must be dropped first"
        assert len(remaining_ids) < 20, "trimming must actually remove rows"
        # remaining rows must be monotonically the highest-risk subset
        remaining_risks = sorted(row["risk_score"] for row in trimmed[0].rows)
        all_risks = sorted(row["risk_score"] for row in rows)
        assert remaining_risks == all_risks[-len(remaining_risks):]

    def test_fit_to_budget_never_below_one_row_per_block(self):
        rows = _rows(20)
        qr = QueryResult(ref="query:x()", rows=rows, entity_ids=[r["txn_id"] for r in rows])
        text, trimmed = fit_to_budget("Header.", [qr], max_tokens=1)
        assert len(trimmed[0].rows) >= 1

    def test_fit_to_budget_multi_block_trims_globally_lowest_first(self):
        rows_a = _rows(10)
        rows_b = [{"txn_id": f"B{i}", "risk_score": 0.9, "amount": 5.0} for i in range(10)]
        qa = QueryResult(ref="query:a()", rows=rows_a, entity_ids=[r["txn_id"] for r in rows_a], title="A")
        qb = QueryResult(ref="query:b()", rows=rows_b, entity_ids=[r["txn_id"] for r in rows_b], title="B")
        # A mild budget: block A's low-risk rows (0..~0.44) should be trimmed first,
        # before block B's uniformly high-risk (0.9) rows are touched at all.
        text, trimmed = fit_to_budget("Header.", [qa, qb], max_tokens=300)
        a_remaining = len(trimmed[0].rows)
        b_remaining = len(trimmed[1].rows)
        assert a_remaining < 10, "low-risk block should be trimmed first"
        assert b_remaining == 10, "high-risk block should be untouched while low-risk block still has rows to give"


class TestEntityIdsRoundTrip:
    def test_entity_ids_appear_in_rendered_block(self):
        ids = ["T100", "T101", "CC-0141"]
        qr = QueryResult(ref="query:device_neighbors(device_id=D1)", rows=[{"card_id": "C1-K1"}], entity_ids=ids)
        text = render_block(qr)
        for eid in ids:
            assert eid in text

    def test_entity_ids_preserved_through_fit_to_budget(self):
        rows = _rows(3)
        ids = [r["txn_id"] for r in rows]
        qr = QueryResult(ref="query:x()", rows=rows, entity_ids=ids)
        _, trimmed = fit_to_budget("Header.", [qr], max_tokens=10_000)
        assert trimmed[0].entity_ids == ids

    def test_entity_ids_independent_of_row_trimming(self):
        # entity_ids is the provenance list for evidence[]; even if row display is
        # trimmed, entity_ids on the QueryResult itself isn't silently mutated by
        # render_block (only fit_to_budget's row deletion touches .rows, not .entity_ids).
        rows = _rows(20)
        ids = [r["txn_id"] for r in rows]
        qr = QueryResult(ref="query:x()", rows=rows, entity_ids=ids)
        render_block(qr)  # rendering alone must not mutate entity_ids
        assert qr.entity_ids == ids

    def test_render_context_includes_narrative_and_all_blocks(self):
        qr1 = QueryResult(ref="query:a()", rows=[{"x": 1}], entity_ids=["X1"], title="Block A")
        qr2 = QueryResult(ref="query:b()", rows=[{"y": 2}], entity_ids=["Y1"], title="Block B")
        ctx = render_context("This case involves two entities.", [qr1, qr2])
        assert "This case involves two entities." in ctx
        assert "Block A" in ctx and "Block B" in ctx
        assert "X1" in ctx and "Y1" in ctx


class TestTokenCounter:
    def test_count_tokens_nonzero_for_nonempty_text(self):
        assert count_tokens("hello world") > 0

    def test_count_tokens_empty_string(self):
        assert count_tokens("") >= 0
