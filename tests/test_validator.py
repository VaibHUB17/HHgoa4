"""Tests for src/answer/validator.py."""
from __future__ import annotations

import copy

from src.answer.validator import (
    _strict_warnings,
    classify_response,
    validate,
    validate_exposure_matches_amounts,
)

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
    # Also clear the shared-device signal: otherwise the §3a SAR gate (fraud verdict +
    # shared connected_card_ids/device_profiles) would itself require sar.file=True,
    # which is not what this fixture is testing.
    c["case"]["connected_card_ids"] = []
    c["case"]["connected_device_profiles"] = []
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


# --- classify_response ---------------------------------------------------------------------


def test_classify_response_no_reply():
    assert classify_response("No reply received from the customer within the 24-hour window.") == "no_reply"
    assert classify_response("Step-up authentication request expired unanswered within the window.") == "no_reply"


def test_classify_response_deny():
    assert classify_response("Customer states they did not make these purchases.") == "deny"
    assert classify_response("Customer denies the transaction.") == "deny"


def test_classify_response_confirm():
    assert classify_response("Customer confirms they made this purchase and does not dispute the charge.") == "confirm"


def test_classify_response_unknown():
    assert classify_response("") == "unknown"
    assert classify_response("something unrelated") == "unknown"


# --- regression guard: the exact HHG-006 false-pass shape -----------------------------------


def _hhg006_shape() -> dict:
    """Reconstructs the real defect: uncertain verdict, BLOCK_CARD + FILE_REPORT citing
    R2, but evidence_requests[].assumed_response is a no-reply, not a denial. HHG-004,
    HHG-006 and HHG-016 all shipped this shape and the old prose-keyword coherence check
    passed all three because the word "denial" happened to appear elsewhere in the prose."""
    c = _valid_case()
    c["case"]["verdict"] = "uncertain"
    c["case"]["fraud_probability"] = 0.70
    c["case"]["connected_card_ids"] = []
    c["case"]["connected_device_profiles"] = []
    c["evidence_requests"] = [
        {
            "type": "customer_validation",
            "asked_after_step": 3,
            "assumed_response": "No reply received from the customer within the 24-hour window.",
        }
    ]
    c["next_best_actions"]["initial"] = [
        {"action": "ESCALATE_TO_ANALYST", "route": "auto", "reason": "R8"},
    ]
    c["next_best_actions"]["final"] = [
        {"action": "BLOCK_CARD", "route": "L1", "reason": "R2, R10"},
        {"action": "CREATE_CASE", "route": "auto", "reason": "R2"},
        {"action": "FILE_REPORT", "route": "L2", "reason": "R2"},
        {"action": "ESCALATE_TO_ANALYST", "route": "auto", "reason": "R8"},
    ]
    c["next_best_actions"]["what_changed"] = (
        "The assumed customer validation response (No reply received...) did not move "
        "fraud probability; actions are unchanged from the initial recommendation."
    )
    c["sar"]["file"] = True
    return c


def test_hhg006_false_pass_is_now_rejected():
    c = _hhg006_shape()
    violations = validate(c)
    assert violations != [], "the HHG-006 shape (R2 cited on a no-reply case) must be rejected"
    assert any("R2" in v and ("den" in v.lower()) for v in violations), violations


# --- rule/response consistency ---------------------------------------------------------------


def test_r2_without_denial_caught():
    c = _valid_case()
    c["evidence_requests"] = [
        {"type": "customer_validation", "asked_after_step": 3,
         "assumed_response": "No reply received from the customer within the 24-hour window."}
    ]
    # final still cites R2 on BLOCK_CARD (inherited from _valid_case)
    violations = validate(c)
    assert any("cites R2" in v for v in violations)


def test_r2_with_denial_passes():
    c = _valid_case()
    c["evidence_requests"] = [
        {"type": "customer_validation", "asked_after_step": 3,
         "assumed_response": "Customer states they did not make these purchases."}
    ]
    violations = validate(c, valid_txn_ids=VALID_TXN_IDS, valid_case_ids=VALID_CASE_IDS)
    assert violations == []


def test_r3_without_confirmation_caught():
    c = _valid_case()
    c["case"]["verdict"] = "legitimate"
    c["case"]["exposure_usd"] = 0
    c["case"]["affected_txn_ids"] = []
    c["case"]["connected_card_ids"] = []
    c["case"]["connected_device_profiles"] = []
    c["evidence_requests"] = [
        {"type": "customer_validation", "asked_after_step": 3,
         "assumed_response": "No reply received from the customer within the 24-hour window."}
    ]
    c["next_best_actions"]["initial"] = [{"action": "CLOSE_NO_FRAUD", "route": "auto", "reason": "R3"}]
    c["next_best_actions"]["final"] = [{"action": "CLOSE_NO_FRAUD", "route": "auto", "reason": "R3"}]
    c["sar"]["file"] = False
    c["sar"]["narrative"] = ""
    c["sar"]["subjects"] = []
    c["sar"]["total_amount_usd"] = 0
    c["sar"]["activity_dates"] = []
    violations = validate(c)
    assert any("cites R3" in v for v in violations)


def test_r4_without_no_reply_caught():
    c = _valid_case()
    c["case"]["verdict"] = "uncertain"
    c["evidence_requests"] = [
        {"type": "customer_validation", "asked_after_step": 3,
         "assumed_response": "Customer confirms they made this purchase and does not dispute the charge."}
    ]
    c["next_best_actions"]["initial"] = [{"action": "MONITOR_CARD", "route": "auto", "reason": "R4"}]
    c["next_best_actions"]["final"] = [{"action": "MONITOR_CARD", "route": "auto", "reason": "R4"}]
    c["sar"]["file"] = False
    c["sar"]["narrative"] = ""
    c["sar"]["subjects"] = []
    c["sar"]["total_amount_usd"] = 0
    c["sar"]["activity_dates"] = []
    violations = validate(c)
    assert any("cites R4" in v for v in violations)


# --- rule/action consistency -----------------------------------------------------------------


def test_r4_with_block_card_caught():
    c = _valid_case()
    c["case"]["verdict"] = "uncertain"
    c["evidence_requests"] = [
        {"type": "customer_validation", "asked_after_step": 3,
         "assumed_response": "No reply received from the customer within the 24-hour window."}
    ]
    c["next_best_actions"]["initial"] = [{"action": "MONITOR_CARD", "route": "auto", "reason": "R4"}]
    c["next_best_actions"]["final"] = [
        {"action": "MONITOR_CARD", "route": "auto", "reason": "R4"},
        {"action": "BLOCK_CARD", "route": "L1", "reason": "R4"},
    ]
    violations = validate(c)
    assert any("R4" in v and "BLOCK_CARD" in v for v in violations)


def test_r7_with_block_card_caught():
    c = _valid_case()
    c["case"]["verdict"] = "legitimate"
    c["case"]["exposure_usd"] = 0
    c["case"]["affected_txn_ids"] = []
    c["case"]["connected_card_ids"] = []
    c["case"]["connected_device_profiles"] = []
    c["evidence_requests"] = []
    c["next_best_actions"]["initial"] = [
        {"action": "CREATE_CASE", "route": "auto", "reason": "R7"},
        {"action": "BLOCK_CARD", "route": "L1", "reason": "R7"},
    ]
    c["next_best_actions"]["final"] = copy.deepcopy(c["next_best_actions"]["initial"])
    c["next_best_actions"]["what_changed"] = "nothing"
    c["sar"]["file"] = False
    c["sar"]["narrative"] = ""
    c["sar"]["subjects"] = []
    c["sar"]["total_amount_usd"] = 0
    c["sar"]["activity_dates"] = []
    violations = validate(c)
    assert any("R7" in v and "BLOCK_CARD" in v for v in violations)


def test_r7_with_file_report_caught():
    c = _valid_case()
    c["case"]["verdict"] = "legitimate"
    c["case"]["exposure_usd"] = 0
    c["case"]["affected_txn_ids"] = []
    c["case"]["connected_card_ids"] = []
    c["case"]["connected_device_profiles"] = []
    c["evidence_requests"] = []
    c["next_best_actions"]["initial"] = [
        {"action": "CREATE_CASE", "route": "auto", "reason": "R7"},
        {"action": "FILE_REPORT", "route": "L2", "reason": "R2, R7"},
    ]
    c["next_best_actions"]["final"] = copy.deepcopy(c["next_best_actions"]["initial"])
    c["next_best_actions"]["what_changed"] = "nothing"
    c["sar"]["file"] = True
    violations = validate(c)
    assert any("R7" in v and "FILE_REPORT" in v for v in violations)


# --- SAR gate ----------------------------------------------------------------------------------


def test_sar_filed_without_trigger_caught():
    c = _valid_case()
    c["case"]["verdict"] = "uncertain"
    c["case"]["fraud_probability"] = 0.4
    c["case"]["exposure_usd"] = 100
    c["case"]["affected_txn_ids"] = ["T0412877"]
    c["case"]["connected_card_ids"] = []
    c["case"]["connected_device_profiles"] = []
    c["case"]["pattern"] = "none"
    c["evidence_requests"] = []
    c["next_best_actions"]["initial"] = [{"action": "MONITOR_CARD", "route": "auto", "reason": "R4"}]
    c["next_best_actions"]["final"] = [{"action": "FILE_REPORT", "route": "L2", "reason": "R6"}]
    c["sar"]["file"] = True
    violations = validate(c)
    assert any("does not hold" in v for v in violations)


def test_sar_not_filed_when_trigger_holds_caught():
    c = _valid_case()
    c["case"]["verdict"] = "fraud"
    c["case"]["fraud_probability"] = 0.9
    c["case"]["exposure_usd"] = 5000
    c["next_best_actions"]["final"] = [a for a in c["next_best_actions"]["final"] if a["action"] != "FILE_REPORT"]
    c["sar"]["file"] = False
    c["sar"]["narrative"] = ""
    c["sar"]["subjects"] = []
    c["sar"]["total_amount_usd"] = 0
    c["sar"]["activity_dates"] = []
    violations = validate(c)
    assert any("trigger holds" in v for v in violations)


# --- exposure/route boundary -------------------------------------------------------------------


def test_block_card_route_boundary_2500_is_l1():
    c = _valid_case()
    c["case"]["exposure_usd"] = 2500
    c["next_best_actions"]["final"][0]["route"] = "L1"
    violations = validate(c)
    assert not any("BLOCK_CARD has route" in v or ("route" in v and "expected" in v) for v in violations)


def test_block_card_route_boundary_2501_is_l2():
    c = _valid_case()
    c["case"]["exposure_usd"] = 2501
    c["next_best_actions"]["final"][0]["route"] = "L1"
    violations = validate(c)
    assert any("expected 'L2'" in v for v in violations)


# --- internal arithmetic (exposure vs summed amounts) -------------------------------------------


def test_exposure_arithmetic_mismatch_caught():
    case = _valid_case()["case"]
    case["affected_txn_ids"] = ["T0412877", "T0412878"]
    case["exposure_usd"] = 999.99
    amounts = {"T0412877": 100.0, "T0412878": -50.0}
    violations = validate_exposure_matches_amounts(case, amounts)
    assert violations != []


def test_exposure_arithmetic_match_passes():
    case = _valid_case()["case"]
    case["affected_txn_ids"] = ["T0412877", "T0412878"]
    case["exposure_usd"] = 150.0
    amounts = {"T0412877": 100.0, "T0412878": -50.0}
    violations = validate_exposure_matches_amounts(case, amounts)
    assert violations == []


# --- ID existence skipped gracefully without a dataset -------------------------------------------


def test_id_existence_skipped_when_no_dataset_given():
    c = _valid_case()
    c["case"]["affected_txn_ids"].append("T9999999")
    c["case"]["similar_prior_cases"].append("CC-9999")
    violations = validate(c)  # no valid_txn_ids / valid_case_ids passed
    assert not any("unknown transaction id" in v for v in violations)
    assert not any("unknown case id" in v for v in violations)


# --- --strict warnings ---------------------------------------------------------------------------


def test_strict_warns_on_overblocking():
    cases = []
    for i in range(20):
        c = _valid_case()
        c["case"]["verdict"] = "fraud" if i < 13 else "legitimate"
        cases.append(c)
    warnings = _strict_warnings(cases)
    assert any("over-blocking" in w for w in warnings)


def test_strict_no_warning_under_half_fraud():
    cases = []
    for i in range(20):
        c = _valid_case()
        c["case"]["verdict"] = "fraud" if i < 9 else "legitimate"
        cases.append(c)
    warnings = _strict_warnings(cases)
    assert not any("over-blocking" in w for w in warnings)


def test_strict_warns_on_identical_tool_calls():
    cases = []
    for _ in range(5):
        c = _valid_case()
        c["tool_calls"] = 6
        cases.append(c)
    warnings = _strict_warnings(cases)
    assert any("fabricated instrumentation" in w for w in warnings)


def test_strict_no_warning_on_varied_tool_calls():
    cases = []
    for i in range(5):
        c = _valid_case()
        c["tool_calls"] = 6 + i
        cases.append(c)
    warnings = _strict_warnings(cases)
    assert not any("fabricated instrumentation" in w for w in warnings)
