"""Tests for src/detectors/patterns.py -- pytest only, no fixtures/frameworks beyond
pytest, synthetic in-memory transaction lists. Per the task brief, the near-miss tests
matter more than the positive ones: half the real cases are legitimate, and a detector
that fires too eagerly is worse than one that misses.
"""

from datetime import datetime, timedelta

from src.detectors.patterns import (
    detect_account_takeover,
    detect_amount_unusual_but_isolated,
    detect_card_testing,
    detect_cnp_burst,
    detect_new_device,
    detect_new_device_otherwise_in_character,
    detect_out_of_region,
    detect_proxy_device_ring,
    detect_shared_origin,
    detect_threshold_structuring,
    detect_travel_consistent_with_history,
)

T0 = datetime(2016, 11, 12, 0, 0, 0)


def txn(txn_id, minutes=0, amount=10.0, channel="online", product_cd="C",
        id_15=None, id_23=None, addr1=None, addr2=None, device_key=None,
        card_id="C04570-K1", customer_id="C04570", M4=None, M6=None):
    return {
        "txn_id": txn_id,
        "ts": T0 + timedelta(minutes=minutes),
        "amount": amount,
        "channel": channel,
        "product_cd": product_cd,
        "risk_score": 0.5,
        "id_15": id_15,
        "id_23": id_23,
        "addr1": addr1,
        "addr2": addr2,
        "device_key": device_key,
        "card_id": card_id,
        "customer_id": customer_id,
        "M4": M4,
        "M6": M6,
    }


# ---------------------------------------------------------------------------
# card_testing
# ---------------------------------------------------------------------------

def test_card_testing_fires_on_three_small_then_large():
    txns = [
        txn("T1", minutes=0, amount=1.10),
        txn("T2", minutes=10, amount=2.40),
        txn("T3", minutes=20, amount=0.95),
        txn("T4", minutes=31, amount=259.98),
    ]
    findings = detect_card_testing("C04570-K1", txns)
    assert len(findings) == 1
    f = findings[0]
    assert f.pattern == "card_testing"
    assert set(f.entity_ids) == {"T1", "T2", "T3", "T4"}
    assert "card_testing_sequence" in f.weight_keys
    assert "card_window" in f.ref


def test_card_testing_does_not_fire_on_two_small_auths():
    """Near-miss: only 2 small auths, not 3 -- the policy's stated minimum. Must NOT fire."""
    txns = [
        txn("T1", minutes=0, amount=1.10),
        txn("T2", minutes=10, amount=2.40),
        txn("T3", minutes=20, amount=259.98),
    ]
    findings = detect_card_testing("C04570-K1", txns)
    assert findings == []


def test_card_testing_does_not_fire_when_no_larger_purchase_follows():
    """Near-miss: three small auths but nothing bigger follows -- not testing, just
    small purchases (e.g. transit fares)."""
    txns = [
        txn("T1", minutes=0, amount=1.10),
        txn("T2", minutes=10, amount=2.40),
        txn("T3", minutes=20, amount=0.95),
        txn("T4", minutes=30, amount=3.50),
    ]
    findings = detect_card_testing("C04570-K1", txns)
    assert findings == []


def test_card_testing_does_not_fire_when_window_exceeded():
    """Near-miss: three small auths spread over 3 hours, not within the 1-hour window."""
    txns = [
        txn("T1", minutes=0, amount=1.10),
        txn("T2", minutes=90, amount=2.40),
        txn("T3", minutes=180, amount=0.95),
        txn("T4", minutes=185, amount=259.98),
    ]
    findings = detect_card_testing("C04570-K1", txns)
    assert findings == []


# ---------------------------------------------------------------------------
# cnp_burst
# ---------------------------------------------------------------------------

def test_cnp_burst_fires_on_three_unusual_purchases_in_48h():
    txns = [
        txn("T1", minutes=0, amount=80, product_cd="H"),
        txn("T2", minutes=600, amount=95, product_cd="H"),
        txn("T3", minutes=1200, amount=120, product_cd="R"),
    ]
    findings = detect_cnp_burst("C04570-K1", txns, baseline_products={"C", "W"})
    assert len(findings) == 1
    assert findings[0].pattern == "card_not_present_fraud"
    assert len(findings[0].entity_ids) == 3


def test_cnp_burst_does_not_fire_on_single_unusual_purchase():
    """Near-miss: README explicitly says one unusual online purchase alone is
    ambiguous -- verify, don't flag as a burst."""
    txns = [txn("T1", minutes=0, amount=80, product_cd="H")]
    findings = detect_cnp_burst("C04570-K1", txns, baseline_products={"C", "W"})
    assert findings == []


def test_cnp_burst_does_not_fire_when_products_match_history():
    """Near-miss: purchases in the card's normal product categories, no mismatch."""
    txns = [
        txn("T1", minutes=0, amount=80, product_cd="C"),
        txn("T2", minutes=600, amount=95, product_cd="C"),
        txn("T3", minutes=1200, amount=120, product_cd="W"),
    ]
    findings = detect_cnp_burst("C04570-K1", txns, baseline_products={"C", "W"})
    assert findings == []


# ---------------------------------------------------------------------------
# new_device
# ---------------------------------------------------------------------------

def test_new_device_fires_on_id15_new():
    txns = [txn("T1", id_15="New")]
    findings = detect_new_device("C04570-K1", txns)
    assert len(findings) == 1
    assert findings[0].pattern == "card_not_present_new_device"
    assert "new_device_marker" in findings[0].weight_keys


def test_new_device_adds_proxy_weight_when_behind_proxy():
    txns = [txn("T1", id_15="New", id_23="Anonymous")]
    findings = detect_new_device("C04570-K1", txns)
    assert "proxy_flag" in findings[0].weight_keys


def test_new_device_does_not_fire_when_found():
    """Near-miss: id_15 == 'Found' (device previously seen) -- not a new-device signal."""
    txns = [txn("T1", id_15="Found")]
    findings = detect_new_device("C04570-K1", txns)
    assert findings == []


def test_new_device_does_not_fire_on_in_person_channel():
    """Near-miss: in_person transactions carry no identity record at all; id_15 should
    never be 'New' for a W-product in_person row, but guard the channel check anyway."""
    txns = [txn("T1", id_15="New", channel="in_person")]
    findings = detect_new_device("C04570-K1", txns)
    assert findings == []


# ---------------------------------------------------------------------------
# out_of_region
# ---------------------------------------------------------------------------

def test_out_of_region_fires_when_home_region_still_active_concurrently():
    """Positive: home-region and new-region transactions interleave within the
    concurrency window -- the card cannot physically be in both places at once. Per the
    README verbatim: 'while their normal activity continues at home' is the fraud tell."""
    txns = [
        txn("T1", minutes=0, addr1="204"),
        txn("T2", minutes=100, addr1="410"),   # new region
        txn("T3", minutes=200, addr1="204"),   # home still active nearby in time
        txn("T4", minutes=300, addr1="410"),
    ]
    findings = detect_out_of_region("C04570-K1", txns, historical_regions={"204"})
    assert len(findings) == 1
    assert findings[0].pattern == "out_of_region_use"
    assert set(findings[0].entity_ids) == {"T2", "T4"}
    assert "out_of_region_pattern" in findings[0].weight_keys


def test_out_of_region_does_not_fire_when_home_quiet_during_trip():
    """Near-miss: the README's own discriminator -- 'several days of purchases in one
    new region is a trip, not a clone.' Home activity cleanly stops before the new-region
    stretch starts and only resumes well after it ends -- no interleaving, no finding."""
    txns = [
        txn("T1", minutes=0, addr1="204"),
        txn("T2", minutes=60, addr1="204"),
        # gap with no home-region activity -- clean sequential split, a trip
        txn("T3", minutes=10000, addr1="410"),
        txn("T4", minutes=10100, addr1="410"),
    ]
    findings = detect_out_of_region("C04570-K1", txns, historical_regions={"204"})
    assert findings == []


def test_out_of_region_fires_more_strongly_on_multiple_new_regions_interleaved():
    """Two or more distinct new regions interleaved within the same short window is a
    stronger clone signal than a single new region (RESEARCH.md §4.2) -- should fire and
    carry the extra multi_region_clone_cluster weight key."""
    txns = [
        txn("T1", minutes=0, addr1="204"),      # home
        txn("T2", minutes=30, addr1="410"),     # new region A
        txn("T3", minutes=45, addr1="777"),     # new region B, same window
        txn("T4", minutes=60, addr1="204"),     # home again, interleaved
    ]
    findings = detect_out_of_region("C04570-K1", txns, historical_regions={"204"})
    assert len(findings) == 1
    assert set(findings[0].entity_ids) == {"T2", "T3"}
    assert "multi_region_clone_cluster" in findings[0].weight_keys


def test_out_of_region_does_not_fire_when_region_is_historical():
    """Near-miss: addr1 is already in the customer's historical set -- not out of region."""
    txns = [
        txn("T1", minutes=0, addr1="204"),
        txn("T2", minutes=60, addr1="410"),
    ]
    findings = detect_out_of_region("C04570-K1", txns, historical_regions={"204", "410"})
    assert findings == []


# ---------------------------------------------------------------------------
# account_takeover
# ---------------------------------------------------------------------------

def test_account_takeover_fires_on_two_cards_breaking_history_together():
    cards_txns = {
        "C04570-K1": [txn("T1", minutes=0, id_15="New", card_id="C04570-K1")],
        "C04570-K2": [txn("T2", minutes=30, M4="F", card_id="C04570-K2", channel="in_person")],
    }
    findings = detect_account_takeover("C04570", cards_txns)
    assert len(findings) == 1
    assert findings[0].pattern == "account_takeover"
    assert set(findings[0].entity_ids) == {"T1", "T2"}


def test_account_takeover_does_not_fire_on_single_card_anomaly():
    """Near-miss: only one card shows an anomaly -- that's a card-centric pattern
    (new_device / cnp_burst), not the customer-centric multi-card break that defines
    account_takeover per RESEARCH.md's own stated discriminator."""
    cards_txns = {
        "C04570-K1": [txn("T1", minutes=0, id_15="New", card_id="C04570-K1")],
        "C04570-K2": [txn("T2", minutes=30, card_id="C04570-K2")],
    }
    findings = detect_account_takeover("C04570", cards_txns)
    assert findings == []


def test_account_takeover_does_not_fire_when_anomalies_far_apart_in_time():
    """Near-miss: two cards each have an anomaly, but months apart -- two unrelated
    new-phone purchases, not one coordinated takeover episode."""
    cards_txns = {
        "C04570-K1": [txn("T1", minutes=0, id_15="New", card_id="C04570-K1")],
        "C04570-K2": [txn("T2", minutes=60 * 24 * 90, id_15="New", card_id="C04570-K2")],
    }
    findings = detect_account_takeover("C04570", cards_txns)
    assert findings == []


# ---------------------------------------------------------------------------
# shared_origin
# ---------------------------------------------------------------------------

def test_shared_origin_fires_on_device_shared_by_two_customers():
    txns = [
        txn("T1", minutes=0, card_id="C04570-K1", customer_id="C04570"),
        txn("T2", minutes=60, card_id="C08877-K1", customer_id="C08877"),
    ]
    findings = detect_shared_origin("device_profile", "SAMSUNG|Android7|Chrome|1920x1080", txns)
    assert len(findings) == 1
    assert findings[0].pattern == "undocumented"
    assert "SAMSUNG" in findings[0].evidence_items[0]
    assert set(findings[0].entity_ids) == {"T1", "T2"}


def test_shared_origin_does_not_fire_for_single_customer_multi_card():
    """Near-miss: same device used by two CARDS but both belong to ONE customer --
    that's normal (a person's own two cards on their own phone), not a shared-origin
    fraud ring across customers."""
    txns = [
        txn("T1", minutes=0, card_id="C04570-K1", customer_id="C04570"),
        txn("T2", minutes=60, card_id="C04570-K2", customer_id="C04570"),
    ]
    findings = detect_shared_origin("device_profile", "SAMSUNG|Android7|Chrome|1920x1080", txns)
    assert findings == []


def test_shared_origin_does_not_fire_outside_window():
    """Near-miss: two customers share a device, but 6 months apart -- not a coordinated
    ring in one window, just device resale or a coincidence long after the fact."""
    txns = [
        txn("T1", minutes=0, card_id="C04570-K1", customer_id="C04570"),
        txn("T2", minutes=60 * 24 * 180, card_id="C08877-K1", customer_id="C08877"),
    ]
    findings = detect_shared_origin("device_profile", "SAMSUNG|Android7|Chrome|1920x1080", txns)
    assert findings == []


# ---------------------------------------------------------------------------
# threshold_structuring (undocumented, existing detector -- was untested)
# ---------------------------------------------------------------------------

def test_threshold_structuring_fires_on_four_just_under_500():
    txns = [
        txn("T1", minutes=0, amount=489.00),
        txn("T2", minutes=10, amount=475.50),
        txn("T3", minutes=20, amount=492.10),
    ]
    findings = detect_threshold_structuring("C04570-K1", txns)
    assert len(findings) == 1
    assert findings[0].pattern == "undocumented"
    assert "cnp_burst_pattern" in findings[0].weight_keys


def test_threshold_structuring_does_not_fire_on_amounts_well_under_floor():
    """Near-miss: small purchases, nowhere near the $500 threshold -- ordinary spend,
    not structuring."""
    txns = [
        txn("T1", minutes=0, amount=20.00),
        txn("T2", minutes=10, amount=35.50),
        txn("T3", minutes=20, amount=42.10),
    ]
    findings = detect_threshold_structuring("C04570-K1", txns)
    assert findings == []


def test_threshold_structuring_does_not_fire_on_amounts_at_or_over_ceiling():
    """Near-miss: amounts at/over $500 -- not staying under the authorization threshold,
    so not structuring even if clustered in time."""
    txns = [
        txn("T1", minutes=0, amount=500.00),
        txn("T2", minutes=10, amount=520.00),
        txn("T3", minutes=20, amount=510.00),
    ]
    findings = detect_threshold_structuring("C04570-K1", txns)
    assert findings == []


# ---------------------------------------------------------------------------
# proxy_device_ring (undocumented -- CC-2649/2971/2985/3035)
# ---------------------------------------------------------------------------

def _ring_txn(txn_id, minutes=0, customer_id="C04570", card_id="C04570-K1",
              device_key="SM-G935F|Chrome|Android"):
    return txn(txn_id, minutes=minutes, channel="online", id_15="New", id_23="Anonymous",
               device_key=device_key, customer_id=customer_id, card_id=card_id)


def test_proxy_device_ring_fires_on_full_signature():
    txns = [_ring_txn("T1"), _ring_txn("T2", minutes=5)]
    other_txns = [
        _ring_txn("T3", customer_id="C08877", card_id="C08877-K1"),
        _ring_txn("T4", customer_id="C09998", card_id="C09998-K1"),
    ]
    findings = detect_proxy_device_ring(
        "C04570-K1", "C04570", txns, customer_denies=True,
        device_key="SM-G935F|Chrome|Android", other_customer_txns=other_txns,
    )
    assert len(findings) == 1
    assert findings[0].pattern == "undocumented"
    assert "proxy_device_ring" in findings[0].weight_keys
    assert set(findings[0].entity_ids) == {"T1", "T2"}


def test_proxy_device_ring_does_not_fire_without_denial():
    """Near-miss: same device/proxy/corroboration shape, but the cardholder never
    reported these as unrecognized -- must not fire on customer_denies=False."""
    txns = [_ring_txn("T1"), _ring_txn("T2", minutes=5)]
    other_txns = [
        _ring_txn("T3", customer_id="C08877", card_id="C08877-K1"),
        _ring_txn("T4", customer_id="C09998", card_id="C09998-K1"),
    ]
    findings = detect_proxy_device_ring(
        "C04570-K1", "C04570", txns, customer_denies=False,
        device_key="SM-G935F|Chrome|Android", other_customer_txns=other_txns,
    )
    assert findings == []


def test_proxy_device_ring_does_not_fire_without_proxy():
    """Near-miss: new device, denied, corroborated by other cardholders -- but NOT behind
    a proxy. That's card_not_present_new_device territory, not the ring."""
    txns = [txn("T1", channel="online", id_15="New", id_23=None,
                 device_key="SM-G935F|Chrome|Android")]
    other_txns = [
        _ring_txn("T3", customer_id="C08877", card_id="C08877-K1"),
        _ring_txn("T4", customer_id="C09998", card_id="C09998-K1"),
    ]
    findings = detect_proxy_device_ring(
        "C04570-K1", "C04570", txns, customer_denies=True,
        device_key="SM-G935F|Chrome|Android", other_customer_txns=other_txns,
    )
    assert findings == []


def test_proxy_device_ring_does_not_fire_with_only_one_other_customer():
    """Near-miss: device shared with only ONE other cardholder, not the two+ the
    precedent notes require -- could be coincidence, not a ring."""
    txns = [_ring_txn("T1")]
    other_txns = [_ring_txn("T3", customer_id="C08877", card_id="C08877-K1")]
    findings = detect_proxy_device_ring(
        "C04570-K1", "C04570", txns, customer_denies=True,
        device_key="SM-G935F|Chrome|Android", other_customer_txns=other_txns,
    )
    assert findings == []


# ---------------------------------------------------------------------------
# travel_consistent_with_history (exonerating)
# ---------------------------------------------------------------------------

def test_travel_consistent_with_history_fires_on_clean_sequential_move():
    txns = [
        txn("T1", minutes=0, addr1="204"),
        txn("T2", minutes=60, addr1="204"),
        txn("T3", minutes=10000, addr1="410"),
        txn("T4", minutes=10100, addr1="410"),
    ]
    findings = detect_travel_consistent_with_history("C04570-K1", txns, historical_regions={"204"})
    assert len(findings) == 1
    assert findings[0].pattern == "none"
    assert "travel_consistent_with_history" in findings[0].weight_keys
    assert set(findings[0].entity_ids) == {"T3", "T4"}


def test_travel_consistent_with_history_does_not_fire_when_home_concurrently_active():
    """Near-miss: home region interleaved with the new region -- that's the clone shape
    (detect_out_of_region's territory), not travel. Must not exonerate a clone."""
    txns = [
        txn("T1", minutes=0, addr1="204"),
        txn("T2", minutes=100, addr1="410"),
        txn("T3", minutes=200, addr1="204"),
        txn("T4", minutes=300, addr1="410"),
    ]
    findings = detect_travel_consistent_with_history("C04570-K1", txns, historical_regions={"204"})
    assert findings == []


def test_travel_consistent_with_history_does_not_fire_with_no_new_region():
    """Near-miss: all activity stays inside the historical region set -- nothing to
    exonerate, not a travel episode at all."""
    txns = [
        txn("T1", minutes=0, addr1="204"),
        txn("T2", minutes=60, addr1="204"),
    ]
    findings = detect_travel_consistent_with_history("C04570-K1", txns, historical_regions={"204"})
    assert findings == []


# ---------------------------------------------------------------------------
# new_device_otherwise_in_character (exonerating)
# ---------------------------------------------------------------------------

def test_new_device_otherwise_in_character_fires_when_in_baseline():
    txns = [txn("T1", channel="online", id_15="New", id_23=None, product_cd="C", addr1="204")]
    findings = detect_new_device_otherwise_in_character(
        "C04570-K1", txns, baseline_products={"C", "W"}, historical_regions={"204"},
    )
    assert len(findings) == 1
    assert findings[0].pattern == "none"
    assert "new_device_otherwise_in_character" in findings[0].weight_keys


def test_new_device_otherwise_in_character_does_not_fire_behind_proxy():
    """Near-miss: new device behind a proxy -- that combination is fraud territory
    (detect_proxy_device_ring / new_device+proxy_flag), never exonerating on its own."""
    txns = [txn("T1", channel="online", id_15="New", id_23="Anonymous", product_cd="C", addr1="204")]
    findings = detect_new_device_otherwise_in_character(
        "C04570-K1", txns, baseline_products={"C", "W"}, historical_regions={"204"},
    )
    assert findings == []


def test_new_device_otherwise_in_character_does_not_fire_on_product_mismatch():
    """Near-miss: new device AND the product category is outside baseline -- not
    'otherwise in character', a real corroborating anomaly."""
    txns = [txn("T1", channel="online", id_15="New", id_23=None, product_cd="H", addr1="204")]
    findings = detect_new_device_otherwise_in_character(
        "C04570-K1", txns, baseline_products={"C", "W"}, historical_regions={"204"},
    )
    assert findings == []


# ---------------------------------------------------------------------------
# amount_unusual_but_isolated (exonerating)
# ---------------------------------------------------------------------------

def test_amount_unusual_but_isolated_fires_on_clear_outlier():
    flagged = txn("T1", amount=300.0)
    findings = detect_amount_unusual_but_isolated("C04570-K1", flagged, historical_amounts=[50.0, 60.0, 55.0, 45.0])
    assert len(findings) == 1
    assert findings[0].pattern == "none"
    assert "amount_unusual_but_isolated" in findings[0].weight_keys
    assert findings[0].entity_ids == ["T1"]


def test_amount_unusual_but_isolated_does_not_fire_within_normal_range():
    """Near-miss: amount is only slightly above average -- not 'unusual', just a bigger
    day. Must not exonerate (or flag) on ordinary variance."""
    flagged = txn("T1", amount=70.0)
    findings = detect_amount_unusual_but_isolated("C04570-K1", flagged, historical_amounts=[50.0, 60.0, 55.0, 45.0])
    assert findings == []


def test_amount_unusual_but_isolated_does_not_fire_with_no_history():
    """Near-miss: no historical amounts at all -- nothing to compare against, can't call
    it 'unusual'."""
    flagged = txn("T1", amount=300.0)
    findings = detect_amount_unusual_but_isolated("C04570-K1", flagged, historical_amounts=[])
    assert findings == []
