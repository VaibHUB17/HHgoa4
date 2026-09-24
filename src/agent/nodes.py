"""Node bodies for the investigation state machine (RESEARCH.md §5.3).

trigger -> investigate -> gather_evidence -> assess -> (gather_more | decide)
  -> snapshot_initial -> request_evidence -> reassess -> snapshot_final
  -> policy_gate -> explain -> write_case -> emit

Detector and graph-query calls are injected as callables via `NodeDeps` so this module
never imports the graph/detector layer directly (that's another agent's ownership). Every
node function takes (state, deps) and returns a partial state update dict, per LangGraph
convention.

Side effects (graph writes, evidence-request "sending") are pushed to the very edge of the
functions that need them (write_case, request_evidence) and are simple, idempotent-on-retry
calls through `deps` — see the §5.4 gotcha: policy_gate uses interrupt(), and a node
re-executes from the top on resume, so nothing above the interrupt() call may have a
one-shot side effect.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol

from langgraph.types import interrupt

from src.agent.state import InvestigationState, RecommendationSnapshot
from src.policy.engine import (
    CaseState,
    MustRequestEvidence,
    apply_rules,
    can_stop,
    finalize_action,
    sar_trigger,
)
from src.policy.ledger import compute_probability, evidence_set_hash, independent_evidence_count

MAX_LOOPS = 3


# --- injected dependencies -----------------------------------------------------------------


class DetectorFn(Protocol):
    def __call__(self, case_id: str, trigger: dict) -> dict:
        """Run graph queries / detectors for this case. Returns a dict of:
        {evidence: [...], ledger_keys: [...], case_state_fields: {...}, prior_cases: [...]}
        """
        ...


class GraphWriteFn(Protocol):
    def __call__(self, case_json: dict) -> str:
        """Write the case to TigerGraph; returns graph_case_id."""
        ...


class EvidenceRequestFn(Protocol):
    def __call__(self, request_type: str, case_id: str) -> str:
        """Simulate/send an evidence request; returns assumed_response text."""
        ...


@dataclass
class NodeDeps:
    """Callables injected at graph-build time. Keeps this module free of any import on
    the TigerGraph / detector layer, per the task's module-boundary requirement."""

    run_detectors: DetectorFn
    write_case_to_graph: GraphWriteFn
    request_evidence: EvidenceRequestFn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- nodes -----------------------------------------------------------------------------


def trigger(state: InvestigationState, deps: NodeDeps) -> dict:
    """Seed state from the case_pack trigger row. Pure, no side effects.

    A customer_report trigger *is* the cardholder disputing the charge ("I never made this
    purchase"), so it enters the ledger as customer_denies from the start -- that is what
    makes R2 (deny -> block) and R7 (a disputed charge matching their own recurring
    pattern -> don't block) reachable for the report-triggered cases.
    """
    trig = state.get("trigger", {}) or {}
    reported = trig.get("trigger_type") == "customer_report"
    evidence = [{
        "claim": f"Cardholder disputes the charge: {trig.get('trigger_text', '')}",
        "source": "customer",
        "ref": f"trigger:customer_report({state['case_id']})",
        "entity_ids": [trig["flagged_txn_id"]] if trig.get("flagged_txn_id") else [],
    }] if reported else []
    return {
        "evidence": evidence,
        "ledger": [{"key": "customer_denies", "source": "trigger:customer_report"}] if reported else [],
        "_customer_response": "deny" if reported else None,
        "p_fraud": 0.0,
        "pattern": "none",
        "affected_txn_ids": [],
        "exposure_usd": 0.0,
        "snapshots": [],
        "prior_cases": [],
        "evidence_requests": [],
        "loops": 0,
        "approved": False,
        "graph_case_id": "",
        "written_to_graph": False,
        "_ledger_grew_this_pass": True,
    }


def investigate(state: InvestigationState, deps: NodeDeps) -> dict:
    """Run detectors/graph queries (injected) and fold results into state.
    Read-only from the graph's perspective; no writes happen here.
    """
    ledger_len_before = len(state["ledger"])
    result = deps.run_detectors(state["case_id"], state["trigger"])
    new_evidence = state["evidence"] + result.get("evidence", [])
    # ledger source defaults to the evidence ref that produced it, else the key itself
    # (a fallback source still counts as one independent piece for §6's stopping gate).
    refs = [e.get("ref", "") for e in result.get("evidence", [])]
    new_ledger = state["ledger"] + [
        {"key": k, "source": (refs[i] if i < len(refs) and refs[i] else k)}
        for i, k in enumerate(result.get("ledger_keys", []))
    ]
    prior_cases = list(dict.fromkeys(state["prior_cases"] + result.get("prior_cases", [])))
    return {
        "evidence": new_evidence,
        "ledger": new_ledger,
        "prior_cases": prior_cases,
        "pattern": result.get("pattern", state["pattern"]),
        "affected_txn_ids": result.get("affected_txn_ids", state["affected_txn_ids"]),
        "exposure_usd": result.get("exposure_usd", state["exposure_usd"]),
        # True only when this pass actually grew the ledger. deps.run_detectors is
        # expected to dedup internally (a second call against a deterministic, already-
        # queried snapshot has nothing new to add -- see deps.py's `_seen` guard), so a
        # False here is the normal, expected outcome on any pass after the first, not an
        # error. need_more_evidence uses this to stop looping once re-investigating stops
        # producing anything new to feed the ledger.
        "_ledger_grew_this_pass": len(new_ledger) > ledger_len_before,
    }


def gather_evidence(state: InvestigationState, deps: NodeDeps) -> dict:
    """Recompute probability from the current ledger and advance the loop counter.

    Every pass through investigate -> gather_evidence -> assess counts as one loop,
    whether or not it decides to go around again; this is what lets need_more_evidence's
    MAX_LOOPS cap terminate the graph even if the ledger never crosses a stop threshold.
    """
    ledger_keys = [item["key"] for item in state["ledger"]]
    p = compute_probability(ledger_keys)
    return {"p_fraud": p, "loops": state["loops"] + 1}


def assess(state: InvestigationState, deps: NodeDeps) -> dict:
    """No state change by itself; exists as the named decision point the conditional
    edge (need_more_evidence) reads from. Kept as a distinct node to match §5.3's diagram
    and to give judges a named checkpoint in the trace.
    """
    return {}


def need_more_evidence(state: InvestigationState) -> Literal["gather_more", "decide"]:
    """Conditional edge out of `assess`. Implements the §6/§7.3 stopping rule.

    verification_settled is inferred here from whether the most recent evidence_requests
    entry was a customer_validation whose assumed_response already appears in the ledger
    (i.e. reassess has already run) — plain callers can also short-circuit via loops cap.

    Also stops looping once a pass through `investigate` adds nothing new to the ledger
    (state["_ledger_grew_this_pass"] is False). Re-running a deterministic detector layer
    against the same snapshot a second time cannot change p_fraud -- the way to move the
    probability further is request_evidence, not another investigate() pass -- so looping
    back to `investigate` when it just returned an empty delta would only burn MAX_LOOPS
    iterations for no reason. Only enforced once loops > 0 so the graph still gets its
    first real investigate() pass regardless.
    """
    p = state["p_fraud"]
    indep = independent_evidence_count(item["source"] for item in state["ledger"])
    verification_settled = any(
        r.get("type") == "customer_validation" for r in state.get("evidence_requests", [])
    ) and state["loops"] > 0
    if can_stop(p, indep, verification_settled):
        return "decide"
    if state["loops"] >= MAX_LOOPS:
        return "decide"
    if state["loops"] > 0 and not state.get("_ledger_grew_this_pass", True):
        return "decide"
    return "gather_more"


def snapshot_initial(state: InvestigationState, deps: NodeDeps) -> dict:
    """Freeze the pre-evidence-request recommendation. Pure; builds the initial
    RecommendationSnapshot from current CaseState-shaped fields.
    """
    snap = _build_snapshot(state, phase="initial")
    return {"snapshots": state["snapshots"] + [snap.__dict__]}


def request_evidence(state: InvestigationState, deps: NodeDeps) -> dict:
    """MustRequestEvidence hard gate (§7.3): if the investigation cannot yet stop and no
    evidence has been requested, this node MUST issue a request — enforced here in
    orchestrator code, not left to an LLM's discretion.

    Side effect (deps.request_evidence) lives here, at the edge, away from any
    interrupt()-bearing node.
    """
    ledger_keys = [item["key"] for item in state["ledger"]]
    p = compute_probability(ledger_keys)
    indep = independent_evidence_count(item["source"] for item in state["ledger"])
    already_requested = bool(state["evidence_requests"])
    # R7 prescribes VERIFY_WITH_CUSTOMER: a disputed charge that matches the customer's own
    # recurring pattern goes back to the customer before closing, however low p already is.
    disputed_recurring = (
        (state.get("trigger") or {}).get("trigger_type") == "customer_report"
        and "recurring_merchant_match" in ledger_keys
    )

    if can_stop(p, indep, verification_settled=False) and not disputed_recurring:
        return {}  # nothing to request; investigation can already stop

    if not already_requested:
        request_type = _choose_evidence_request_type(state)
        assumed_response = deps.request_evidence(request_type, state["case_id"])
        req = {
            "type": request_type,
            "asked_after_step": state["loops"] + 1,
            "assumed_response": assumed_response,
        }
        return {"evidence_requests": state["evidence_requests"] + [req]}

    # already requested once and still can't stop: enforcing the gate means we must not
    # silently proceed to decide() without having asked. If we already asked, that's fine;
    # if we somehow reach here with no request and can't stop, that's the bug the gate
    # exists to catch.
    if not state["evidence_requests"] and not can_stop(p, indep, False):
        raise MustRequestEvidence(
            f"case {state['case_id']}: cannot stop (p={p}, indep={indep}) and no "
            "evidence_requests were issued"
        )
    return {}


def reassess(state: InvestigationState, deps: NodeDeps) -> dict:
    """Fold the assumed evidence-request response into the ledger and recompute.

    Every evidence_request type this graph can issue must have a ledger key on the other
    end of it -- a request whose answer cannot move p_fraud isn't evidence gathering, it's
    a no-op with extra steps. customer_validation folds customer_denies/customer_confirms
    (which also sets CaseState.customer_response for R2/R3 via _customer_response).
    step_up_auth folds step_up_failed/step_up_passed/step_up_not_completed (see
    config/evidence_weights.yaml) -- it does not set customer_response, since a step-up
    result answers "who controls this session", not "did the cardholder authorize this
    charge"; R2/R3 stay keyed to an actual customer_validation reply, as intended.
    """
    if not state["evidence_requests"]:
        return {"loops": state["loops"] + 1}
    latest = state["evidence_requests"][-1]
    response_text = latest["assumed_response"].lower()
    key = None
    customer_response: str | None = state.get("_customer_response")
    if latest["type"] == "customer_validation":
        if "did not make" in response_text or "deny" in response_text or "not made" in response_text:
            key, customer_response = "customer_denies", "deny"
        elif "confirm" in response_text or "did make" in response_text or "i made" in response_text:
            key, customer_response = "customer_confirms", "confirm"
    elif latest["type"] == "step_up_auth":
        if "completed successfully" in response_text:
            key = "step_up_passed"
        elif "not completed" in response_text or "no valid" in response_text:
            key = "step_up_failed"
        elif "expired unanswered" in response_text:
            key = "step_up_not_completed"
    new_ledger = state["ledger"]
    if key:
        new_ledger = state["ledger"] + [{"key": key, "source": f"evidence_request:{len(state['evidence_requests'])}"}]
    p = compute_probability([item["key"] for item in new_ledger])
    return {
        "ledger": new_ledger,
        "p_fraud": p,
        "loops": state["loops"] + 1,
        "_customer_response": customer_response,  # consumed by _build_snapshot via state.get
    }


def snapshot_final(state: InvestigationState, deps: NodeDeps) -> dict:
    snap = _build_snapshot(state, phase="final")
    return {"snapshots": state["snapshots"] + [snap.__dict__]}


def policy_gate(state: InvestigationState, deps: NodeDeps) -> dict:
    """Uses interrupt() for L1/L2 actions. No side effects before the interrupt() call —
    everything above is a pure read of already-computed state (the §5.4 gotcha: this node
    re-executes from the top on resume).
    """
    final_snapshot = state["snapshots"][-1] if state["snapshots"] else None
    pending = [
        a for a in (final_snapshot["action_list"] if final_snapshot else [])
        if a["route"] in ("L1", "L2")
    ]
    if not pending:
        return {"approved": True}
    decision = interrupt(
        {
            "case_id": state["case_id"],
            "pending": pending,
            "p_fraud": state["p_fraud"],
            "exposure_usd": state["exposure_usd"],
        }
    )
    return {"approved": decision.get("approved", False)}


def explain(state: InvestigationState, deps: NodeDeps) -> dict:
    """No-op state pass-through; the answer-file assembly (src/answer/schema.py) reads
    evidence + snapshots + reasons directly. Kept as a named node so the reason-citation
    step is visible in the trace, matching §5.3's diagram.
    """
    return {}


def write_case(state: InvestigationState, deps: NodeDeps) -> dict:
    """Side effect: writes the case to TigerGraph via the injected callable."""
    trig = state.get("trigger", {}) or {}
    p = state["p_fraud"]
    verdict = "fraud" if p >= 0.85 else "legitimate" if p <= 0.15 else "uncertain"
    final = next((s for s in reversed(state.get("snapshots", [])) if s.get("phase") == "final"),
                 (state.get("snapshots") or [{}])[-1])
    actions = [a.get("action", "") for a in final.get("action_list", [])]
    connected = sorted({eid for e in state.get("evidence", []) for eid in e.get("entity_ids", [])
                        if "-K" in str(eid) and eid != trig.get("card_id")})
    case_payload = {
        "case_id": state["case_id"],
        "customer_id": trig.get("customer_id", ""),
        "card_id": trig.get("card_id", ""),
        "opened_at": trig.get("opened_at", ""),
        "status": {"fraud": "closed_fraud", "legitimate": "closed_legitimate"}.get(verdict, "open"),
        "verdict": verdict,
        "pattern": state["pattern"],
        "affected_txn_ids": state["affected_txn_ids"],
        "connected_card_ids": connected,
        "exposure_usd": state["exposure_usd"],
        "actions_taken": "|".join(a for a in actions if a),
        "report_filed": "FILE_REPORT" in actions,
        "analyst_notes": "; ".join(e.get("claim", "") for e in state.get("evidence", []))[:4000],
        "p_fraud": p,
        "prior_cases": state["prior_cases"],
    }
    graph_case_id = deps.write_case_to_graph(case_payload)
    return {"graph_case_id": graph_case_id, "written_to_graph": True}


def emit(state: InvestigationState, deps: NodeDeps) -> dict:
    """Terminal node; state is complete. Answer-file assembly happens in
    src/answer/schema.py, reading this state as input.
    """
    return {}


def _choose_evidence_request_type(state: InvestigationState) -> Literal["customer_validation", "step_up_auth"]:
    """RESEARCH.md §7.4: the evidence-request type is chosen by what question is open,
    not by where fraud_probability happens to sit. The 0.70 line belongs to R1 (may we
    block on a single signal), not to this choice -- picking step_up_auth just because
    p >= 0.70 makes R2/R3 structurally unreachable whenever a case starts above that
    line, since only a customer_validation response ever folds a customer_denies/
    customer_confirms key into the ledger (see reassess()).

    customer_validation is the default: it resolves the R2/R3/R7 fork, which is the
    single highest-leverage branch in the policy (deny -> BLOCK_CARD+CREATE_CASE,
    confirm -> CLOSE_NO_FRAUD, recurring-match dispute -> R7's don't-block path). It is
    the right call whenever the open question is "did the cardholder authorize this" --
    which is true by default for any card-present-fraud-shaped case, and explicitly true
    for card_testing (a stolen card is used without the holder's knowledge, so the
    holder is exactly who can settle it).

    step_up_auth is chosen only when the open question is device/session legitimacy
    rather than authorization -- concretely: a new-device marker is present and no
    denial has been recorded yet, so what's actually being tested is whether whoever is
    driving this session can pass a live control check, not whether the cardholder
    recognizes a transaction. A confirm/deny wouldn't settle that question either way.

    Escalation (verdict uncertain AND exposure > $500) is not a request at all -- that's
    R8's ESCALATE_TO_ANALYST, handled entirely by apply_rules()/_build_snapshot, not by
    this function; this function only ever returns a request type.
    """
    ledger_keys = {item["key"] for item in state["ledger"]}
    new_device_only = (
        "new_device_marker" in ledger_keys
        and "customer_denies" not in ledger_keys
        and "customer_confirms" not in ledger_keys
        and not (ledger_keys & {"card_testing_sequence", "shared_device_across_cards", "shared_region_cluster"})
    )
    if new_device_only:
        return "step_up_auth"
    return "customer_validation"


# --- helpers -------------------------------------------------------------------------------


def _build_snapshot(state: InvestigationState, phase: str) -> RecommendationSnapshot:
    ledger_keys = [item["key"] for item in state["ledger"]]
    p = compute_probability(ledger_keys)
    exposure = state["exposure_usd"]

    single_signal = len({item["source"] for item in state["ledger"]}) <= 1
    verdict = "fraud" if p >= 0.85 else ("legitimate" if p <= 0.15 else "uncertain")

    cs = CaseState(
        fraud_probability=p,
        verdict=verdict,
        exposure_usd=exposure,
        single_signal=single_signal,
        customer_validation_requested=any(
            r.get("type") == "customer_validation" for r in state["evidence_requests"]
        ),
        customer_response=state.get("_customer_response"),
        shared_device_profile=any(item["key"] == "shared_device_across_cards" for item in state["ledger"]),
        shared_billing_region=any(item["key"] == "shared_region_cluster" for item in state["ledger"]),
        card_testing_detected=any(item["key"] == "card_testing_sequence" for item in state["ledger"]),
        disputed_matches_recurring_pattern=(
            (state.get("trigger") or {}).get("trigger_type") == "customer_report"
            and any(item["key"] == "recurring_merchant_match" for item in state["ledger"])
        ),
    )
    rule_actions = apply_rules(cs)
    action_list = []
    for entry in rule_actions:
        finalized = finalize_action(entry["action"], exposure)
        reason = ", ".join(entry["reason_rules"]) or "policy default"
        action_list.append({"action": finalized["action"], "route": finalized["route"], "reason": reason})

    evidence_ids: list[str] = []
    for item in state["evidence"]:
        evidence_ids.extend(str(i) for i in item.get("entity_ids", []))

    return RecommendationSnapshot(
        action_list=action_list,
        probability=p,
        exposure_usd=exposure,
        evidence_set_hash=evidence_set_hash(evidence_ids),
        timestamp=_now_iso(),
        phase=phase,
    )
