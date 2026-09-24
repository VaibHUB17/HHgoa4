"""SAR generation (RESEARCH.md 6.5c), FinCEN who/what/when/where/how/why structure.

The narrative is built from the structured evidence chain, not free-form LLM prose --
every ID in the output must be traceable to an input, so a `render_fn` (defaults to a
deterministic template, swappable for an LLM call that only rephrases already-assembled
facts) never introduces an ID that wasn't already in the SarFacts it was given. That's
what "the LLM's job is to render, not invent" means operationally: subjects/dates/amount
are computed in Python from typed fields, and any render_fn is checked afterward for
hallucinated IDs.

Gate: file_report() implements the README section 3a trigger --
    (confirmed OR strongly_suspected) AND
    (exposure_usd > 1000 OR shared_device_or_region_or_other_customer OR pattern == undocumented)

Fields: subjects = every ID named in the narrative; total_amount_usd = exposure_usd;
activity_dates = [min(ts), max(ts)] over affected_txn_ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Sequence

MIN_SENTENCES = 6
MAX_SENTENCES = 12


@dataclass
class SarFacts:
    """Everything the narrative is built from. Every field here is a value already
    established elsewhere in the investigation (graph query results, the ledger, the
    case record) -- narrative.py assembles and renders, it does not discover new facts."""

    customer_id: str
    card_ids: list[str]
    connected_card_ids: list[str]
    device_profiles: list[str]
    pattern: str                       # enum value, e.g. "card_testing" | "undocumented"
    pattern_description: str = ""      # required narrative color when pattern == undocumented
    channel: str = "online"            # "online" | "in_person" | "mixed"
    billing_regions: list[str] = field(default_factory=list)
    mechanism: str = ""                # one sentence: how the fraud was carried out
    why_suspicious: str = ""           # one sentence: what confirmed it / ruled out innocence
    affected_txn_ids: list[str] = field(default_factory=list)
    affected_txn_timestamps: list[str] = field(default_factory=list)  # parallel to affected_txn_ids, ISO-ish
    exposure_usd: float = 0.0
    prior_case_ids: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)  # e.g. ["Card blocked and scheduled for reissue"]
    verdict: str = "fraud"             # "fraud" | "legitimate" | "uncertain"
    strongly_suspected: bool = False   # true if not fully confirmed but evidence is strong
    shared_device_or_region_or_other_customer: bool = False


@dataclass
class SarReport:
    file: bool
    reason: str
    narrative: str
    subjects: list[str]
    total_amount_usd: float
    activity_dates: list[str]


def gate_file_report(facts: SarFacts) -> tuple[bool, str]:
    """README section 3a: file when fraud is confirmed or strongly suspected AND at
    least one of (exposure > $1,000; shared device/region/other-customer connection;
    coordinated/undocumented pattern) holds. Returns (should_file, reason_citing_rule)."""
    confirmed_or_suspected = facts.verdict == "fraud" or facts.strongly_suspected
    if not confirmed_or_suspected:
        return False, "3a: verdict is not confirmed or strongly suspected fraud"

    reasons = []
    if facts.exposure_usd > 1000:
        reasons.append(f"exposure ${facts.exposure_usd:,.2f} exceeds $1,000")
    if facts.shared_device_or_region_or_other_customer:
        reasons.append("activity connects to a shared device/region or another customer's fraud")
    if facts.pattern == "undocumented":
        reasons.append("pattern is undocumented/coordinated (R9)")

    if not reasons:
        return False, "3a: confirmed/suspected fraud but none of the SAR triggers (exposure > $1,000, shared origin, undocumented pattern) hold"

    return True, "3a: " + "; ".join(reasons)


def _min_max_dates(timestamps: Sequence[str]) -> list[str]:
    """[min(ts), max(ts)] as YYYY-MM-DD. Accepts 'YYYY-MM-DD HH:MM:SS' or bare dates;
    unparsable entries are skipped rather than raising, so one malformed timestamp
    doesn't crash SAR generation."""
    parsed: list[datetime] = []
    for ts in timestamps:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed.append(datetime.strptime(ts[:19], fmt))
                break
            except ValueError:
                continue
    if not parsed:
        return []
    lo, hi = min(parsed), max(parsed)
    return [lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")]


def build_subjects(facts: SarFacts) -> list[str]:
    """Every ID named in the narrative: customer, own + connected cards, device
    profiles, prior-case IDs actually cited. Order: customer, cards, connected cards,
    devices, prior cases -- stable and dedup'd."""
    subjects: list[str] = [facts.customer_id]
    for cid in facts.card_ids:
        if cid not in subjects:
            subjects.append(cid)
    for cid in facts.connected_card_ids:
        if cid not in subjects:
            subjects.append(cid)
    for dp in facts.device_profiles:
        if dp not in subjects:
            subjects.append(dp)
    for pc in facts.prior_case_ids:
        if pc not in subjects:
            subjects.append(pc)
    return subjects


_PATTERN_PROSE = {
    "card_testing": "a card-testing sequence (small online authorizations preceding a larger purchase)",
    "card_not_present_fraud": "card-not-present fraud inconsistent with the cardholder's history",
    "card_not_present_new_device": "card-not-present fraud from a device new to this account",
    "out_of_region_use": "card-present use in a billing region outside the cardholder's history",
    "account_takeover": "account takeover activity across the cardholder's cards",
    "undocumented": "an undocumented fraud pattern",
}


def _default_render(facts: SarFacts, subjects: list[str], dates: list[str]) -> str:
    """Deterministic template renderer: assembles who/what/when/where/how/why into
    6-12 sentences using only fields already present on `facts`. This is the fallback
    (and the one used by tests, since it makes no network/LLM call); an LLM-backed
    render_fn may replace it but must only rephrase these same facts."""
    who = (
        f"Customer {facts.customer_id}, card{'s' if len(facts.card_ids) != 1 else ''} "
        f"{', '.join(facts.card_ids)}"
        + (f", connected to card(s) {', '.join(facts.connected_card_ids)}" if facts.connected_card_ids else "")
        + "."
    )

    pattern_prose = _PATTERN_PROSE.get(facts.pattern, "suspicious activity")
    what = f"The activity is consistent with {pattern_prose}."
    if facts.pattern == "undocumented" and facts.pattern_description:
        what += f" {facts.pattern_description}"

    when = (
        f"The activity occurred between {dates[0]} and {dates[1]}."
        if len(dates) == 2
        else "The exact activity window could not be fully established from available timestamps."
    )

    where = f"Activity occurred over the {facts.channel} channel"
    if facts.billing_regions:
        where += f", billed in region(s) {', '.join(facts.billing_regions)}"
    where += "."

    how = facts.mechanism.strip() or "The mechanism is described in the attached case evidence."
    if not how.endswith((".", "!", "?")):
        how += "."

    why_parts = []
    if facts.why_suspicious.strip():
        w = facts.why_suspicious.strip()
        why_parts.append(w if w.endswith((".", "!", "?")) else w + ".")
    if facts.device_profiles:
        why_parts.append(
            f"The device profile{'s' if len(facts.device_profiles) > 1 else ''} "
            f"{', '.join(facts.device_profiles)} link this activity to other affected transactions."
        )
    if facts.prior_case_ids:
        why_parts.append(
            f"Related prior investigations reviewed as case memory: {', '.join(facts.prior_case_ids)}."
        )
    why_parts.append(f"Total exposure identified: ${facts.exposure_usd:,.2f}.")
    if facts.actions_taken:
        why_parts.append(" ".join(a if a.endswith(".") else a + "." for a in facts.actions_taken))
    why = " ".join(why_parts)

    sentences = [who, what, when, where, how, why]
    text = " ".join(s for s in sentences if s.strip())
    return text


RenderFn = Callable[[SarFacts, list[str], list[str]], str]


def _split_sentences(text: str) -> list[str]:
    # ponytail: naive sentence splitter on '. ' boundaries -- good enough to count
    # sentences for the 6-12 range check, not meant to be a real NLP tokenizer.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _validate_no_hallucinated_ids(narrative: str, allowed_ids: set[str]) -> None:
    """Every ID-shaped token in the narrative (customer/card/device/case id patterns)
    must be one of the facts' own subjects. This is the enforcement that a swapped-in
    LLM render_fn can't invent an ID: if it emits one not present in `facts`, this
    raises rather than letting the SAR silently carry a fabricated ID."""
    id_like = re.findall(r"\b(?:C\d{3,}(?:-K\d+)?|CC-\d{3,}|CASE-[\w-]+|T\d{5,})\b", narrative)
    unknown = [tok for tok in id_like if tok not in allowed_ids]
    if unknown:
        raise ValueError(f"SAR narrative references IDs not present in SarFacts: {unknown}")


def generate_sar(facts: SarFacts, render_fn: RenderFn | None = None) -> SarReport:
    """Build the SAR. Returns file=False with narrative="" etc. when the section-3a
    gate doesn't fire -- callers should still call this for every case (cheap) rather
    than branching before it, so the gate logic lives in one place."""
    should_file, reason = gate_file_report(facts)
    if not should_file:
        return SarReport(file=False, reason=reason, narrative="", subjects=[], total_amount_usd=0.0, activity_dates=[])

    subjects = build_subjects(facts)
    dates = _min_max_dates(facts.affected_txn_timestamps)

    render = render_fn or _default_render
    narrative = render(facts, subjects, dates)

    sentences = _split_sentences(narrative)
    if len(sentences) < MIN_SENTENCES:
        # Pad conservatively with a closing sentence rather than fabricating content --
        # only happens if a custom render_fn under-produces; the default template
        # reliably hits >= 6 sentences on its own.
        narrative = narrative.rstrip() + f" This report covers {len(facts.affected_txn_ids)} transaction(s) totaling ${facts.exposure_usd:,.2f}."
        sentences = _split_sentences(narrative)
    if len(sentences) > MAX_SENTENCES:
        narrative = " ".join(sentences[:MAX_SENTENCES])

    allowed_ids = set(subjects) | set(facts.affected_txn_ids)
    _validate_no_hallucinated_ids(narrative, allowed_ids)

    return SarReport(
        file=True,
        reason=reason,
        narrative=narrative,
        subjects=subjects,
        total_amount_usd=facts.exposure_usd,
        activity_dates=dates,
    )


def demo() -> None:
    """Self-check: gate fires on exposure>$1000, subjects/dates/amount trace to facts,
    sentence count in [6,12], no ID outside `facts` appears in the narrative."""
    facts = SarFacts(
        customer_id="C00377",
        card_ids=["C00377-K1"],
        connected_card_ids=["C00877-K1"],
        device_profiles=["SAMSUNG SM-G935F | Android 7.0 | Chrome | 1920x1080"],
        pattern="card_testing",
        channel="online",
        mechanism="Three sub-$3 online authorizations within 40 minutes preceded a $259.98 purchase in a product category never used before.",
        why_suspicious="The cardholder denied making these purchases when contacted.",
        affected_txn_ids=["T0412877", "T0412878", "T0412879", "T0412883"],
        affected_txn_timestamps=["2016-11-14 09:12:00", "2016-11-14 09:52:00", "2016-11-14 10:05:00", "2016-11-14 10:31:00"],
        exposure_usd=268.43,
        prior_case_ids=["CC-0141"],
        actions_taken=["Card blocked and scheduled for reissue", "Connected card placed under monitoring"],
        verdict="fraud",
        shared_device_or_region_or_other_customer=True,
    )
    report = generate_sar(facts)
    assert report.file is True
    assert report.total_amount_usd == 268.43
    assert report.activity_dates == ["2016-11-14", "2016-11-14"]
    assert "C00377" in report.subjects and "C00877-K1" in report.subjects and "CC-0141" in report.subjects
    n_sent = len(_split_sentences(report.narrative))
    assert MIN_SENTENCES <= n_sent <= MAX_SENTENCES, n_sent

    legit = SarFacts(customer_id="C1", card_ids=["C1-K1"], connected_card_ids=[], device_profiles=[],
                      pattern="none", exposure_usd=39.08, verdict="legitimate")
    legit_report = generate_sar(legit)
    assert legit_report.file is False and legit_report.narrative == ""
    print("narrative.py demo OK:", n_sent, "sentences,", report.activity_dates)


if __name__ == "__main__":
    demo()
