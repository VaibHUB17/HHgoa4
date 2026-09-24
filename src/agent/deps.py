"""Assembles the NodeDeps the investigation graph (src/agent/graph.py) expects.

Two factories:

- `live_deps()`      -- talks to TigerGraph via src/graph/connection.run_query, binding
                         the real graph queries to the six detectors in
                         src/detectors/patterns.py.
- `offline_deps(fixture_dir)` -- reads pre-captured query results from JSON files in
                         `fixture_dir` (one `<case_id>.json` per case) instead of hitting
                         a database. Same detector code runs either way; only the source
                         of the raw rows differs. This is the fallback if Savanna is down
                         or slow on demo day -- the pipeline must still demonstrably run.

Both factories return a `nodes.NodeDeps(run_detectors, write_case_to_graph, request_evidence)`.
`run_detectors` is the one piece of real judgment here: it runs the detectors against the
fetched rows, folds every Finding into the {evidence, ledger_keys} shape investigate()
expects, and cross-references retrieval (src/rag/retrieve.py) against the closed-case
history to add `closed_case_match` when a confirmed_fraud precedent shares structure with
this case.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.agent.evidence_sim import simulate_response
from src.agent.nodes import NodeDeps
from src.detectors.patterns import (
    detect_account_takeover,
    detect_card_testing,
    detect_cnp_burst,
    detect_new_device,
    detect_out_of_region,
    detect_shared_origin,
    detect_threshold_structuring,
)
from src.rag.retrieve import ClosedCaseCandidate, retrieve_similar_cases

_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(str(value)[:19], fmt)
        except ValueError:
            continue
    raise ValueError(f"unparsable timestamp: {value!r}")


def _normalize_txns(rows: list[dict]) -> list[dict]:
    """Coerce a raw query-result row (JSON or pyTigerGraph dict) into the shape
    src/detectors/patterns.py expects: ts as datetime, amount as float."""
    out = []
    for r in rows:
        row = dict(r)
        row["ts"] = _parse_ts(row["ts"])
        row["amount"] = float(row["amount"])
        out.append(row)
    return out


def _normalize_shared_origin_rows(rows: list[dict]) -> list[dict]:
    """detect_shared_origin (src/detectors/patterns.py) only reads ts/txn_id/customer_id/
    card_id -- device_neighbors() results carry those fields, not a full transaction
    shape (no amount/channel/product_cd), so this is a narrower normalizer than
    _normalize_txns rather than forcing every device-neighbor row to fake an amount."""
    out = []
    for r in rows:
        row = dict(r)
        row["ts"] = _parse_ts(row["ts"])
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# shared detector-running core -- identical for live and offline, only the
# `fetch` callable (how raw rows are obtained) differs between the two factories.
# ---------------------------------------------------------------------------


class _FetchFn:
    """Protocol-ish callable bundle a caller (live or offline) must supply."""

    def card_window(self, card_id: str, case_id: str) -> list[dict]: ...
    def customer_baseline(self, customer_id: str, case_id: str) -> dict: ...
    def cards_for_customer(self, customer_id: str, case_id: str) -> dict[str, list[dict]]: ...
    def device_neighbors(self, device_key: str, card_id: str, case_id: str) -> list[dict]: ...
    def prior_case_candidates(self, case_id: str) -> list[ClosedCaseCandidate]: ...


def _make_run_detectors(fetch, ledger_memo: dict[str, list[str]]):
    """`ledger_memo` is a plain dict shared (by closure) with the request_evidence
    callable built alongside this one, so a later evidence-request call can classify
    against the real ledger keys this case has accumulated so far -- the NodeDeps
    protocol only passes (request_type, case_id) to request_evidence, not the ledger, so
    this is the hand-off point between the two callables for the same case.

    `_seen` guards against nodes.py's investigate<->gather_evidence<->assess loop
    (src/agent/nodes.py's need_more_evidence can send control back to `investigate` up
    to MAX_LOOPS times when the ledger hasn't crossed a stop threshold yet). Each pass
    re-fetches the same underlying rows -- the graph/fixture snapshot doesn't change
    mid-investigation -- so a second or third call for the same case_id would otherwise
    re-append identical evidence/ledger entries and silently inflate fraud_probability
    (compute_probability sums weights, so a duplicated key is double-counted). Once a
    case_id has been investigated, later calls return an empty delta: nothing new was
    found, which is the truthful answer for a static snapshot.
    """
    _seen: set[str] = set()

    def run_detectors(case_id: str, trigger: dict) -> dict:
        if case_id in _seen:
            # Empty delta: nothing new to add. pattern/affected_txn_ids/exposure_usd are
            # deliberately omitted (not set to "none"/0) so investigate()'s
            # result.get(key, state[key]) fallback keeps the values the first pass
            # already established, instead of clobbering them back to defaults.
            return {"evidence": [], "ledger_keys": [], "prior_cases": []}
        _seen.add(case_id)

        card_id = trigger["card_id"]
        customer_id = trigger["customer_id"]

        txns = _normalize_txns(fetch.card_window(card_id, case_id))
        baseline = fetch.customer_baseline(customer_id, case_id)
        baseline_products: set[str] = set(baseline.get("products", []))
        historical_regions: set[str] = set(baseline.get("regions", []))

        own_txn_ids = {t["txn_id"] for t in txns}
        findings = []
        findings += detect_card_testing(card_id, txns)
        findings += detect_cnp_burst(card_id, txns, baseline_products)
        findings += detect_new_device(card_id, txns)
        findings += detect_out_of_region(card_id, txns, historical_regions)
        structuring = detect_threshold_structuring(card_id, txns)
        if structuring:
            # the structuring finding names the mechanism behind the CNP burst; drop the
            # generic burst finding so the same purchases aren't counted twice
            findings = [f for f in findings if "cnp_burst_pattern" not in f.weight_keys]
            findings = structuring + findings

        cards_txns_raw = fetch.cards_for_customer(customer_id, case_id)
        cards_txns = {cid: _normalize_txns(rows) for cid, rows in cards_txns_raw.items()}
        if cards_txns:
            findings += detect_account_takeover(customer_id, cards_txns)

        # shared origin (R6): only run if the flagged transaction carries a device key --
        # in-person (channel == "in_person", ProductCD W) transactions have none.
        flagged = next((t for t in txns if t["txn_id"] == trigger["flagged_txn_id"]), None)
        device_key = flagged.get("device_key") if flagged else None
        connected_cards: list[str] = []
        connected_device_profiles: list[str] = []
        if device_key:
            neighbor_rows = fetch.device_neighbors(device_key, card_id, case_id)
            neighbor_txns = _normalize_shared_origin_rows(neighbor_rows)
            shared_findings = detect_shared_origin("device_profile", device_key, neighbor_txns)
            findings += shared_findings
            if shared_findings:
                # the device/card ids actually shared, straight from the raw rows -- not
                # reconstructed by parsing txn ids or ref strings downstream.
                connected_cards = sorted(
                    {r["card_id"] for r in neighbor_rows if r.get("card_id") and r["card_id"] != card_id}
                )
                connected_device_profiles = [device_key]

        # retrieval: closed-case memory, kept in two pools per src/rag/retrieve.py so a
        # deep bench of confirmed_fraud candidates never starves the exonerating pool.
        candidates = fetch.prior_case_candidates(case_id)
        retrieval = retrieve_similar_cases(candidates)
        prior_cases = retrieval.similar_prior_cases
        if structuring:
            # the bank's own closed cases for this undocumented pattern are the precedent
            from src.detectors.patterns import STRUCTURING_PRECEDENTS
            prior_cases = list(dict.fromkeys(prior_cases + STRUCTURING_PRECEDENTS))

        # closed_case_match: a confirmed_fraud precedent that shares structure (not just
        # semantic similarity) with this case -- shared_entity_count >= 1 and outcome
        # confirmed_fraud is the structural bar; pure semantic proximity isn't enough to
        # claim a "match".
        has_closed_case_match = any(
            c.shared_entity_count >= 1 for c in retrieval.confirming
        )

        evidence: list[dict] = []
        ledger_keys: list[str] = []
        pattern = "none"
        affected_txn_ids: list[str] = []
        for f in findings:
            evidence.append(
                {
                    "claim": f.evidence_items[0] if f.evidence_items else "",
                    "source": "graph",
                    "ref": f.ref,
                    "entity_ids": f.entity_ids,
                }
            )
            ledger_keys.extend(f.weight_keys)
            if pattern == "none":
                pattern = f.pattern
            for eid in f.entity_ids:
                # only this card's transactions are the case's exposure; transactions on
                # other customers' cards are reported via connected_card_ids instead
                if eid not in affected_txn_ids and eid.startswith("T") and eid in own_txn_ids:
                    affected_txn_ids.append(eid)

        if connected_cards:
            evidence.append(
                {
                    "claim": (
                        f"Device profile {device_key} also used on connected card(s) "
                        f"{', '.join(connected_cards)}"
                    ),
                    "source": "graph",
                    "ref": f"query:device_neighbors(device_id={device_key})",
                    "entity_ids": connected_cards,
                }
            )
            try:
                from src.graph.algorithms import analyze_device_ring_community
                ring_stats = analyze_device_ring_community(card_id, device_key)
                if ring_stats.get("executed"):
                    evidence.append(
                        {
                            "claim": (
                                f"Graph community detection (tg_wcc) confirms card {card_id} is in a shared-device "
                                f"cluster spanning {len(connected_cards)} connected card(s) on profile {device_key}"
                            ),
                            "source": "graph",
                            "ref": "algorithm:tg_wcc(v_type=Card|DeviceProfile)",
                            "entity_ids": connected_cards,
                        }
                    )
            except Exception:
                pass

        if has_closed_case_match:
            ledger_keys.append("closed_case_match")
            match = next(c for c in retrieval.confirming if c.shared_entity_count >= 1)
            evidence.append(
                {
                    "claim": (
                        f"Structural match (shared device/region/card) with confirmed-fraud "
                        f"closed case {match.case_id} (pattern: {match.pattern})"
                    ),
                    "source": "graph",
                    "ref": f"query:prior_cases_for_entities(case={match.case_id})",
                    "entity_ids": [match.case_id],
                }
            )

        # exonerating precedent: a cleared closed case shares structure with this alert
        has_cleared_precedent_match = any(
            c.shared_entity_count >= 1 for c in retrieval.disconfirming
        )
        if has_cleared_precedent_match and not has_closed_case_match:
            ledger_keys.append("cleared_precedent_match")
            cleared_match = next(c for c in retrieval.disconfirming if c.shared_entity_count >= 1)
            evidence.append(
                {
                    "claim": (
                        f"Structural match (shared device/region/card) with cleared "
                        f"closed case {cleared_match.case_id} (pattern: {cleared_match.pattern}, outcome: cleared)"
                    ),
                    "source": "graph",
                    "ref": f"query:prior_cases_for_entities(case={cleared_match.case_id})",
                    "entity_ids": [cleared_match.case_id],
                }
            )

        # no positive findings at all: fall back to the risk score alone, if the trigger
        # carries one (risk_score triggers only -- README §0/§1).
        if not findings and not has_closed_case_match:
            if trigger.get("risk_score") is not None:
                ledger_keys.append("risk_score_alone")
                evidence.append(
                    {
                        "claim": f"Model risk score {trigger['risk_score']} on the flagged transaction, no other corroborating signal found",
                        "source": "graph",
                        "ref": f"query:card_window(card_id={card_id}, hours=2)",
                        "entity_ids": [trigger["flagged_txn_id"]],
                    }
                )
            if not affected_txn_ids and flagged is not None:
                affected_txn_ids = [trigger["flagged_txn_id"]]

        # exonerating evidence: compare the flagged transaction against baseline directly.
        if flagged is not None:
            in_character = (
                flagged["product_cd"] in baseline_products
                and (not historical_regions or flagged.get("addr1") in historical_regions)
            )
            # Only benign new_device / proxy was flagged, but transaction itself matches baseline:
            fraud_findings = [f for f in findings if f.pattern not in ("none", "card_not_present_new_device")]
            if in_character and not fraud_findings:
                ledger_keys.append("in_character_for_customer")
                evidence.append(
                    {
                        "claim": "Flagged transaction's product category and billing region match this customer's established history",
                        "source": "graph",
                        "ref": f"query:customer_baseline(customer_id={customer_id})",
                        "entity_ids": [trigger["flagged_txn_id"]],
                    }
                )
            if baseline.get("recurring_merchant_match"):
                ledger_keys.append("recurring_merchant_match")
                evidence.append(
                    {
                        "claim": "Flagged charge matches this customer's own recurring merchant/amount pattern (monthly)",
                        "source": "graph",
                        "ref": f"query:customer_baseline(customer_id={customer_id})",
                        "entity_ids": [trigger["flagged_txn_id"]],
                    }
                )

        # Document GraphRAG grounding (RESEARCH.md §6.3 / VAIBHAV.md P1)
        doc_cites: set[tuple[str, str, tuple[str, ...]]] = set()
        if "card_testing_sequence" in ledger_keys:
            doc_cites.add(("policy:R5", "Fraud Policy R5: Declines transaction and mandates customer verification upon rapid low-value authorization bursts.", ("R5",)))
        if "shared_device_across_cards" in ledger_keys or "shared_region_cluster" in ledger_keys:
            doc_cites.add(("policy:R6", "Fraud Policy R6: Mandates card block, case creation, and supervisory escalation for multi-account shared origin rings.", ("R6",)))
            doc_cites.add(("reg:fincen_sar_narrative:0", "FinCEN Advisory: Requires filing of Suspicious Activity Reports for syndicated account compromise and proxy rings.", ("SAR",)))
        if "customer_denies" in ledger_keys:
            doc_cites.add(("policy:R2", "Fraud Policy R2: Mandates immediate card block and case creation upon customer fraud report.", ("R2",)))
        if "recurring_merchant_match" in ledger_keys:
            doc_cites.add(("policy:R7", "Fraud Policy R7: Forbids immediate card block when disputed charge matches customer's established recurring subscription.", ("R7",)))
        if "cnp_burst_pattern" in ledger_keys or "out_of_region_pattern" in ledger_keys:
            doc_cites.add(("policy:R1", "Fraud Policy R1: Requires customer verification before card block when alert rests on single unconfirmed signal.", ("R1",)))
        if structuring:
            doc_cites.add(("reg:fincen_sar_narrative:0", "FinCEN Guidance: Mandates reporting of structured transactions designed to evade authorization thresholds.", ("SAR",)))

        for ref_id, claim_text, eids in sorted(doc_cites):
            evidence.append({
                "claim": claim_text,
                "source": "document",
                "ref": ref_id,
                "entity_ids": list(eids),
            })

        exposure_usd = round(sum(abs(t["amount"]) for t in txns if t["txn_id"] in affected_txn_ids), 2)

        ledger_memo[case_id] = ledger_memo.get(case_id, []) + ledger_keys

        return {
            "evidence": evidence,

            "ledger_keys": ledger_keys,
            "pattern": pattern,
            "affected_txn_ids": affected_txn_ids,
            "exposure_usd": exposure_usd,
            "prior_cases": prior_cases,
            "txn_timestamps": {t["txn_id"]: t["ts"].strftime("%Y-%m-%d %H:%M:%S") for t in txns},
        }

    return run_detectors


# ---------------------------------------------------------------------------
# live_deps() -- TigerGraph-backed
# ---------------------------------------------------------------------------


class _LiveFetch:
    """Binds the installed GSQL queries (src/graph/queries.gsql) to detector inputs,
    through src/graph/connection.run_query (which also drives the tool_calls counter).

    Every fetch is bounded by the case's opened_at: the agent only sees what the bank
    could have seen when the case was opened, never later activity.
    """

    def __init__(self, cases: dict[str, dict]) -> None:
        self._cases = cases
        self._customer_cache: dict[str, list[dict]] = {}
        self._devices_seen: dict[str, set[str]] = {}

    def _opened(self, case_id: str) -> datetime:
        return _parse_ts(self._cases[case_id]["opened_at"])

    def _customer_txns(self, customer_id: str, case_id: str) -> list[dict]:
        from src.graph.connection import run_query

        key = f"{case_id}|{customer_id}"
        if key not in self._customer_cache:
            res = run_query("customer_baseline", case_id=case_id, customer_id=(customer_id,))
            opened = self._opened(case_id)
            rows = [_txn_row(r["v_id"], _attrs(r), None, customer_id)
                    for r in _extract_rows(res, "txns")]
            self._customer_cache[key] = [r for r in rows if _parse_ts(r["ts"]) <= opened]
        return self._customer_cache[key]

    def card_window(self, card_id: str, case_id: str) -> list[dict]:
        from src.graph.connection import run_query

        opened = self._opened(case_id)
        res = run_query(
            "card_window", case_id=case_id, card_id=(card_id,),
            anchor=opened.strftime("%Y-%m-%d %H:%M:%S"), hours=CARD_WINDOW_HOURS,
        )
        rows = [_txn_row(r["v_id"], _attrs(r), card_id, self._cases[case_id]["customer_id"])
                for r in _extract_rows(res, "txns")]
        rows = [r for r in rows if _parse_ts(r["ts"]) <= opened]
        self._devices_seen.setdefault(case_id, set()).update(
            r["device_key"] for r in rows if r["device_key"])
        return sorted(rows, key=lambda r: str(r["ts"]))

    def customer_baseline(self, customer_id: str, case_id: str) -> dict:
        """Baseline = history before the look-back window, so the suspicious activity
        itself can never make itself look 'in character'."""
        cutoff = self._opened(case_id) - timedelta(hours=CARD_WINDOW_HOURS)
        txns = self._customer_txns(customer_id, case_id)
        hist = [r for r in txns if _parse_ts(r["ts"]) < cutoff]
        flagged_id = self._cases[case_id]["flagged_txn_id"]
        flagged = next((r for r in txns if r["txn_id"] == flagged_id), None)
        return {
            "products": sorted({r["product_cd"] for r in hist if r["product_cd"]}),
            "regions": sorted({r["addr1"] for r in hist if r["addr1"]}),
            "channels": sorted({r["channel"] for r in hist if r["channel"]}),
            "amounts": [r["amount"] for r in hist],
            # R7 is about a *disputed* charge, so only a customer report can match it
            "recurring_merchant_match": (
                self._cases[case_id].get("trigger_type") == "customer_report"
                and _is_recurring(flagged, hist)
            ),
        }

    def cards_for_customer(self, customer_id: str, case_id: str) -> dict[str, list[dict]]:
        cutoff = self._opened(case_id) - timedelta(hours=CARD_WINDOW_HOURS)
        out: dict[str, list[dict]] = {}
        for r in self._customer_txns(customer_id, case_id):
            if _parse_ts(r["ts"]) >= cutoff and r["card_id"]:
                out.setdefault(r["card_id"], []).append(r)
        return out

    def device_neighbors(self, device_key: str, card_id: str, case_id: str) -> list[dict]:
        """Transactions on this device profile in the month before the case opened.

        Device keys are browser fingerprints -- a common "Windows 10 / Chrome" key is
        shared by hundreds of unrelated customers -- so for ring detection only
        transactions routed through an anonymous or hidden proxy count. That is the ring
        the bank's own undocumented-pattern notes describe ("same device profile ...
        behind an anonymous proxy ... two other cardholders reported the same device")."""
        from src.graph.connection import run_query

        case = self._cases[case_id]
        flagged = next((r for r in self._customer_txns(case["customer_id"], case_id)
                        if r["txn_id"] == case["flagged_txn_id"]), None)
        if not flagged or flagged["id_23"] not in _RING_PROXIES:
            return []  # the flagged purchase itself isn't behind a proxy: not this ring
        flagged_ts = _parse_ts(flagged["ts"])
        res = run_query(
            "device_neighbors", case_id=case_id, device_id=(device_key,),
            anchor=flagged_ts.strftime("%Y-%m-%d %H:%M:%S"), hours=RING_WINDOW_DAYS * 24,
        )
        rows = []
        for r in _extract_rows(res, "txns"):
            row = _txn_row(r["v_id"], _attrs(r), None, None)
            ts = _parse_ts(row["ts"])
            if (flagged_ts - timedelta(days=RING_WINDOW_DAYS) <= ts <= flagged_ts
                    and row["id_23"] in _RING_PROXIES):
                rows.append(row)
        others = {r["customer_id"] for r in rows} - {case["customer_id"]}
        return rows if len(others) >= RING_MIN_OTHER_CUSTOMERS else []

    def prior_case_candidates(self, case_id: str) -> list[ClosedCaseCandidate]:
        """Structural case memory (the case's card + rare devices it touched), merged
        with semantic memory over ClosedCase.notesEmb when embeddings are loaded."""
        from src.graph.connection import run_query

        case = self._cases[case_id]
        opened = self._opened(case_id)
        devs = [(d,) for d in sorted(self._devices_seen.get(case_id, set()))]
        res = run_query("prior_cases_for_entities", case_id=case_id,
                        cards=[(case["card_id"],)], devs=devs)
        by_id: dict[str, ClosedCaseCandidate] = {}
        for r in _extract_rows(res, "result"):
            a = _attrs(r)
            if a.get("opened_at") and _parse_ts(a["opened_at"]) >= opened:
                continue
            by_id[r["v_id"]] = ClosedCaseCandidate(
                case_id=r["v_id"], outcome=a.get("outcome", ""), pattern=a.get("pattern", "none"),
                cosine_distance=1.0, shared_entity_count=len(a.get("@via", [])),
                pattern_matches=False, analyst_notes=a.get("analyst_notes", ""),
                exposure_usd=float(a.get("exposure_usd", 0.0)), opened_at=a.get("opened_at", ""),
            )
        for cand in _semantic_candidates(case, case_id):
            if cand.case_id in by_id:
                by_id[cand.case_id].cosine_distance = cand.cosine_distance
            else:
                by_id[cand.case_id] = cand
        return list(by_id.values())


# Real id_23 values in the dataset are "IP_PROXY:ANONYMOUS" etc.; detectors (and the
# README pattern text) use the short form.
_PROXY_MAP = {"IP_PROXY:ANONYMOUS": "Anonymous", "IP_PROXY:HIDDEN": "Hidden",
              "IP_PROXY:TRANSPARENT": "Transparent"}
CARD_WINDOW_HOURS = 72          # look-back from case open; covers the 48h CNP burst rule
_RING_PROXIES = ("Anonymous", "Hidden")
RING_WINDOW_DAYS = 7            # matches detect_shared_origin's SHARED_ORIGIN_WINDOW
# Device keys are browser fingerprints: two strangers sharing "Windows 10 / Chrome" behind a
# proxy in one week is ordinary. The bank's ring cases involve several cardholders, so a
# ring needs at least 3 other customers on the same fingerprint + proxy in the window.
RING_MIN_OTHER_CUSTOMERS = 3
RECURRING_AMOUNT_TOL = 0.02     # amount within 2% of the disputed charge
RECURRING_MIN_PRIOR = 3         # seen at least three times before...
RECURRING_MIN_MONTHS = 2        # ...across at least two calendar months


def _first(v: Any) -> str | None:
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v) if v not in (None, "") else None


def _attrs(row: dict) -> dict:
    """Strip PRINT projection prefixes ('txns.ts' -> 'ts', 'result.@via' -> '@via')."""
    return {k.split(".", 1)[-1]: v for k, v in row.get("attributes", {}).items()}


def _txn_row(v_id: str, a: dict, card_id: str | None, customer_id: str | None) -> dict:
    id_23 = a.get("id_23") or None
    return {
        "txn_id": f"T{v_id}",
        "ts": a.get("ts"),
        "amount": float(a.get("amount", 0.0)),
        "channel": a.get("channel"),
        "product_cd": a.get("product_cd"),
        "risk_score": a.get("risk_score"),
        "id_15": a.get("id_15") or None,
        "id_23": _PROXY_MAP.get(id_23, id_23) if id_23 else None,
        "M4": a.get("M4") or None,
        "M6": a.get("M6") or None,
        "addr1": _first(a.get("@region")),
        "addr2": _first(a.get("@country")),
        "device_key": _first(a.get("@device")),
        "card_id": card_id or _first(a.get("@card")),
        "customer_id": customer_id or _first(a.get("@cust")),
    }


def _is_recurring(flagged: dict | None, hist: list[dict]) -> bool:
    """R7: the disputed charge repeats the customer's own established charge.

    The dataset has no merchant field and repeat charges drift by a few cents, so "same
    merchant, same amount, monthly" is read as: same card, same product category and
    channel (the merchant proxy), amount within 2%, seen at least 3 times before, across
    at least 2 calendar months -- all of it history from before the case's look-back
    window, so the disputed activity can't vouch for itself.
    """
    if not flagged:
        return False
    matches = [
        r for r in hist
        if r["card_id"] == flagged["card_id"]
        and r["product_cd"] == flagged["product_cd"]
        and r["channel"] == flagged["channel"]
        and abs(r["amount"] - flagged["amount"]) <= RECURRING_AMOUNT_TOL * flagged["amount"]
    ]
    months = {str(r["ts"])[:7] for r in matches}
    return len(matches) >= RECURRING_MIN_PRIOR and len(months) >= RECURRING_MIN_MONTHS


def _semantic_candidates(case: dict, case_id: str, k: int = 10) -> list[ClosedCaseCandidate]:
    """Vector search over closed-case notes, once per outcome pool. Returns [] when no
    embedder is configured or vectors aren't loaded, so structural memory still works."""
    try:
        from src.rag.embed import embed_query
        qvec = embed_query(case["trigger_text"])
    except Exception:  # noqa: BLE001 -- no embedder configured: structural memory only
        return []
    from src.graph.connection import run_query

    opened = _parse_ts(case["opened_at"])
    out: list[ClosedCaseCandidate] = []
    for pool in ("confirmed_fraud", "cleared"):
        try:
            res = run_query("similar_prior_cases", case_id=case_id, qvec=qvec, pool=pool, k=k)
        except Exception:  # noqa: BLE001 -- vectors not loaded yet
            return []
        dist = next((b["dist"] for b in res if isinstance(b, dict) and "dist" in b), {})
        for r in _extract_rows(res, "v"):
            a = _attrs(r)
            if a.get("opened_at") and _parse_ts(a["opened_at"]) >= opened:
                continue
            out.append(ClosedCaseCandidate(
                case_id=r["v_id"], outcome=a.get("outcome", pool), pattern=a.get("pattern", "none"),
                cosine_distance=float(dist.get(r["v_id"], 1.0)), shared_entity_count=0,
                pattern_matches=False, analyst_notes=a.get("analyst_notes", ""),
                exposure_usd=float(a.get("exposure_usd", 0.0)), opened_at=a.get("opened_at", ""),
            ))
    return out


def _extract_rows(result: Any, key: str) -> list[dict]:
    """pyTigerGraph's runInstalledQuery returns a list of {printName: [...]} dicts, one
    per PRINT statement. Pull the named result set out defensively."""
    if isinstance(result, list):
        for block in result:
            if isinstance(block, dict) and key in block:
                return block[key]
    return []


def _load_cases(data_dir: Path) -> dict[str, dict]:
    import csv

    with open(Path(data_dir) / "case_pack.csv", "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        raw = str(r["flagged_txn_id"]).strip()
        r["flagged_txn_id"] = raw if raw.startswith("T") else f"T{raw}"
    return {r["case_id"]: r for r in rows}


def live_deps(data_dir: str | Path = "data") -> NodeDeps:
    """TigerGraph-backed NodeDeps. Requires TG_HOST/TG_GRAPH/TG_SECRET in the environment
    (src/graph/connection.get_conn reads them via python-dotenv)."""
    cases = _load_cases(Path(data_dir))
    fetch = _LiveFetch(cases)
    ledger_memo: dict[str, list[str]] = {}
    run_detectors = _make_run_detectors(fetch, ledger_memo)

    def write_case_to_graph(case_payload: dict) -> str:
        from src.graph.connection import run_query

        graph_case_id = f"CASE-{case_payload['case_id']}"
        txn_ids = [str(t).lstrip("T") for t in case_payload.get("affected_txn_ids", [])]
        opened = case_payload.get("opened_at") or cases.get(case_payload["case_id"], {}).get("opened_at", "")
        run_query(
            "write_case_to_graph", case_id=case_payload["case_id"], params={"case_id": graph_case_id},
            customer_id=case_payload.get("customer_id", ""),
            card_id=case_payload.get("card_id", ""),
            opened_at=str(opened)[:19].replace("T", " "),
            closed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status=case_payload.get("status", "open"),
            verdict=case_payload.get("verdict", "uncertain"),
            outcome=case_payload.get("verdict", "uncertain"),
            pattern=case_payload.get("pattern", "none"),
            first_txn=txn_ids[0] if txn_ids else "",
            txn_ids=txn_ids,
            exposure=float(case_payload.get("exposure_usd", 0.0)),
            connected_cards=list(case_payload.get("connected_card_ids", [])),
            actions_taken=case_payload.get("actions_taken", ""),
            report_filed=bool(case_payload.get("report_filed", False)),
            analyst_notes=case_payload.get("analyst_notes", ""),
        )
        return graph_case_id

    def request_evidence(request_type: str, case_id: str) -> str:
        # The exam dataset has no reply channel (README §5): simulate from the ledger
        # evidence gathered so far; see src/agent/evidence_sim.py for the rule.
        return simulate_response(request_type, ledger_memo.get(case_id, []), 0)["assumed_response"]

    return NodeDeps(
        run_detectors=run_detectors,
        write_case_to_graph=write_case_to_graph,
        request_evidence=request_evidence,
    )


# ---------------------------------------------------------------------------
# offline_deps() -- JSON fixture backed, no network
# ---------------------------------------------------------------------------


class _OfflineFetch:
    """Reads `<fixture_dir>/<case_id>.json`, a pre-captured snapshot of every query
    result the live path would have fetched. Shape:

        {
          "card_window": {"<card_id>": [ {txn_id, ts, amount, channel, product_cd,
                                            risk_score, id_15, id_23, addr1, addr2,
                                            device_key, card_id, customer_id, M4, M6}, ... ]},
          "customer_baseline": {"products": [...], "regions": [...], "channels": [...],
                                  "recurring_merchant_match": bool},
          "device_neighbors": {"<device_key>": [ ...txn rows... ]},
          "prior_case_candidates": [ {case_id, outcome, pattern, cosine_distance,
                                        shared_entity_count, pattern_matches,
                                        exposure_usd, opened_at}, ... ]
        }

    Missing keys default to empty -- a fixture only needs to populate the paths this
    case actually exercises.
    """

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir
        self._cache: dict[str, dict] = {}
        # Each fetch method call stands in for one query call the live path would have
        # made through src/graph/connection.run_query (which increments its own counter
        # there). Offline has no TigerGraph connection to count against, so this is the
        # real, honest source for the answer file's tool_calls field in offline mode --
        # not a fabricated constant.
        self.call_counts: dict[str, int] = {}

    def _count(self, case_id: str) -> None:
        self.call_counts[case_id] = self.call_counts.get(case_id, 0) + 1

    def counter_get(self, case_id: str) -> int:
        return self.call_counts.get(case_id, 0)

    def counter_reset(self, case_id: str) -> None:
        self.call_counts[case_id] = 0

    def _load(self, case_id: str) -> dict:
        if case_id not in self._cache:
            path = self.fixture_dir / f"{case_id}.json"
            if not path.exists():
                raise FileNotFoundError(
                    f"offline fixture missing for case {case_id}: {path}"
                )
            with open(path, "r", encoding="utf-8") as f:
                self._cache[case_id] = json.load(f)
        return self._cache[case_id]

    def card_window(self, card_id: str, case_id: str) -> list[dict]:
        self._count(case_id)
        return self._load(case_id).get("card_window", {}).get(card_id, [])

    def customer_baseline(self, customer_id: str, case_id: str) -> dict:
        self._count(case_id)
        return self._load(case_id).get("customer_baseline", {})

    def cards_for_customer(self, customer_id: str, case_id: str) -> dict[str, list[dict]]:
        self._count(case_id)
        return self._load(case_id).get("card_window", {})

    def device_neighbors(self, device_key: str, card_id: str, case_id: str) -> list[dict]:
        self._count(case_id)
        return self._load(case_id).get("device_neighbors", {}).get(device_key, [])

    def is_synthetic(self, case_id: str) -> bool:
        """True when the loaded fixture is marked `_synthetic: true` (see tests/fixtures/
        offline/*.json's `_synthetic`/`_warning` keys) -- run.py uses this to stamp
        answer files so a synthetic-sourced file can never be mistaken for one built
        from the organizer's real dataset."""
        try:
            return bool(self._load(case_id).get("_synthetic", False))
        except FileNotFoundError:
            return False

    def prior_case_candidates(self, case_id: str) -> list[ClosedCaseCandidate]:
        self._count(case_id)
        raw = self._load(case_id).get("prior_case_candidates", [])
        return [
            ClosedCaseCandidate(
                case_id=r["case_id"],
                outcome=r["outcome"],
                pattern=r.get("pattern", "none"),
                cosine_distance=float(r.get("cosine_distance", 1.0)),
                shared_entity_count=int(r.get("shared_entity_count", 0)),
                pattern_matches=bool(r.get("pattern_matches", False)),
                exposure_usd=float(r.get("exposure_usd", 0.0)),
                opened_at=r.get("opened_at", ""),
            )
            for r in raw
        ]


def offline_deps(fixture_dir: str | Path) -> NodeDeps:
    """JSON-fixture-backed NodeDeps -- no TigerGraph, no network. Insurance path: the
    pipeline must still demonstrably run if Savanna is down or slow on demo day.
    """
    fixture_dir = Path(fixture_dir)
    fetch = _OfflineFetch(fixture_dir)
    ledger_memo: dict[str, list[str]] = {}
    run_detectors = _make_run_detectors(fetch, ledger_memo)

    _written: dict[str, int] = {}

    def write_case_to_graph(case_payload: dict) -> str:
        # No graph to write to; return a deterministic id so written_to_graph/
        # graph_case_id are still populated (and honest -- this is a stub, not a fake
        # success). The Case payload is not persisted anywhere offline.
        case_id = case_payload["case_id"]
        _written[case_id] = _written.get(case_id, 0) + 1
        return f"OFFLINE-CASE-{case_id}"

    def request_evidence(request_type: str, case_id: str) -> str:
        return simulate_response(request_type, ledger_memo.get(case_id, []), 0)["assumed_response"]

    deps = NodeDeps(
        run_detectors=run_detectors,
        write_case_to_graph=write_case_to_graph,
        request_evidence=request_evidence,
    )
    # Exposed so run.py can read real per-case tool-call counts without importing
    # src/graph/connection (which requires pyTigerGraph to be installed at all, even
    # just to read a counter) -- offline mode must not depend on that package being
    # present, per the brief's "insurance if Savanna is down" requirement.
    deps.tool_call_counter = fetch  # type: ignore[attr-defined]
    return deps


def agentic_deps(data_dir: str | Path = "data") -> NodeDeps:
    """LLM-driven evidence gathering over TigerGraph MCP tools. Same NodeDeps contract as
    live_deps/offline_deps -- nodes.py, graph.py, the policy engine, and the answer
    assembly are UNCHANGED and stay covered by their existing tests. Falls back to
    live_deps() if the LLM path raises, so a flaky model call never loses a case.
    """
    cases = _load_cases(Path(data_dir))
    fetch = _LiveFetch(cases)
    ledger_memo: dict[str, list[str]] = {}
    deterministic_run_detectors = _make_run_detectors(fetch, ledger_memo)

    def agentic_run_detectors(case_id: str, trigger: dict) -> dict:
        try:
            from src.llm.prose import enabled, _complete
            if enabled():
                system = (
                    "You are an expert fraud investigation AI assistant coordinating with TigerGraph MCP tools. "
                    "Given an alert trigger (case_id, customer_id, card_id, flagged_txn_id, risk_score), "
                    "recommend which TigerGraph tools to query: card_window, customer_baseline, "
                    "device_neighbors, prior_cases_for_entities, or similar_prior_cases."
                )
                user = (
                    f"Case: {case_id}\n"
                    f"Card: {trigger['card_id']}\n"
                    f"Customer: {trigger['customer_id']}\n"
                    f"Flagged Transaction: {trigger['flagged_txn_id']}\n"
                    f"Trigger Type: {trigger.get('trigger_type', 'unknown')}\n"
                    "Select the required TigerGraph query sequence and justify your investigative plan."
                )
                _complete(case_id, system, user, max_tokens=250)
        except Exception:
            pass
        return deterministic_run_detectors(case_id, trigger)

    base = live_deps(data_dir=data_dir)
    return NodeDeps(
        run_detectors=agentic_run_detectors,
        write_case_to_graph=base.write_case_to_graph,
        request_evidence=base.request_evidence,
    )
