"""Tests for src/answer/validator.py."""
from __future__ import annotations

import copy

from src.answer.validator import validate

VALID_TXN_IDS = {"T0412877", "T0412878", "T0412879", "T0412883"}
VALID_CASE_IDS = {"CC-0141"}


def _valid_case() -> dict:
    """The README's own worked example (HHG-017), reshaped into a plain dict."""
    return {
        "case_id": "HHG-017",
        "case": {
            "status": "closed_fraud",
            "verdict": "fraud",
            "fraud_probability": 0.86,
            "pattern": "card_testing",
            "pattern_description": "",
            "affected_txn_ids": ["T0412877", "T0412878", "T0412879", "T0412883"],
            "first_suspicious_txn_id": "T0412877",
            "connected_card_ids": ["C00877-K1"],
            "connected_device_profiles": ["dev1"],
            "exposure_usd": 268.43,
            "evidence": [
                {"claim": "x", "source": "graph", "ref": "query:card_window", "entity_ids": ["T0412877"]}
            ],
            "similar_prior_cases": ["CC-0141"],
            "summary": "summary",
            "written_to_graph": True,
            "graph_case_id": "CASE-2016-1187",
        },
        "evidence_requests": [
            {"type": "customer_validation", "asked_after_step": 4, "assumed_response": "denied"}
        ],
        "next_best_actions": {
            "initial": [
                {"action": "DECLINE_TRANSACTION", "route": "L1", "reason": "R5: testing sequence"},
                {"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R1: probability below 0.70"},
            ],
            "final": [
                {"action": "BLOCK_CARD", "route": "L1", "reason": "R2: customer denied, exposure under $2,500"},
                {"action": "CREATE_CASE", "route": "auto", "reason": "R2"},
                {"action": "FILE_REPORT", "route": "L2", "reason": "R2: shared device links to another card"},
                {"action": "MONITOR_CONNECTED_CARDS", "route": "auto", "reason": "R6: shared device"},
            ],
            "what_changed": "Customer denial raised probability and confirmed the block.",
        },
        "sar": {
            "file": True,
            "reason": "R2: confirmed unauthorized use linked to a second card",
            "narrative": "On 2016-11-14 ... six to twelve sentences ...",
            "subjects": ["C00377", "C00377-K1", "C00877-K1"],
            "total_amount_usd": 268.43,
            "activity_dates": ["2016-11-14", "2016-11-14"],
        },
        "stop_reason": "Customer denial settled the verdict.",
        "tool_calls": 9,
        "tokens": 12480,
        "latency_s": 18.7,
    }


def test_valid_answer_file_passes():
    c = _valid_case()
    violations = validate(c, valid_txn_ids=VALID_TXN_IDS, valid_case_ids=VALID_CASE_IDS)
    assert violations == []


def test_missing_top_level_field_caught():
    c = _valid_case()
    del c["stop_reason"]
    violations = validate(c)
    assert any("stop_reason" in v for v in violations)


def test_sar_file_mismatch_caught():
    c = _valid_case()
    c["sar"]["file"] = False
    violations = validate(c)
    assert any("sar.file" in v for v in violations)


def test_legitimate_with_nonzero_exposure_caught():
    c = _valid_case()
    c["case"]["verdict"] = "legitimate"
    c["case"]["affected_txn_ids"] = []
    # exposure_usd left non-zero on purpose
    violations = validate(c)
    assert any("exposure_usd != 0" in v for v in violations)


def test_legitimate_with_nonempty_affected_txns_caught():
    c = _valid_case()
    c["case"]["verdict"] = "legitimate"
    c["case"]["exposure_usd"] = 0
    # affected_txn_ids left non-empty on purpose
    violations = validate(c)
    assert any("affected_txn_ids" in v and "empty" in v for v in violations)


def test_undocumented_without_description_caught():
    c = _valid_case()
    c["case"]["pattern"] = "undocumented"
    c["case"]["pattern_description"] = ""
    violations = validate(c)
    assert any("pattern_description" in v for v in violations)


def test_no_evidence_requests_requires_final_equals_initial():
    c = _valid_case()
    c["evidence_requests"] = []
    # initial != final still, which should now be flagged
    violations = validate(c)
    assert any("final != .initial" in v or "what_changed" in v for v in violations)


def test_no_evidence_requests_valid_when_final_equals_initial():
    c = _valid_case()
    c["evidence_requests"] = []
    c["next_best_actions"]["final"] = copy.deepcopy(c["next_best_actions"]["initial"])
    c["next_best_actions"]["what_changed"] = "nothing"
    # initial has no FILE_REPORT action, so sar.file must follow suit to stay consistent.
    c["sar"]["file"] = False
    c["sar"]["narrative"] = ""
    c["sar"]["subjects"] = []
    c["sar"]["total_amount_usd"] = 0
    c["sar"]["activity_dates"] = []
    violations = validate(c)
    assert violations == []


def test_unknown_txn_id_caught():
    c = _valid_case()
    c["case"]["affected_txn_ids"].append("T9999999")
    violations = validate(c, valid_txn_ids=VALID_TXN_IDS, valid_case_ids=VALID_CASE_IDS)
    assert any("T9999999" in v for v in violations)


def test_unknown_prior_case_id_caught():
    c = _valid_case()
    c["case"]["similar_prior_cases"].append("CC-9999")
    violations = validate(c, valid_txn_ids=VALID_TXN_IDS, valid_case_ids=VALID_CASE_IDS)
    assert any("CC-9999" in v for v in violations)


def test_wrong_route_caught():
    c = _valid_case()
    # exposure is 268.43 (<=2500), so BLOCK_CARD must route L1; force it wrong.
    c["next_best_actions"]["final"][0]["route"] = "L2"
    violations = validate(c)
    assert any("expected 'L1'" in v for v in violations)


def test_missing_rule_citation_caught():
    c = _valid_case()
    c["next_best_actions"]["final"][0]["reason"] = "customer denied, block the card"
    violations = validate(c)
    assert any("does not cite an R-number" in v for v in violations)


def test_invalid_pattern_enum_caught():
    c = _valid_case()
    c["case"]["pattern"] = "phishing"  # not one of the 7 values
    violations = validate(c)
    assert any("not one of the 7 enum values" in v for v in violations)


def test_invalid_verdict_enum_caught():
    c = _valid_case()
    c["case"]["verdict"] = "maybe"
    violations = validate(c)
    assert any("not one of fraud/legitimate/uncertain" in v for v in violations)


def test_invalid_status_enum_caught():
    c = _valid_case()
    c["case"]["status"] = "pending"
    violations = validate(c)
    assert any("open/closed_fraud/closed_legitimate/escalated" in v for v in violations)
