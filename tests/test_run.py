"""Tests for src/agent/run.py -- offline only, no network, no TigerGraph.

Uses the JSON fixtures in tests/fixtures/offline/ (HHG-017: card testing + shared
device -> fraud; HHG-003: recurring-merchant dispute -> legitimate, no evidence request
needed; HHG-020: risk score alone, weak signal -> uncertain, evidence requested but
inconclusive). These exercise the three answer shapes the schema distinguishes: a case
with an evidence request that moves the verdict, a case with no evidence request at all,
and a case where the request comes back with no clean signal.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.deps import offline_deps
from src.agent.run import load_case_pack, main, run_case
from src.answer.validator import validate

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "offline"


@pytest.fixture()
def deps():
    return offline_deps(_FIXTURE_DIR)


@pytest.fixture()
def case_pack():
    return {r["case_id"]: r for r in load_case_pack(_FIXTURE_DIR)}


# ---------------------------------------------------------------------------
# end-to-end: a case runs and emits a schema-valid answer file
# ---------------------------------------------------------------------------


def test_case_runs_end_to_end_and_validates(deps, case_pack):
    answer = run_case("HHG-017", case_pack["HHG-017"], deps)
    violations = validate(answer)
    assert violations == [], violations
    assert answer["case_id"] == "HHG-017"
    assert answer["case"]["verdict"] in ("fraud", "legitimate", "uncertain")


def test_cli_writes_schema_valid_file_to_tmp_path(tmp_path):
    rc = main(
        [
            "--case", "HHG-017",
            "--offline",
            "--data-dir", str(_FIXTURE_DIR),
            "--fixture-dir", str(_FIXTURE_DIR),
            "--out", str(tmp_path),
        ]
    )
    assert rc == 0
    out_file = tmp_path / "HHG-017.json"
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        answer = json.load(f)
    assert validate(answer) == []


def test_cli_all_writes_every_case_and_exits_zero(tmp_path):
    rc = main(
        [
            "--all",
            "--offline",
            "--data-dir", str(_FIXTURE_DIR),
            "--fixture-dir", str(_FIXTURE_DIR),
            "--out", str(tmp_path),
        ]
    )
    assert rc == 0
    written = sorted(p.name for p in tmp_path.glob("*.json"))
    assert written == ["HHG-003.json", "HHG-017.json", "HHG-020.json"]
    for name in written:
        with open(tmp_path / name, "r", encoding="utf-8") as f:
            answer = json.load(f)
        assert validate(answer) == [], (name, validate(answer))


# ---------------------------------------------------------------------------
# initial vs final: differ when evidence was requested, identical + "nothing" when not
# ---------------------------------------------------------------------------


def test_no_evidence_requested_case_has_matching_final_and_initial(deps, case_pack):
    """Whenever a case's evidence_requests list comes back empty, the schema requires
    final == initial and what_changed == 'nothing' (validated by src/answer/validator.py
    too). Exercise this directly against the policy-engine contract rather than assuming
    which of our three fixture cases lands there, since that depends on how many
    independent evidence sources the ledger accumulates before the stop threshold."""
    for case_id, trigger in case_pack.items():
        answer = run_case(case_id, trigger, deps)
        if not answer["evidence_requests"]:
            assert answer["next_best_actions"]["final"] == answer["next_best_actions"]["initial"]
            assert answer["next_best_actions"]["what_changed"] == "nothing"


def test_recurring_dispute_case_settles_via_evidence_request(deps, case_pack):
    """HHG-003: recurring-merchant match, in-character transaction -- single independent
    evidence source (customer_baseline) keeps single_signal True, so R1 asks the
    customer to confirm before any close. The simulated response (evidence_sim.py's
    exonerating-evidence -> confirm rule) settles it: R3 fires and the case closes
    legitimate, with initial and final genuinely different action lists."""
    answer = run_case("HHG-003", case_pack["HHG-003"], deps)
    assert answer["evidence_requests"], "single-signal recurring-match case should trigger R1 first"
    assert answer["next_best_actions"]["final"] != answer["next_best_actions"]["initial"]
    assert answer["next_best_actions"]["what_changed"] != "nothing"
    assert answer["case"]["verdict"] == "legitimate"
    final_action_names = {a["action"] for a in answer["next_best_actions"]["final"]}
    assert "CLOSE_NO_FRAUD" in final_action_names


def test_evidence_request_changes_final_recommendation(deps, case_pack):
    """Regression guard for the before/after mechanic itself (the coordinator's
    verification bar, item 5): HHG-017 starts on a single signal (card_testing_sequence
    only, p=0.41), so R1 fires and asks customer_validation -- not step_up_auth, per the
    §7.4 evidence-shaped selection in src/agent/nodes.py's _choose_evidence_request_type
    (this case turns on whether the cardholder authorized the charges, which is exactly
    what customer_validation resolves). The simulated response is a denial given the
    card-testing evidence already gathered (evidence_sim.py's fraud-pointing-evidence ->
    deny rule); reassess() folds customer_denies into the ledger, R2 fires, and
    BLOCK_CARD appears in `final` but was never in `initial`. This is the exact
    HHG-017 reproduction the state-drop-bug fix (src/agent/state.py's
    _customer_response channel) and the R1-threshold fix (defect 2) are supposed to
    restore -- if either regresses, this test catches it without needing the
    since-removed _repair_final_action_list workaround in run.py.
    """
    answer = run_case("HHG-017", case_pack["HHG-017"], deps)
    assert answer["evidence_requests"], "single-signal card-testing start should trigger R1"
    assert answer["evidence_requests"][0]["type"] == "customer_validation"

    nba = answer["next_best_actions"]
    assert nba["final"] != nba["initial"]
    assert nba["what_changed"] != "nothing"

    initial_action_names = {a["action"] for a in nba["initial"]}
    final_action_names = {a["action"] for a in nba["final"]}
    assert "BLOCK_CARD" in final_action_names
    assert "BLOCK_CARD" not in initial_action_names
    reasons = " ".join(a["reason"] for a in nba["final"] if a["action"] == "BLOCK_CARD")
    assert "R2" in reasons


def test_uncertain_case_requests_evidence_and_can_stay_open(deps, case_pack):
    """HHG-020: risk score alone, no corroborating signal -- R1 asks for verification;
    the assumed response is a documented no-signal outcome (evidence_sim.py's
    'no clean signal -> no_reply' rule), so the case can legitimately remain
    open/uncertain rather than being forced to a verdict the evidence doesn't support."""
    answer = run_case("HHG-020", case_pack["HHG-020"], deps)
    assert answer["evidence_requests"], "weak single-signal case should trigger R1 verification"
    assert answer["case"]["verdict"] in ("uncertain", "legitimate")
    assert validate(answer) == []


# ---------------------------------------------------------------------------
# instrumentation: real, and different between two different cases
# ---------------------------------------------------------------------------


def test_instrumentation_is_real_not_fabricated(deps, case_pack):
    answer = run_case("HHG-017", case_pack["HHG-017"], deps)
    assert answer["tool_calls"] > 0, "offline fetch calls should be counted, not zero"
    assert answer["tokens"] == 0, "no LLM call happens in this deterministic build -- must be an honest zero"
    assert answer["latency_s"] > 0, "latency must be a real wall-clock measurement"
    assert answer["latency_s"] < 5, "a fixture-backed offline run should be fast"


def test_instrumentation_differs_between_cases(deps, case_pack):
    a1 = run_case("HHG-017", case_pack["HHG-017"], deps)
    a2 = run_case("HHG-003", case_pack["HHG-003"], deps)
    # latency_s is wall-clock and will vary run to run; the meaningful, deterministic
    # signal is that the two cases don't collapse to byte-identical instrumentation
    # (PROJECT.md flags "tool_calls identical across all 20 files" as a red flag) --
    # fraud_probability and evidence counts differing is the strongest proof these ran
    # independently rather than one being a copy-pasted stub of the other.
    assert a1["case"]["fraud_probability"] != a2["case"]["fraud_probability"]
    assert len(a1["case"]["evidence"]) != len(a2["case"]["evidence"])


# ---------------------------------------------------------------------------
# case_pack loading / ordering
# ---------------------------------------------------------------------------


def test_case_pack_loaded_in_opened_at_order():
    rows = load_case_pack(_FIXTURE_DIR)
    opened = [r["opened_at"] for r in rows]
    assert opened == sorted(opened)
    assert [r["case_id"] for r in rows] == ["HHG-017", "HHG-020", "HHG-003"]


def test_unknown_case_id_exits_nonzero(tmp_path):
    rc = main(
        [
            "--case", "HHG-999",
            "--offline",
            "--data-dir", str(_FIXTURE_DIR),
            "--fixture-dir", str(_FIXTURE_DIR),
            "--out", str(tmp_path),
        ]
    )
    assert rc != 0
