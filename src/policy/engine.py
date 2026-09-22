"""Policy engine: R1-R10 as predicate functions over a case-state object.

Every function here is a pure decision over typed fields — no LLM calls, no graph calls.
Thresholds are copied verbatim from README.md's Fraud Policy section; see the docstring on
each rule for the exact wording it implements. Boundaries matter: read the comparison
operators literally (>, >=, <=) before touching them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Route = Literal["auto", "L1", "L2"]

# --- action routes, per README §2 --------------------------------------------------------
_AUTO_ACTIONS = {
    "ALLOW_TRANSACTION",
    "MONITOR_CARD",
    "MONITOR_CONNECTED_CARDS",
    "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER",
    "STEP_UP_AUTH",
    "GENERATE_REPORT",
    "CREATE_CASE",
    "ESCALATE_TO_ANALYST",
    "CLOSE_NO_FRAUD",
}
_L1_FIXED_ACTIONS = {"DECLINE_TRANSACTION"}
_L2_FIXED_ACTIONS = {"BLOCK_ALL_CARDS", "FILE_REPORT"}

ALL_ACTIONS = _AUTO_ACTIONS | _L1_FIXED_ACTIONS | _L2_FIXED_ACTIONS | {"BLOCK_CARD"}
assert len(ALL_ACTIONS) == 14, "the policy defines exactly 14 action identifiers"


def resolve_route(action: str, exposure_usd: float) -> Route:
    """Approval routing per README §2.

    BLOCK_CARD: exposure <= 2500 -> L1, exposure > 2500 -> L2 (exact boundary at 2500;
    2500.00 itself is L1, 2500.01 is L2).
    """
    if action == "BLOCK_CARD":
        return "L1" if exposure_usd <= 2500 else "L2"
    if action in _AUTO_ACTIONS:
        return "auto"
    if action in _L1_FIXED_ACTIONS:
        return "L1"
    if action in _L2_FIXED_ACTIONS:
        return "L2"
    raise ValueError(f"unknown action identifier: {action!r}")


def finalize_action(action: str, exposure_usd: float = 0.0) -> dict:
    """{action, route, executed} — executed is True only for auto routes."""
    route = resolve_route(action, exposure_usd)
    return {"action": action, "route": route, "executed": route == "auto"}


# --- case state --------------------------------------------------------------------------


@dataclass
class CaseState:
    """Minimal set of typed fields the R1-R10 predicates read.

    This is intentionally a plain dataclass, not the LangGraph InvestigationState —
    engine.py must not import the agent layer. src/agent/nodes.py adapts
    InvestigationState -> CaseState (or reads/writes the same field names) at the call site.
    """

    fraud_probability: float = 0.0
    verdict: Literal["fraud", "legitimate", "uncertain"] = "uncertain"
    exposure_usd: float = 0.0

    single_signal: bool = False  # case rests on one signal only (incl. risk score alone)

    # evidence-request / response state
    customer_validation_requested: bool = False
    customer_response: Literal["deny", "confirm", "no_reply", None] = None
    no_reply_within_24h: bool = False

    # pattern / motif flags
    card_testing_detected: bool = False
    purchase_over_100_already_cleared: bool = False
    shared_device_profile: bool = False
    shared_billing_region: bool = False
    shared_recipient_email: bool = False
    shared_element_name: str = ""  # e.g. "device profile D000731" — must be named per R6
    other_card_fraud: bool = False
    disputed_matches_recurring_pattern: bool = False  # R7: same merchant/amount, monthly
    evidence_conflicts: bool = False
    fits_no_known_pattern: bool = False
    coordinated_or_repeated_abuse_across_customers: bool = False

    # R10 guard inputs
    block_all_cards_proposed: bool = False
    two_plus_cards_confirmed_fraud: bool = False
    credentials_confirmed_compromised: bool = False

    fired_rules: list[str] = field(default_factory=list)


# --- R1-R10 -------------------------------------------------------------------------------


def rule_r1(s: CaseState) -> list[str]:
    """R1. Verify before you block on a weak signal.

    predicate: single_signal AND fraud_probability < 0.70
    """
    if s.single_signal and s.fraud_probability < 0.70:
        return ["VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH"]
    return []


def rule_r2(s: CaseState) -> list[str]:
    """R2. Customer denies the transaction.

    predicate: customer_validation requested AND response == deny
    add FILE_REPORT if exposure_usd > 1000 OR shared_device_profile OR other_card_fraud
    """
    if s.customer_validation_requested and s.customer_response == "deny":
        actions = ["BLOCK_CARD", "CREATE_CASE"]
        if s.exposure_usd > 1000 or s.shared_device_profile or s.other_card_fraud:
            actions.append("FILE_REPORT")
        return actions
    return []


def rule_r3(s: CaseState) -> list[str]:
    """R3. Customer confirms the transaction. -> CLOSE_NO_FRAUD"""
    if s.customer_response == "confirm":
        return ["CLOSE_NO_FRAUD"]
    return []


def rule_r4(s: CaseState) -> list[str]:
    """R4. No reply within 24 hours.

    -> MONITOR_CARD, DECLINE_TRANSACTION; add ESCALATE_TO_ANALYST if exposure_usd > 500
    """
    if s.no_reply_within_24h:
        actions = ["MONITOR_CARD", "DECLINE_TRANSACTION"]
        if s.exposure_usd > 500:
            actions.append("ESCALATE_TO_ANALYST")
        return actions
    return []


def rule_r5(s: CaseState) -> list[str]:
    """R5. Card testing.

    3+ small online authorizations on one card within an hour, then a larger purchase:
    -> DECLINE_TRANSACTION, STEP_UP_AUTH.
    override: if a purchase over $100 has already cleared -> BLOCK_CARD instead.
    """
    if not s.card_testing_detected:
        return []
    if s.purchase_over_100_already_cleared:
        return ["BLOCK_CARD"]
    return ["DECLINE_TRANSACTION", "STEP_UP_AUTH"]


def rule_r6(s: CaseState) -> list[str]:
    """R6. Shared origin.

    predicate: shared device_profile OR billing_region OR recipient_email across cards
    in one window. Caller must record the named shared element in evidence
    (CaseState.shared_element_name) — the rule fires regardless, but omitting the name
    is a reporting bug, not a predicate failure.
    """
    if s.shared_device_profile or s.shared_billing_region or s.shared_recipient_email:
        return ["CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS"]
    return []


def rule_r7(s: CaseState) -> list[str]:
    """R7. Disputed but legitimate.

    predicate: dispute matches the customer's own recurring pattern (same merchant,
    same amount, monthly) -> CREATE_CASE, VERIFY_WITH_CUSTOMER, WARN_CUSTOMER.
    Do not block: forbids BLOCK_CARD and DECLINE_TRANSACTION downstream (see apply_rules).
    """
    if s.disputed_matches_recurring_pattern:
        return ["CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"]
    return []


def rule_r7_forbidden_actions(s: CaseState) -> set[str]:
    """Actions R7 forbids outright, if it fires."""
    if s.disputed_matches_recurring_pattern:
        return {"BLOCK_CARD", "DECLINE_TRANSACTION"}
    return set()


def rule_r8(s: CaseState) -> list[str]:
    """R8. Escalate when uncertain and exposed.

    predicate: verdict == uncertain AND exposure_usd > 500, OR evidence_conflicts
    """
    if (s.verdict == "uncertain" and s.exposure_usd > 500) or s.evidence_conflicts:
        return ["ESCALATE_TO_ANALYST"]
    return []


def rule_r9(s: CaseState) -> list[str]:
    """R9. Undocumented patterns.

    predicate: fits none of the 5 known patterns AND coordinated/repeated abuse
    across customers -> CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST.
    Caller must set case.pattern = "undocumented" and provide pattern_description.
    """
    if s.fits_no_known_pattern and s.coordinated_or_repeated_abuse_across_customers:
        return ["CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"]
    return []


def rule_r10_guard_ok(s: CaseState) -> bool:
    """R10 guard: BLOCK_ALL_CARDS only allowed if >=2 cards confirmed fraud
    OR credentials confirmed compromised."""
    return s.two_plus_cards_confirmed_fraud or s.credentials_confirmed_compromised


def apply_r10(actions: list[str], s: CaseState) -> list[str]:
    """R10. Never BLOCK_ALL_CARDS unless the guard holds; else downgrade to BLOCK_CARD."""
    if "BLOCK_ALL_CARDS" not in actions and not s.block_all_cards_proposed:
        return actions
    if rule_r10_guard_ok(s):
        return actions
    downgraded = []
    for a in actions:
        downgraded.append("BLOCK_CARD" if a == "BLOCK_ALL_CARDS" else a)
    if s.block_all_cards_proposed and "BLOCK_ALL_CARDS" not in actions and "BLOCK_CARD" not in downgraded:
        downgraded.append("BLOCK_CARD")
    return downgraded


_RULES = {
    "R1": rule_r1,
    "R2": rule_r2,
    "R3": rule_r3,
    "R4": rule_r4,
    "R5": rule_r5,
    "R6": rule_r6,
    "R7": rule_r7,
    "R8": rule_r8,
    "R9": rule_r9,
}


def apply_rules(s: CaseState) -> list[dict]:
    """Run R1-R9 in order, dedupe/forbid/guard, return ordered [{action, reason}, ...].

    - R7's forbid list strips BLOCK_CARD/DECLINE_TRANSACTION from every other rule's output
      when R7 fires (a recurring-charge dispute must never be blocked, even if e.g. R5 also
      matched on stale evidence).
    - R10 downgrades BLOCK_ALL_CARDS -> BLOCK_CARD when its guard fails.
    - Order preserved: first rule to propose an action wins position; reason strings record
      every rule that proposed it.
    """
    forbidden = rule_r7_forbidden_actions(s)
    ordered_actions: list[str] = []
    reasons: dict[str, list[str]] = {}

    for rule_id, fn in _RULES.items():
        for action in fn(s):
            if action in forbidden:
                continue
            if action not in ordered_actions:
                ordered_actions.append(action)
                reasons[action] = []
            reasons[action].append(rule_id)

    ordered_actions = apply_r10(ordered_actions, s)
    if "BLOCK_CARD" in ordered_actions and "BLOCK_ALL_CARDS" not in reasons:
        reasons.setdefault("BLOCK_CARD", []).append("R10")

    return [
        {"action": a, "reason_rules": reasons.get(a, [])}
        for a in ordered_actions
    ]


# --- SAR trigger, §3a ----------------------------------------------------------------------


def sar_trigger(
    verdict: str,
    exposure_usd: float,
    shared_device_or_region_or_other_customer_fraud: bool,
    pattern: str,
) -> bool:
    """File a SAR when fraud is confirmed or strongly suspected AND at least one of:
    exposure_usd > 1000; shared device/region/other-customer fraud; pattern is
    coordinated/undocumented (R9).

    "strongly suspected" is read as verdict == "fraud" (this engine has no separate
    strongly_suspected state; see engine.py report for the ambiguity note).
    """
    if verdict != "fraud":
        return False
    return (
        exposure_usd > 1000
        or shared_device_or_region_or_other_customer_fraud
        or pattern == "undocumented"
    )


# --- stopping, §6 / §7.3 -------------------------------------------------------------------


def can_stop(p: float, independent_evidence_count: int, verification_settled: bool) -> bool:
    """§6 stopping rule, exactly as specified in RESEARCH.md §7.3:

    - verification_settled -> stop
    - (p >= 0.85 or p <= 0.15) AND independent_evidence_count >= 2 -> stop
    - else -> keep going
    """
    if verification_settled:
        return True
    if independent_evidence_count >= 2 and (p >= 0.85 or p <= 0.15):
        return True
    return False


class MustRequestEvidence(Exception):
    """Raised by orchestrator code when the investigation cannot stop yet and no
    evidence has been requested. Enforced in code (src/agent/nodes.py), not a prompt."""


def demo() -> None:
    """ponytail: smallest runnable self-check for engine.py's money-path logic."""
    assert resolve_route("BLOCK_CARD", 2500) == "L1"
    assert resolve_route("BLOCK_CARD", 2500.01) == "L2"
    assert resolve_route("FILE_REPORT", 0) == "L2"
    assert resolve_route("CREATE_CASE", 0) == "auto"
    assert finalize_action("ALLOW_TRANSACTION")["executed"] is True
    assert finalize_action("DECLINE_TRANSACTION")["executed"] is False

    s = CaseState(single_signal=True, fraud_probability=0.45)
    assert rule_r1(s) == ["VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH"]

    s2 = CaseState(customer_validation_requested=True, customer_response="deny", exposure_usd=100)
    assert rule_r2(s2) == ["BLOCK_CARD", "CREATE_CASE"]
    s3 = CaseState(customer_validation_requested=True, customer_response="deny", exposure_usd=1500)
    assert "FILE_REPORT" in rule_r2(s3)

    s4 = CaseState(disputed_matches_recurring_pattern=True, card_testing_detected=True,
                    purchase_over_100_already_cleared=True)
    result = apply_rules(s4)
    actions = [r["action"] for r in result]
    assert "BLOCK_CARD" not in actions, "R7 must forbid BLOCK_CARD even if R5 also fired"
    assert "DECLINE_TRANSACTION" not in actions

    s5 = CaseState(block_all_cards_proposed=True, two_plus_cards_confirmed_fraud=False,
                    credentials_confirmed_compromised=False)
    r10_result = apply_r10(["BLOCK_ALL_CARDS"], s5)
    assert r10_result == ["BLOCK_CARD"], "R10 must downgrade when guard fails"

    assert sar_trigger("fraud", 1001, False, "card_testing") is True
    assert sar_trigger("fraud", 1000, False, "card_testing") is False

    assert can_stop(0.85, 2, False) is True
    assert can_stop(0.85, 1, False) is False
    assert can_stop(0.5, 5, False) is False
    assert can_stop(0.2, 0, True) is True
    print("engine.py self-check OK")


if __name__ == "__main__":
    demo()
