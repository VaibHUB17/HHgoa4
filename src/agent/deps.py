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

        findings = []
        findings += detect_card_testing(card_id, txns)
        findings += detect_cnp_burst(card_id, txns, baseline_products)
        findings += detect_new_device(card_id, txns)
        findings += detect_out_of_region(card_id, txns, historical_regions)

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
                if eid not in affected_txn_ids and eid.startswith("T"):
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
            if in_character and not findings:
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

        exposure_usd = round(sum(abs(t["amount"]) for t in txns if t["txn_id"] in affected_txn_ids), 2)

        ledger_memo[case_id] = ledger_memo.get(case_id, []) + ledger_keys

        return {
            "evidence": evidence,
            "ledger_keys": ledger_keys,
            "pattern": pattern,
            "affected_txn_ids": affected_txn_ids,
            "exposure_usd": exposure_usd,
            "prior_cases": prior_cases,
        }

    return run_detectors


# ---------------------------------------------------------------------------
# live_deps() -- TigerGraph-backed
# ---------------------------------------------------------------------------


class _LiveFetch:
    """Binds the six installed GSQL queries (src/graph/queries.gsql) to detector inputs,
    through src/graph/connection.run_query (which also drives the real tool_calls counter).
    """

    def card_window(self, card_id: str, case_id: str) -> list[dict]:
        from src.graph.connection import run_query

        result = run_query(
            "card_window", case_id=case_id, card_id=card_id,
            anchor=datetime.utcnow().isoformat(), hours=48,
        )
        return _extract_rows(result, "txns")

    def customer_baseline(self, customer_id: str, case_id: str) -> dict:
        from src.graph.connection import run_query

        result = run_query("customer_baseline", case_id=case_id, customer_id=customer_id)
        payload = result[0] if isinstance(result, list) and result else (result or {})
        return {
            "products": payload.get("@@products", []),
            "regions": payload.get("@@regions", []),
            "channels": payload.get("@@channels", []),
            "amounts": payload.get("@@amounts", []),
            "recurring_merchant_match": bool(payload.get("recurring_merchant_match", False)),
        }

    def cards_for_customer(self, customer_id: str, case_id: str) -> dict[str, list[dict]]:
        # No dedicated installed query enumerates every card's txns for a customer in one
        # call; customer_baseline's card traversal is reused per-card via card_window.
        # ponytail: one extra query per known card, acceptable at 20-case exam scale.
        # Upgrade path: add a `customer_cards` GSQL query if this becomes a hot path.
        from src.graph.connection import run_query

        result = run_query("customer_baseline", case_id=case_id, customer_id=customer_id)
        payload = result[0] if isinstance(result, list) and result else (result or {})
        card_ids = payload.get("card_ids", [])
        out = {}
        for cid in card_ids:
            out[cid] = self.card_window(cid, case_id)
        return out

    def device_neighbors(self, device_key: str, card_id: str, case_id: str) -> list[dict]:
        from src.graph.connection import run_query

        result = run_query("device_neighbors", case_id=case_id, device_id=device_key)
        return _extract_rows(result, "cards")

    def prior_case_candidates(self, case_id: str) -> list[ClosedCaseCandidate]:
        from src.graph.connection import run_query

        result = run_query("prior_cases_for_entities", case_id=case_id, cards=[], devs=[], regs=[])
        rows = _extract_rows(result, "result")
        return [
            ClosedCaseCandidate(
                case_id=r["case_id"],
                outcome=r["outcome"],
                pattern=r.get("pattern", "none"),
                cosine_distance=float(r.get("cosine_distance", 1.0)),
                shared_entity_count=int(r.get("shared_entity_count", 1)),
                pattern_matches=bool(r.get("pattern_matches", False)),
                exposure_usd=float(r.get("exposure_usd", 0.0)),
                opened_at=r.get("opened_at", ""),
            )
            for r in rows
        ]


def _extract_rows(result: Any, key: str) -> list[dict]:
    """pyTigerGraph's runInstalledQuery returns a list of {printName: [...]} dicts, one
    per PRINT statement. Pull the named result set out defensively."""
    if isinstance(result, list):
        for block in result:
            if isinstance(block, dict) and key in block:
                return block[key]
        # fallback: single PRINT, unwrapped
        if result and isinstance(result[0], dict) and "v_id" not in result[0]:
            return result
    return []


def live_deps() -> NodeDeps:
    """TigerGraph-backed NodeDeps. Requires TG_HOST/TG_GRAPHNAME/... in the environment
    (src/graph/connection.get_conn reads them via python-dotenv)."""
    fetch = _LiveFetch()
    ledger_memo: dict[str, list[str]] = {}
    run_detectors = _make_run_detectors(fetch, ledger_memo)

    def write_case_to_graph(case_payload: dict) -> str:
        from src.graph.connection import run_query

        graph_case_id = f"CASE-{case_payload['case_id']}"
        run_query(
            "write_case_to_graph",
            case_id=graph_case_id,
            customer_id=case_payload.get("customer_id", ""),
            card_id=case_payload.get("card_id", ""),
            opened_at=case_payload.get("opened_at", datetime.utcnow().isoformat()),
            status=case_payload.get("status", "open"),
            verdict=case_payload.get("verdict", "uncertain"),
            outcome=case_payload.get("verdict", "uncertain"),
            pattern=case_payload["pattern"],
            first_txn=case_payload["affected_txn_ids"][0] if case_payload["affected_txn_ids"] else "",
            txn_ids=case_payload["affected_txn_ids"],
            exposure=case_payload["exposure_usd"],
            connected_cards=case_payload.get("connected_card_ids", []),
            actions_taken=case_payload.get("actions_taken", ""),
            report_filed=case_payload.get("report_filed", False),
            analyst_notes=case_payload.get("analyst_notes", ""),
        )
        return graph_case_id

    def request_evidence(request_type: str, case_id: str) -> str:
        # Customer/analyst replies are not available live either (README §5) -- the exam
        # dataset has no reply channel. Simulate using whatever ledger evidence
        # run_detectors has gathered so far for this case (see ledger_memo above); see
        # src/agent/evidence_sim.py for the documented rule. asked_after_step is filled
        # in by nodes.request_evidence's caller, which records the real step number in
        # the evidence_requests entry it builds -- this callable only returns the text.
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
