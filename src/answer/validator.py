"""Validates one or many answer-file JSON dicts against the README's Answer Format
contract and the policy engine's routing table (RESEARCH.md §10.1, expanded).

Returns a list of violation strings per case rather than raising on the first one, so a
batch run over cases/*.json can report every problem in a single pass.

CLI: python -m src.answer.validator cases/
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from src.answer.schema import PATTERN_VALUES, STATUS_VALUES, VERDICT_VALUES
from src.policy.engine import resolve_route

_RULE_CITE_RE = re.compile(r"R\d+")


def validate(
    c: dict,
    valid_txn_ids: set[str] | None = None,
    valid_case_ids: set[str] | None = None,
) -> list[str]:
    """Validate one answer-file dict. Returns a list of violation descriptions
    (empty list means the case is valid). `valid_txn_ids`/`valid_case_ids` are optional
    sets from the dataset; when omitted, ID-existence checks are skipped.
    """
    v: list[str] = []

    def fail(msg: str) -> None:
        v.append(msg)

    # --- top level shape -------------------------------------------------------------
    for key in (
        "case_id", "case", "evidence_requests", "next_best_actions", "sar",
        "stop_reason", "tool_calls", "tokens", "latency_s",
    ):
        if key not in c:
            fail(f"missing top-level field: {key}")
    if v:
        return v  # everything below assumes these keys exist

    case = c["case"]
    nba = c["next_best_actions"]
    sar = c["sar"]

    for key in ("initial", "final", "what_changed"):
        if key not in nba:
            fail(f"next_best_actions missing field: {key}")
    for key in (
        "status", "verdict", "fraud_probability", "pattern", "pattern_description",
        "affected_txn_ids", "first_suspicious_txn_id", "connected_card_ids",
        "connected_device_profiles", "exposure_usd", "evidence", "similar_prior_cases",
        "summary", "written_to_graph", "graph_case_id",
    ):
        if key not in case:
            fail(f"case missing field: {key}")
    for key in ("file", "reason", "narrative", "subjects", "total_amount_usd", "activity_dates"):
        if key not in sar:
            fail(f"sar missing field: {key}")
    if v:
        return v

    final_actions = nba["final"]
    initial_actions = nba["initial"]
    final_action_names = [a.get("action") for a in final_actions]

    # --- sar.file agrees with FILE_REPORT in final -------------------------------------
    if sar["file"] != ("FILE_REPORT" in final_action_names):
        fail("sar.file does not agree with whether FILE_REPORT appears in next_best_actions.final")

    # --- legitimate => exposure 0 and affected_txn_ids empty ---------------------------
    if case["verdict"] == "legitimate":
        if case["exposure_usd"] != 0:
            fail("verdict is legitimate but exposure_usd != 0")
        if case["affected_txn_ids"] != []:
            fail("verdict is legitimate but affected_txn_ids is not empty")
        if sar["file"] is not False:
            fail("verdict is legitimate but sar.file is not false")

    # --- undocumented => non-empty pattern_description ---------------------------------
    if case["pattern"] == "undocumented":
        if not case["pattern_description"]:
            fail("pattern is undocumented but pattern_description is empty")
    else:
        if case["pattern_description"] != "":
            fail("pattern_description must be \"\" unless pattern == undocumented")

    # --- no evidence_requests => final == initial AND what_changed == 'nothing' --------
    if not c["evidence_requests"]:
        if final_actions != initial_actions:
            fail("evidence_requests is empty but next_best_actions.final != .initial")
        if nba["what_changed"] != "nothing":
            fail("evidence_requests is empty but what_changed != 'nothing'")

    # --- every txn_id / prior-case id exists in the dataset -----------------------------
    if valid_txn_ids is not None:
        for t in case["affected_txn_ids"]:
            if t not in valid_txn_ids:
                fail(f"affected_txn_ids references unknown transaction id: {t}")
        if case["first_suspicious_txn_id"] and case["first_suspicious_txn_id"] not in valid_txn_ids:
            fail(f"first_suspicious_txn_id references unknown transaction id: {case['first_suspicious_txn_id']}")
        # evidence[].entity_ids are heterogeneous (txn/card/device/case ids) and this
        # function isn't given a combined ID set, so they aren't checked here beyond
        # affected_txn_ids / first_suspicious_txn_id / similar_prior_cases above and below.
    if valid_case_ids is not None:
        for p in case["similar_prior_cases"]:
            if p not in valid_case_ids:
                fail(f"similar_prior_cases references unknown case id: {p}")

    # --- every route matches resolve_route given the exposure ---------------------------
    for phase_name, actions in (("initial", initial_actions), ("final", final_actions)):
        for a in actions:
            try:
                expected = resolve_route(a["action"], case["exposure_usd"])
            except (KeyError, ValueError):
                fail(f"next_best_actions.{phase_name} has unknown action: {a.get('action')}")
                continue
            if a["route"] != expected:
                fail(
                    f"next_best_actions.{phase_name} action {a['action']} has route "
                    f"{a['route']!r}, expected {expected!r} for exposure_usd={case['exposure_usd']}"
                )

    # --- every action's reason cites an R-number ----------------------------------------
    for phase_name, actions in (("initial", initial_actions), ("final", final_actions)):
        for a in actions:
            if not _RULE_CITE_RE.search(a.get("reason", "")):
                fail(f"next_best_actions.{phase_name} action {a.get('action')} reason does not cite an R-number: {a.get('reason')!r}")

    # --- exposure_usd equals the summed absolute amounts --------------------------------
    # Validator is not given per-transaction amounts here; if the caller wants this check
    # it must pass amounts via a separate helper. We do check internal consistency instead:
    # a non-empty affected_txn_ids with exposure_usd == 0 (or vice versa) is almost always
    # wrong and worth flagging even without amounts.
    if case["affected_txn_ids"] and case["exposure_usd"] == 0 and case["verdict"] != "legitimate":
        fail("affected_txn_ids is non-empty but exposure_usd is 0 for a non-legitimate verdict")
    if not case["affected_txn_ids"] and case["exposure_usd"] != 0:
        fail("affected_txn_ids is empty but exposure_usd is non-zero")

    # --- pattern is in the 7-value enum --------------------------------------------------
    if case["pattern"] not in PATTERN_VALUES:
        fail(f"pattern {case['pattern']!r} is not one of the 7 enum values")

    # --- verdict/status in their enums ----------------------------------------------------
    if case["verdict"] not in VERDICT_VALUES:
        fail(f"verdict {case['verdict']!r} is not one of fraud/legitimate/uncertain")
    if case["status"] not in STATUS_VALUES:
        fail(f"status {case['status']!r} is not one of open/closed_fraud/closed_legitimate/escalated")

    return v


def validate_exposure_matches_amounts(
    case: dict, amounts_by_txn_id: dict[str, float]
) -> list[str]:
    """Separate helper: exposure_usd must equal the sum of absolute amounts of
    affected_txn_ids, given a {txn_id: amount} lookup from the dataset. Kept apart from
    validate() because the core validator is not always given per-transaction amounts.
    """
    v: list[str] = []
    total = 0.0
    for t in case["affected_txn_ids"]:
        if t in amounts_by_txn_id:
            total += abs(amounts_by_txn_id[t])
    if round(total, 2) != round(case["exposure_usd"], 2):
        v.append(
            f"exposure_usd {case['exposure_usd']} does not equal the sum of absolute "
            f"amounts of affected_txn_ids ({round(total, 2)})"
        )
    return v


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m src.answer.validator <cases_dir>", file=sys.stderr)
        return 2
    cases_dir = Path(argv[0])
    files = sorted(cases_dir.glob("*.json"))
    if not files:
        print(f"no .json files found in {cases_dir}", file=sys.stderr)
        return 2

    total_violations = 0
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            c = json.load(f)
        violations = validate(c)
        if violations:
            total_violations += len(violations)
            print(f"{fp.name}: {len(violations)} violation(s)")
            for msg in violations:
                print(f"  - {msg}")
        else:
            print(f"{fp.name}: OK")

    print(f"\n{len(files)} file(s) checked, {total_violations} total violation(s)")
    return 1 if total_violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
