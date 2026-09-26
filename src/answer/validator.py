"""Validates one or many answer-file JSON dicts against the README's Answer Format
contract and the policy engine's routing table (RESEARCH.md §10.1, expanded).

Returns a list of violation strings per case rather than raising on the first one, so a
batch run over cases/*.json can report every problem in a single pass.

CLI: python -m src.answer.validator cases/ [--strict]
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from src.answer.schema import PATTERN_VALUES, STATUS_VALUES, VERDICT_VALUES
from src.policy.engine import resolve_route, sar_trigger

_RULE_CITE_RE = re.compile(r"R\d+")

# --- structured response classification --------------------------------------------------
# Vocabulary mirrors src/agent/evidence_sim.py's simulator output verbatim -- that module is
# the single source of assumed_response text in this dataset. This classifies the
# *structured* evidence_requests[].assumed_response field, never case.summary prose: that
# distinction is the whole fix for the HHG-004/006/016 false pass (see module-level note
# below apply_rules-style checks).
_DENY_MARKERS = ("did not make", "not authoris", "not authoriz", "do not recognize", "denies", "denied")
_CONFIRM_MARKERS = ("confirms they made", "completed successfully", "does not dispute")
_NO_REPLY_MARKERS = ("no reply received", "expired unanswered", "not completed within")


def classify_response(text: str) -> str:
    """Classify one evidence_requests[].assumed_response as 'deny' | 'confirm' |
    'no_reply' | 'unknown'. Deny is checked before no_reply so a step-up "not completed"
    denial reads as deny, not no_reply."""
    t = (text or "").lower()
    if any(m in t for m in _DENY_MARKERS):
        return "deny"
    if any(m in t for m in _CONFIRM_MARKERS):
        return "confirm"
    if any(m in t for m in _NO_REPLY_MARKERS):
        return "no_reply"
    return "unknown"


def _customer_response_kinds(evidence_requests: list[dict]) -> set[str]:
    """The set of response classifications actually recorded across every
    customer_validation / step_up_auth evidence request in the case."""
    kinds = set()
    for er in evidence_requests:
        if er.get("type") in ("customer_validation", "step_up_auth"):
            kinds.add(classify_response(er.get("assumed_response", "")))
    return kinds



_R4_FORBIDDEN = {"BLOCK_CARD"}  
_R7_FORBIDDEN = {"BLOCK_CARD", "DECLINE_TRANSACTION", "FILE_REPORT"} 


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

    # --- synthetic-fixture guard -------------------------------------------------------
    # An answer file stamped _synthetic_source (src/agent/run.py, set when the offline
    # fixture behind it carries `_synthetic: true`) was built from fabricated test data,
    # never the organizer's real dataset. It must fail validation outright so it can
    # never pass as submission-ready.
    if c.get("_synthetic_source") is True:
        fail("generated from synthetic fixtures — regenerate against the real dataset before submitting")

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

    # --- rule/response consistency: a cited rule must match the recorded evidence ----------
    # Replaces the old prose-keyword coherence check, which grepped case.summary for words
    # like "denial" and passed HHG-004/006/016: all three cite R2 (denial) and recommend
    # BLOCK_CARD, while their evidence_requests[].assumed_response is a no-reply. The
    # structured field is the source of truth, not prose that happens to contain the word.
    response_kinds = _customer_response_kinds(c["evidence_requests"])
    cited_rules: set[str] = set()
    for phase_name, actions in (("initial", initial_actions), ("final", final_actions)):
        for a in actions:
            rules_cited = set(_RULE_CITE_RE.findall(a.get("reason", "")))
            cited_rules |= rules_cited
            if "R2" in rules_cited and "deny" not in response_kinds:
                fail(
                    f"next_best_actions.{phase_name} action {a.get('action')} cites R2 "
                    "(customer denies) but no evidence_requests entry has an assumed_response "
                    f"classified as a denial (got: {sorted(response_kinds) or ['none recorded']})"
                )
            if "R3" in rules_cited and "confirm" not in response_kinds:
                fail(
                    f"next_best_actions.{phase_name} action {a.get('action')} cites R3 "
                    "(customer confirms) but no evidence_requests entry has an assumed_response "
                    f"classified as a confirmation (got: {sorted(response_kinds) or ['none recorded']})"
                )
            if "R4" in rules_cited and "no_reply" not in response_kinds:
                fail(
                    f"next_best_actions.{phase_name} action {a.get('action')} cites R4 "
                    "(no reply within 24h) but no evidence_requests entry has an assumed_response "
                    f"classified as a no-reply (got: {sorted(response_kinds) or ['none recorded']})"
                )

    # --- rule/action consistency: a cited rule must only produce actions the policy allows -
    final_action_set = set(final_action_names)
    if "R4" in cited_rules and final_action_set & _R4_FORBIDDEN:
        fail(
            f"a final action cites R4 (no-reply) but final also recommends "
            f"{sorted(final_action_set & _R4_FORBIDDEN)}; R4 produces MONITOR_CARD/"
            "DECLINE_TRANSACTION only, never a block"
        )
    if "R7" in cited_rules and final_action_set & _R7_FORBIDDEN:
        fail(
            f"a final action cites R7 (disputed but legitimate) but final also recommends "
            f"{sorted(final_action_set & _R7_FORBIDDEN)}; R7 explicitly forbids "
            f"{sorted(_R7_FORBIDDEN)}"
        )

    # --- verdict/action coherence, structural: uncertain + BLOCK_CARD/FILE_REPORT must be ---
    # justified by a rule that legitimately produces that action given the recorded evidence.
    # This subsumes the old keyword coherence check: instead of asking "does the prose say
    # 'denial'", it asks "does a cited rule actually license this action given the structured
    # evidence" -- which is exactly the check the rule/response and rule/action checks above
    # perform. Left here as an explicit backstop for the case where BLOCK_CARD/FILE_REPORT
    # is cited under a rule number that doesn't license it at all (R1, R4, R8, R9...).
    _BLOCK_LICENSING_RULES = {"R2", "R5", "R10"}
    _FILE_REPORT_LICENSING_RULES = {"R2", "R6", "R9"}
    if case["verdict"] == "uncertain":
        for phase_name, actions in (("final", final_actions),):
            for a in actions:
                rules_cited = set(_RULE_CITE_RE.findall(a.get("reason", "")))
                if a.get("action") == "BLOCK_CARD" and not (rules_cited & _BLOCK_LICENSING_RULES):
                    fail(
                        f"verdict is 'uncertain' and {phase_name} recommends BLOCK_CARD, but "
                        f"its cited rule(s) {sorted(rules_cited)} do not include one that "
                        f"licenses a block ({sorted(_BLOCK_LICENSING_RULES)})"
                    )
                if a.get("action") == "FILE_REPORT" and not (rules_cited & _FILE_REPORT_LICENSING_RULES):
                    fail(
                        f"verdict is 'uncertain' and {phase_name} recommends FILE_REPORT, but "
                        f"its cited rule(s) {sorted(rules_cited)} do not include one that "
                        f"licenses a report ({sorted(_FILE_REPORT_LICENSING_RULES)})"
                    )

    # --- SAR gate: sar.file must agree with FILE_REPORT AND the §3a trigger must hold -------
    strongly_suspected_or_fraud = case["verdict"] == "fraud" or case["fraud_probability"] >= 0.70
    shared_signal = bool(case["connected_card_ids"]) or bool(case["connected_device_profiles"])
    undocumented_pattern = case["pattern"] == "undocumented"
    exposure_over_1000 = case["exposure_usd"] > 1000
    trigger_should_hold = sar_trigger(
        verdict=case["verdict"],
        exposure_usd=case["exposure_usd"],
        shared_device_or_region_or_other_customer_fraud=shared_signal or undocumented_pattern,
        pattern=case["pattern"],
        fraud_probability=case["fraud_probability"],
    )
    if sar["file"] and not trigger_should_hold:
        fail(
            "sar.file is true but the §3a SAR trigger does not hold: verdict="
            f"{case['verdict']!r}, fraud_probability={case['fraud_probability']}, "
            f"exposure_usd={case['exposure_usd']} (>1000: {exposure_over_1000}), "
            f"shared connected_card_ids/device_profiles: {shared_signal}, "
            f"pattern={case['pattern']!r} (undocumented: {undocumented_pattern}) -- "
            "needs fraud confirmed/strongly suspected (p>=0.70) AND "
            "(exposure>$1000 OR shared device/region/other-customer OR undocumented pattern)"
        )
    if strongly_suspected_or_fraud and (exposure_over_1000 or shared_signal or undocumented_pattern):
        if not sar["file"]:
            fail(
                "sar.file is false but the §3a SAR trigger holds: fraud confirmed/strongly "
                f"suspected (verdict={case['verdict']!r}, p={case['fraud_probability']}) AND "
                f"(exposure>$1000: {exposure_over_1000}, shared signal: {shared_signal}, "
                f"undocumented: {undocumented_pattern})"
            )

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


def _load_dataset_ids_and_amounts(
    repo_root: Path,
) -> tuple[set[str] | None, set[str] | None, dict[str, float]]:
    """Load valid txn ids (case-pack `T`-prefixed TransactionID), valid closed-case ids,
    and a {txn_id: amount} map, from data/*.csv when present. Returns (None, None, {}) for
    the id sets when the dataset isn't on disk -- callers must skip those checks gracefully
    rather than hard-fail on a machine without the dataset (per the brief).
    """
    txn_path = repo_root / "data" / "transactions.csv"
    closed_path = repo_root / "data" / "closed_cases_history.csv"

    valid_txn_ids: set[str] | None = None
    amounts: dict[str, float] = {}
    if txn_path.exists():
        valid_txn_ids = set()
        with open(txn_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                tid = "T" + row["TransactionID"]
                valid_txn_ids.add(tid)
                try:
                    amounts[tid] = float(row["TransactionAmt"])
                except (KeyError, ValueError):
                    pass

    valid_case_ids: set[str] | None = None
    if closed_path.exists():
        valid_case_ids = set()
        with open(closed_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                valid_case_ids.add(row["case_id"])

    return valid_txn_ids, valid_case_ids, amounts


def _strict_warnings(all_cases: list[dict]) -> list[str]:
    """--strict: legal-but-suspicious patterns across the whole batch, not violations of
    any single file. The brief calls out two: over-blocking (more than 12/20 fraud verdicts
    when the brief says about half are legitimate) and identical tool_calls counts across
    every case (suggesting fabricated instrumentation rather than a real per-case agent run).
    """
    warnings: list[str] = []
    n = len(all_cases)
    if n == 0:
        return warnings

    fraud_count = sum(1 for c in all_cases if c.get("case", {}).get("verdict") == "fraud")
    if n == 20 and fraud_count > 12:
        warnings.append(
            f"{fraud_count}/{n} cases have verdict=fraud; the brief says about half the "
            "cases are legitimate, so this many fraud verdicts suggests over-blocking"
        )

    tool_calls = [c.get("tool_calls") for c in all_cases if "tool_calls" in c]
    if len(tool_calls) == n and n > 1 and len(set(tool_calls)) == 1:
        warnings.append(
            f"every case has the identical tool_calls count ({tool_calls[0]}), which "
            "suggests fabricated instrumentation rather than a real per-case agent run"
        )

    return warnings


def _main(argv: list[str]) -> int:
    strict = "--strict" in argv
    positional = [a for a in argv if a != "--strict"]
    if not positional:
        print("usage: python -m src.answer.validator <cases_dir> [--strict]", file=sys.stderr)
        return 2
    cases_dir = Path(positional[0])
    files = sorted(cases_dir.glob("*.json"))
    if not files:
        print(f"no .json files found in {cases_dir}", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[2]
    valid_txn_ids, valid_case_ids, amounts = _load_dataset_ids_and_amounts(repo_root)
    if valid_txn_ids is None:
        print("note: data/transactions.csv not found; skipping txn-id-existence and "
              "exposure-arithmetic checks", file=sys.stderr)
    if valid_case_ids is None:
        print("note: data/closed_cases_history.csv not found; skipping prior-case-id-"
              "existence checks", file=sys.stderr)

    total_violations = 0
    all_cases = []
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            c = json.load(f)
        all_cases.append(c)
        violations = validate(c, valid_txn_ids=valid_txn_ids, valid_case_ids=valid_case_ids)
        if amounts:
            violations = violations + validate_exposure_matches_amounts(c["case"], amounts)
        if violations:
            total_violations += len(violations)
            print(f"{fp.name}: {len(violations)} violation(s)")
            for msg in violations:
                print(f"  - {msg}")
        else:
            print(f"{fp.name}: OK")

    print(f"\n{len(files)} file(s) checked, {total_violations} total violation(s)")

    if strict:
        warnings = _strict_warnings(all_cases)
        if warnings:
            print(f"\n{len(warnings)} strict warning(s):")
            for w in warnings:
                print(f"  ! {w}")
        else:
            print("\nno strict warnings")

    return 1 if total_violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
