"""Tests for src/policy/engine.py and src/policy/ledger.py."""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from src.policy.engine import (
    CaseState,
    apply_r10,
    apply_rules,
    can_stop,
    finalize_action,
    resolve_route,
    rule_r1,
    rule_r2,
    rule_r5,
    sar_trigger,
)
from src.policy.ledger import UnknownEvidenceKey, compute_probability

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# --- README §3b worked example: R1 -> R2 flip ------------------------------------------


def test_r1_to_r2_flip_worked_example():
    """README §3b: probability 0.45 on a single signal -> initial action is
    VERIFY_WITH_CUSTOMER under R1. Customer denies -> probability rises, final actions
    become BLOCK_CARD + CREATE_CASE (+ FILE_REPORT if applicable) under R2.
    """
    initial_state = CaseState(single_signal=True, fraud_probability=0.45)
    initial_actions = [r["action"] for r in apply_rules(initial_state)]
    assert initial_actions == ["VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH"]
    assert "BLOCK_CARD" not in initial_actions

    final_state = CaseState(
        single_signal=True,
        fraud_probability=0.86,
        customer_validation_requested=True,
        customer_response="deny",
        exposure_usd=268.43,
    )
    final_actions = [r["action"] for r in apply_rules(final_state)]
    assert "BLOCK_CARD" in final_actions
    assert "CREATE_CASE" in final_actions
    # R1 does not re-fire once single_signal is no longer the whole story, but the engine
    # doesn't need to suppress it explicitly here: fraud_probability 0.86 >= 0.70 means R1's
    # own predicate (fraud_probability < 0.70) is false, so it naturally does not fire.
    assert "VERIFY_WITH_CUSTOMER" not in final_actions


# --- $2500 BLOCK_CARD route boundary -----------------------------------------------------


def test_block_card_route_boundary_2500():
    assert resolve_route("BLOCK_CARD", 2500) == "L1"
    assert resolve_route("BLOCK_CARD", 2500.00) == "L1"


def test_block_card_route_boundary_2501():
    assert resolve_route("BLOCK_CARD", 2501) == "L2"
    assert resolve_route("BLOCK_CARD", 2500.01) == "L2"


# --- R7 forbidding a block on a recurring charge -----------------------------------------


def test_r7_forbids_block_on_recurring_charge():
    s = CaseState(
        disputed_matches_recurring_pattern=True,
        card_testing_detected=True,  # would otherwise propose a block via R5's override
        purchase_over_100_already_cleared=True,
    )
    result = apply_rules(s)
    actions = [r["action"] for r in result]
    assert "BLOCK_CARD" not in actions
    assert "DECLINE_TRANSACTION" not in actions
    assert "CREATE_CASE" in actions
    assert "VERIFY_WITH_CUSTOMER" in actions
    assert "WARN_CUSTOMER" in actions


# --- R10 downgrading BLOCK_ALL_CARDS -> BLOCK_CARD ---------------------------------------


def test_r10_downgrades_block_all_cards_when_guard_fails():
    s = CaseState(
        block_all_cards_proposed=True,
        two_plus_cards_confirmed_fraud=False,
        credentials_confirmed_compromised=False,
    )
    result = apply_r10(["BLOCK_ALL_CARDS"], s)
    assert result == ["BLOCK_CARD"]


def test_r10_keeps_block_all_cards_when_guard_holds():
    s = CaseState(
        block_all_cards_proposed=True,
        two_plus_cards_confirmed_fraud=True,
    )
    result = apply_r10(["BLOCK_ALL_CARDS"], s)
    assert result == ["BLOCK_ALL_CARDS"]


# --- SAR trigger at exposure 1000 vs 1001 -------------------------------------------------


def test_sar_trigger_exposure_1000_does_not_fire_alone():
    assert sar_trigger("fraud", 1000, False, "card_testing") is False


def test_sar_trigger_exposure_1001_fires():
    assert sar_trigger("fraud", 1001, False, "card_testing") is True


def test_sar_trigger_requires_fraud_verdict():
    assert sar_trigger("uncertain", 5000, True, "card_testing") is False


def test_sar_trigger_fires_on_shared_device_regardless_of_exposure():
    assert sar_trigger("fraud", 10, True, "card_testing") is True


def test_sar_trigger_fires_on_undocumented_pattern():
    assert sar_trigger("fraud", 10, False, "undocumented") is True


# --- can_stop at 0.85 / 0.15 with 1 vs 2 independent evidence pieces ---------------------


def test_can_stop_high_needs_two_independent_pieces():
    assert can_stop(0.85, 1, False) is False
    assert can_stop(0.85, 2, False) is True


def test_can_stop_low_needs_two_independent_pieces():
    assert can_stop(0.15, 1, False) is False
    assert can_stop(0.15, 2, False) is True


def test_can_stop_verification_settled_always_stops():
    assert can_stop(0.5, 0, True) is True


def test_can_stop_mid_band_never_stops_without_settlement():
    assert can_stop(0.5, 10, False) is False


# --- finalize_action ----------------------------------------------------------------------


def test_finalize_action_executed_only_for_auto():
    assert finalize_action("ALLOW_TRANSACTION", 0)["executed"] is True
    assert finalize_action("DECLINE_TRANSACTION", 0)["executed"] is False
    assert finalize_action("BLOCK_CARD", 100)["executed"] is False
    assert finalize_action("BLOCK_CARD", 100)["route"] == "L1"


# --- R5 card testing -----------------------------------------------------------------------


def test_r5_decline_and_step_up_when_nothing_cleared():
    s = CaseState(card_testing_detected=True, purchase_over_100_already_cleared=False)
    assert rule_r5(s) == ["DECLINE_TRANSACTION", "STEP_UP_AUTH"]


def test_r5_block_card_when_purchase_already_cleared():
    s = CaseState(card_testing_detected=True, purchase_over_100_already_cleared=True)
    assert rule_r5(s) == ["BLOCK_CARD"]


# --- ledger calibration (see coordinator-requested fix) -----------------------------------


def test_ledger_calibration_no_evidence_is_low():
    assert compute_probability([]) <= 0.15


def test_ledger_calibration_risk_score_alone_stays_low():
    # §0: a risk score is a reason to look, never a verdict.
    assert compute_probability(["risk_score_alone"]) <= 0.25


def test_ledger_calibration_hhg017_worked_example_band():
    # README's own worked example (HHG-017): card_testing + shared device + customer
    # denial -> fraud_probability 0.86 in the spec. The ledger should land in the same
    # decision band, not necessarily hit 0.86 exactly.
    p = compute_probability(["card_testing_sequence", "shared_device_across_cards", "customer_denies"])
    assert 0.82 <= p <= 0.90


def test_ledger_calibration_customer_confirms_closes_low():
    p = compute_probability(["risk_score_alone", "customer_confirms"])
    assert p <= 0.10


def test_ledger_calibration_r7_recurring_stays_low():
    p = compute_probability(["risk_score_alone", "recurring_merchant_match", "in_character_for_customer"])
    assert p <= 0.20


def test_ledger_calibration_single_strong_signal_stays_under_r1_block_line():
    # A lone strong detector must not clear 0.70 by itself, or R1's verify-before-block
    # guard could be skipped on a single signal.
    p = compute_probability(["card_testing_sequence"])
    assert 0.40 <= p <= 0.70


# --- unknown evidence keys must fail loudly, not silently contribute zero ----------------


def test_compute_probability_raises_on_unknown_key():
    with pytest.raises(UnknownEvidenceKey):
        compute_probability(["this_key_does_not_exist_in_the_config"])


def test_compute_probability_raises_listing_all_unknown_keys():
    with pytest.raises(UnknownEvidenceKey) as excinfo:
        compute_probability(["risk_score_alone", "bogus_key_one", "bogus_key_two"])
    msg = str(excinfo.value)
    assert "bogus_key_one" in msg
    assert "bogus_key_two" in msg


# --- contract: every detector weight_keys literal must exist in evidence_weights.yaml ----


def test_every_detector_weight_key_exists_in_config():
    """If a detector emits a ledger key with no matching weight, it silently contributes
    zero and under-scores every case that hits it. This scans src/detectors/patterns.py
    for weight_keys literals and asserts each one is a real key in the config -- so a
    newly added detector key with no weight fails the test suite instead of shipping
    unnoticed. Only checked in this direction (detector keys subset of config keys):
    several config keys (customer_denies, customer_confirms, recurring_merchant_match,
    cleared_precedent_match, closed_case_match, in_character_for_customer,
    risk_score_alone, shared_region_cluster) are set by the agent loop / memory-retrieval
    layer, not by src/detectors/patterns.py, so config is expected to be a strict
    superset of the detector-emitted keys.
    """
    detectors_path = _REPO_ROOT / "src" / "detectors" / "patterns.py"
    if not detectors_path.exists():
        pytest.skip("src/detectors/patterns.py not present yet")
    src = detectors_path.read_text(encoding="utf-8")

    used: set[str] = set()
    for m in re.finditer(r"weight_keys\s*=\s*\[(.*?)\]", src, re.S):
        used |= set(re.findall(r"[\"']([a-zA-Z_]+)[\"']", m.group(1)))
    for m in re.finditer(r"weight_keys\.append\(\s*[\"']([a-zA-Z_]+)", src):
        used.add(m.group(1))

    cfg_path = _REPO_ROOT / "config" / "evidence_weights.yaml"
    cfg_keys = set(yaml.safe_load(cfg_path.read_text(encoding="utf-8")).keys())

    missing = used - cfg_keys
    assert not missing, f"detector keys missing from config/evidence_weights.yaml: {sorted(missing)}"
