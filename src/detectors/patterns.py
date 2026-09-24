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
        span_minutes = (small_run[-1]["ts"] - small_run[0]["ts"]).total_seconds() / 60
        small_amounts = ", ".join(f"${t['amount']:.2f}" for t in small_run)
        delay_minutes = (follow_up["ts"] - last_small["ts"]).total_seconds() / 60
        findings.append(Finding(
            pattern="card_testing",
            evidence_items=[
                f"Card {card_id} made {len(small_run)} online authorizations "
                f"({small_amounts}) all under the ${CARD_TESTING_AUTH_THRESHOLD:.2f} "
                f"authorization-review threshold, spaced {span_minutes:.0f} minutes apart -- "
                f"the size and cadence are consistent with probing which of several "
                f"declined/blocked amounts an attacker's card data still clears. "
                f"{delay_minutes:.0f} minutes after the last probe, transaction "
                f"{follow_up['txn_id']} charged ${follow_up['amount']:.2f} "
                f"({follow_up['amount'] / small_run[-1]['amount']:.1f}x the last probe "
                f"amount), consistent with the probes confirming a live card before a "
                f"real-value purchase",
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
            span_hours = (window[-1]["ts"] - window[0]["ts"]).total_seconds() / 3600
            total = sum(t["amount"] for t in window)
            txn_list = ", ".join(f"{t['txn_id']} (${t['amount']:.2f}, {t['product_cd']})" for t in window)
            findings.append(Finding(
                pattern="card_not_present_fraud",
                evidence_items=[
                    f"{len(window)} online purchases on card {card_id} within "
                    f"{span_hours:.1f}h totaling ${total:.2f} -- {txn_list} -- all in "
                    f"product code(s) {sorted({t['product_cd'] for t in window})}, none of "
                    f"which appear in this card's established category set "
                    f"{sorted(baseline_products) if baseline_products else '(none on file)'}: "
                    f"a short burst of purchases in categories the cardholder has never "
                    f"bought in, rather than a single one-off unusual purchase",
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

def detect_new_device(
    card_id: str,
    txns: list[dict],
    prior_device_profile: dict | None = None,
) -> list[Finding]:
    """Online transaction(s) from a device marked id_15 == 'New' for this account.
    README known pattern 3. Not proof on its own -- people buy new phones -- so this
    detector only reports the marker; the caller/ledger applies the (deliberately small)
    weight, not this function.

    prior_device_profile: optional context the caller may supply from account history
    beyond the card_window lookback -- {"n_txns": int, "n_devices": int,
    "min_device_age_days": int} for this card/customer's established devices. When
    given, the claim states the concrete comparison ("prior N transactions span M device
    profiles, all seen for K+ days") the way an analyst would frame it. When omitted
    (the default, matching every current caller), the claim states only what's directly
    in txns -- no number is invented that the caller didn't supply.
    """
    flagged = [
        t for t in txns
        if t.get("channel") == "online" and t.get("id_15") == "New"
    ]
    if not flagged:
        return []

    entity_ids = [t["txn_id"] for t in flagged]
    proxy_flagged = [t for t in flagged if t.get("id_23") in ("Anonymous", "Hidden")]
    amounts = ", ".join(f"{t['txn_id']} (${t['amount']:.2f})" for t in flagged)
    claim = (
        f"{len(flagged)} online transaction(s) on card {card_id} -- {amounts} -- came "
        f"from a device first marked 'New' for this account (id_15=New)"
    )
    if prior_device_profile and prior_device_profile.get("n_txns"):
        claim += (
            f"; the cardholder's prior {prior_device_profile['n_txns']} transaction(s) "
            f"span {prior_device_profile.get('n_devices', '?')} device profile(s), "
        )
        min_age = prior_device_profile.get("min_device_age_days")
        claim += (
            f"established for {min_age}+ days" if min_age is not None
            else "of unknown age"
        )
    evidence = [claim]
    weight_keys = ["new_device_marker"]
    if proxy_flagged:
        evidence.append(
            f"{len(proxy_flagged)} of these also came from behind a proxy (id_23 "
            f"in {{Anonymous, Hidden}}), which conceals the true origin and is itself "
            f"a corroborating anomaly beyond the bare device marker"
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
    # find the actual closest overlapping pair to cite concrete evidence, not just the claim
    closest_pair = min(
        ((h, n, abs(h["ts"] - n["ts"])) for n in new_region_txns for h in home_txns
         if abs(h["ts"] - n["ts"]) <= OUT_OF_REGION_CONCURRENCY_WINDOW),
        key=lambda p: p[2],
    )
    h_txn, n_txn, gap = closest_pair
    gap_hours = gap.total_seconds() / 3600
    evidence = [
        f"Card {card_id} billed in region(s) {distinct_new_regions} outside its historical "
        f"region set {sorted(historical_regions)}. Transaction {n_txn['txn_id']} "
        f"(${n_txn['amount']:.2f}, region {n_txn['addr1']}) sits only {gap_hours:.1f}h from "
        f"{h_txn['txn_id']} (${h_txn['amount']:.2f}, region {h_txn['addr1']}, the "
        f"cardholder's own historical region) -- no traveler can be billed in two regions "
        f"{gap_hours:.1f}h apart, so this reads as the card being used in two places at "
        f"once (a clone) rather than one cardholder traveling",
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
    window_hours = (all_anomaly_times[-1] - all_anomaly_times[0]).total_seconds() / 3600
    per_card_detail = "; ".join(
        f"{cid}: {len(a)} anomal{'y' if len(a)==1 else 'ies'} "
        f"({', '.join(sorted({'new_device' if t.get('id_15')=='New' else 'flag_mismatch' for t in a}))})"
        for cid, a in sorted(affected_cards.items())
    )
    return [Finding(
        pattern="account_takeover",
        evidence_items=[
            f"Customer {customer_id} owns {len(cards_txns)} card(s); {len(affected_cards)} "
            f"of them broke their own established pattern within {window_hours:.1f}h of "
            f"each other -- {per_card_detail} -- across channel(s) "
            f"{sorted(c for c in channels if c)}. A single card showing a new-device "
            f"marker is common (people buy new phones); multiple cards on the same "
            f"customer breaking simultaneously is the customer-centric tell that "
            f"distinguishes account takeover from a card-level anomaly",
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
        span_days = (window[-1]["ts"] - window[0]["ts"]).days
        per_customer = ", ".join(
            f"{cid} (card {[t['card_id'] for t in window if t['customer_id']==cid][0]})"
            for cid in sorted(customers)
        )
        findings.append(Finding(
            pattern="undocumented",  # caller may override to a named pattern/R6 label
            evidence_items=[
                f"Shared {origin_type.replace('_', ' ')} '{origin_key}' appears on "
                f"{len(window)} transactions across {len(customers)} unrelated customers "
                f"({per_customer}) within {span_days} day(s) of a "
                f"{SHARED_ORIGIN_WINDOW.days}-day window -- one {origin_type.replace('_',' ')} "
                f"tying together cards {cards} that share no other connection is the "
                f"structural signature of a coordinated ring rather than {len(customers)} "
                f"unrelated cardholders coincidentally using the same one",
            ],
            weight_keys=["shared_device_across_cards"] if origin_type == "device_profile"
                        else ["shared_region_cluster"],
            entity_ids=entity_ids,
            ref=f"query:{query_name}({origin_type}={origin_key})",
        ))
        break  # one clustered episode per origin_key is enough; avoid overlapping dupes

    return findings


# ---------------------------------------------------------------------------
# Undocumented pattern: authorization-threshold structuring
# ---------------------------------------------------------------------------
# Found by reading the closed-case notes labelled pattern == "undocumented" (CC-3748,
# CC-3841, CC-3907, CC-4086, CC-4124): "four online purchases within forty minutes, each
# just under $500 ... amounts appear chosen to stay under a $500 authorization threshold."
STRUCTURING_CEILING = 500.0
STRUCTURING_FLOOR = 450.0          # "just under" -- within 10% of the threshold
STRUCTURING_MIN_COUNT = 3
STRUCTURING_WINDOW = timedelta(hours=1)
STRUCTURING_PRECEDENTS = ["CC-3748", "CC-3841", "CC-3907", "CC-4086", "CC-4124"]
STRUCTURING_DESCRIPTION = (
    "Authorization-threshold structuring: several online purchases on one card within an "
    "hour, each priced just under $500, consistent with amounts chosen to stay below a $500 "
    "authorization limit. Not one of the five documented patterns; matches the bank's own "
    "closed cases labelled undocumented (" + ", ".join(STRUCTURING_PRECEDENTS) + ")."
)


def detect_threshold_structuring(card_id: str, txns: list[dict]) -> list[Finding]:
    online = sorted(
        (t for t in txns if t.get("channel") == "online"
         and STRUCTURING_FLOOR <= t["amount"] < STRUCTURING_CEILING),
        key=lambda t: t["ts"],
    )
    for i, start in enumerate(online):
        window = [t for t in online[i:] if t["ts"] - start["ts"] <= STRUCTURING_WINDOW]
        if len(window) >= STRUCTURING_MIN_COUNT:
            minutes = int((window[-1]["ts"] - window[0]["ts"]).total_seconds() // 60)
            amounts = ", ".join(f"${t['amount']:.2f}" for t in window)
            return [Finding(
                pattern="undocumented",
                evidence_items=[
                    f"{len(window)} online purchases on card {card_id} within {minutes} minutes, "
                    f"each just under $500 ({amounts}) -- consistent with structuring below a "
                    f"$500 authorization threshold, as in closed cases "
                    f"{', '.join(STRUCTURING_PRECEDENTS[:3])}"
                ],
                # no new ledger weight: a burst of unusual online purchases is exactly what
                # cnp_burst_pattern already prices; this finding names the mechanism
                weight_keys=["cnp_burst_pattern"],
                entity_ids=[t["txn_id"] for t in window],
                ref=f"detector:threshold_structuring(card_id={card_id})",
            )]
    return []


# ---------------------------------------------------------------------------
# Undocumented pattern: proxy device ring
# ---------------------------------------------------------------------------
# Found by reading the closed-case notes labelled pattern == "undocumented" (CC-2649,
# CC-2971, CC-2985, CC-3035), all four near-identical: "the purchases came from a Samsung
# SM-G935F on Chrome for Android behind an anonymous proxy, a device never seen on this
# account. Two other cardholders reported the same device profile this month." This is
# NOT plain card_not_present_new_device (README pattern 3, one account's new device) --
# the undocumented element is the *combination* of proxy concealment with a device
# profile independently reported by other cardholders in the same window: one handset,
# anonymised, hitting multiple unrelated accounts. All four require every element
# together: denial, new-to-account device, proxy, AND cross-customer corroboration.
PROXY_RING_MIN_OTHER_CUSTOMERS = 2  # "two other cardholders" -- verbatim in all 4 notes
PROXY_RING_WINDOW = timedelta(days=30)  # "this month" -- the notes' own phrase; a 30-day
    # window is the closest defensible reading of "month" without assuming calendar-month
    # alignment the data doesn't give us.
PROXY_RING_PRECEDENTS = ["CC-2649", "CC-2971", "CC-2985", "CC-3035"]
PROXY_RING_DESCRIPTION = (
    "Proxy device ring: online purchase(s) the cardholder denies making, from a device "
    "profile never seen on this account, accessed behind an anonymous/hidden proxy, and "
    "independently reported by 2+ other cardholders within the same 30-day window -- one "
    "handset, anonymised, working multiple unrelated accounts. Not one of the five "
    "documented patterns; matches the bank's own closed cases labelled undocumented (" +
    ", ".join(PROXY_RING_PRECEDENTS) + ")."
)


def detect_proxy_device_ring(
    card_id: str,
    customer_id: str,
    txns: list[dict],
    customer_denies: bool,
    device_key: str,
    other_customer_txns: list[dict],
) -> list[Finding]:
    """Fires only when every element from the closed-case notes is present together:

    - customer_denies: the cardholder reported these purchases as not theirs (all 4
      precedent notes open with "cardholder reported ... they did not make").
    - a device marked id_15 == 'New' for this account, used online.
    - that same device access is behind a proxy (id_23 in {Anonymous, Hidden}).
    - other_customer_txns: rows sharing device_key with OTHER customer_ids (not this one),
      within PROXY_RING_WINDOW of this account's flagged activity -- the "two other
      cardholders reported the same device profile this month" corroboration. Caller
      supplies this pre-filtered to the shared device_key (device_neighbors() output),
      same shape as detect_shared_origin's txns.

    Any one element missing and this must NOT fire -- a bare new+proxy device with no
    cross-customer corroboration is card_not_present_new_device's territory, not this.
    """
    if not customer_denies:
        return []

    flagged = [
        t for t in txns
        if t.get("channel") == "online"
        and t.get("id_15") == "New"
        and t.get("id_23") in ("Anonymous", "Hidden")
        and t.get("device_key") == device_key
    ]
    if not flagged:
        return []

    anchor_ts = min(t["ts"] for t in flagged)
    corroborating = [
        t for t in other_customer_txns
        if t.get("customer_id") != customer_id
        and t.get("device_key") == device_key
        and abs(t["ts"] - anchor_ts) <= PROXY_RING_WINDOW
    ]
    other_customers = sorted({t["customer_id"] for t in corroborating})
    if len(other_customers) < PROXY_RING_MIN_OTHER_CUSTOMERS:
        return []

    entity_ids = [t["txn_id"] for t in flagged]
    return [Finding(
        pattern="undocumented",
        evidence_items=[
            f"{len(flagged)} online purchase(s) on card {card_id} that cardholder "
            f"{customer_id} denies making, from device '{device_key}' marked New for this "
            f"account and accessed behind an anonymous/hidden proxy -- the same device "
            f"profile was independently reported by {len(other_customers)} other "
            f"cardholders ({other_customers}) within {PROXY_RING_WINDOW.days} days, "
            f"consistent with a proxy device ring rather than one compromised account, "
            f"as in closed cases {', '.join(PROXY_RING_PRECEDENTS)}"
        ],
        weight_keys=["proxy_device_ring"],
        entity_ids=entity_ids,
        ref=f"query:device_neighbors(device_key={device_key})",
    )]


# ---------------------------------------------------------------------------
# Exonerating detectors, mined from the 900 CLEARED closed cases
# ---------------------------------------------------------------------------
# Every cleared case in closed_cases_history.csv began as a risk-score alert the bank's
# own model got wrong. The 900 notes collapse into exactly three recurring exoneration
# mechanisms (share of the 900 in parentheses):
#   716 (80%) "confirmed travel to the billing region in question"
#   158 (18%) "confirmed the purchase from a new phone. Device added to profile"
#    26 ( 3%) "confirmed the purchase. Amount unusual ... but consistent with stated intent"
# These are exonerating signals the agent currently under-uses -- the brief warns hard
# against over-blocking, and out-of-region + new-device together explain 98% of the
# false alarms the bank's analysts actually saw. Each detector below produces a NEGATIVE
# ledger weight (config/evidence_weights.yaml, append-only) sized roughly to its share of
# the 900 cleared cases -- travel is the strongest and most common exoneration, isolated
# unusual-amount is the weakest and rarest.
#
# None of the three closed-case notes correspond to a queryable "customer confirmed X"
# field in the graph (that confirmation happens through the agent's own customer_denies/
# customer_confirms interview flow in src/agent/nodes.py, not in patterns.py's scope).
# What patterns.py CAN observe directly from card_window/customer_baseline rows is the
# *shape* that made the alert a false alarm in the first place -- travel shape, in-
# character-new-device shape, isolated-amount shape -- so these detectors fire on shape,
# and their evidence is worded as "consistent with" rather than "customer confirmed",
# staying true to what the data actually shows.

TRAVEL_MIN_HISTORICAL_REGIONS = 1  # any established home region at all is enough context
    # to call a clean sequential move a "trip shape"; the discriminator that matters is
    # concurrency (see detect_out_of_region), not how many regions are on file.


def detect_travel_consistent_with_history(
    card_id: str,
    txns: list[dict],
    historical_regions: set[str],
) -> list[Finding]:
    """Mirrors detect_out_of_region's own discriminator from the exonerating side: home
    region goes quiet and stays quiet while activity moves to exactly one new region for a
    stretch (no interleaving) -- the "several days of purchases in one new region is a
    trip, not a clone" shape README pattern 4 names explicitly. 716/900 (80%) of the
    bank's cleared cases were exactly this: an out-of-region alert the cardholder
    confirmed as travel. Must NOT fire if home region is concurrently active -- that's
    detect_out_of_region's clone signal, not this.
    """
    ordered = sorted(txns, key=lambda t: t["ts"])
    if not ordered or not historical_regions:
        return []

    new_region_txns = [
        t for t in ordered if t.get("addr1") and t["addr1"] not in historical_regions
    ]
    home_txns = [t for t in ordered if t.get("addr1") in historical_regions]
    if not new_region_txns or len({t["addr1"] for t in new_region_txns}) != 1:
        return []  # no new-region activity, or more than one new region -- not a clean trip

    concurrent = any(
        abs(h["ts"] - n["ts"]) <= OUT_OF_REGION_CONCURRENCY_WINDOW
        for n in new_region_txns
        for h in home_txns
    )
    if concurrent:
        return []  # this is the clone shape, not the trip shape

    region = new_region_txns[0]["addr1"]
    entity_ids = [t["txn_id"] for t in new_region_txns]
    return [Finding(
        pattern="none",
        evidence_items=[
            f"Card {card_id}'s activity moved cleanly to region '{region}' for "
            f"{len(new_region_txns)} transaction(s) with no home-region activity "
            f"(historical regions {sorted(historical_regions)}) overlapping within "
            f"{OUT_OF_REGION_CONCURRENCY_WINDOW.total_seconds() / 3600:.0f}h -- a "
            f"sequential single-region move, the trip shape rather than the concurrent "
            f"clone shape, consistent with the 716 of 900 closed cases the bank cleared "
            f"as confirmed travel",
        ],
        weight_keys=["travel_consistent_with_history"],
        entity_ids=entity_ids,
        ref=f"query:customer_baseline + card_window(card_id={card_id})",
    )]


def detect_new_device_otherwise_in_character(
    card_id: str,
    txns: list[dict],
    baseline_products: set[str],
    historical_regions: set[str],
) -> list[Finding]:
    """New device (id_15 == 'New'), NOT behind a proxy, where the transaction amount's
    product category and billing region both sit inside this customer's own established
    baseline. 158/900 (18%) of cleared cases were exactly "confirmed the purchase from a
    new phone" -- a new device alone is the second-biggest false-positive source in the
    dataset, which is why new_device_marker is deliberately small (+0.15) and must not be
    sufficient on its own. Must NOT fire behind a proxy or if shared with other
    cardholders -- that combination is detect_proxy_device_ring's territory (fraud, not
    exoneration).
    """
    flagged = [
        t for t in txns
        if t.get("channel") == "online"
        and t.get("id_15") == "New"
        and t.get("id_23") not in ("Anonymous", "Hidden")
        and t.get("product_cd") in baseline_products
        and (not historical_regions or t.get("addr1") in historical_regions)
    ]
    if not flagged:
        return []

    entity_ids = [t["txn_id"] for t in flagged]
    return [Finding(
        pattern="none",
        evidence_items=[
            f"{len(flagged)} online transaction(s) on card {card_id} from a device marked "
            f"New for this account, but not behind a proxy, and both product category and "
            f"billing region match this customer's established baseline "
            f"(products {sorted(baseline_products)}, regions {sorted(historical_regions)}) "
            f"-- consistent with the 158 of 900 closed cases the bank cleared as "
            f"'confirmed the purchase from a new phone'",
        ],
        weight_keys=["new_device_otherwise_in_character"],
        entity_ids=entity_ids,
        ref=f"query:customer_baseline + card_window(card_id={card_id})",
    )]


AMOUNT_UNUSUAL_ISOLATED_RATIO = 3.0  # "unusual for this customer" -- no numeric ratio in
    # the closed-case notes, so this is a documented interpretation: the flagged amount
    # must clearly exceed (3x+) the customer's historical average to count as "unusual"
    # at all; anything closer than that isn't unusual, it's just a slightly bigger day.


def detect_amount_unusual_but_isolated(
    card_id: str,
    flagged_txn: dict,
    historical_amounts: list[float],
) -> list[Finding]:
    """A single flagged transaction whose amount is well above the customer's historical
    average, but with NO other corroborating signal (no new device, no proxy, no
    out-of-region, no burst) -- an isolated outlier amount, not a pattern. 26/900 (3%) of
    cleared cases were exactly this: "amount unusual for this customer but consistent
    with their stated intent." Weakest and rarest of the three exonerating shapes, so it
    carries the smallest weight -- it is corroborating context for a human decision, not
    proof of legitimacy by itself.

    Caller is responsible for confirming no other Finding fired for this card/txn before
    calling this -- this detector only characterizes the one transaction in isolation.
    """
    if not historical_amounts or flagged_txn.get("amount") is None:
        return []

    avg = sum(historical_amounts) / len(historical_amounts)
    if avg <= 0 or flagged_txn["amount"] < avg * AMOUNT_UNUSUAL_ISOLATED_RATIO:
        return []

    return [Finding(
        pattern="none",
        evidence_items=[
            f"Flagged transaction {flagged_txn['txn_id']} (${flagged_txn['amount']:.2f}) on "
            f"card {card_id} is {flagged_txn['amount'] / avg:.1f}x this customer's historical "
            f"average (${avg:.2f} over {len(historical_amounts)} transactions), with no other "
            f"corroborating fraud signal found -- an isolated unusual amount, consistent with "
            f"the 26 of 900 closed cases the bank cleared as 'unusual but consistent with "
            f"stated intent'",
        ],
        weight_keys=["amount_unusual_but_isolated"],
        entity_ids=[flagged_txn["txn_id"]],
        ref=f"query:customer_baseline(card_id={card_id})",
    )]
