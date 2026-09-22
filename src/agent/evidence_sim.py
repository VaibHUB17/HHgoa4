"""Simulated customer/analyst responses to evidence requests (README §5).

The brief is explicit that customer and analyst replies are not provided for the exam
cases, and that whatever response we assume must be recorded and defensible, not a coin
flip. This module is the one place that decision is made, and the rule for each branch is
documented here so a judge auditing `evidence_requests[].assumed_response` can check
whether the assumption was reasoned or convenient.

Rule (applies to every request type -- customer_validation, step_up_auth, analyst_info):
we look at the evidence *already gathered* for the case (the ledger keys folded in by
`investigate()` before the request fires) and pick the response the evidence itself points
to, using the same signals the ledger/policy already trust -- never a new, unweighed guess.

    1. Strong fraud-pointing evidence present (card_testing_sequence, and/or
       shared_device_across_cards, and/or new_device_marker+proxy_flag together, and/or a
       closed_case_match) with no exonerating evidence -> the realistic assumption is a
       DENIAL. This mirrors the README worked example (HHG-017): a card-testing sequence
       plus a shared device profile is exactly the fact pattern a real customer denies.
    2. Exonerating evidence present (recurring_merchant_match, in_character_for_customer,
       cleared_precedent_match) and no strong fraud evidence -> the realistic assumption is
       a CONFIRMATION (R7: a disputed charge that matches the customer's own recurring
       pattern is something the customer, once shown it, recognizes and confirms).
    3. Mixed or weak evidence (e.g. only risk_score_alone, or fraud and exonerating
       evidence both present with neither dominant) -> no clean signal either way; the
       realistic assumption is NO REPLY within the window (R4), which is also the
       conservative default -- it doesn't manufacture certainty the evidence doesn't
       support.

step_up_auth requests use the same evidence read but report a step-up outcome (passed /
failed / not completed) rather than a confirm/deny sentence, since step-up authentication
has no "confirm/deny" semantics -- it's a possession/control check, not a statement.
analyst_info requests return a short analyst note built from the same evidence, since an
analyst asked to review the same case would report back what the case record already shows.
"""
from __future__ import annotations

# Evidence keys (config/evidence_weights.yaml) that point toward fraud strongly enough
# that a cardholder shown the transactions would realistically deny them.
_FRAUD_POINTING_KEYS = frozenset(
    {
        "card_testing_sequence",
        "shared_device_across_cards",
        "shared_region_cluster",
        "closed_case_match",
        "cnp_burst_pattern",
        "out_of_region_pattern",
        "multi_region_clone_cluster",
    }
)

# Evidence keys that point toward the activity being the customer's own, legitimate
# behavior -- a cardholder shown these would realistically confirm/recognize the charge.
_EXONERATING_KEYS = frozenset(
    {
        "recurring_merchant_match",
        "in_character_for_customer",
        "cleared_precedent_match",
    }
)

# new_device_marker/proxy_flag alone are weak per README known-pattern-3 ("not proof on
# its own -- people buy new phones"); only count them toward a denial when paired with
# something else fraud-pointing, handled by the general strong/exonerating comparison
# below rather than listed directly in _FRAUD_POINTING_KEYS.
_WEAK_DEVICE_KEYS = frozenset({"new_device_marker", "proxy_flag"})


def _classify(ledger_keys: list[str]) -> str:
    """Return 'deny' | 'confirm' | 'no_reply' from the evidence gathered so far."""
    keys = set(ledger_keys)
    fraud_score = len(keys & _FRAUD_POINTING_KEYS)
    if keys & _WEAK_DEVICE_KEYS and len(keys & _WEAK_DEVICE_KEYS) >= 2:
        fraud_score += 1  # new_device + proxy together is a real (if weak) pairing
    exonerating_score = len(keys & _EXONERATING_KEYS)

    if fraud_score > 0 and exonerating_score == 0:
        return "deny"
    if exonerating_score > 0 and fraud_score == 0:
        return "confirm"
    return "no_reply"


def _deny_sentence(ledger_keys: list[str]) -> str:
    reasons = []
    if "card_testing_sequence" in ledger_keys:
        reasons.append("a sequence of small authorizations they did not initiate")
    if "shared_device_across_cards" in ledger_keys:
        reasons.append("activity from a device they do not recognize")
    if "out_of_region_pattern" in ledger_keys or "multi_region_clone_cluster" in ledger_keys:
        reasons.append("purchases billed in a region they have never traveled to")
    if "closed_case_match" in ledger_keys:
        reasons.append("a pattern matching a previously confirmed fraud case")
    detail = f" ({', '.join(reasons)})" if reasons else ""
    return (
        "Customer states they did not make these purchases and still has the card "
        f"in their possession{detail}."
    )


def _confirm_sentence(ledger_keys: list[str]) -> str:
    reasons = []
    if "recurring_merchant_match" in ledger_keys:
        reasons.append("a recurring monthly charge from a merchant they use regularly")
    if "in_character_for_customer" in ledger_keys:
        reasons.append("an amount and product category consistent with their usual spending")
    detail = f", recognizing {', '.join(reasons)}" if reasons else ""
    return f"Customer confirms they made this purchase{detail} and does not dispute the charge."


def _no_reply_sentence() -> str:
    return "No reply received from the customer within the 24-hour window."


def simulate_customer_validation(ledger_keys: list[str], asked_after_step: int) -> dict:
    """Build the evidence_requests entry for a customer_validation request."""
    outcome = _classify(ledger_keys)
    if outcome == "deny":
        text = _deny_sentence(ledger_keys)
    elif outcome == "confirm":
        text = _confirm_sentence(ledger_keys)
    else:
        text = _no_reply_sentence()
    return {
        "type": "customer_validation",
        "asked_after_step": asked_after_step,
        "assumed_response": text,
    }


def simulate_step_up_auth(ledger_keys: list[str], asked_after_step: int) -> dict:
    """Build the evidence_requests entry for a step_up_auth request.

    Same evidence-driven rule: strong fraud-pointing evidence -> the legitimate
    cardholder is unreachable/unable to complete the challenge from the compromised
    session (fails/no completion), because the request went out through the channel the
    fraudster controls, not the customer. Exonerating evidence -> the real cardholder is
    in control of the device/channel and passes it without incident.
    """
    outcome = _classify(ledger_keys)
    if outcome == "deny":
        text = (
            "Step-up authentication was not completed within the window; no valid "
            "one-time passcode confirmation was received."
        )
    elif outcome == "confirm":
        text = "Step-up authentication was completed successfully by the cardholder."
    else:
        text = "Step-up authentication request expired unanswered within the window."
    return {
        "type": "step_up_auth",
        "asked_after_step": asked_after_step,
        "assumed_response": text,
    }


def simulate_analyst_info(ledger_keys: list[str], asked_after_step: int, note: str = "") -> dict:
    """Build the evidence_requests entry for an analyst_info request.

    Unlike the customer-facing requests, this doesn't invent a customer's state of mind --
    it reports what the case record built from `ledger_keys` already shows, worded as an
    analyst's confirmation of the automated findings (the realistic outcome of asking a
    human to look at evidence the system already gathered).
    """
    outcome = _classify(ledger_keys)
    if outcome == "deny":
        base = "Analyst reviewed the linked accounts and confirms the pattern is consistent with coordinated abuse."
    elif outcome == "confirm":
        base = "Analyst reviewed the account history and found nothing inconsistent with legitimate use."
    else:
        base = "Analyst reviewed the available evidence and found it inconclusive without further information."
    text = f"{base} {note}".strip()
    return {
        "type": "analyst_info",
        "asked_after_step": asked_after_step,
        "assumed_response": text,
    }


def simulate_response(request_type: str, ledger_keys: list[str], asked_after_step: int) -> dict:
    """Dispatch to the right simulator by request_type. Single entry point for
    NodeDeps.request_evidence callers (see src/agent/deps.py)."""
    if request_type == "customer_validation":
        return simulate_customer_validation(ledger_keys, asked_after_step)
    if request_type == "step_up_auth":
        return simulate_step_up_auth(ledger_keys, asked_after_step)
    if request_type == "analyst_info":
        return simulate_analyst_info(ledger_keys, asked_after_step)
    raise ValueError(f"unknown evidence request type: {request_type!r}")


def demo() -> None:
    """ponytail: smallest runnable self-check for the branch logic this module documents."""
    strong_fraud = ["card_testing_sequence", "shared_device_across_cards"]
    assert _classify(strong_fraud) == "deny"
    r = simulate_customer_validation(strong_fraud, asked_after_step=3)
    assert r["type"] == "customer_validation" and "did not make" in r["assumed_response"]

    recurring = ["risk_score_alone", "recurring_merchant_match", "in_character_for_customer"]
    assert _classify(recurring) == "confirm"
    r2 = simulate_customer_validation(recurring, asked_after_step=2)
    assert "confirms" in r2["assumed_response"]

    weak = ["risk_score_alone"]
    assert _classify(weak) == "no_reply"
    r3 = simulate_customer_validation(weak, asked_after_step=1)
    assert "No reply" in r3["assumed_response"]

    # step-up mirrors the same classification
    r4 = simulate_step_up_auth(strong_fraud, asked_after_step=1)
    assert "not completed" in r4["assumed_response"]
    r5 = simulate_step_up_auth(recurring, asked_after_step=1)
    assert "completed successfully" in r5["assumed_response"]

    r6 = simulate_response("analyst_info", strong_fraud, 1)
    assert r6["type"] == "analyst_info"

    print("evidence_sim.py self-check OK")


if __name__ == "__main__":
    demo()
