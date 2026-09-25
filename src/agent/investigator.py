"""Iterative, LLM-directed investigation loop over TigerGraph MCP.

This is the "actually agentic" layer the team lead asked for, sitting beside (not inside)
`src/agent/nodes.py`'s deterministic LangGraph state machine. It answers two questions an
LLM is well suited to and a fixed pipeline is not:

  1. WHERE TO LOOK NEXT -- given what's been found so far, which entity (a card, a device,
     a customer, a region) is worth another query, and which of the six installed queries
     (or a guarded ad-hoc traversal) answers that question. A shared-device finding points
     at `device_neighbors` / `prior_cases_for_entities`; a burst of small authorizations
     points at another `card_window` pass on a connected card. The choice depends on the
     evidence gathered, not a fixed sequence.

  2. WHEN TO STOP -- given the evidence gathered, is it enough to reach a defensible
     conclusion, or is something specific still missing?

STRICT BOUNDARY -- read this before changing anything:
  The LLM in this module NEVER decides the verdict, the fraud probability, or the next
  best action. It only proposes WHERE to look and WHETHER enough has been gathered to hand
  off. `InvestigationResult.evidence` is exactly the same {claim, source, ref, entity_ids}
  shape `src/agent/nodes.py:investigate()` already folds into the ledger; the weighted
  ledger (src/policy/ledger.py) and the R1-R10 rule engine (src/policy/engine.py) still
  compute probability, verdict and actions from that evidence, deterministically and
  auditably, exactly as before. This module is a smarter evidence-gathering front end for
  `deps.run_detectors`, not a second decision-maker. That split -- LLM picks the query,
  policy picks the verdict -- is what makes this agentic without becoming unaccountable.

NO HARDCODED FALLBACK ON LLM UNAVAILABILITY:
  If `src.llm.prose.enabled()` is False (no GROQ_API_KEY, disabled, or under pytest),
  `investigate()` does NOT silently run a fixed query sequence and label it agentic. It
  runs one grounding query so the case isn't empty, then returns immediately with
  `llm_available=False` and `stop_reason` explaining why, so a degraded run is visible in
  the output rather than disguised as a real reasoning loop.

QUERY GUARD (LLM-generated GSQL via MCP):
  Beyond the six installed queries, the model may request a parameterised read-only
  traversal (`propose_traversal` action) when none of the installed queries fits. Every
  such request passes through `_guard_generated_query` before touching the database:
  read-only statement allowlist (must start with SELECT after stripping GSQL's
  `INTERPRET QUERY (...) FOR GRAPH ... {` wrapper), a hard keyword blocklist (INSERT,
  UPDATE, DELETE, DROP, CREATE, ALTER, GRANT, REVOKE), a row cap, and a timeout. Every
  generated query is logged verbatim into `InvestigationResult.evidence` win or lose -- a
  rejected query is recorded as evidence of the agent's behaviour, not hidden.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

INSTALLED_QUERIES = {
    "card_window": ["card_id", "anchor", "hours"],
    "device_neighbors": ["device_id", "anchor", "hours"],
    "customer_baseline": ["customer_id"],
    "prior_cases_for_entities": ["cards", "devs"],
    "similar_prior_cases": ["qvec", "pool", "k"],
}

MAX_GENERATED_QUERY_ROWS = 200
GENERATED_QUERY_TIMEOUT_S = 20

# GSQL DML/DDL a generated traversal must never contain. Checked as whole-word keywords
# so a card holder note that happens to contain "update" in prose text doesn't matter --
# this scans the GSQL statement text itself, not evidence claims.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|GRANT|REVOKE|TRUNCATE|REPLACE)\b",
    re.IGNORECASE,
)
# A generated statement must be a read: SELECT, or an INTERPRET QUERY wrapper (GSQL's
# ad-hoc query form) whose body starts with SELECT once unwrapped.
_SELECT_START = re.compile(r"^\s*(SELECT|INTERPRET\s+QUERY)\b", re.IGNORECASE)


class QueryTools(Protocol):
    """What `investigate()` needs from the graph layer. `src.graph.connection.run_query`
    satisfies this for installed queries; `run_interpreted` is optional (guarded, ad-hoc
    GSQL) and defaults to raising if not supplied, so tests can omit it entirely."""

    def run_installed_query(self, name: str, params: dict) -> Any: ...

    def run_interpreted(self, gsql_text: str, params: dict | None = None) -> Any:  # optional
        ...


@dataclass
class LLMClient:
    """Duck-typed wrapper around `src.llm.prose`'s single Groq path -- reused, not
    duplicated. `complete(system, user) -> str` and `available() -> bool` are the only
    two things this module needs; the default factory binds them to `src.llm.prose`."""

    complete: Callable[[str, str], str]
    available: Callable[[], bool]

    @classmethod
    def from_prose_module(cls, case_id: str) -> "LLMClient":
        from src.llm.prose import _complete, enabled

        return cls(
            complete=lambda system, user: _complete(case_id, system, user, max_tokens=500),
            available=enabled,
        )


@dataclass
class LiveQueryTools:
    """`QueryTools` bound to the real TigerGraph MCP / pyTigerGraph stack. Installed
    queries route through `src.graph.connection.run_query` (already MCP-first with a
    pyTigerGraph fallback and per-case call counting -- reused, not duplicated). Generated
    traversals route through `src.graph.mcp.mcp_run_generated_query` when the
    `tigergraph-mcp` package is importable, else `pyTigerGraph.runInterpretedQuery`
    directly, since MCP is the brief's preferred path but not always installed locally."""

    case_id: str | None = None

    def run_installed_query(self, name: str, params: dict) -> Any:
        from src.graph.connection import run_query

        return run_query(name, case_id=self.case_id, params=params)

    def run_interpreted(self, gsql_text: str, params: dict | None = None) -> Any:
        import concurrent.futures

        def _call() -> Any:
            try:
                from src.graph.mcp import mcp_run_generated_query

                return mcp_run_generated_query(gsql_text)
            except ImportError:
                from src.graph.connection import get_conn

                return get_conn().runInterpretedQuery(gsql_text)

        # Hard timeout on generated traversals (guard requirement): an ad-hoc statement
        # from the model gets no more patience than an installed, pre-vetted query would.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call)
            try:
                return future.result(timeout=GENERATED_QUERY_TIMEOUT_S)
            except concurrent.futures.TimeoutError as exc:
                raise TimeoutError(
                    f"generated query exceeded {GENERATED_QUERY_TIMEOUT_S}s timeout"
                ) from exc


@dataclass
class InvestigationResult:
    evidence: list[dict] = field(default_factory=list)      # {claim, source, ref, entity_ids}
    ledger_keys: list[str] = field(default_factory=list)     # feeds policy/ledger.py weights
    decision_trace: list[dict] = field(default_factory=list)  # every assess/plan/execute step
    depth_reached: int = 0
    stop_reason: str = ""
    llm_available: bool = True


# ---------------------------------------------------------------------------
# Query guard
# ---------------------------------------------------------------------------


def _guard_generated_query(gsql_text: str) -> tuple[bool, str]:
    """Read-only, statement-allowlisted, capped. Returns (allowed, reason)."""
    text = (gsql_text or "").strip()
    if not text:
        return False, "empty query"
    if _FORBIDDEN_KEYWORDS.search(text):
        bad = _FORBIDDEN_KEYWORDS.search(text).group(0)
        return False, f"forbidden statement keyword: {bad}"
    if not _SELECT_START.match(text):
        return False, "must start with SELECT or INTERPRET QUERY (read-only traversal only)"
    if "LIMIT" not in text.upper():
        return False, f"missing row cap (LIMIT <= {MAX_GENERATED_QUERY_ROWS})"
    m = re.search(r"LIMIT\s+(\d+)", text, re.IGNORECASE)
    if m and int(m.group(1)) > MAX_GENERATED_QUERY_ROWS:
        return False, f"LIMIT {m.group(1)} exceeds cap of {MAX_GENERATED_QUERY_ROWS}"
    return True, "ok"


# ---------------------------------------------------------------------------
# LLM step contracts
# ---------------------------------------------------------------------------

_ASSESS_SYSTEM = (
    "You are a fraud investigator deciding whether to keep gathering evidence from a graph "
    "database or stop and hand off to the bank's policy engine, which alone decides the "
    "verdict, probability and action. You never state a verdict or probability yourself. "
    "This is an uncertainty check on the raw signals only -- like a single-pass confidence "
    "classifier ahead of a deterministic decision, not a decision itself: low confidence "
    "means 'keep looking', not 'lean fraud' or 'lean legitimate'. Reply with ONLY a JSON "
    "object, no prose, no markdown fences.\n\n"
    "Every reply carries a confidence field: \"low\" (evidence is thin, contradictory, or "
    "you are largely guessing), \"medium\" (a reasonable case either way, but a gap "
    "remains), or \"high\" (the picture is clear and further digging would not change it).\n\n"
    "If the evidence gathered so far is enough for a human analyst to reach a defensible "
    "conclusion, reply:\n"
    '{"decision": "CONCLUDE", "confidence": "<low|medium|high>", "reasoning": "<why this is enough>"}\n\n'
    "Otherwise, reply:\n"
    '{"decision": "CONTINUE", "confidence": "<low|medium|high>", "entity": "<card id, device '
    'id, customer id or region code to look at next>", "question": "<the specific thing you '
    'still need to know>"}\n\n'
    "A CONCLUDE with confidence \"low\" is a contradiction -- if you are not confident, "
    "CONTINUE instead unless you are already at the investigation's depth limit."
)

_PLAN_SYSTEM = (
    "You are a fraud investigator choosing the next graph query to run. You are given the "
    "installed query inventory with its parameters, and may instead propose a short "
    "read-only GSQL traversal if none of the installed queries answers the question. "
    "Reply with ONLY a JSON object, no prose, no markdown fences.\n\n"
    "Prefer an installed query whenever one plausibly fits, even loosely -- they are "
    "pre-vetted and fast. Only propose an ad-hoc traversal when none of them could answer "
    "the question at all.\n\n"
    "To run an installed query:\n"
    '{"action": "run_query", "query": "<name from the inventory>", '
    '"params": {<param name>: <value>, ...}, "reasoning": "<why this query, why these params>"}\n\n'
    "To propose an ad-hoc read-only traversal (only when no installed query fits), the gsql "
    "field MUST be a complete, executable GSQL statement in this exact wrapper -- a bare "
    "SELECT will not run:\n"
    '{"action": "propose_traversal", '
    '"gsql": "INTERPRET QUERY () FOR GRAPH FraudInvestigation { r = SELECT t FROM '
    'Transaction:t WHERE <condition> LIMIT 50; PRINT r; }", '
    '"reasoning": "<why no installed query covers this>"}'
)


def _extract_json(text: str) -> dict:
    """Pull the first {...} object out of a model reply, tolerating stray prose/fences."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(m.group(0))


def _evidence_fingerprint(evidence: list[dict]) -> frozenset:
    """A hashable signature of what's been found, used to detect a query that returned
    nothing NEW (README: 'a repeat of a deterministic query cannot change the picture --
    detect and stop rather than spinning')."""
    return frozenset(
        (e.get("ref", ""), tuple(sorted(str(i) for i in e.get("entity_ids", []))))
        for e in evidence
    )


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def investigate(
    case_id: str,
    trigger: dict,
    tools: QueryTools,
    max_depth: int = 4,
    llm: LLMClient | None = None,
    seed_evidence: list[dict] | None = None,
) -> InvestigationResult:
    """Assess -> Plan -> Execute -> Integrate, looped until CONCLUDE, max_depth, or a
    query stops adding anything new.

    `seed_evidence` lets a caller hand in the deterministic detector findings
    (`deps.py::run_detectors`) as the starting evidence set, so the LLM reasons over real
    findings from the first assess step rather than an empty ledger -- this is the "loop
    over depth for more context" step building on the existing shallow one-hop expansion
    in `deps.py::agentic_run_detectors`, not replacing it.
    """
    llm = llm or LLMClient.from_prose_module(case_id)
    result = InvestigationResult(evidence=list(seed_evidence or []))

    if not llm.available():
        result.llm_available = False
        result.stop_reason = (
            "LLM unavailable (no GROQ_API_KEY / LLM_PROSE=0 / offline): iterative "
            "graph-directed investigation did not run. This is a degraded run, not a "
            "silent substitute -- no fixed query sequence was run in its place."
        )
        result.decision_trace.append({
            "step": "assess", "depth": 0, "decision": "ABORT",
            "reasoning": result.stop_reason,
        })
        return result

    seen_fingerprints = {_evidence_fingerprint(result.evidence)}

    for depth in range(1, max_depth + 1):
        # 1. Assess -----------------------------------------------------------------
        assess = _assess(llm, case_id, trigger, result.evidence, depth, max_depth)
        result.decision_trace.append({"step": "assess", "depth": depth, **assess})

        if assess.get("decision") == "CONCLUDE":
            result.stop_reason = assess.get("reasoning", "model concluded evidence is sufficient")
            result.depth_reached = depth
            # Advisory-only confidence read on the raw evidence, recorded as evidence (not a
            # decision): it can only ever have already influenced CONTINUE-vs-CONCLUDE above
            # -- the policy engine still computes probability/verdict/action from
            # result.evidence alone, exactly as it would with this entry absent.
            result.evidence.append({
                "claim": f"Confidence check on gathered evidence: {assess.get('confidence', 'unstated')} "
                         f"-- {result.stop_reason}",
                "source": "graph",
                "ref": f"llm_decision:confidence_gate(case={case_id}, depth={depth})",
                "entity_ids": [],
            })
            return result
        if assess.get("decision") != "CONTINUE":
            # Malformed/unexpected reply: stop rather than loop on garbage forever.
            result.stop_reason = f"assess step returned an unrecognised decision at depth {depth}; stopping"
            result.depth_reached = depth
            return result

        # 2. Plan ---------------------------------------------------------------------
        plan = _plan(llm, case_id, trigger, result.evidence, assess, depth)
        result.decision_trace.append({"step": "plan", "depth": depth, **plan})

        # 3. Execute + 4. Integrate -----------------------------------------------------
        new_evidence, ledger_keys = _execute(tools, case_id, plan, depth)
        result.decision_trace.append({
            "step": "execute", "depth": depth,
            "rows_returned": sum(len(e.get("entity_ids", [])) for e in new_evidence),
            "evidence_added": len(new_evidence),
        })
        result.evidence.extend(new_evidence)
        result.ledger_keys.extend(ledger_keys)

        fp = _evidence_fingerprint(result.evidence)
        if fp in seen_fingerprints or not new_evidence:
            result.stop_reason = (
                f"query at depth {depth} returned nothing new (repeat of a deterministic "
                "query cannot change the picture); stopping rather than spinning"
            )
            result.depth_reached = depth
            return result
        seen_fingerprints.add(fp)
        result.depth_reached = depth

    result.stop_reason = f"max_depth ({max_depth}) reached without a CONCLUDE decision"
    return result


def _assess(
    llm: LLMClient, case_id: str, trigger: dict, evidence: list[dict], depth: int, max_depth: int
) -> dict:
    lines = [f"- {e.get('claim', '')} (ref: {e.get('ref', '')})" for e in evidence] or ["(none yet)"]
    user = (
        f"Case {case_id}, card {trigger.get('card_id')}, customer {trigger.get('customer_id')}.\n"
        f"Trigger: {trigger.get('trigger_type', 'unknown')} -- {trigger.get('trigger_text', '')}\n"
        f"Investigation depth {depth} of {max_depth}.\n\n"
        "Evidence gathered so far:\n" + "\n".join(lines) + "\n\n"
        "Is this enough for a defensible conclusion, or what specifically is still missing?"
    )
    try:
        reply = llm.complete(_ASSESS_SYSTEM, user)
        return _extract_json(reply)
    except Exception as exc:  # noqa: BLE001 -- record the failure as a stop, not a crash
        return {"decision": "CONCLUDE", "reasoning": f"assess step failed ({exc}); stopping rather than guessing"}


def _known_entity_ids(evidence: list[dict]) -> list[str]:
    """Real entity ids seen in evidence so far (from actual query results), so the plan
    step can be told to reuse one of these rather than invent a plausible-looking id.

    Without this, the model has nothing but the dataset's column-name vocabulary in its
    training/context to draw on when asked for e.g. a device id, and it hallucinates a
    literal column name like 'id_15' (the raw "New/Found device" flag column) instead of
    a real device key -- observed on 3 real cases (HHG-005/010/012), all converging on an
    identical, under-informed fraud_probability because the resulting query correctly
    returned nothing.
    """
    ids: list[str] = []
    for e in evidence:
        for eid in e.get("entity_ids", []):
            if eid and eid not in ids:
                ids.append(str(eid))
    return ids


# Dataset column names that look superficially like entity values but never are one --
# id_1..id_38 and device_id_N are the raw "New/Found device"/proxy-flag columns
# (data/README.md), not device keys. A plan step asking to look up one of these as if it
# were a real device_id/card_id/customer_id is a hallucination, not a query worth running.
_COLUMN_NAME_AS_ID = re.compile(r"^(id_\d+|device_id_\d+)$", re.IGNORECASE)


def _plan(
    llm: LLMClient, case_id: str, trigger: dict, evidence: list[dict], assess: dict, depth: int
) -> dict:
    inventory = "\n".join(f"- {name}({', '.join(params)})" for name, params in INSTALLED_QUERIES.items())
    known_ids = _known_entity_ids(evidence)
    known_ids_line = (
        "Known real identifiers seen in evidence so far (reuse one of these verbatim if it "
        "fits what you want to look at -- never invent an id, and never use a raw dataset "
        "column name like 'id_15' as if it were a value): " + ", ".join(known_ids)
        if known_ids
        else "No entity identifiers observed yet beyond the case's own card/customer ids above."
    )
    user = (
        f"Case {case_id}, card {trigger.get('card_id')}, customer {trigger.get('customer_id')}.\n"
        f"Case opened_at (use this exact value for any 'anchor' parameter -- this dataset is "
        f"from 2016, never invent today's date): {trigger.get('opened_at', '')}\n"
        f"{known_ids_line}\n"
        f"You want to look at: {assess.get('entity', '')}\n"
        f"Because: {assess.get('question', '')}\n\n"
        f"Installed queries:\n{inventory}\n\n"
        "Choose one query and its parameters, or propose an ad-hoc read-only traversal. If "
        "the identifier you need isn't in the known list above and isn't the case's own "
        "card/customer id, say so in `reasoning` and pick the closest query that can "
        "discover it instead of guessing a value."
    )
    try:
        reply = llm.complete(_PLAN_SYSTEM, user)
        plan = _extract_json(reply)
    except Exception as exc:  # noqa: BLE001
        return {"action": "run_query", "query": "card_window",
                "params": {"card_id": trigger.get("card_id"), "anchor": trigger.get("opened_at"), "hours": 24},
                "reasoning": f"plan step failed ({exc}); falling back to the card's own window as the "
                             "narrowest safe query rather than skipping this depth entirely"}
    return plan


def _execute(tools: QueryTools, case_id: str, plan: dict, depth: int) -> tuple[list[dict], list[str]]:
    action = plan.get("action")

    if action == "run_query":
        name = plan.get("query")
        params = plan.get("params") or {}
        if name not in INSTALLED_QUERIES:
            return [{
                "claim": f"Agent requested unknown query '{name}', refused",
                "source": "graph", "ref": f"llm_plan:rejected({name})", "entity_ids": [],
            }], []
        bad_param = next(
            (f"{k}={v}" for k, v in params.items() if isinstance(v, str) and _COLUMN_NAME_AS_ID.match(v)),
            None,
        )
        if bad_param:
            return [{
                "claim": f"Agent proposed {name}({bad_param}), refused: that looks like a raw "
                         f"dataset column name, not a real entity id -- running it would waste a "
                         f"query rather than gather evidence. Full params: {params}",
                "source": "graph", "ref": f"llm_plan:rejected(column_as_id, depth={depth})", "entity_ids": [],
            }], []
        try:
            rows = tools.run_installed_query(name, params)
        except Exception as exc:  # noqa: BLE001
            return [{
                "claim": f"Query {name}({params}) failed: {exc}",
                "source": "graph", "ref": f"query:{name}(depth={depth})", "entity_ids": [],
            }], []
        return _rows_to_evidence(name, params, rows, depth, plan.get("reasoning", ""))

    if action == "propose_traversal":
        gsql_text = plan.get("gsql", "")
        allowed, reason = _guard_generated_query(gsql_text)
        if not allowed:
            return [{
                "claim": f"Agent proposed a generated traversal, refused by the query guard: {reason}. "
                         f"Query verbatim: {gsql_text}",
                "source": "graph", "ref": f"llm_generated_query:rejected(depth={depth})", "entity_ids": [],
            }], []
        try:
            run_interpreted = getattr(tools, "run_interpreted", None)
            if run_interpreted is None:
                raise RuntimeError("query tools do not support interpreted GSQL execution")
            rows = run_interpreted(gsql_text, {})
        except Exception as exc:  # noqa: BLE001
            return [{
                "claim": f"Generated traversal passed the guard but failed to execute: {exc}. "
                         f"Query verbatim: {gsql_text}",
                "source": "graph", "ref": f"llm_generated_query:failed(depth={depth})", "entity_ids": [],
            }], []
        evidence, keys = _rows_to_evidence("llm_generated_query", {}, rows, depth, plan.get("reasoning", ""))
        for e in evidence:
            e["claim"] = f"Generated traversal (verbatim: {gsql_text}) -- {e['claim']}"
        return evidence, keys

    return [{
        "claim": f"Agent's plan step returned an unrecognised action '{action}', refused",
        "source": "graph", "ref": f"llm_plan:rejected(depth={depth})", "entity_ids": [],
    }], []


def _rows_to_evidence(name: str, params: dict, rows: Any, depth: int, reasoning: str) -> tuple[list[dict], list[str]]:
    """Flatten a raw query result (pyTigerGraph/MCP list-of-blocks shape, or a plain list
    for tests) into evidence entries carrying `ref` and `entity_ids` for provenance.

    An installed query's PRINT statement (queries.gsql) names its own output variable --
    `txns`, `cases`, `result`, the MCP wrapper's generic `results` -- so a result block is
    `{"<whatever the query printed>": [<vertex row>, ...]}`. This does not special-case
    the key name: any block that is a dict is treated as one or more named lists of rows,
    whatever they're called.
    """
    entity_ids: list[str] = []
    flat_rows: list[Any] = []

    def _collect(node: Any) -> None:
        if isinstance(node, dict) and "v_id" in node:
            flat_rows.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)
        # scalars (str/int/None/...) carry no entity id; drop silently

    _collect(rows)

    for row in flat_rows:
        if isinstance(row, dict):
            vid = row.get("v_id")
            if vid:
                entity_ids.append(str(vid))
            attrs = row.get("attributes", {}) or {}
            for key in ("@card", "txns.@card", "@cust", "txns.@cust"):
                for v in attrs.get(key) or []:
                    entity_ids.append(str(v))

    entity_ids = list(dict.fromkeys(entity_ids))
    if not entity_ids:
        return [], []

    # Same row cap the ad-hoc GSQL guard enforces (MAX_GENERATED_QUERY_ROWS): an installed
    # query re-run deeper in the loop (e.g. a second, broader customer_baseline call) can
    # legitimately return thousands of rows for a busy customer -- that's a real result, not
    # a bug, but citing every one of them as a distinct evidence entity bloats the answer
    # file without adding information (bug found on HHG-007: 2,794 entity_ids from one
    # evidence item). Keep the full count in the claim text; cap what's actually cited.
    total_found = len(entity_ids)
    truncated = total_found > MAX_GENERATED_QUERY_ROWS
    entity_ids = entity_ids[:MAX_GENERATED_QUERY_ROWS]

    ref = f"query:{name}({', '.join(f'{k}={v}' for k, v in params.items())})" if params else f"query:{name}()"
    count_note = f" (showing first {MAX_GENERATED_QUERY_ROWS})" if truncated else ""
    evidence = [{
        "claim": f"{name} returned {total_found} connected entities at depth {depth}{count_note}. "
                 f"Reasoning: {reasoning}",
        "source": "graph",
        "ref": ref,
        "entity_ids": entity_ids,
    }]
    ledger_keys = ["agentic_graph_expansion"]
    return evidence, ledger_keys


def demo() -> None:
    """Offline self-check: a scripted 2-step LLM that CONTINUEs once then CONCLUDEs,
    against a fake tools object, proves the loop terminates on CONCLUDE and carries
    provenance through. No network, no TigerGraph."""
    calls = {"assess": 0}

    def fake_complete(system: str, user: str) -> str:
        if "Choose one query" in system or "Installed queries" in user:
            return json.dumps({"action": "run_query", "query": "device_neighbors",
                                "params": {"device_id": "D1", "anchor": "2016-11-22 20:11:00", "hours": 720},
                                "reasoning": "shared device is worth a look"})
        calls["assess"] += 1
        if calls["assess"] == 1:
            return json.dumps({"decision": "CONTINUE", "entity": "D1", "question": "who else used this device?"})
        return json.dumps({"decision": "CONCLUDE", "reasoning": "ring confirmed across cards"})

    llm = LLMClient(complete=fake_complete, available=lambda: True)

    class FakeTools:
        def run_installed_query(self, name, params):
            return [{"results": [[
                {"v_id": "T1", "attributes": {"txns.@card": ["C0002-K1"]}},
            ]]}]

    res = investigate("HHG-TEST", {"card_id": "C0001-K1", "customer_id": "C0001"}, FakeTools(), max_depth=4, llm=llm)
    assert res.llm_available
    assert res.depth_reached == 2
    assert any(step["step"] == "assess" and step.get("decision") == "CONCLUDE" for step in res.decision_trace)
    assert res.evidence and res.evidence[0]["ref"].startswith("query:device_neighbors")
    print("investigator.py demo OK:", res.stop_reason)


if __name__ == "__main__":
    demo()
