"""Regression tests for the customer_report-is-a-dispute-not-a-denial bug.

Bug: trigger() used to seed `_customer_response = "deny"` (and a `customer_denies`
ledger key) for every customer_report-triggered case, before any evidence request went
out. That made R2 fire immediately and permanently: when the simulated evidence-request
reply later came back as a no-reply, nothing reset `_customer_response`, so R2 stayed
fired and R4 (no reply -> MONITOR_CARD/DECLINE_TRANSACTION) never got a chance. Three
cases (HHG-004, HHG-006, HHG-016) recommended BLOCK_CARD citing R2 on nothing but "the
customer didn't answer the phone."

Fix: a customer_report trigger records a `customer_disputes` ledger/evidence item (real
but weaker signal -- keeps R7 reachable) and leaves `_customer_response` unset. Only
reassess(), reading the actual simulated evidence-request reply, sets
`_customer_response` to "deny" / "confirm" / "no_reply".
"""
from __future__ import annotations

from src.agent.nodes import NodeDeps, _build_snapshot, reassess, trigger
from src.policy.engine import CaseState, apply_rules


def _base_state(trigger_type: str, extra_trigger: dict | None = None) -> dict:
    trig = {
        "trigger_type": trigger_type,
        "trigger_text": "I never made this purchase.",
        "flagged_txn_id": "T0000001",
        "card_id": "C00001-K1",
        "customer_id": "C00001",
    }
    trig.update(extra_trigger or {})
    return {
        "case_id": "TEST-1",
        "trigger": trig,
        "evidence": [],
        "ledger": [],
        "p_fraud": 0.0,
        "pattern": "none",
        "affected_txn_ids": [],
        "exposure_usd": 0.0,
        "txn_timestamps": {},
        "snapshots": [],
        "prior_cases": [],
        "evidence_requests": [],
        "loops": 0,
        "approved": False,
        "graph_case_id": "",
        "written_to_graph": False,
        "_customer_response": None,
        "_ledger_grew_this_pass": True,
    }


_NOOP_DEPS = NodeDeps(run_detectors=None, write_case_to_graph=None, request_evidence=None)


def test_customer_report_trigger_does_not_set_deny():
    """The bug, directly: trigger() must not pre-convict a dispute as a denial."""
    state = _base_state("customer_report")
    update = trigger(state, _NOOP_DEPS)
    assert update["_customer_response"] is None
    ledger_keys = [item["key"] for item in update["ledger"]]
    assert "customer_denies" not in ledger_keys
    assert "customer_disputes" in ledger_keys


def test_customer_report_with_no_reply_fires_r4_not_r2():
    """A customer_report trigger whose evidence-request reply comes back as a no-reply
    must land as R4 (MONITOR_CARD/DECLINE_TRANSACTION), never R2 (BLOCK_CARD)."""
    state = _base_state("customer_report")
    state.update(trigger(state, _NOOP_DEPS))

    state["evidence_requests"] = [{
        "type": "customer_validation",
        "asked_after_step": 1,
        "assumed_response": "No reply received from the customer within the 24-hour window.",
    }]
    state.update(reassess(state, _NOOP_DEPS))
    assert state["_customer_response"] == "no_reply"

    snap = _build_snapshot(state, phase="final")
    actions = [a["action"] for a in snap.action_list]
    reasons = " ".join(a["reason"] for a in snap.action_list)
    assert "BLOCK_CARD" not in actions
    assert "R2" not in reasons
    assert "MONITOR_CARD" in actions
    assert "R4" in reasons


def test_customer_report_with_actual_denial_still_fires_r2():
    """A customer_report trigger whose evidence-request reply is a genuine denial must
    still reach R2 -- the fix must not make R2 unreachable."""
    state = _base_state("customer_report")
    state.update(trigger(state, _NOOP_DEPS))

    state["evidence_requests"] = [{
        "type": "customer_validation",
        "asked_after_step": 1,
        "assumed_response": "Customer states they did not make these purchases.",
    }]
    state.update(reassess(state, _NOOP_DEPS))
    assert state["_customer_response"] == "deny"

    snap = _build_snapshot(state, phase="final")
    actions = [a["action"] for a in snap.action_list]
    reasons = " ".join(a["reason"] for a in snap.action_list)
    assert "BLOCK_CARD" in actions
    assert "R2" in reasons


def test_r7_still_fires_on_disputed_recurring_charge_and_forbids_block():
    """R7 keys off trigger_type == customer_report + recurring_merchant_match directly
    (src/agent/nodes.py's disputed_matches_recurring_pattern), not off
    _customer_response -- must still fire on a disputed recurring charge, and must still
    forbid BLOCK_CARD, even with the dispute no longer pre-set as a denial."""
    state = _base_state("customer_report")
    state.update(trigger(state, _NOOP_DEPS))
    state["ledger"] = state["ledger"] + [
        {"key": "recurring_merchant_match", "source": "query:customer_baseline"}
    ]

    snap = _build_snapshot(state, phase="initial")
    actions = [a["action"] for a in snap.action_list]
    reasons = " ".join(a["reason"] for a in snap.action_list)
    assert "R7" in reasons
    assert "BLOCK_CARD" not in actions
    assert "DECLINE_TRANSACTION" not in actions


def test_case_state_r7_forbids_block_even_with_denial_present():
    """Engine-level guard: if a case somehow carries both a genuine denial and a
    recurring-pattern match, R7's forbid list must still win (matches
    rule_r7_forbidden_actions' contract) -- disputed-but-legitimate always wins over a
    denial-driven block."""
    s = CaseState(
        customer_validation_requested=True,
        customer_response="deny",
        disputed_matches_recurring_pattern=True,
    )
    actions = [r["action"] for r in apply_rules(s)]
    assert "BLOCK_CARD" not in actions
    assert "DECLINE_TRANSACTION" not in actions
