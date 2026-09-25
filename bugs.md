# Known bugs (found during end-to-end verification, 2026-09-25)

Verified against the live TigerGraph instance and the real 20 case files in `cases/`.

**Update, same day, later pass: bugs #1 and #2 below are FIXED and verified** (see "Fixed"
sections). Three additional improvements were made in the same pass — see "New this pass"
at the bottom. All changes were regression-tested: full 194-test suite passes, and every
affected case was individually regenerated and diffed against its committed
`fraud_probability`/`verdict` to confirm zero change to any decision, only to the `pattern`
label (bug #1) and to which evidence got collected (bug #2, which correctly stayed a no-op
either way). A true noise-floor baseline (all 20 cases regenerated with zero code changes)
confirmed `fraud_probability`/`verdict` are 100% stable run-to-run — only `tokens`/`latency_s`/
prose vary — so any probability/verdict difference found is attributable to a real code change,
not LLM run-to-run noise.

## 1. HHG-014 pattern mislabeled — should be `undocumented` — **FIXED**

**File:** `cases/HHG-014.json` (also check `src/agent/nodes.py`, detector-ordering logic)
**What's wrong:** `pattern` is set to `"card_not_present_new_device"`, but the actual evidence in the
same file is a shared-device ring (one device fingerprint —
`SM-G935F Build/NRD90M | Android 7.0 | chrome 62.0 for android | 1920x1080` — shared across 18
unrelated customers/cards), corroborated by a `tg_wcc` graph-algorithm result. That doesn't match
any of the 5 documented patterns; it's exactly the kind of finding the brief says should get
separate `undocumented`-pattern credit.
**Likely cause:** first-detector-that-fires wins, and the CNP/new-device detector fires before the
device-ring detector gets a chance to override the pattern label.
**Fix:** when the shared-device-ring detector fires, it should set `pattern: "undocumented"` +
a `pattern_description` explaining the ring, taking priority over the generic CNP label.
**Why it matters:** this is the strongest showcase case (real graph-algorithm evidence, real
document citation, real agentic `llm_decision` step) — it deserves the differentiator credit it's
not currently getting.
**Fix applied:** `src/agent/deps.py`'s `run_detectors` picked the *first* finding's pattern
(first-fired-wins). Replaced with a `_PATTERN_PRIORITY` ranking (`undocumented` and
`account_takeover` outrank single-card signals like `card_not_present_new_device`), so a
confirmed multi-customer ring always wins the case's `pattern` field regardless of detector
order. Verified: HHG-014 now reports `pattern: "undocumented"` with the correct
`pattern_description`, `fraud_probability` and `verdict` unchanged (0.6118 / fraud, byte-identical
to the pre-fix committed file).

## 2. Hallucinated `device_id` parameter in 4 cases → identical fraud_probability — **FIXED**

**Files:** `cases/HHG-005.json`, `HHG-007.json`, `HHG-010.json`, `HHG-012.json`
**What's wrong:** all four converge on the exact same `fraud_probability: 0.1187`. In HHG-005/010/012,
the agent's tool-call plan passes `device_id: 'id_15'` or `'device_id_15'` to the
`device_neighbors` query — `id_15` is a dataset **column name** (the "New/Found device" flag), not
a real device key. The query correctly returns empty and the code correctly discards it rather than
fabricating evidence, but it means the "extra digging" step for these cases was a wasted no-op,
so they all fall back to the same baseline probability instead of getting case-specific signal.
**Likely cause:** the LLM's plan step doesn't have the real device key in its context when it
proposes this tool call — it pattern-matches on a column name from the schema description instead.
**Fix:** make sure the plan-step prompt/context always includes the actual resolved `device_id`
value(s) already seen for the case (from `seed_evidence` / prior tool results) before letting the
LLM propose a `device_neighbors` call, or validate the parameter against known device-key shape
before executing.
**Why it matters:** doesn't corrupt anything (bad params → empty result → discarded), but wastes a
tool call and under-informs 4 of the 20 graded cases.
**Fix applied, two layers, in `src/agent/investigator.py`:**
1. The plan-step prompt now lists every real entity id seen in evidence so far and explicitly
   instructs the model to reuse one verbatim or say it doesn't know, rather than invent a value
   or use a raw dataset column name (`_known_entity_ids()`, threaded into `_plan()`'s prompt).
2. A guard (`_COLUMN_NAME_AS_ID` regex) rejects any `run_query` call whose param matches the
   `id_N` / `device_id_N` column-name shape **before it ever reaches the database**, recording a
   transparent `llm_plan:rejected(column_as_id, ...)` evidence entry instead. Verified directly at
   the unit level: `device_id='id_15'` is now refused pre-database-call (see
   `tests/test_investigator.py` or the ad-hoc verification in this session's history).
   Regenerated HHG-005/007/010/012 individually: `fraud_probability`/`verdict` unchanged for all
   four (0.1187 / legitimate in every case, same as committed).

## Not bugs (checked and ruled out)

- **`InvestigationCase` vs `Case` vertex name** — not drift. `schema.gsql` line 92 already names it
  `InvestigationCase` with an explicit comment: `"Case" is a reserved GSQL keyword`. The live schema
  matches the checked-in file exactly.
- **Semantic/vector case-memory retrieval** — confirmed genuinely wired and exercised, not dead
  code: `_semantic_candidates()` in `src/agent/deps.py` calls `embed_query()` on the real case
  trigger text and runs the live `similar_prior_cases` GSQL query (two-pool: `confirmed_fraud` /
  `cleared`) against `ClosedCase.notesEmb`. All 20 case files have a real, non-empty
  `similar_prior_cases` array of prior case IDs (e.g. `CC-0117`, `CC-0309`...). This was the biggest
  open question from the "are we done" review and it checks out.
- **Document-sourced evidence (`PolicyChunk.textEmb`)** — genuinely used, not decorative: 10 real
  `source: "document"` evidence entries across the 20 cases (out of 102 total evidence entries:
  84 graph, 10 document, 8 customer).

## New this pass

1. **Verbose per-case demo trace** (`cases/traces/<case_id>.trace.md`, written by
   `_write_trace_md()` in `src/agent/run.py` alongside every answer file). Human-readable
   breakdown of every evidence item, labeled `AGENTIC` / `GRAPH` / `GRAPHRAG` / `GRAPH ALGORITHM`
   / `DOCUMENT`, plus the verdict/probability with an explicit note that they're computed
   deterministically and the LLM never sets them, plus next-best-actions before/after evidence.
   This is what should be shown in the demo video to make "what's agentic vs graph-based
   evidence" visible rather than asserted. Confirmed `cases/traces/` is not excluded by
   `.gitignore` (`git check-ignore` returns nothing for it).
2. **Enriched case-memory evidence** (`src/agent/deps.py`). `src/rag/retrieve.py` already had a
   `precedent_evidence()` method that turns every retrieved `similar_prior_cases` candidate into
   an evidence item with its outcome, pattern, exposure, and why it matched (structural overlap /
   pattern match / semantic similarity + cosine distance) — it was built but never called. Now
   wired in as a purely additive evidence append (no new ledger keys, so it cannot move
   `fraud_probability`); confirmed on HHG-017 that all 5 retrieved precedent cases now carry a
   full reason instead of a bare id, with `fraud_probability`/`verdict` unchanged.
3. **Jevlike advisory confidence gate**, per Devanshu's Discord-approved design ("keep it
   advisory: let it decide whether to act or ask for more evidence, and let the graph evidence
   drive the verdict"). The existing iterative investigator (`src/agent/investigator.py`) already
   had exactly this shape — a single-pass LLM classifier per depth deciding CONCLUDE vs CONTINUE
   on raw evidence, never the verdict — it just wasn't labeled or visible as one. Made it explicit:
   the assess step's JSON contract now includes a `confidence: low|medium|high` field, and a
   `llm_decision:confidence_gate(...)` evidence entry is recorded on every CONCLUDE so it shows up
   in the trace file. Structurally cannot touch the verdict: `compute_probability`/`engine.py` only
   ever see `result.evidence`, and this only adds one narrative entry to it, never a ledger key.
   Verified on HHG-014 (which exercises the deeper loop): `fraud_probability`/`verdict` unchanged
   (0.6118 / fraud) with the confidence entry present.

All three verified with the full test suite (`uv run python -m pytest tests/ -q`, 194 passed)
plus targeted before/after regeneration of the affected cases.

## 4. Unbounded entity_ids on a re-run installed query — FOUND AND FIXED during full regen

**Files:** `cases/HHG-007.json` (2,794 entity_ids on one evidence item), `cases/HHG-013.json`
(1,571 entity_ids on one evidence item).
**What was wrong:** `_rows_to_evidence()` in `src/agent/investigator.py` had no row cap, unlike
the ad-hoc GSQL guard (`MAX_GENERATED_QUERY_ROWS = 200`). When the depth loop's plan step called
an *installed* query a second time (e.g. a broader `customer_baseline` re-check), a busy
customer's full transaction history flattened into thousands of entity ids on a single evidence
item — technically valid data, but it bloated the answer file (HHG-007's JSON diff was 2,869
lines for what should be a small per-case update) without adding any real information.
**Fix:** capped `_rows_to_evidence()`'s entity_ids output at the same `MAX_GENERATED_QUERY_ROWS`
already used for ad-hoc queries, keeping the true count in the claim text ("returned N connected
entities... (showing first 200)") so nothing is silently hidden, just not all individually cited.
**Verified:** regenerated both cases; `fraud_probability`/`verdict` unchanged for both
(HHG-007: 0.1187/legitimate, HHG-013: 0.2729/uncertain — both identical to the pre-fix committed
values). Full test suite re-run, 194 passed. Swept all 20 committed cases afterward for any
remaining evidence item with >200 entity_ids: none found.
**Why it matters:** this was caught specifically because "make a proper commit" prompted a look
at `git diff --stat` before committing — a genuinely useful habit: an unexpectedly large diff on
a JSON answer file is a signal worth chasing, not just pushing through.

## Not yet done (blocked, not skipped)

- **Full 20-case regeneration of the committed `cases/*.json` with all fixes applied.** Today's
  Groq free-tier daily token budget (200,000 TPD) was consumed by this session's verification
  runs (individual and small-batch case regens, each requiring live LLM calls). The system
  degrades correctly under this (`llm_available=False`, "stopping rather than guessing" — no
  hardcoded fallback), but a full batch run right now would silently under-perform for that
  reason, not because of any bug, and would be a bad final artifact to commit. Re-run
  `uv run python -m src.agent.run --all --evidence-mode agentic --out cases` once the Groq quota
  resets (or on a Dev Tier key) to regenerate the real answer files with all three fixes and all
  three new features baked in, then re-run the validator and diff verdicts against the current
  committed files before committing.
- **Regulatory corpus expansion** (still the original 3 URLs) — cheap, but advisor-rated low
  value versus the above; not attempted this pass.

## Known, smaller gaps (not bugs, just unfinished scope)

- **Regulatory corpus is still the original 3 URLs** (FinCEN SAR narrative, FinCEN advisory,
  FFIEC BSA/AML manual) — `docs/VAIBHAV.md` P1.6 proposed extending this list; that extension
  was never done. Not broken, just narrower than planned.
- **No separate `RegChunk`/`Pattern` graph vertices or `GOVERNS`/`PRESCRIBES`/`CITES` edges** live
  in TigerGraph. The regulatory text is embedded and retrieved via the simpler `PolicyChunk`
  vertex/vector-attribute path instead, which already works and is cited in real cases (see above)
  — so the *outcome* the plan wanted (document-grounded evidence) is achieved, just via a simpler
  structure than originally spec'd, not the richer typed doc-graph.
