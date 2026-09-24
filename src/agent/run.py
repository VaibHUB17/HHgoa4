"""CLI: run the investigation agent over case_pack.csv and emit answer files.

    python -m src.agent.run --case HHG-017 [--offline] [--out cases/]
    python -m src.agent.run --all [--offline] [--out cases/]

For each case: load its trigger row, run the LangGraph investigation
(src/agent/graph.py), read the initial/final RecommendationSnapshots it produced, generate
a SAR if the policy calls for one, assemble the answer JSON per src/answer/schema.py,
validate it with src/answer/validator.py, and write cases/<case_id>.json.

Instrumentation is real, not fabricated: tool_calls comes from
src/graph/connection.counter_get (live) or a per-case call count the offline fetch layer
tracks; tokens is 0 unless an LLM was actually called (none is, in this build -- the
policy engine and SAR template are both deterministic per PROJECT.md's design); latency_s
is measured with time.perf_counter() around the actual graph.invoke() call for that case.

Cases run in `opened_at` order (README's case memory requirement: an earlier case must be
retrievable by a later one) -- logged explicitly.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

from src.agent.deps import live_deps, offline_deps
from src.agent.graph import build_graph
from src.agent.nodes import NodeDeps
from src.answer.schema import (
    AnswerFile,
    Case,
    Evidence,
    EvidenceRequest,
    NextAction,
    NextBestActions,
    Sar,
)
from src.answer.validator import validate
from src.policy.engine import sar_trigger
from src.sar.narrative import SarFacts, generate_sar

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

VERDICT_THRESHOLDS = (0.85, 0.15)  # >= fraud, <= legitimate, else uncertain


# ---------------------------------------------------------------------------
# case_pack.csv loading
# ---------------------------------------------------------------------------


def load_case_pack(data_dir: Path) -> list[dict]:
    """Load case_pack.csv, sorted by opened_at ascending (README case-memory ordering)."""
    path = data_dir / "case_pack.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"case_pack.csv not found in {data_dir}. Put the organizer's data files in "
            f"{data_dir} (see data/README.md), or point --data-dir at a fixture directory."
        )
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row["risk_score"] = float(row["risk_score"]) if row.get("risk_score") else None
            row["flagged_txn_id"] = _normalize_txn_id(row["flagged_txn_id"])
            rows.append(row)
    rows.sort(key=lambda r: r["opened_at"])
    return rows


def _normalize_txn_id(raw: str) -> str:
    """case_pack.csv's flagged_txn_id column is the bare TransactionID (e.g. 3450629);
    our fixtures/graph use the T-prefixed txn_id form (e.g. T3450629). Normalize once,
    here, rather than letting every downstream consumer guess."""
    raw = str(raw).strip()
    return raw if raw.startswith("T") else f"T{raw}"


def _verdict_from_probability(p: float) -> str:
    if p >= VERDICT_THRESHOLDS[0]:
        return "fraud"
    if p <= VERDICT_THRESHOLDS[1]:
        return "legitimate"
    return "uncertain"


def _status_for(verdict: str, escalated: bool) -> str:
    if escalated:
        return "escalated"
    if verdict == "fraud":
        return "closed_fraud"
    if verdict == "legitimate":
        return "closed_legitimate"
    return "open"


# ---------------------------------------------------------------------------
# running one case
# ---------------------------------------------------------------------------


def run_case(case_id: str, trigger: dict, deps: NodeDeps) -> dict:
    """Invoke the investigation graph for one case and assemble the answer-file dict.

    Returns a plain dict (AnswerFile.to_dict() shape) ready for validation/writing.
    """
    offline_counter = getattr(deps, "tool_call_counter", None)
    if offline_counter is not None:
        counter_reset = offline_counter.counter_reset
        counter_get = offline_counter.counter_get
    else:
        # live mode: src/graph/connection's real counter, driven by run_query() calls.
        # Only imported here (not offline) since it requires pyTigerGraph to be
        # installed -- offline runs must not depend on that package being present.
        from src.graph.connection import counter_get, counter_reset

    counter_reset(case_id)
    start = time.perf_counter()

    graph = build_graph(deps)
    init_state = {"case_id": case_id, "trigger": trigger}
    cfg = {"configurable": {"thread_id": case_id}}
    result = graph.invoke(init_state, config=cfg)

    # policy_gate may pause at interrupt() for L1/L2 actions; auto-approve on resume for
    # the CLI (the agent only *executes* auto actions regardless -- see policy engine
    # finalize_action.executed -- approval here just lets the graph reach `emit`).
    if "__interrupt__" in result:
        from langgraph.types import Command

        result = graph.invoke(Command(resume={"approved": True}), config=cfg)

    latency_s = round(time.perf_counter() - start, 3)
    tool_calls = counter_get(case_id)  # 0 offline (no graph counter increments there);
    # honest zero, not fabricated -- offline fixtures aren't graph calls.

    snapshots = result["snapshots"]
    initial_snap = next((s for s in snapshots if s["phase"] == "initial"), snapshots[0] if snapshots else None)
    final_snap = next((s for s in snapshots if s["phase"] == "final"), initial_snap)

    p_final = final_snap["probability"] if final_snap else result["p_fraud"]
    verdict = _verdict_from_probability(p_final)
    exposure_usd = round(result["exposure_usd"], 2)
    pattern = result["pattern"] if result["pattern"] != "none" or exposure_usd > 0 else "none"
    if verdict == "legitimate":
        # README notes: legitimate => affected_txn_ids empty, exposure 0, pattern reported
        # honestly rather than forced -- but the detector pattern field describes what was
        # *investigated*, not a fraud finding, so we don't relabel it here; we just zero
        # exposure/txn_ids per the schema's own legitimate-verdict rule.
        affected_txn_ids: list[str] = []
        exposure_usd = 0.0
        pattern = "none"
    else:
        affected_txn_ids = list(result["affected_txn_ids"])

    escalated = any(
        a["action"] == "ESCALATE_TO_ANALYST" for a in (final_snap["action_list"] if final_snap else [])
    )
    status = _status_for(verdict, escalated)

    evidence = [
        Evidence(
            claim=e.get("claim", ""),
            source=e.get("source", "graph"),
            ref=e.get("ref", ""),
            entity_ids=[str(i) for i in e.get("entity_ids", [])],
        )
        for e in result["evidence"]
    ]

    pattern_description = ""
    if pattern == "undocumented" and any(
        e.get("ref", "").startswith("detector:threshold_structuring") for e in result["evidence"]
    ):
        from src.detectors.patterns import STRUCTURING_DESCRIPTION
        pattern_description = STRUCTURING_DESCRIPTION
    elif pattern == "undocumented":
        pattern_description = (
            "Activity shares a device profile, billing region, or recipient email across "
            "multiple customers within a short window but does not match any of the five "
            "documented patterns; flagged per R9 as coordinated/repeated abuse across "
            "customers rather than forced into a named category."
        )

    # deps.py's run_detectors tags the "connected card(s)" evidence item with a dedicated
    # ref (device_neighbors(device_id=...)) and puts the actual shared card_ids straight
    # in entity_ids, so extraction here doesn't need to parse ids out of ref strings.
    _DEVICE_ID_REF_RE = re.compile(r"device_neighbors\(device_id=([^)]+)\)")
    connected_card_ids: list[str] = []
    connected_device_profiles: list[str] = []
    for e in result["evidence"]:
        m = _DEVICE_ID_REF_RE.search(e.get("ref", ""))
        if m:
            connected_device_profiles.append(m.group(1))
            connected_card_ids.extend(str(i) for i in e.get("entity_ids", []))
    connected_card_ids = sorted(set(connected_card_ids))
    connected_device_profiles = sorted(set(connected_device_profiles))

    first_suspicious = affected_txn_ids[0] if affected_txn_ids else ""

    summary = _build_summary(case_id, verdict, pattern, exposure_usd, len(affected_txn_ids))
    final_actions = final_snap["action_list"] if final_snap else []
    blocks = [a for a in final_actions if a["action"] in ("BLOCK_CARD", "BLOCK_ALL_CARDS", "DECLINE_TRANSACTION")]
    if verdict == "uncertain" and blocks:
        why = sorted({r.strip() for a in blocks for r in a["reason"].split(",")})
        summary += (
            f" The cardholder denied making the charge, so {'/'.join(a['action'] for a in blocks)} "
            f"is recommended under {', '.join(why)} (route {blocks[0]['route']}, awaiting approval) "
            f"even though the evidence alone stays below the 0.85 fraud threshold."
        ) if "R2" in why else (
            f" {'/'.join(a['action'] for a in blocks)} is recommended under {', '.join(why)} "
            f"(route {blocks[0]['route']}, awaiting approval) although the verdict remains uncertain."
        )

    case = Case(
        status=status,
        verdict=verdict,
        fraud_probability=round(p_final, 4),
        pattern=pattern,
        pattern_description=pattern_description,
        affected_txn_ids=affected_txn_ids,
        first_suspicious_txn_id=first_suspicious,
        connected_card_ids=connected_card_ids,
        connected_device_profiles=[d for d in connected_device_profiles if d],
        exposure_usd=exposure_usd,
        evidence=evidence,
        similar_prior_cases=list(result["prior_cases"]),
        summary=summary,
        written_to_graph=result["written_to_graph"],
        graph_case_id=result["graph_case_id"],
    )

    initial_actions = [NextAction(**a) for a in (initial_snap["action_list"] if initial_snap else [])]
    final_actions = [NextAction(**a) for a in (final_snap["action_list"] if final_snap else [])]
    evidence_requests = [EvidenceRequest(**r) for r in result["evidence_requests"]]

    if not evidence_requests:
        final_actions = list(initial_actions)
        what_changed = "nothing"
    else:
        what_changed = _describe_change(initial_snap, final_snap, evidence_requests)

    nba = NextBestActions(initial=initial_actions, final=final_actions, what_changed=what_changed)

    final_action_names = {a.action for a in final_actions}
    should_file = "FILE_REPORT" in final_action_names
    sar = _build_sar(trigger, case, evidence_requests, should_file)

    stop_reason = _build_stop_reason(evidence_requests, p_final, verdict)

    answer = AnswerFile(
        case_id=case_id,
        case=case,
        evidence_requests=evidence_requests,
        next_best_actions=nba,
        sar=sar,
        stop_reason=stop_reason,
        tool_calls=tool_calls,
        tokens=0,  # no LLM call in this build's deterministic path -- honest zero, not fabricated
        latency_s=latency_s,
    )
    return answer.to_dict()


def _build_summary(case_id: str, verdict: str, pattern: str, exposure_usd: float, n_txns: int) -> str:
    if verdict == "legitimate":
        return f"Investigation of {case_id} found no corroborating evidence of fraud; closed as legitimate."
    if verdict == "fraud":
        return (
            f"Investigation of {case_id} concluded fraud ({pattern}), covering {n_txns} "
            f"transaction(s) totaling ${exposure_usd:,.2f}."
        )
    return (
        f"Investigation of {case_id} could not reach a confident verdict "
        f"({pattern if pattern != 'none' else 'mixed signals'}); escalated per policy."
    )


def _describe_change(initial_snap: dict | None, final_snap: dict | None, requests: list[EvidenceRequest]) -> str:
    if not initial_snap or not final_snap:
        return "nothing"
    p0, p1 = initial_snap["probability"], final_snap["probability"]
    req = requests[-1]
    if p1 > p0:
        return (
            f"The assumed {req.type.replace('_', ' ')} response ({req.assumed_response}) "
            f"raised fraud probability from {p0:.2f} to {p1:.2f}, changing the recommended actions."
        )
    if p1 < p0:
        return (
            f"The assumed {req.type.replace('_', ' ')} response ({req.assumed_response}) "
            f"lowered fraud probability from {p0:.2f} to {p1:.2f}, changing the recommended actions."
        )
    return (
        f"The assumed {req.type.replace('_', ' ')} response ({req.assumed_response}) "
        f"did not move fraud probability (stayed at {p1:.2f}); actions are unchanged from the initial recommendation."
    )


def _build_stop_reason(requests: list[EvidenceRequest], p_final: float, verdict: str) -> str:
    if requests:
        return (
            f"Evidence request settled the question: probability reached {p_final:.2f} "
            f"({verdict}); further steps are unlikely to change the decision."
        )
    if verdict == "fraud":
        return f"Probability {p_final:.2f} with at least two independent evidence sources; stopping per policy §6."
    if verdict == "legitimate":
        return f"Probability {p_final:.2f} with at least two independent evidence sources supporting no fraud; stopping per policy §6."
    return f"Probability {p_final:.2f} remains uncertain after available evidence; escalating rather than continuing indefinitely."


def _build_sar(trigger: dict, case: Case, requests: list[EvidenceRequest], should_file: bool) -> Sar:
    device_profiles = case.connected_device_profiles
    facts = SarFacts(
        customer_id=trigger["customer_id"],
        card_ids=[trigger["card_id"]],
        connected_card_ids=case.connected_card_ids,
        device_profiles=device_profiles,
        pattern=case.pattern,
        pattern_description=case.pattern_description,
        channel="online",
        billing_regions=[],
        mechanism=case.summary,
        why_suspicious=(
            requests[-1].assumed_response if requests else "The evidence gathered is consistent with fraud."
        ),
        affected_txn_ids=case.affected_txn_ids,
        affected_txn_timestamps=[],
        exposure_usd=case.exposure_usd,
        prior_case_ids=case.similar_prior_cases,
        actions_taken=[],
        verdict=case.verdict,
        strongly_suspected=case.fraud_probability >= 0.70,
        shared_device_or_region_or_other_customer=bool(case.connected_card_ids or device_profiles),
    )
    should_file_gate = sar_trigger(
        case.verdict, case.exposure_usd, facts.shared_device_or_region_or_other_customer, case.pattern,
        fraud_probability=case.fraud_probability,
    )
    file_flag = should_file and should_file_gate
    if not file_flag:
        reason = (
            "R2/3a: no FILE_REPORT recommended for this case"
            if not should_file
            else "3a: SAR gate did not fire despite FILE_REPORT in final actions -- treated as no-file"
        )
        return Sar(file=False, reason=reason, narrative="", subjects=[], total_amount_usd=0.0, activity_dates=[])

    if not case.affected_txn_ids:
        return Sar(file=False, reason="3a: no affected transactions to report", narrative="", subjects=[], total_amount_usd=0.0, activity_dates=[])

    dates = [str(trigger["opened_at"])[:10]] * 2
    facts.affected_txn_timestamps = [trigger["opened_at"]] * len(case.affected_txn_ids)
    report = generate_sar(facts)
    if not report.file:
        return Sar(file=False, reason=report.reason, narrative="", subjects=[], total_amount_usd=0.0, activity_dates=[])
    return Sar(
        file=True,
        reason=report.reason,
        narrative=report.narrative,
        subjects=report.subjects,
        total_amount_usd=report.total_amount_usd,
        activity_dates=report.activity_dates or dates,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_valid_ids(data_dir: Path) -> tuple[set[str] | None, set[str] | None]:
    """Best-effort: if closed_cases_history.csv is available, collect its case_ids for
    similar_prior_cases validation. Transaction-id universe validation is skipped when
    transactions.csv isn't present (708MB, not always local) -- validate() already
    handles valid_txn_ids=None by skipping that check rather than failing."""
    case_ids: set[str] | None = None
    history_path = data_dir / "closed_cases_history.csv"
    if history_path.exists():
        with open(history_path, "r", encoding="utf-8", newline="") as f:
            case_ids = {row["case_id"] for row in csv.DictReader(f)}
    return None, case_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fraud investigation agent.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", help="single case_id to run, e.g. HHG-017")
    group.add_argument("--all", action="store_true", help="run every case in case_pack.csv, in opened_at order")
    parser.add_argument("--offline", action="store_true", help="use offline_deps (JSON fixtures, no TigerGraph)")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR), help="directory with case_pack.csv etc. (default: data/)")
    parser.add_argument("--fixture-dir", default=None, help="offline fixture directory (default: <data-dir>/offline)")
    parser.add_argument("--out", default="cases", help="output directory for answer files (default: cases/)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.offline:
        fixture_dir = Path(args.fixture_dir) if args.fixture_dir else data_dir / "offline"
        deps = offline_deps(fixture_dir)
    else:
        deps = live_deps(data_dir)

    all_rows = load_case_pack(data_dir)
    if args.case:
        rows = [r for r in all_rows if r["case_id"] == args.case]
        if not rows:
            print(f"case_id {args.case!r} not found in {data_dir / 'case_pack.csv'}", file=sys.stderr)
            return 2
    else:
        rows = all_rows

    print(
        f"Running {len(rows)} case(s) in opened_at order so an earlier case's evidence "
        f"is retrievable as case memory by a later one: "
        f"{', '.join(r['case_id'] for r in rows)}"
    )

    _, valid_case_ids = _load_valid_ids(data_dir)

    results: list[dict] = []
    failed = False
    for row in rows:
        case_id = row["case_id"]
        answer = run_case(case_id, row, deps)

        # Safety guard: a fixture marked `_synthetic: true` (tests/fixtures/offline/*.json)
        # must never produce an answer file indistinguishable from real organizer output.
        # Stamp it and warn loudly so this can't slip into a submission unnoticed.
        offline_fetch = getattr(deps, "tool_call_counter", None)
        if offline_fetch is not None and getattr(offline_fetch, "is_synthetic", lambda _cid: False)(case_id):
            answer["_synthetic_source"] = True
            print(
                f"\n{'!' * 70}\n"
                f"!! SYNTHETIC FIXTURE WARNING -- case {case_id}\n"
                f"!! This answer file was generated from a SYNTHETIC test fixture,\n"
                f"!! not the organizer's real dataset. It is stamped _synthetic_source:\n"
                f"!! true and MUST NOT be submitted.\n"
                f"{'!' * 70}\n",
                file=sys.stderr,
            )

        violations = validate(answer, valid_txn_ids=None, valid_case_ids=valid_case_ids)
        out_path = out_dir / f"{case_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            import json

            json.dump(answer, f, indent=2, ensure_ascii=False)
        if violations:
            failed = True
            print(f"{case_id}: INVALID ({len(violations)} violation(s))", file=sys.stderr)
            for v in violations:
                print(f"  - {v}", file=sys.stderr)
        else:
            print(f"{case_id}: wrote {out_path} (OK)")
        results.append(answer)

    if len(results) > 1:
        _print_summary(results)

    return 1 if failed else 0


def _print_summary(results: list[dict]) -> None:
    print("\ncase_id      verdict      probability  pattern                        actions  sar")
    print("-" * 90)
    verdict_counts: dict[str, int] = {}
    for r in results:
        c = r["case"]
        verdict_counts[c["verdict"]] = verdict_counts.get(c["verdict"], 0) + 1
        n_actions = len(r["next_best_actions"]["final"])
        sar_flag = "yes" if r["sar"]["file"] else "no"
        print(
            f"{r['case_id']:<12} {c['verdict']:<12} {c['fraud_probability']:<12.2f} "
            f"{c['pattern']:<30} {n_actions:<8} {sar_flag}"
        )

    print("-" * 90)
    print("Aggregate by verdict: " + ", ".join(f"{k}={v}" for k, v in sorted(verdict_counts.items())))

    n_fraud = verdict_counts.get("fraud", 0)
    n_total = len(results)
    if n_total >= 20 and n_fraud > 12:
        print(
            f"\n*** WARNING: {n_fraud}/{n_total} cases came out 'fraud'. The brief states "
            "roughly half the cases are legitimate -- this looks like over-blocking. "
            "Review the evidence thresholds before submitting. ***"
        )


if __name__ == "__main__":
    raise SystemExit(main())
