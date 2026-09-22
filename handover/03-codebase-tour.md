# 3. Codebase tour

~5,300 lines across 23 files. Here's what each one does and the API you'd actually call.

```
config/          the contracts — read these first, everything else implements them
src/graph/       TigerGraph: schema, queries, loading, connection
src/detectors/   the six fraud pattern detectors
src/policy/      R1-R10 rule engine + the probability ledger
src/agent/       LangGraph orchestration + the CLI
src/rag/         case memory, retrieval, context building
src/sar/         regulatory narrative
src/answer/      output schema + validator
ui/              Next.js analyst console
tests/           105 tests
```

---

## config/ — start here

These two YAML files are the contract. Everything else implements them, and they're what
you change when you want different behaviour.

**`config/fraud_policy.yaml`** — the 14 action names with their approval routes, and R1–R10
as structured predicates. Quoted from the brief; don't rename anything.

**`config/evidence_weights.yaml`** — every piece of evidence and what it's worth:

```yaml
card_testing_sequence:      +0.35   # strongest single pattern
shared_device_across_cards: +0.30   # R6 ring signal
customer_denies:            +0.30   # R2
...
recurring_merchant_match:   -0.25   # R7 — this is why we don't block everything
customer_confirms:          -0.90   # R3
risk_score_alone:           +0.05   # deliberately tiny, see below
```

The negative weights are as important as the positive ones. And `risk_score_alone` is near
zero on purpose: the brief says most high scores are legitimate, so treating the model's
score as strong evidence would wreck our calibration.

---

## src/policy/ — the load-bearing 50%

### `ledger.py` (158 lines)

Turns a list of evidence keys into a probability. Deterministic — the LLM never produces
this number.

```python
compute_probability(["card_testing_sequence", "customer_denies"]) -> float
independent_evidence_count(sources) -> int       # distinct sources, not items
evidence_set_hash(evidence_ids) -> str           # proves which evidence a snapshot used
```

The formula is `sigmoid(-1.8 + 4.1 × Σweights)`. Those two constants matter: without the
`-1.8` bias, zero evidence would read as 0.5 (a coin flip) and the stopping thresholds at
0.15/0.85 would be unreachable. Calibrated so the brief's own worked example lands at 0.89
against its stated 0.86.

Unknown keys raise rather than silently scoring zero. There's a contract test that fails if
a detector emits a key with no weight.

### `engine.py` (370 lines)

R1–R10 as predicate functions.

```python
resolve_route("BLOCK_CARD", exposure_usd=268) -> "L1"     # >2500 would be "L2"
finalize_action(action, exposure_usd) -> {action, route, executed}
apply_rules(CaseState) -> [{action, reason_rules}, ...]   # ordered
sar_trigger(verdict, exposure_usd, shared_origin, pattern) -> bool
can_stop(p, independent_evidence_count, verification_settled) -> bool
```

Two rules aren't simple additions:
- **R7 forbids** — a disputed charge matching the customer's own recurring pattern must not
  produce `BLOCK_CARD` or `DECLINE_TRANSACTION`, even if another rule proposed it
- **R10 downgrades** — `BLOCK_ALL_CARDS` becomes `BLOCK_CARD` unless its guard holds

`finalize_action` is the single chokepoint enforcing that the agent only executes `auto`.

---

## src/detectors/patterns.py (428 lines)

Six pure functions over query results. No I/O, easy to test.

```python
detect_card_testing(card_id, txns)                  -> [Finding]
detect_cnp_burst(card_id, txns, baseline_products)  -> [Finding]
detect_new_device(card_id, txns)                    -> [Finding]
detect_out_of_region(card_id, txns, historical_regions) -> [Finding]
detect_account_takeover(customer_id, cards_txns)    -> [Finding]
detect_shared_origin(rows, window_days)             -> [Finding]
```

Each `Finding` carries `pattern`, `weight_keys`, `entity_ids`, and `ref` — the query string
that produced it. That `ref` is mandatory: the answer file's `evidence[]` needs provenance,
and without it the agent literally cannot fill the field.

**The subtle one:** `detect_out_of_region` fires when the home region is **still active**
at the same time as purchases elsewhere — a card can't be in two places, so that's a clone.
A clean move to one new region is a holiday and must not fire. This was implemented
backwards at first and would have cleared real fraud while flagging every trip.

21 tests, 13 of them near-misses (proving a detector *doesn't* fire). Those matter more
than the positive tests, because half the cases are legitimate.

---

## src/graph/

**`schema.gsql`** (153 lines) — 10 vertices, 14 edges, plus the vector-attribute job for
embedding closed-case notes.

**`queries.gsql`** (130 lines) — six installed queries: `card_window`, `device_neighbors`,
`customer_baseline`, `prior_cases_for_entities`, `similar_prior_cases` (hybrid graph +
vector), `write_case_to_graph`.

**`load.py`** (431 lines) — three-tier CSV loading. Tier 1+2 (about 30 columns) into the
graph; tier 3 (V1–V339, 85% of the file, no published meaning) into a parquet sidecar.
Uses a GSQL loading job for bulk, confirmed by TigerGraph's own DevRel: *"Don't do
row-by-row REST. Use a GSQL loading job. 600K rows takes minutes."*

**`connection.py`** (120 lines) — pyTigerGraph wrapper with TigerGraph Cloud (Savanna) configuration, token-refresh-on-401, and a per-case tool-call counter, so the `tool_calls` field in the answer file is a real number.

**`mcp.py`** (85 lines) — TigerGraph MCP server bridge using `langchain-mcp-adapters`. Launches `tigergraph-mcp` via stdio, exposing 69 graph tools directly to LLM agents. Includes a CLI check: `python -m src.graph.mcp --check`.

---

## src/agent/

**`state.py`** (53 lines) — the `InvestigationState` TypedDict. Read the comments: LangGraph
merges state per *declared* channel, so an undeclared key is silently dropped between nodes.
That bug cost us R2 and R3 firing at all.

**`graph.py`** (71 lines) — wires the state machine. Short; read it to see the flow.

**`nodes.py`** (407 lines) — the node implementations. Key ones:
- `need_more_evidence` — the conditional edge that decides loop vs decide
- `request_evidence` — holds the `MustRequestEvidence` hard gate
- `policy_gate` — `interrupt()` for L1/L2 actions

**`deps.py`** (536 lines) — dependency injection. `live_deps()` talks to TigerGraph;
`offline_deps(fixture_dir)` reads captured JSON. The offline path is our demo-day insurance
and is what the tests run against.

**`evidence_sim.py`** (221 lines) — simulates the customer/analyst replies the dataset
doesn't provide. Read the module docstring: the rule is documented so a judge auditing
`assumed_response` can see it was reasoned, not convenient. Mixed evidence defaults to *no
reply* under R4 rather than inventing a helpful denial.

**`run.py`** (463 lines) — the CLI.

```bash
python -m src.agent.run --case HHG-017
python -m src.agent.run --all
python -m src.agent.run --all --offline --fixture-dir tests/fixtures/offline
```

Runs cases in `opened_at` order so an earlier case is memory for a later one. Warns loudly
if more than 12 of 20 come out `fraud` — that's the over-blocking alarm.

---

## src/rag/

**`retrieve.py`** (167 lines) — case memory.

```python
blended_score(semantic, structural, pattern_match) -> float   # 0.4 / 0.4 / 0.2
retrieve_similar_cases(...) -> {confirming: [...], disconfirming: [...]}
```

The two-pool split is the important bit — see `02-how-it-works.md`.

**`serialize.py`** (240 lines) — turns a subgraph into LLM context as markdown tables. It
**refuses to emit a block without a `ref`**, structurally enforcing provenance. Has a real
token budget (1.5k–3k per case) that trims lowest-risk rows first.

**`embed.py`** (237 lines) — OpenAI embeddings with a local sentence-transformers fallback,
disk-cached.

**`policy_docs.py`** (382 lines) — chunks R1–R10 one rule per chunk (so a citation is a
whole rule) and fetches the FinCEN guidance. Two of three regulatory PDFs extract; the FFIEC
one returns 403 and is skipped without crashing.

---

## src/sar/narrative.py (285 lines)

```python
gate_file_report(verdict, exposure, shared_origin, pattern) -> bool
generate_sar(facts) -> SarRecord
```

Builds the regulator-facing narrative on FinCEN's who/what/when/where/how/why structure.
Assembled from established facts, and `_validate_no_hallucinated_ids` rejects any output
containing an ID that wasn't an input — the LLM renders prose, it never invents identifiers.

---

## src/answer/

**`schema.py`** (238 lines) — dataclasses matching the brief's Answer Format exactly.

**`validator.py`** (222 lines) — run this before submitting anything.

```bash
python -m src.answer.validator cases/
```

Checks `sar.file` agrees with `FILE_REPORT` in final; legitimate ⟹ zero exposure; every
txn ID exists in the dataset; every route matches the exposure; every action cites an
R-number; and a coherence check that an `uncertain` verdict paired with a card block
explains itself. Returns all violations at once, not just the first.

---

## ui/

Next.js 16 + Tailwind v4 + `motion`. The centrepiece is `RecommendationDelta.tsx` — the
before/after view. Verdict colours are magenta-red vs cobalt (not red/green) so they survive
colour-vision deficiency.

Reads `cases/*.json` if present, else three fixtures, with an on-screen banner saying which
— so fixture data can't be demoed by accident.

```bash
cd ui && npm install && npm run dev
```

---

## tests/ — 105 passing

```bash
python -m pytest tests/ -q
```

| File | Covers |
|---|---|
| `test_detectors.py` (21) | Each detector fires correctly **and** doesn't fire on near-misses |
| `test_policy.py` (27) | Rule predicates, route boundaries at exactly 2500/2501, ledger calibration |
| `test_validator.py` (15) | Each violation type is caught |
| `test_retrieve.py` (15) | Two-pool retrieval survives the 5:1 imbalance |
| `test_serialize.py` (21) | Provenance enforced, token budget trims correctly |
| `test_run.py` (11) | End-to-end, and the before/after delta regression guard |
