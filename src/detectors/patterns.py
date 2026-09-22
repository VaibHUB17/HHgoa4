"""Six fraud detectors as pure functions over query results.

Source: RESEARCH.md §4.2 (thresholds) and the policy rules in README.md (R1-R10).
Every function takes plain dicts/lists shaped like the JSON a query in queries.gsql
would return (or the equivalent Python dict after pyTigerGraph parses it) and returns a
list of Finding -- pure, no I/O, no TigerGraph dependency, so they're unit-testable with
synthetic data (tests/test_detectors.py) and reusable regardless of how the caller
fetched the underlying rows.

Each transaction dict is expected to carry at least:
    txn_id: str, ts: datetime, amount: float, channel: str ("online"|"in_person"),
    product_cd: str, risk_score: float, id_15: str | None ("New"|"Found"|"Unknown"),
    id_23: str | None, addr1: str | None, addr2: str | None,
    device_key: str | None, card_id: str, customer_id: str

Thresholds are taken exactly as the policy/README states them -- see each function's
docstring for the citation. Nothing here invents a number the spec didn't give.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations


@dataclass
class Finding:
    """One detector's output: a claim, the evidence it rests on, which ledger weight
    keys it justifies (RESEARCH.md §7.1's evidence_weights.yaml keys), the entity IDs
    for provenance, and the `ref` string (query name + params) the answer file's
    evidence[].ref field requires for provenance (README Answer Format, evidence[])."""

    pattern: str
    evidence_items: list[str]
    weight_keys: list[str]
    entity_ids: list[str]
    ref: str


CARD_TESTING_AUTH_THRESHOLD = 5.0      # "under $5" — README known pattern 1 / R5
CARD_TESTING_MIN_COUNT = 3             # "three or more" — README known pattern 1 / R5
CARD_TESTING_WINDOW = timedelta(hours=1)  # "within an hour" — R5
CARD_TESTING_LARGER_PURCHASE_MULTIPLE = 3.0  # a "materially larger" follow-up purchase;
    # the policy doesn't give a numeric ratio, so this is a documented interpretation:
    # the follow-up purchase must clearly exceed the testing amounts, not just nudge over $5.

CNP_BURST_MIN_COUNT = 2                # "two to four" — README known pattern 2
CNP_BURST_MAX_COUNT = 4
CNP_BURST_WINDOW = timedelta(hours=48)  # "within 48 hours"

OUT_OF_REGION_CONCURRENCY_WINDOW = timedelta(hours=24)  # tunable physical-plausibility
    # threshold, not a magic number: a card cannot be physically used in two regions at
    # once, so a home-region transaction within +/-N hours of a new-region transaction is
    # implausible for one person traveling -- that overlap is the clone signal. 24h is a
    # conservative window (same-day-ish) chosen because same-day home+away activity is
    # already hard to explain as one traveling cardholder; it is NOT the same knob as "how
    # long is a trip" -- a real trip can run for days, but during it the home region goes
    # quiet, it doesn't interleave with the away region hour-by-hour. Widen if avoiding
    # false positives on borderline timezone/red-eye-flight edge cases matters more than
    # catching clones fast.

SHARED_ORIGIN_WINDOW = timedelta(days=7)  # R6 "in one window" — not a stated number;
    # documented interpretation, matches the closed-case-history granularity (opened_at/
    # closed_at are date-level, not hour-level) and gives R6 room to catch a ring that
    # doesn't all fire within the same hour.
SHARED_ORIGIN_MIN_CUSTOMERS = 2        # R6 "across cards" / README "shared across many
    # cards" -- minimum for a *shared origin* claim is 2 distinct customers, matching
    # the task prompt's "2+ customers".


def _within_window(a: datetime, b: datetime, window: timedelta) -> bool:
    return abs(a - b) <= window


# ---------------------------------------------------------------------------
# 1. card_testing
# ---------------------------------------------------------------------------

def detect_card_testing(card_id: str, txns: list[dict]) -> list[Finding]:
    """>=3 online auths <$5 within a 1-hour window, followed by a materially larger
    purchase. README known pattern 1 / policy R5.

    txns: card_window() output for one card, any order -- sorted internally by ts.
    """
    findings: list[Finding] = []
    ordered = sorted(txns, key=lambda t: t["ts"])
    online = [t for t in ordered if t.get("channel") == "online"]

    n = len(online)
    for i in range(n):
        window_start = online[i]
        if window_start["amount"] >= CARD_TESTING_AUTH_THRESHOLD:
            continue
        # collect the maximal run of sub-threshold auths within CARD_TESTING_WINDOW of
        # window_start
        small_run = [
            t for t in online
            if t["amount"] < CARD_TESTING_AUTH_THRESHOLD
            and window_start["ts"] <= t["ts"] <= window_start["ts"] + CARD_TESTING_WINDOW
        ]
        if len(small_run) < CARD_TESTING_MIN_COUNT:
            continue

        # a larger purchase after the last small auth in the run, still reasonably soon
        # after (within the same 1hr window from the run's last small auth, generously)
        last_small = small_run[-1]
        threshold_amount = max(
            CARD_TESTING_AUTH_THRESHOLD,
            small_run[-1]["amount"] * CARD_TESTING_LARGER_PURCHASE_MULTIPLE,
        )
        larger = [
            t for t in online
            if t["ts"] > last_small["ts"]
            and t["ts"] <= last_small["ts"] + CARD_TESTING_WINDOW
            and t["amount"] >= threshold_amount
        ]
        if not larger:
            continue

        follow_up = larger[0]
        episode = small_run + [follow_up]
        entity_ids = [t["txn_id"] for t in episode]
        findings.append(Finding(
            pattern="card_testing",
            evidence_items=[
                f"{len(small_run)} online authorizations under "
                f"${CARD_TESTING_AUTH_THRESHOLD:.2f} within "
                f"{CARD_TESTING_WINDOW.total_seconds() / 3600:.0f}hr on card {card_id}, "
                f"followed by a ${follow_up['amount']:.2f} purchase",
            ],
            weight_keys=["card_testing_sequence"],
            entity_ids=entity_ids,
            ref=f"query:card_window(card_id={card_id}, hours=1)",
        ))
        break  # one episode per call is enough signal; avoid duplicate overlapping findings

    return findings


# ---------------------------------------------------------------------------
# 2. cnp_burst (card_not_present_fraud)
# ---------------------------------------------------------------------------

def detect_cnp_burst(card_id: str, txns: list[dict], baseline_products: set[str]) -> list[Finding]:
    """2-4 unusual online purchases within 48h with a category mismatch vs. the card's
    own history. README known pattern 2 / RESEARCH.md §4.2.

    txns: card_window() output. baseline_products: the set of product_cd values this
    card/customer has historically used (from customer_baseline()) -- a purchase whose
    product_cd is NOT in this set is "unusual" per the category-mismatch criterion.
    """
    ordered = sorted(
        [t for t in txns if t.get("channel") == "online"], key=lambda t: t["ts"]
    )
    findings: list[Finding] = []

    n = len(ordered)
    for i in range(n):
        anchor = ordered[i]
        if anchor["product_cd"] in baseline_products:
            continue  # not a category mismatch, not unusual by this criterion
        window = [
            t for t in ordered
            if anchor["ts"] <= t["ts"] <= anchor["ts"] + CNP_BURST_WINDOW
            and t["product_cd"] not in baseline_products
        ]
        if CNP_BURST_MIN_COUNT <= len(window) <= CNP_BURST_MAX_COUNT:
            entity_ids = [t["txn_id"] for t in window]
            findings.append(Finding(
                pattern="card_not_present_fraud",
                evidence_items=[
                    f"{len(window)} online purchases within 48h on card {card_id} using "
                    f"product code(s) {sorted({t['product_cd'] for t in window})} not seen "
                    f"in this card's history",
                ],
                weight_keys=["cnp_burst_pattern"],
                entity_ids=entity_ids,
                ref=f"query:card_window(card_id={card_id}, hours=48)",
            ))
            break

    return findings


# ---------------------------------------------------------------------------
# 3. new_device (card_not_present_new_device)
# ---------------------------------------------------------------------------

def detect_new_device(card_id: str, txns: list[dict]) -> list[Finding]:
    """Online transaction(s) from a device marked id_15 == 'New' for this account.
    README known pattern 3. Not proof on its own -- people buy new phones -- so this
    detector only reports the marker; the caller/ledger applies the (deliberately small)
    weight, not this function.
    """
    flagged = [
        t for t in txns
        if t.get("channel") == "online" and t.get("id_15") == "New"
    ]
    if not flagged:
        return []

    entity_ids = [t["txn_id"] for t in flagged]
    proxy_flagged = [t for t in flagged if t.get("id_23") in ("Anonymous", "Hidden")]
    evidence = [
        f"{len(flagged)} online transaction(s) on card {card_id} from a device marked "
        f"'New' for this account (id_15=New)",
    ]
    weight_keys = ["new_device_marker"]
    if proxy_flagged:
        evidence.append(
            f"{len(proxy_flagged)} of these also came from behind a proxy (id_23 "
            f"in {{Anonymous, Hidden}})"
        )
        weight_keys.append("proxy_flag")

    return [Finding(
        pattern="card_not_present_new_device",
        evidence_items=evidence,
        weight_keys=weight_keys,
        entity_ids=entity_ids,
        ref=f"query:card_window(card_id={card_id})",
    )]


# ---------------------------------------------------------------------------
# 4. out_of_region_use
# ---------------------------------------------------------------------------

def detect_out_of_region(
    card_id: str,
    txns: list[dict],
    historical_regions: set[str],
) -> list[Finding]:
    """Card-present purchases billed in a region outside the customer's historical
    addr1 set. The discriminator (README known pattern 4, verbatim: "Card-present
    purchases in a billing region the cardholder has no history in, while their normal
    activity continues at home. Several days of purchases in one new region is a trip,
    not a clone."):

    - Home region STILL ACTIVE, interleaved in time with new-region activity => the card
      is being used in two places the cardholder cannot physically be at once => CLONE,
      fires.
    - Home region goes quiet and stays quiet while activity moves to (one) new region for
      a stretch, then optionally resumes at home afterward => a TRIP, does not fire.

    "Interleaved" is operationalized as: for at least one new-region transaction, a
    home-region transaction falls within +/-OUT_OF_REGION_CONCURRENCY_WINDOW of it. A
    clean split (all home txns end before the new-region stretch starts, and any
    resumption starts only after it ends, each beyond the window) reads as sequential
    travel, not concurrent use.

    Multiple new regions interleaved within the same short window is a stronger clone
    signal than one new region (RESEARCH.md §4.2's "out-of-region" motif combined with
    the R6/BIN-attack-style "clustering across identities" note) -- reported via the
    extra_new_regions weight key so the caller's ledger can weight it higher.

    historical_regions: addr1 values seen for this card/customer BEFORE the window
    covered by txns (from customer_baseline()).
    """
    ordered = sorted(txns, key=lambda t: t["ts"])
    if not ordered:
        return []

    new_region_txns = [
        t for t in ordered if t.get("addr1") and t["addr1"] not in historical_regions
    ]
    home_txns = [t for t in ordered if t.get("addr1") in historical_regions]
    if not new_region_txns:
        return []

    # concurrency check: does any home-region txn fall within the window of any
    # new-region txn? That overlap is the physically-implausible clone signal.
    concurrent = any(
        abs(h["ts"] - n["ts"]) <= OUT_OF_REGION_CONCURRENCY_WINDOW
        for n in new_region_txns
        for h in home_txns
    )
    if not concurrent:
        return []  # clean sequential split (or no home activity at all) => trip, not a clone

    distinct_new_regions = sorted({t["addr1"] for t in new_region_txns})
    weight_keys = ["out_of_region_pattern"]
    evidence = [
        f"Card {card_id} billed in region(s) {distinct_new_regions} outside its historical "
        f"region set {sorted(historical_regions)}, with home-region activity interleaved "
        f"within {OUT_OF_REGION_CONCURRENCY_WINDOW.total_seconds() / 3600:.0f}h -- the card "
        f"cannot physically be in both places, consistent with a clone rather than a trip",
    ]
    if len(distinct_new_regions) >= 2:
        weight_keys.append("multi_region_clone_cluster")
        evidence.append(
            f"Activity spans {len(distinct_new_regions)} distinct new regions in the same "
            f"window, a stronger clone signal than a single new region",
        )

    entity_ids = [t["txn_id"] for t in new_region_txns]
    return [Finding(
        pattern="out_of_region_use",
        evidence_items=evidence,
        weight_keys=weight_keys,
        entity_ids=entity_ids,
        ref=f"query:customer_baseline + card_window(card_id={card_id})",
    )]


# ---------------------------------------------------------------------------
# 5. account_takeover
# ---------------------------------------------------------------------------

def detect_account_takeover(customer_id: str, cards_txns: dict[str, list[dict]]) -> list[Finding]:
    """Customer-centric: multiple cards each break their own history at once, with
    device/match-flag anomalies and mixed channels. README known pattern 5 / RESEARCH.md
    §4.2: "the structural tell is customer-centric, where patterns 1-4 are card-centric."

    cards_txns: {card_id: [recent txns for that card]} for every card this customer owns.
    A positive finding requires >=2 distinct cards each showing an anomaly (new device OR
    mismatched M-flag) within the same short window, which is the multi-card break the
    policy prompt calls "customer-centric multi-card break."
    """
    ANOMALY_WINDOW = timedelta(hours=24)

    def card_anomalies(txns: list[dict]) -> list[dict]:
        out = []
        for t in txns:
            is_new_device = t.get("id_15") == "New"
            mismatched_flag = t.get("M4") == "F" or t.get("M6") == "F"
            if is_new_device or mismatched_flag:
                out.append(t)
        return out

    anomalies_by_card = {
        cid: card_anomalies(txns) for cid, txns in cards_txns.items()
    }
    affected_cards = {cid: a for cid, a in anomalies_by_card.items() if a}
    if len(affected_cards) < 2:
        return []

    # require the anomalies across cards to cluster in time (a real takeover episode,
    # not two unrelated new-phone purchases months apart)
    all_anomaly_times = [
        t["ts"] for anomalies in affected_cards.values() for t in anomalies
    ]
    all_anomaly_times.sort()
    if all_anomaly_times[-1] - all_anomaly_times[0] > ANOMALY_WINDOW * len(affected_cards):
        return []

    channels = {
        t.get("channel") for anomalies in affected_cards.values() for t in anomalies
    }

    entity_ids = [
        t["txn_id"] for anomalies in affected_cards.values() for t in anomalies
    ]
    return [Finding(
        pattern="account_takeover",
        evidence_items=[
            f"Customer {customer_id}: {len(affected_cards)} distinct cards "
            f"({sorted(affected_cards)}) each show a new-device or mismatched-flag "
            f"anomaly within a clustered window, across channel(s) {sorted(c for c in channels if c)}",
        ],
        weight_keys=["shared_device_across_cards"] if len(channels) > 1 else ["new_device_marker"],
        entity_ids=entity_ids,
        ref=f"query:customer_baseline(customer_id={customer_id}) + card_window per card",
    )]


# ---------------------------------------------------------------------------
# 6. shared_origin (R6 / undocumented)
# ---------------------------------------------------------------------------

def detect_shared_origin(
    origin_type: str,
    origin_key: str,
    txns: list[dict],
) -> list[Finding]:
    """Shared DeviceProfile / BillingRegion / recipient email across 2+ customers within
    a window. Policy R6: "several cards show fraud from the same device profile, the
    same billing region, or the same recipient email in one window ... name the shared
    element." Also the base case for an `undocumented` R9 finding when it doesn't fit
    any of the five named patterns.

    origin_type: one of "device_profile" | "billing_region" | "recipient_email"
    txns: all transactions sharing origin_key (device_neighbors() output, or the
    equivalent BILLED_IN / RECIPIENT_EMAIL traversal), each carrying customer_id, card_id,
    ts, txn_id.
    """
    if origin_type not in ("device_profile", "billing_region", "recipient_email"):
        raise ValueError(f"unknown origin_type: {origin_type}")

    ordered = sorted(txns, key=lambda t: t["ts"])
    if not ordered:
        return []

    findings: list[Finding] = []
    n = len(ordered)
    for i in range(n):
        window_start = ordered[i]
        window = [
            t for t in ordered
            if window_start["ts"] <= t["ts"] <= window_start["ts"] + SHARED_ORIGIN_WINDOW
        ]
        customers = {t["customer_id"] for t in window}
        if len(customers) < SHARED_ORIGIN_MIN_CUSTOMERS:
            continue

        cards = sorted({t["card_id"] for t in window})
        entity_ids = [t["txn_id"] for t in window]
        query_name = {
            "device_profile": "device_neighbors",
            "billing_region": "prior_cases_for_entities",
            "recipient_email": "prior_cases_for_entities",
        }[origin_type]
        findings.append(Finding(
            pattern="undocumented",  # caller may override to a named pattern/R6 label
            evidence_items=[
                f"Shared {origin_type.replace('_', ' ')} '{origin_key}' used by "
                f"{len(customers)} distinct customers across cards {cards} within a "
                f"{SHARED_ORIGIN_WINDOW.days}-day window",
            ],
            weight_keys=["shared_device_across_cards"] if origin_type == "device_profile"
                        else ["shared_region_cluster"],
            entity_ids=entity_ids,
            ref=f"query:{query_name}({origin_type}={origin_key})",
        ))
        break  # one clustered episode per origin_key is enough; avoid overlapping dupes

    return findings
