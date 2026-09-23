## Status update from Bhavya, 2026-09-24 — read this first

Real dataset is in `data/`. Real work happened since the last version of this doc. Written
as phases with hard gates because you're reading this cold — do them in order, don't skip
ahead, each phase assumes the one before it is actually green, not "probably fine."

### P0 — foundational. Every later phase reads or writes through this.

**Scope note:** this phase now absorbs what was originally Karan's slice
(`docs/KARAN.md` — Savanna setup, schema, loading, the 4 core queries, the 6 detectors),
since he hasn't been reachable and coding responsibility is consolidating into this file
so it happens in one place. Good news: the actual coding there is **already done** — the
schema (including all 5 of Karan's documented additions: `RECIPIENT_EMAIL` edge,
`ProductCategory` vertex, `country_code`, `dist1`/`dist2`, C/D/M scalars — verified present
in `src/graph/schema.gsql` directly, not assumed), the 4 queries, and the 6 detectors are
all written and passing tests against fixtures. What's pending is **running it live and
fixing whatever a real GSQL parser rejects that a fixture never could** — that's what
steps 1–5 below actually are. `docs/KARAN.md` still has the full technical detail (schema
rationale, query GSQL, detector table, pyTigerGraph gotchas) if you need to go deeper on
any one piece — it's kept as reference, not duplicated wholesale here.

`cases/` is empty. Zero real answer files exist. That's 50% of the rubric (accuracy +
next-best-action) sitting at zero right now, and every phase after this one — embeddings,
the agentic layer, graph algorithms — needs a live, loaded graph to actually run against
real data rather than fixtures. This is the foundation everything else builds on:

1. Get the Savanna workspace URL + token into `.env` (`TG_HOST` = the
   `https://<workspace>.i.tgcloud.io` form, not `savanna.tgcloud.io`).
2. `python -m scripts.setup_graph --check`, then `python -m scripts.setup_graph`. Budget an
   hour — the GSQL has never run on a live instance. Nested `POST-ACCUM`/`FOREACH` is the
   most likely thing a live parser rejects; `SHOW QUERY <name>` after install tells you the
   parsed syntax version if something breaks.
3. `python -m src.graph.load --data-dir ./data`
4. Run **HHG-017 first** (the README's own worked example, so you have an expected shape to
   check against), then all 20: `python -m src.agent.run --all --data-dir ./data --out cases/`
5. `python -m src.answer.validator cases/` — must exit clean.

**Do not start P1 or P2 until this is green.** Not a deadline-pressure rule — every later
phase (embeddings, the ReAct/MCP layer, graph algorithms) needs a live, loaded graph to run
against at all. Building them against fixtures now would mean redoing the wiring once P0
lands anyway. Gate is structural, not about time.

**Sequencing trap:** `schema.gsql`'s `add_embeddings` is a `GLOBAL SCHEMA_CHANGE JOB` using
`ADD VECTOR ATTRIBUTE`, which needs TigerGraph ≥4.2. Check the provisioned workspace's
version before assuming this compiles — if it's older, the fallback is an external
FAISS/Chroma store keyed by vertex id (RESEARCH.md §6.2), not a blocker for P0 either way
since P0 doesn't touch vectors at all.

### The `card_id` bug — already fixed, know why

`src/graph/load.py`'s `derive_card_id()` used to rank a customer's card tuples by
first-seen timestamp. Checked against all 20 real `card_id`s in `data/case_pack.csv`: it
was **wrong on 10/20 (50%)**. Fixed to rank by ascending transaction count instead (the
customer's least-used card tuple is `K1`) — now correct on 19/20. The one exception
(`HHG-006`/`C07297`: two fully-populated tuples close in count, ground truth goes the
other direction) is documented in the code comment. If a customer's card_id lands in that
shape — two card tuples, neither with blank fields, counts within ~2x of each other — don't
trust the derived K-number without checking `case_pack.csv`/`closed_cases_history.csv`
directly. This touches your work because case memory's structural-match signal is keyed on
`card_id`.

### P1 — do this once P0 is green

**LLM prose, not LLM decisions.** The brief wants the LLM used for "reasoning, tool
selection, evidence synthesis, and generating explanations" — right now it's used for none
of those; every `tokens: 0` in the answer files is honest but weak on that criterion.
Fix only the parts that can't corrupt a graded decision:

- **`explain` node in `src/agent/nodes.py`** currently `return {}`. Have it call an LLM to
  write `case.summary` from the already-computed evidence/snapshots — pure prose, reads
  finalized state, writes nothing back into `p_fraud`/`pattern`/actions.
- **`src/sar/narrative.py`** — same pattern for `sar.narrative`.
- Use Groq, model `qwen/qwen3.8-27b` (already tested and working, key is in `.env`).
  **Not** `openai/gpt-oss-120b` / `llama-3.3-70b-versatile` — the latter is decommissioned
  on Groq (404s), and the former silently replaces every ASCII hyphen with a Unicode
  non-breaking hyphen (U+2011) in its output — confirmed on a live test, even when told to
  repeat text verbatim. That would put IDs like `C04570‑K1` (wrong byte) into a narrative
  where the real ID is `C04570-K1`, which is exactly the kind of thing your own
  hallucinated-ID guard exists to catch. `qwen/qwen3.8-27b` doesn't do this, is faster, and
  doesn't burn tokens on hidden reasoning the way `gpt-oss-120b` does (measured 155 of 370
  completion tokens spent on invisible reasoning for one call).
- **Gotcha:** `qwen/qwen3.8-27b` needs no special handling, but if anyone reaches for a
  `gpt-oss-*` model later, remember it's a reasoning model — set `max_tokens` ≥300, not a
  tight cap, or hidden reasoning tokens can eat the whole budget and leave an empty
  response (reproduced this with `max_tokens=5`).
- Prompt constraint for both call sites: "use only the IDs and facts provided, invent
  nothing." Keep the existing hallucinated-ID guard as the actual check, don't just trust
  the instruction.

**Also P1: give every rule-fired action a real `document`-sourced evidence item — and now
that there's time, build the whole thing properly, not just the cheap fallback.**

Right now `src/agent/deps.py` hardcodes every evidence item as `"source": "graph"` — none
are `"document"`, even though the answer schema explicitly supports it and the brief wants
GraphRAG grounding "from documents such as fraud policies." `src/rag/policy_docs.py`
already extracts and chunks the policy (by rule), the five patterns, and 3 regulatory PDFs
— but nothing embeds them, writes them into TigerGraph, or retrieves them at runtime. That
gap was flagged earlier as "skip it, do the rule-keyed shortcut instead" purely because of
time pressure. That pressure is gone. Build the real version:

1. **Schema:** `src/graph/schema.gsql` only declares `PolicyChunk` (no vector attribute
   target for `Pattern` or `RegChunk`, and no `GOVERNS`/`PRESCRIBES`/`CITES` edges at all,
   even though `policy_docs.py`'s dataclasses already compute them). Add:
   ```gsql
   CREATE VERTEX RegChunk (PRIMARY_ID chunk_id STRING, source STRING, url STRING,
                           section_idx INT, text STRING)
   CREATE VERTEX Pattern  (PRIMARY_ID pattern_id STRING, name STRING, text STRING)
   CREATE DIRECTED EDGE GOVERNS    (FROM PolicyChunk, TO Pattern)
   CREATE DIRECTED EDGE PRESCRIBES (FROM PolicyChunk, TO Action)   -- Action is a string
                                                                    -- attribute match, not
                                                                    -- a vertex; see below
   CREATE DIRECTED EDGE CITES      (FROM PolicyChunk, TO RegChunk)
   ```
   and extend the existing `add_embeddings` `SCHEMA_CHANGE JOB` to also add
   `RegChunk.textEmb` and `Pattern.textEmb` vector attributes (`DIMENSION=1536`, same as
   `PolicyChunk.textEmb`). Note: `PRESCRIBES` targets an action identifier, not a vertex —
   either add a lightweight `Action` vertex (14 rows, one per action name) so the edge has
   a real target, or store `prescribes_actions` as a `SET<STRING>` attribute on
   `PolicyChunk` directly. The vertex approach is more "graph," the attribute approach is
   less schema churn — either is defensible, pick the vertex approach if going for the
   Innovation score, since it makes "which rule prescribes which action" a real traversal.

2. **Embed + write:** add `embed_policy_docs()` to `src/rag/embed.py`, mirroring
   `embed_closed_cases()` — call `policy_docs.load_all()`, embed every chunk's `text` with
   `task_type="RETRIEVAL_DOCUMENT"` (same Gemini config already wired), and upsert into
   the graph via a new GSQL query or `conn.upsertVertexDataFrame` (pyTigerGraph), wiring
   the `GOVERNS`/`PRESCRIBES`/`CITES` edges from the dataclass fields that already compute
   them (`policy_docs.py`'s `governs_patterns`/`prescribes_actions`/`cites_reg_chunks`).

3. **Retrieve at runtime:** `src/rag/retrieve.py`'s `policy_for_pattern()` already exists
   and is fully unit-tested — it just needs its `graph_filter` callable wired to a real
   GSQL traversal (`SELECT pc FROM (p:Pattern {id: pattern_id})<-[:GOVERNS]-(pc:PolicyChunk)`),
   then vector-ranked against the case's evidence text within that small candidate set
   (graph-filter-then-vector-rank, same pattern as `similar_prior_cases`). Call this from
   `deps.py`'s `run_detectors` once a pattern is identified, and append the top-ranked
   `PolicyChunk`(s) as real `source: "document"` evidence with `ref` pointing at the actual
   retrieved chunk_id — not just "Fraud Policy Rn" as a string, but a chunk that was
   genuinely vector-searched and found.

This is strictly better than the rule-keyed shortcut: it's the actual GraphRAG document
pipeline the brief asks for, it's graph-filter-then-vector-rank (the same architectural
move `RESEARCH.md` §6.2 calls "the headline move — why TigerGraph and not a vector DB
bolted onto Postgres"), and it gives every judge-facing evidence item a real, checkable
retrieval trace instead of a hardcoded string. Keep the rule-keyed version as the fallback
if the vector retrieval path errors for any reason — never let a missing document citation
silently become a missing evidence item.

**Never do this one — this isn't a time-pressure shortcut, it's permanent:** do not let the
LLM pick the evidence request type, decide when to stop, or emit a probability/action/route,
no matter how much time is available. `_choose_evidence_request_type` in `nodes.py` is
already the site of a bug that once made R2/R3 (the two highest-value rules in the whole
policy) structurally unreachable — replacing tested deterministic logic with a
nondeterministic LLM call risks the 25% next-best-action score to chase 15%
agentic-design credit, and that trade is bad at any time budget. `config/fraud_policy.yaml`
and `config/evidence_weights.yaml` are correct as designed — Devanshu's own words on
Discord: "we don't score a model, we score the investigation and the reasoning." Leave
them alone regardless of how much time is left.

### P1.5 — the real agentic layer: LLM-driven evidence gathering over TigerGraph MCP

This is the answer to "is LLM usage even needed" — yes, and here's exactly where, because
the split was already written in this doc before any of this session (see Part 1 below:
*"The LLM classifies evidence into the ledger and writes the prose; it never emits the
number"*) and it matches the brief verbatim: *"The LLM should be used for reasoning, tool
selection, evidence synthesis, and generating explanations rather than replacing graph
analysis."* That sentence has four verbs. Today's build does zero of them. P1 (prose) does
one. This phase does the other three — **tool selection** and **evidence synthesis**
specifically — without touching the deterministic decision layer at all.

**What "agentic" currently means here, honestly:** a fixed Python function
(`_make_run_detectors` in `deps.py`) always calls the same detectors in the same order for
every case. That's an orchestrated pipeline, not an agent choosing what to look at. The fix
is not a new graph — it's a new *implementation* of one function, because
`run_detectors(case_id, trigger) -> {evidence, ledger_keys, pattern, affected_txn_ids,
exposure_usd, prior_cases}` is already exactly the contract a ReAct loop's output should be.

**Do this as a third factory, not a rewrite:**

```python
# src/agent/deps.py
def agentic_deps(mcp_tools, llm_client) -> NodeDeps:
    """LLM-driven evidence gathering over TigerGraph MCP tools. Same NodeDeps contract as
    live_deps/offline_deps -- nodes.py, graph.py, the policy engine, and the answer
    assembly are UNCHANGED and stay covered by their existing tests. Falls back to
    live_deps() if the LLM path raises, so a flaky model call never loses a case.
    """
```

Wire it behind a `--evidence-mode {agentic,deterministic}` flag in `src/agent/run.py`
(default `deterministic` = today's `live_deps`), so nothing about the P0 path changes and
this is opt-in per run, comparable side by side.

**How the loop actually works, in English:**

1. The LLM sees the trigger (case_id, flagged transaction, customer, card) and the list of
   available MCP tools (`card_window`, `device_neighbors`, `customer_baseline`,
   `prior_cases_for_entities`, vector search over closed-case notes/policy chunks).
2. It **chooses** which tool to call next and with what arguments — this is "tool
   selection." A ReAct-style agent: observe → decide next tool → call → observe result →
   repeat, instead of a hardcoded call order.
3. After each tool result, the LLM **classifies** what it found into the fixed ledger-key
   vocabulary already in `config/evidence_weights.yaml` (`card_testing_sequence`,
   `shared_device_across_cards`, `recurring_merchant_match`, etc.) plus the evidence-item
   shape (`claim`, `source`, `ref`, `entity_ids`). This is "evidence synthesis" — turning a
   raw graph row into a citable claim — not a probability judgment.
4. Loop ends on a hard cap (e.g. 8 tool calls) or when the LLM signals it has nothing more
   to check. The result dict is handed to the *exact same* `investigate`/`gather_evidence`
   nodes that already exist — they don't know or care whether a human wrote the detector
   calls or an LLM chose them.
5. `compute_probability`, `apply_rules`, `finalize_action`, routing, and the stopping
   thresholds are **completely unaware this happened**. Same deterministic math, same
   audit trail, same "when a judge asks where 0.86 came from, we open a config file."

**Which MCP mechanism this actually uses — be precise about this, there are two:**

- **Primary (this is what step 2 above means):** the LLM calls the small set of
  **pre-written, precompiled** GSQL queries (`card_window`, `device_neighbors`,
  `customer_baseline`, `prior_cases_for_entities`, vector search) as structured tools —
  standard function-calling. The LLM picks *which* tool and *what parameters*
  (`card_id`, `hours`, `device_id`); it is not writing GSQL text. That GSQL was already
  written, tested against fixtures, and installed on the graph ahead of time. This is
  "tool selection," per the brief's wording, not "query generation."
- **Secondary, available but not the core path:** `tigergraph-mcp[llm]` (the `[llm]` extra)
  adds `generate_gsql` / `generate_cypher` tools that do genuine natural-language-to-GSQL
  translation at runtime. This is real and exists — but don't build the core evidence loop
  for the 20 graded cases on it. Generating novel, unvalidated GSQL against a schema that's
  never run live before (see the P0 note above: budget an hour for first-contact GSQL
  rejections) is a worse failure mode than "the LLM picked the wrong pre-built tool" — a
  pre-built query has a known, tested output shape the ledger classification step can
  trust; free-generated GSQL doesn't. Fine to use `generate_gsql` for **exploratory** work
  (P3's self-monitoring-beyond-20-cases bonus, or ad-hoc investigation while building) —
  just don't make the graded path depend on it.
- **Either way, gate by permission tier:** `tigergraph-mcp --allowed-tools read-only` during
  the whole investigation loop (RESEARCH.md §5.2's "blast-radius control"), so neither
  mechanism can mutate the graph mid-investigation. Only the dedicated `write_case` node,
  outside this loop, gets write access.

**Two guards that make this safe to ship, not just a good idea:**

- **`compute_probability` already raises on an unknown ledger key** (this repo has a
  contract test for exactly this). That is now your safety net against an LLM inventing a
  key that isn't in `evidence_weights.yaml` — don't loosen it, it will catch a bad
  classification loudly instead of silently.
- **Every `entity_id` the LLM emits must be validated against the real CSVs before it
  reaches an answer file** — reuse the existing hallucinated-ID guard
  (`06-decisions-and-gotchas.md`: "SAR narratives reject hallucinated IDs"). Extend it to
  cover LLM-classified evidence items too, not just SAR text.

**What you get that the deterministic-only path can't show a judge:** `tool_calls` becomes
genuinely variable per case (a clear-cut case might take 3 calls, an ambiguous one 8) instead
of being suspiciously identical across all 20 files — and the trace of *which* tool the
agent chose to call next, and why, is real content for the "agentic design" criterion (15%)
and for the demo video. Show this loop live if you build it; it's a better demo beat than
anything the deterministic path can offer.

**Do not let this delay or replace P0.** It is additive and optional, gated on P0 being
green first. If Savanna lands late, the deterministic path alone still produces a complete,
correct, fully-scoreable submission — this phase is what pushes agentic-design and
innovation from "adequate" to "the thing a judge remembers."

**Run the existing test suite after every phase, not just at the end.** 125 tests
currently pass against fixtures (`uv run python -m pytest tests/ -q` — use `python -m
pytest`, not bare `pytest`, or `src` won't resolve). That count is the floor after any
change, not a nice-to-have check. This matters concretely here: the Gemini embedding fix
already made to `src/rag/embed.py` changed `embed_texts`'s cache-key shape (task_type is
now folded into the key), which touches a code path `test_serialize.py`/`test_retrieve.py`
may assume the old shape of. Confirmed 125/125 still pass as of this write-up — but re-run
this after `agentic_deps()` lands, and after the P1 document-GraphRAG wiring lands, since
both touch shared code (`deps.py`, `embed.py`) that other tests already cover. A regression
caught by an existing test costs a minute; one caught by a judge costs the criterion.

### P1.6 — extend the regulatory corpus to the dataset README's actual full list

`src/rag/policy_docs.py`'s `PRIORITY_REG_DOCS` currently has 3 of the 9 FinCEN/FFIEC
documents the dataset's own README names under "Regulatory references." That subset was
chosen under time pressure ("skip to the 3 that matter most"). With more time, load the
rest of the *same list the organizers already gave us* — this is not scope creep, it's
finishing the list:

```python
PRIORITY_REG_DOCS += [
    {"source": "FinCEN SAR Filing FAQs (Oct 2025)",
     "url": "https://www.fincen.gov/system/files/2025-10/SAR-FAQs-October-2025.pdf"},
    {"source": "FinCEN Preparing a Complete and Sufficient SAR Narrative",
     "url": "https://www.fincen.gov/system/files/shared/sarnarrcompletguidfinal_112003.pdf"},
    {"source": "FinCEN SAR Supporting Documentation (FIN-2007-G003)",
     "url": "https://www.fincen.gov/system/files/shared/fin-2007-g003.pdf"},
    {"source": "FinCEN SAR Activity Review: Trends, Tips and Issues",
     "url": "https://www.fincen.gov/sites/default/files/sar_report/sar_tti_19.pdf"},
    {"source": "FinCEN Advisory on Imposter Scams and Money Mule Schemes",
     "url": "https://www.fincen.gov/system/files/advisory/2020-07-07/Advisory_%20Imposter_and_Money_Mule_COVID_19_508_FINAL.pdf"},
    {"source": "FinCEN Identity-Related Suspicious Activity (2021)",
     "url": "https://www.fincen.gov/system/files/shared/FTA_Identity_Final508.pdf"},
    {"source": "FFIEC Suspicious Activity Reporting",
     "url": "https://bsaaml.ffiec.gov/manual/AssessingComplianceWithBSARegulatoryRequirements/04"},
]
```

**Still correctly skip the 6 FATF documents** — that was never a time-saving shortcut, it's
a real methodological call already documented in `RESEARCH.md` §6.3: FATF's corpus is
money-laundering typologies (trade-based laundering, remittance networks, professional
laundering), which is weakly relevant to card fraud specifically. Loading it would dilute
the vector index with material that will never be the right retrieval hit for any of the
20 cases. Extra time doesn't change that reasoning — don't add them back just because
there's room.

**The OFAC SDN list is not usable here, and that's worth stating rather than forcing.** The
README lists it, but it's a list of sanctioned real names/entities, and this dataset is
anonymized — customers are `C01234`-style codes, cards are derived IDs, there are no real
names anywhere to screen against it. There is no case in `case_pack.csv` where a "sanctions
screening" evidence item could be honestly populated. Note this explicitly in the blog post
as a deliberate, reasoned exclusion ("we considered OFAC screening; the dataset has no
subject names to screen") rather than silently omitting it — that reads as diligence, not
as a gap.

Same fetch-and-chunk pipeline already handles all of these (`fetch_and_chunk_reg_doc`
degrades gracefully per-URL, already proven — 2 of the current 3 URLs are reachable live,
FFIEC's Red Flags appendix blocks automated fetches with a 403 regardless of user-agent,
confirmed on a real request). Expect a similar hit rate on the new ones; that's fine, the
pipeline already handles partial failures without crashing.

### P2 — only if P0 and P1/P1.5 are both green

- Upsert Gemini embeddings into `ClosedCase.notesEmb` (case memory) and `PolicyChunk.textEmb`
  (policy grounding) — `.env` already has `EMBED_PROVIDER=gemini`, `GEMINI_API_KEY`, and
  `src/rag/embed.py` now has a working, tested Gemini branch (`gemini-embedding-001`,
  `output_dimensionality=1536`, L2-normalized — verified live, raw vectors were NOT
  unit-norm at 1536-d, that's now handled). This is additive: it improves which prior cases
  get retrieved, but P0's pipeline doesn't need it to produce valid answer files.
- Louvain / connected-components over Card–DeviceProfile via `conn.gds.featurizer()`
  (RESEARCH.md §2.5, calls already written) — proves shared-device rings (HHG-014) for
  real. This is Devanshu's own stated Innovation angle on Discord, not a guess.
- Jaccard similarity over shared devices/emails for account linkage, and k-core for dense
  clusters (RESEARCH.md §2.5's other two featurizer calls) — same API, same live-graph
  dependency, worth running alongside Louvain once P0 is green rather than as a separate
  pass.

### P3 — genuinely optional, but no longer cut for time. Build these too.

These were previously marked "skip if out of time." The reason to skip was time, not
merit — with the deadline extended, do them. The one exception (GNN) is called out
separately because its reason for being dropped was never about time.

**The calibrated ML baseline (`docs/BHAVYA.md` Task 1, the part that survived the GNN
cut).** Logistic regression or gradient boosting over per-case features from the 5,565
closed cases (exposure, n_txns, time span, connected-card count, channel mix, shared-device
flag, region diversity), **time-split** (train on Jul–Sep, validate on Oct — never random,
the closed-case history itself has enough span to hold out a validation slice this way),
Platt/isotonic-calibrated, reliability curve checked. This was never the thing Devanshu
said to skip — he specifically objected to a **GNN** trained on the closed cases because
"it just gives you another score like risk_score." A calibrated baseline feeding
`prior_probability()` as *one more weighted signal in the ledger* (already how
`config/evidence_weights.yaml` is designed to consume it) is a different thing: it's not
replacing graph analysis or reasoning, it's one more calibrated number the deterministic
ledger sums alongside the others. Keep the weight small and honest, the same way
`risk_score_alone` is deliberately +0.05 — this model is another imperfect signal, not a
verdict, and the same overfitting concern Devanshu raised (5,565 rows is imbalanced 5:1 and
entirely retrospective) means it should never dominate the ledger the way a naive read of
"we have a trained model now" might tempt.

**Deeper undocumented-pattern mining across all 5,565 closed cases, not just the 9 already
read.** `docs/BHAVYA.md` covers the 9 rows explicitly labeled `pattern == 'undocumented'`
— confirmed real against the actual `analyst_notes` (proxy-ring device sharing, $500
structuring). With more time, look for a *second* unnamed pattern the labels don't
capture: cluster `confirmed_fraud` rows by shared structural features (device, region,
email-domain overlap; timing signatures) independent of their labeled `pattern` column,
and read the notes on any cluster that doesn't obviously map to one of the five documented
patterns or the two already-found undocumented ones. The brief rewards finding an
undocumented pattern once per case where it applies (`pattern_description`) — finding a
*second* genuine one (if it exists) is more Innovation credit, not double-counted risk,
as long as it's real and not forced. Don't manufacture one to look thorough — an honestly
absent second pattern is better than a strained one that doesn't survive a judge's read.

**The self-monitoring-beyond-20-cases folder** (README's own "Optional" section: *"If your
agent also monitors the exam period on its own, picks up alerts from the risk scores, and
investigates beyond the 20 cases, put those in a separate folder. They count toward
Innovation, not accuracy."*). Run the same live pipeline over November–December
transactions that never made it into `case_pack.csv` — i.e. treat every sufficiently
high-`risk_score` transaction in that window as a self-triggered alert, same as
`trigger_type: risk_score` cases already are, and write the results into e.g.
`cases_extended/` (a different folder from `cases/`, per the README's own instruction —
never mix these into the graded 20). This is a genuine, low-risk way to show the agent
operating autonomously rather than only ever being handed a pre-picked case, which is
exactly what "Innovation" and "agentic design" are scoring for.

**Skip permanently, not just for now — the GNN.** This is the one item that stays cut
regardless of time, because the reason was never time: Devanshu, directly, on Discord, to
a participant asking this exact question: *"I would skip it. It just gives you another
score like risk_score, and we don't score a model, we score the investigation and the
reasoning."* See `docs/BHAVYA.md` for the full re-scope. Building it now would spend real
hours reproducing something the person scoring the submission already said he doesn't want.

### Devanshu's GSQL bulk-load guidance — already aligned, no action needed

You may see this quoted at you again: "Don't do row-by-row REST. Use a GSQL loading job...
600K rows takes minutes." `src/graph/load.py` and `scripts/setup_graph.py` are already built
around `CREATE LOADING JOB` / `RUN LOADING JOB`, not row-by-row REST upsert. This was
checked against the actual code, not assumed — no change needed, don't re-litigate it.

---

# Vaibhav — policy engine, agent loop, answer assembly

You own the load-bearing half of the rubric. Investigation accuracy (25%) and next-best
action (25%) both run through your code.

**In one line:** turn evidence into a defensible decision, with the approval route attached,
and write the 20 JSON files that get graded.

---

## What you hand back

```python
def run_case(case_id: str, findings: list[Finding], similar_cases: dict) -> dict:
    """The complete answer file for one case, matching the README schema exactly."""
```

Karan gives you `findings` and `similar_cases`. Bhavya gives you a calibrated prior. You
produce `cases/<case_id>.json`.

---

## Part 1 — the probability ledger

Confidence is **computed, not guessed**. The LLM classifies evidence into the ledger and
writes the prose; it never emits the number. When a judge asks where 0.72 came from, we
point at a config file.

`config/evidence_weights.yaml`:

```yaml
card_testing_sequence:      +0.35    # R5
shared_device_across_cards: +0.30    # R6
customer_denies:            +0.30    # R2
shared_region_cluster:      +0.25    # R6
cnp_burst_pattern:          +0.20
out_of_region_pattern:      +0.20
closed_case_match:          +0.20
new_device_marker:          +0.15
proxy_flag:                 +0.10
risk_score_alone:           +0.05    # deliberately tiny — see below

recurring_merchant_match:   -0.25    # R7 disputed-but-legitimate
cleared_precedent_match:    -0.20    # a cleared prior case matches
in_character_for_customer:  -0.20    # amount/product/region all normal
customer_confirms:          -0.90    # R3
```

`fraud_probability = sigmoid(sum of applicable weights)`, clipped to [0,1].

**Why `risk_score_alone` is only +0.05:** the README states that above 0.7, most flagged
transactions turn out to be legitimate, and some fraud scores near zero. Treating the
model's score as a strong prior would wreck our calibration score. It's a reason to look,
not evidence.

**The negative weights are as important as the positive ones.** Half the exam cases are
legitimate. Without real exonerating weights the agent drifts toward blocking everything,
which is the stated way to score badly.

---

## Part 2 — the rule engine

R1–R10 from the README, as predicate functions returning ordered action lists. Not an LLM
deciding — a lookup. `config/fraud_policy.yaml` holds it; `src/policy/engine.py` executes it.

The 14 action identifiers are exact. Don't rename anything:

```
ALLOW_TRANSACTION  DECLINE_TRANSACTION  MONITOR_CARD  MONITOR_CONNECTED_CARDS
WARN_CUSTOMER  VERIFY_WITH_CUSTOMER  STEP_UP_AUTH  BLOCK_CARD  BLOCK_ALL_CARDS
GENERATE_REPORT  CREATE_CASE  FILE_REPORT  ESCALATE_TO_ANALYST  CLOSE_NO_FRAUD
```

Approval routing — note that one route depends on exposure:

| Route | Applies to |
|---|---|
| `auto` | everything not listed below |
| `L1` | `DECLINE_TRANSACTION`; `BLOCK_CARD` when exposure ≤ $2,500 |
| `L2` | `BLOCK_CARD` when exposure > $2,500; `BLOCK_ALL_CARDS`; `FILE_REPORT` |

**The agent executes `auto` only.** `L1`/`L2` get recommended with the route stated and wait
for a human. Enforce that in code — one `finalize_action()` chokepoint, not a prompt
instruction.

Two rules that aren't simple additions:
- **R7 forbids** — a disputed charge that matches the customer's own recurring pattern must
  *not* produce BLOCK_CARD or DECLINE_TRANSACTION.
- **R10 downgrades** — BLOCK_ALL_CARDS becomes BLOCK_CARD unless 2+ cards are confirmed
  fraud or credentials are confirmed compromised.

**Boundary conditions are worth real points.** The policy says `> $1,000`, `> $500`,
`≤ $2,500`, `< 0.70`, `≥ 0.85`. Match the inequality exactly. Test 2500 and 2501.

---

## Part 3 — the before/after mechanic

This is the most load-bearing single feature in the submission. The README demands the
recommendation be recorded **before** any evidence request and **after** the response.

```
initial:  p=0.45 on a risk score alone
          -> R1 -> VERIFY_WITH_CUSTOMER (auto) + CREATE_CASE (auto, since p >= 0.30)

evidence_requests: [{type: customer_validation, asked_after_step: 4,
                     assumed_response: "Customer states they did not make these purchases"}]

final:    p=0.86
          -> R2 -> BLOCK_CARD (L1) + CREATE_CASE + FILE_REPORT (L2, shared device)

what_changed: "Customer denial raised probability from 0.45 to 0.86 and triggered the block."
```

Make it real, not back-filled. Two safeguards:

1. **Hard gate in orchestrator code**, not a prompt: if the stopping criteria aren't met and
   no evidence has been requested, refuse to finalize.
   ```python
   if not can_stop(p, independent_evidence_count, verification_settled) \
      and not evidence_requests:
       raise MustRequestEvidence
   ```
2. **Hash the evidence set** on each snapshot. It proves the "after" number was computed
   from strictly more evidence than the "before" — a judge reading the JSON can verify the
   delta is causal rather than a re-roll.

Stopping criteria (README §6): p ≥ 0.85 or ≤ 0.15 **with at least 2 independent evidence
pieces**; or a verification response settles it; or further steps won't change the decision.
"Independent" means distinct sources — two facts from the same query are one piece.

**Don't force artificial evidence requests on clear-cut cases.** §6 marks down
investigations that continue past a defensible decision. `final == initial` with
`what_changed: "nothing"` is a valid, correct answer.

---

## Part 4 — the answer file

Exact shape is in README.md's "Answer Format" section. Missing fields score zero for that
part. Read it directly; don't work from memory.

Write `src/answer/validator.py` and run it over all 20 before submitting. It must check:

- `sar.file` agrees with whether `FILE_REPORT` is in `final`
- verdict `legitimate` ⟹ `exposure_usd == 0` and `affected_txn_ids == []`
- pattern `undocumented` ⟹ non-empty `pattern_description`
- no evidence requests ⟹ `final == initial` and `what_changed == "nothing"`
- **every txn_id and prior-case id exists in the dataset** — fabricated IDs score zero
- every `route` matches the table given that case's exposure
- every action's `reason` cites an R-number
- `exposure_usd` equals the summed absolute amounts of `affected_txn_ids`

Return a list of violations rather than raising on the first, so all 20 can be fixed in one
pass.

Field gotchas:
- `escalated` is a distinct status from `open`. R8 cases are usually `escalated`.
- `uncertain` is a **fully creditable verdict**. Forcing a binary call to look decisive is
  the more common failure than leaving it uncertain.
- Don't set `written_to_graph: true` speculatively — a judge can check the graph.
- `tool_calls` / `tokens` / `latency_s` identical across all 20 files looks fabricated. Log
  real per-case values.

---

## Part 5 — the agent loop

LangGraph. Picked because the cyclic investigate→assess→gather-more loop and the human
approval gate are native primitives rather than things we hand-roll.

```
trigger -> investigate -> gather_evidence -> assess
               ^                               |
               +--------- need_more? ----------+
                                               |
                                    snapshot_initial
                                               |
                                      request_evidence
                                               |
                                    snapshot_final
                                               |
                              policy_gate (interrupt for L1/L2)
                                               |
                          explain -> write_case_to_graph -> emit_json
```

Use `interrupt()` for the approval gate — it carries a payload for the reviewer UI.
**Gotcha:** on resume the node re-executes from the top, so keep side effects out of any
node containing an `interrupt()` call.

---

## Files you own

```
config/fraud_policy.yaml
config/evidence_weights.yaml
src/policy/engine.py
src/policy/ledger.py
src/agent/state.py
src/agent/graph.py
src/agent/nodes.py
src/answer/schema.py
src/answer/validator.py
tests/test_policy.py
tests/test_validator.py
```

Don't edit outside these — Karan and Bhavya are in other directories concurrently.

---

## Order of work

1. `fraud_policy.yaml` + `evidence_weights.yaml` first — they're the contract everyone reads
2. `engine.py` + `ledger.py` with tests, against the README's own HHG-017 worked example
3. `validator.py` — you want this before you generate 20 files, not after
4. The LangGraph loop
5. Batch-run all 20

Start with **HHG-017**: the README's worked example uses that exact case, so you have the
expected output shape for free. Then HHG-014, the device-ring case.
