"""Tests for src/agent/investigator.py's iterative, LLM-directed investigation loop.

All tests use a stubbed LLMClient (scripted decisions, no network) so they run offline
and deterministically, per the task brief. Live-graph behaviour is exercised separately
(see the report), not here.
"""
from __future__ import annotations

import json

import pytest

from src.agent.investigator import (
    GENERATED_QUERY_TIMEOUT_S,
    MAX_GENERATED_QUERY_ROWS,
    LLMClient,
    _guard_generated_query,
    investigate,
)


def _llm(script):
    """Build an LLMClient whose complete() pops one scripted reply per call, in order."""
    calls = iter(script)

    def complete(system: str, user: str) -> str:
        return json.dumps(next(calls))

    return LLMClient(complete=complete, available=lambda: True)


class _RowTools:
    """Fake QueryTools returning a fixed row shape, tracking every call made."""

    def __init__(self, rows_by_query=None):
        self.rows_by_query = rows_by_query or {}
        self.calls = []

    def run_installed_query(self, name, params):
        self.calls.append((name, params))
        return self.rows_by_query.get(name, [{"results": [[]]}])

    def run_interpreted(self, gsql_text, params=None):
        self.calls.append(("__interpreted__", gsql_text))
        return [{"results": [[{"v_id": "T9", "attributes": {}}]]}]


_SOME_ROWS = [{"results": [[{"v_id": "T1", "attributes": {"txns.@card": ["C0002-K1"]}}]]}]


# ---------------------------------------------------------------------------
# Loop termination
# ---------------------------------------------------------------------------


def test_terminates_on_conclude():
    llm = _llm([
        {"decision": "CONCLUDE", "reasoning": "single clean signal, nothing more to check"},
    ])
    tools = _RowTools()
    res = investigate("HHG-T1", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=4, llm=llm)
    assert res.llm_available
    assert res.depth_reached == 1
    assert "single clean signal" in res.stop_reason
    assert tools.calls == []  # no plan/execute step ever ran


def test_terminates_at_max_depth():
    # Always CONTINUE, and plan always asks for a query that returns fresh rows each time
    # (distinct entity per depth) so the "nothing new" guard never fires first --
    # this isolates the max_depth cap as the actual stopping cause.
    script = []
    for i in range(10):
        script.append({"decision": "CONTINUE", "entity": f"D{i}", "question": "who else?"})
        script.append({"action": "run_query", "query": "device_neighbors",
                        "params": {"device_id": f"D{i}", "anchor": "2016-01-01 00:00:00", "hours": 1},
                        "reasoning": "widen"})
    llm = _llm(script)

    class _GrowingTools:
        def __init__(self):
            self.n = 0

        def run_installed_query(self, name, params):
            self.n += 1
            return [{"results": [[{"v_id": f"T{self.n}", "attributes": {"txns.@card": [f"C{self.n:04d}-K1"]}}]]}]

    tools = _GrowingTools()
    res = investigate("HHG-T2", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=3, llm=llm)
    assert res.depth_reached == 3
    assert "max_depth" in res.stop_reason
    assert len(res.evidence) == 3  # one new evidence entry per depth, none deduped away


def test_stops_when_query_yields_nothing_new():
    # CONTINUE forever, but the plan always requests the *same* query with the *same*
    # params, returning the *same* rows -- the fingerprint guard must catch this and stop
    # rather than spinning to max_depth.
    repeat_plan = {"action": "run_query", "query": "device_neighbors",
                   "params": {"device_id": "D1", "anchor": "2016-01-01 00:00:00", "hours": 1},
                   "reasoning": "widen"}
    script = [
        {"decision": "CONTINUE", "entity": "D1", "question": "who else?"},
        repeat_plan,
        {"decision": "CONTINUE", "entity": "D1", "question": "who else, again?"},
        repeat_plan,
    ]
    llm = _llm(script)
    tools = _RowTools(rows_by_query={"device_neighbors": _SOME_ROWS})
    res = investigate("HHG-T3", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=5, llm=llm)
    assert res.depth_reached == 2
    assert "nothing new" in res.stop_reason
    # Stopped after the second (duplicate) pass rather than looping to max_depth=5 --
    # the fingerprint guard fires on the repeat and the loop returns immediately after,
    # so the trace has exactly 2 execute steps, not 5.
    assert sum(1 for t in res.decision_trace if t["step"] == "execute") == 2


# ---------------------------------------------------------------------------
# LLM unavailable -- must surface, never silently substitute a fixed sequence
# ---------------------------------------------------------------------------


def test_llm_unavailable_surfaces_not_silently_falls_back():
    llm = LLMClient(complete=lambda s, u: (_ for _ in ()).throw(AssertionError("must not be called")),
                     available=lambda: False)
    tools = _RowTools()
    res = investigate("HHG-T4", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=4, llm=llm)
    assert res.llm_available is False
    assert "LLM unavailable" in res.stop_reason
    assert tools.calls == []  # no query sequence ran in its place
    assert res.decision_trace and res.decision_trace[0]["decision"] == "ABORT"


# ---------------------------------------------------------------------------
# Query guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_gsql", [
    "INSERT INTO Transaction VALUES (1)",
    "DROP QUERY card_window",
    "UPDATE Transaction SET amount = 0 LIMIT 10",
    "DELETE FROM Transaction LIMIT 10",
    "CREATE QUERY evil() FOR GRAPH G { }",
])
def test_guard_rejects_non_select_statements(bad_gsql):
    allowed, reason = _guard_generated_query(bad_gsql)
    assert not allowed
    assert reason  # a human-readable rejection reason is always present


def test_guard_accepts_read_only_select_with_limit():
    good = "INTERPRET QUERY () FOR GRAPH FraudInvestigation { r = SELECT t FROM Transaction:t LIMIT 50; PRINT r; }"
    allowed, reason = _guard_generated_query(good)
    assert allowed
    assert reason == "ok"


def test_guard_rejects_missing_limit():
    allowed, reason = _guard_generated_query("SELECT t FROM Transaction:t;")
    assert not allowed
    assert "LIMIT" in reason


def test_guard_rejects_limit_over_cap():
    over = f"SELECT t FROM Transaction:t LIMIT {MAX_GENERATED_QUERY_ROWS + 1};"
    allowed, reason = _guard_generated_query(over)
    assert not allowed
    assert "exceeds cap" in reason


def test_rejected_generated_query_is_recorded_as_evidence_not_hidden():
    """A refused query must still show up in the trail, per the brief: 'a refused query is
    interesting evidence about the agent's behaviour, not something to hide.'"""
    llm = _llm([
        {"decision": "CONTINUE", "entity": "D1", "question": "who else?"},
        {"action": "propose_traversal", "gsql": "DROP QUERY card_window",
         "reasoning": "trying something outside the inventory"},
        {"decision": "CONCLUDE", "reasoning": "done"},
    ])
    tools = _RowTools()
    res = investigate("HHG-T5", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=4, llm=llm)
    rejected = [e for e in res.evidence if "rejected" in e["ref"]]
    assert rejected, res.evidence
    assert "DROP QUERY card_window" in rejected[0]["claim"]
    assert tools.calls == []  # never reached execution


def test_generated_traversal_runs_when_guard_passes():
    llm = _llm([
        {"decision": "CONTINUE", "entity": "region", "question": "any other query fit?"},
        {"action": "propose_traversal",
         "gsql": "INTERPRET QUERY () FOR GRAPH FraudInvestigation { r = SELECT t FROM Transaction:t LIMIT 10; PRINT r; }",
         "reasoning": "no installed query covers this angle"},
        {"decision": "CONCLUDE", "reasoning": "done"},
    ])
    tools = _RowTools()
    res = investigate("HHG-T6", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=4, llm=llm)
    assert tools.calls and tools.calls[0][0] == "__interpreted__"
    assert any("Generated traversal" in e["claim"] for e in res.evidence)


# ---------------------------------------------------------------------------
# Provenance / depth
# ---------------------------------------------------------------------------


def test_evidence_carries_ref_and_entity_ids_across_depth():
    llm = _llm([
        {"decision": "CONTINUE", "entity": "D1", "question": "who else used this device?"},
        {"action": "run_query", "query": "device_neighbors",
         "params": {"device_id": "D1", "anchor": "2016-11-22 20:11:00", "hours": 720},
         "reasoning": "widen to the device neighbourhood"},
        {"decision": "CONCLUDE", "reasoning": "ring confirmed"},
    ])
    tools = _RowTools(rows_by_query={"device_neighbors": _SOME_ROWS})
    res = investigate("HHG-T7", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=4, llm=llm)
    assert res.evidence[0]["ref"].startswith("query:device_neighbors(")
    assert "C0002-K1" in res.evidence[0]["entity_ids"]
    assert res.evidence[0]["entity_ids"]  # provenance is non-empty


def test_seed_evidence_is_carried_into_the_loop():
    seed = [{"claim": "deterministic detector found X", "source": "graph", "ref": "query:card_window()", "entity_ids": ["T1"]}]
    llm = _llm([{"decision": "CONCLUDE", "reasoning": "seed evidence already sufficient"}])
    res = investigate("HHG-T8", {"card_id": "C0001-K1", "customer_id": "C0001"}, _RowTools(),
                       max_depth=4, llm=llm, seed_evidence=seed)
    # seed evidence itself is carried through unchanged; investigate() appends one advisory
    # confidence-check entry on CONCLUDE (never touches the seed evidence's own content).
    assert res.evidence[:len(seed)] == seed
    assert res.evidence[-1]["ref"].startswith("llm_decision:confidence_gate(")
    assert res.depth_reached == 1


def test_unknown_query_name_is_refused_not_executed():
    llm = _llm([
        {"decision": "CONTINUE", "entity": "X", "question": "?"},
        {"action": "run_query", "query": "not_a_real_query", "params": {}, "reasoning": "typo"},
        {"decision": "CONCLUDE", "reasoning": "done"},
    ])
    tools = _RowTools()
    res = investigate("HHG-T9", {"card_id": "C0001-K1", "customer_id": "C0001"}, tools, max_depth=4, llm=llm)
    assert tools.calls == []
    assert any("unknown query" in e["claim"] for e in res.evidence)


def test_timeout_constant_is_positive_and_bounded():
    """Sanity check on the guard configuration itself (README: 'a row cap and a timeout')."""
    assert 0 < GENERATED_QUERY_TIMEOUT_S <= 60
    assert 0 < MAX_GENERATED_QUERY_ROWS <= 1000
