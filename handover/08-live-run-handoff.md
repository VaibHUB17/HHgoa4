# 08 — Live-run handoff (2026-09-24, ~05:45 IST)

For the agent picking this up cold. Read this file first, then `docs/VAIBHAV.md` for the full
phase plan (P0–P3). This file records the actual state and overrides any doc that says
something different.

**Deadline:** 24 Sept 2026, 11:59 PM IST. Treat it as real: an extension has been mentioned
but not confirmed in writing (`docs/KARAN.md`). The submission form accepts one submission,
with no resubmits.

---

## 1. Current state in one paragraph

TigerGraph Savanna is set up and fully loaded. All 6 GSQL queries are installed. The agent
runs **live** against the graph for all 20 exam cases, and `cases/` holds 20 answer files
that pass the validator with **0 violations**; these are committed. Tests: **112 passed**
(`tests/test_ml.py` can't run on this machine, see §6). Work in progress, not committed:
- LLM prose (Groq) for the case summary and SAR narrative;
- real transaction timestamps in SARs;
- a background job that embeds the closed-case notes with Gemini.

Nothing has been pushed.

---

## 2. Git

- Branch: **`p0-live-tigergraph`**, one commit ahead of `main`: `558490e feat(p0): run the agent live on TigerGraph Savanna; all 20 answer files validate`.
- **Not pushed.** Don't push or merge unless the user asks.
- Uncommitted working-tree changes (all described in §4):
  ```
   M src/agent/deps.py      M src/agent/nodes.py     M src/agent/run.py
   M src/agent/state.py     M src/rag/embed.py       M src/sar/narrative.py
  ?? src/llm/                (new: __init__.py, prose.py)
  ```
- Ignored and never committed: `.env`, `data/`, `data_labeled/`, `artifacts/`, `embeddings/`, `scratch/`.

---

## 3. Environment and credentials (verified working)

- **Python:** `.venv/Scripts/python` (3.14). Run modules from the repo root with `PYTHONPATH=.`.
- **`.env`:** the values are set; don't print them. The keys that matter:
  - `TG_HOST`, `TG_GRAPH=FraudInvestigation`, `TG_SECRET`. The secret alone authenticates both GSQL and REST; there's no username/password in `.env` and none is needed.
  - `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_MODEL=qwen/qwen3.8-27b`.
  - `GEMINI_API_KEY`, `EMBED_PROVIDER=gemini`, `EMBED_MODEL=gemini-embedding-001`, `EMBED_DIM=1536`.
- **TigerGraph:** Savanna **4.2.5**, so vector attributes are supported. If the workspace
  auto-suspends, the first call takes 1–2 minutes to wake it.
- `google-genai` is installed into `.venv` (it's in `pyproject.toml`/`uv.lock` from Bhavya's commit).

---

## 4. What was done

### 4.1 Committed (`558490e`) — P0 is green

| Area | What changed and why |
|---|---|
| `scripts/setup_graph.py` | Creates the global types, then runs `CREATE GRAPH FraudInvestigation(*)`, then the vector schema-change job, then the queries (each one inside `USE GRAPH`), then `INSTALL QUERY ALL`. `conn.gsql()` returns errors **as text** rather than raising, so failures are detected by regex on the output. |
| `src/graph/schema.gsql` | `Case` is a **reserved GSQL keyword**, so the vertex is now **`InvestigationCase`**. The vector attributes `ClosedCase.notesEmb` and `PolicyChunk.textEmb` are 1536-d cosine, and live. |
| `src/graph/queries.gsql` | All 6 queries rewritten for 4.2.5 and installed: `card_window`, `device_neighbors`, `customer_baseline`, `prior_cases_for_entities`, `similar_prior_cases` (vectorSearch, one pool at a time), `write_case_to_graph`. 4.2.5 SYNTAX v2 **requires edge direction** (`-(MADE>)-`). Primary IDs aren't attributes, so region/device/card ids are collected into `SetAccum<VERTEX>`. `prior_cases_for_entities` counts only rare devices (`outdegree("DEVICE_OF") <= 100`). |
| `src/graph/load.py` | The loading job now POSTs header-less CSV chunks of about 24 MB to `/ddl`, because Savanna can't read local paths. It was hard-coded to graph `FraudGraph`; the name now comes from the connection. **Loaded:** 590,742 transactions, 14,780 cards, 13,553 customers, 9,704 device profiles, 5,565 closed cases, all edges, **0 rejects**. card_id: the known ids from `case_pack.csv` and `closed_cases_history.csv` override the heuristic for the whole card tuple they cover, giving **20/20 exam cases and 4,665/4,665 closed cases** correct. |
| `src/graph/connection.py` | Uses `gsqlSecret`. `run_query(name, case_id=..., params={...}, **kw)`: here `case_id` is the **tool-call counter key**, so a query that itself takes a `case_id` parameter must pass it inside `params=`. |
| `src/agent/deps.py` (`_LiveFetch`) | The live evidence layer. Every fetch is bounded by the case's `opened_at` (no future data). The baseline uses only history from before the 72 h look-back window. Real `id_23` values `IP_PROXY:ANONYMOUS/HIDDEN/TRANSPARENT` are mapped to `Anonymous/Hidden/Transparent`. Transaction ids are "T"-prefixed in the agent and bare in the graph. **Ring rule (R6):** the flagged purchase itself must be behind an Anonymous/Hidden proxy, **and** at least 3 *other* customers must use the same fingerprint through such a proxy in the 7 days before it. Device keys are browser fingerprints (median 1 customer per key, max 842), so without this rule nearly every online case looks like a ring. `affected_txn_ids`/exposure cover **only the case's own card**. |
| `src/agent/nodes.py` | `customer_report` triggers seed `customer_denies` plus a customer evidence item, which makes R2 and R7 reachable. **R7 was never wired into `CaseState` before** and could not fire. R7 cases always get a customer verification request. `write_case` sends the full payload (card, customer, verdict, actions, …). |
| `src/policy/engine.py` | SAR "strongly suspected" means `p >= 0.70` (R1's block line). R7 also forbids `FILE_REPORT`, since "disputed but legitimate" and a SAR contradict each other. |
| `src/detectors/patterns.py` | New `detect_threshold_structuring`: 3 or more online purchases within 1 h, each between $450 and $500. This is Bhavya's undocumented pattern, with precedents CC-3748, 3841, 3907, 4086, 4124. It uses the existing `cnp_burst_pattern` weight; **no new weight**. It fires on HHG-006. |
| R7 recurring definition | The data has no merchant field, so: same card + product + channel, amount within 2%, at least 3 prior occurrences across at least 2 calendar months, all before the look-back window. Implemented in `deps._is_recurring`. |

**Result committed in `cases/`:** 2 fraud, 3 legitimate, 15 uncertain; validator 20/20 clean.
- HHG-006 → fraud, `undocumented` (structuring), SAR filed.
- HHG-014 → 18-customer device ring, BLOCK_CARD (L1) + FILE_REPORT (L2), SAR filed, p=0.84.
- HHG-009 → customer confirms a recurring charge, R3 close.
- HHG-003/008/011/018 → R7 protects them from blocks.

### 4.2 Uncommitted work in progress (tests pass, **not yet run across all 20**)

1. **`src/llm/prose.py`** (new): Groq writes `case.summary` and `sar.narrative` from facts that
   are **already decided**. Guards:
   - every ID in the output must already appear in the input facts, otherwise the template is kept;
   - U+2011 hyphens are normalised;
   - any error falls back to the template;
   - it's disabled when `GROQ_API_KEY` is missing, `LLM_PROSE=0` is set, or pytest is running;
   - real token counts go into `tokens` (they were hard-coded to 0).

   Tested once on HHG-006 (1,960 tokens, good prose).
   The SAR prompt now tells the model not to mention routes or rule numbers: it had mislabelled FILE_REPORT as "R10".
2. **`src/agent/run.py`:** wires in prose, `tokens=prose.tokens_used(...)`, and the SAR uses **real transaction timestamps**. Before, every timestamp was faked as `opened_at`, so HHG-006 showed 11-22 instead of 11-21.
3. **`src/agent/state.py` / `nodes.py` / `deps.py`:** a new `txn_timestamps` state channel (txn_id → ts) carried from the card window.
4. **`src/sar/narrative.py`:** the template said every prior case was "previously confirmed as fraud", including cleared ones. It now says "Related prior investigations reviewed as case memory".
5. **`src/rag/embed.py`:** added `embed_query(text)` (task type `RETRIEVAL_QUERY`) and `load_dotenv()`. `deps._semantic_candidates` imports `embed_query`. Before this it silently returned `[]`.

### 4.3 Background job (may still be running)

`scratch/embed_cases.py` (log: `artifacts/embed.log`) embeds all 5,565 `analyst_notes` with
Gemini and then upserts `ClosedCase.notesEmb`.
- Gemini's free tier returns **429 about every 128 notes (a per-minute limit)**. The script waits 30 s and retries, so it should finish in about an hour from 05:37.
- The cache (`embeddings/*.json`) is saved after every chunk, so re-running resumes where it stopped.
- **It upserts only at the end.** Until then, the graph holds just 3 test vectors (CC-0001..0003), and semantic retrieval returns those three as junk "precedents". So **don't generate final answer files until the log prints `upserted 5565`.**
- Check: `tail -3 artifacts/embed.log`. To restart: `PYTHONPATH=. .venv/Scripts/python -u scratch/embed_cases.py > artifacts/embed.log 2>&1`.
- Vector search is confirmed working on TigerGraph. The HNSW index updates a few seconds after an upsert.

---

## 5. What's left, in priority order

**A. Finish and verify P1 prose + P2 embeddings (highest value, nearly done)**
1. Wait for `upserted 5565` in `artifacts/embed.log`. Then check that `similar_prior_cases` returns
   sensible cases for a query, and that the confirmed and cleared pools both come back.
2. Run all 20 into a scratch folder first:
   `PYTHONPATH=. .venv/Scripts/python -m src.agent.run --all --data-dir ./data --out scratch/cases_try/`,
   then `python -m src.answer.validator scratch/cases_try/`. Must be 0 violations.
3. Read every summary and SAR against its evidence. Check that the dates match the transaction timestamps, that the rules and routes quoted match `final`, and that no ID is invented.
4. Only then regenerate `cases/`, re-validate, run the tests, and commit.

**B. MCP in the agent path (a *required* component in the brief, currently missing).**
`src/graph/mcp.py` only lists tools, and the agent calls pyTigerGraph directly. The minimum
credible version: route the installed-query calls through the `tigergraph-mcp` tool
`tigergraph__run_installed_query`, read-only. `docs/VAIBHAV.md` P1.5 has a fuller
`agentic_deps()` design (LLM *selects* tools, behind `--evidence-mode agentic`, falls back to
`live_deps`). Whatever you build, the LLM must never pick probabilities, actions, routes or stopping.

**C. Document GraphRAG (VAIBHAV.md P1).** Add the `Pattern`/`RegChunk`(/`Action`) vertices and
the GOVERNS/CITES(/PRESCRIBES) edges, embed the chunks from `policy_docs.load_all()` into
`PolicyChunk.textEmb` etc., and add `source: "document"` evidence citing the retrieved
chunk_id. **Rate limits:** the Gemini free tier caps embeddings at about 100 per minute, so budget time.

**D. Graph algorithms (VAIBHAV.md P2).** Run Louvain / WCC over Card–DeviceProfile. HHG-014's
ring is the demo story: 18+ customers, one fingerprint, anonymous proxy, 8 days.

**E. Submission items** (`docs/KARAN.md`): check the UI in a browser, demo video, blog with real numbers, social post tagging @TigerGraphDB, make the repo public, and a single form submission.

### Known quality issues worth a look (don't tune against labels)
- **15/20 are "uncertain."** Many risk-score cases stall at p=0.61: a new device plus a *simulated* failed step-up. That's defensible under the current weights, but judges reward moving to a clear decision. Improve the **evidence**, not the weights or thresholds: `config/*.yaml` is a frozen contract (VAIBHAV.md). Options:
  - real semantic memory once the embeddings land;
  - the `cleared_precedent_match` key, which exists in the weights but is never emitted by any detector;
  - a closed-case outcome on the connected cards.
- HHG-014 sits at p=0.84, just under the 0.85 fraud line. Leave it unless *new evidence* moves it.
- HHG-009's final actions list `CLOSE_NO_FRAUD` next to R7's `CREATE_CASE/VERIFY/WARN`. That's valid, but could read better.
- `datetime.utcnow()` deprecation warnings appear in logs (harmless).

---

## 6. Rules and gotchas (hard-won; don't relearn them)

- ⚠️ **Never read `data_labeled/`.** It contains the benchmark answer key (`is_fraud`, `derived_verdict`, `final_action`, …). Using it to shape outputs is effectively cheating and a disqualification risk. Nothing in `src/` reads it; keep it that way.
- **Don't change `config/evidence_weights.yaml`, `config/fraud_policy.yaml`, or the 0.85/0.15/0.70 thresholds** to push verdicts around.
- **The LLM writes prose only.** The ID guard is the real check; don't rely on prompt wording alone.
- **GSQL on 4.2.5:**
  - `USE GRAPH X` must prefix each statement sent separately;
  - directed edges need `>`;
  - `INSTALL QUERY` often drops the HTTP connection but finishes on the server. Check with `LS` and look for `(installed v2)`;
  - pass VERTEX params as 1-tuples (`card_id=("C123-K1",)`) to avoid a deprecation retry.
- **Loading:** `runLoadingJobWithData` per `DEFINE FILENAME` tag, header-less chunks, `QUOTE="double"`. Counts show up asynchronously.
- **Bash heredocs on this Windows box mangle `\n` inside Python strings** (turned into real newlines). Use a proper file edit for code containing `\n`.
- **`tests/test_ml.py` can't import here:** Windows Application Control blocks a scikit-learn DLL. It's a machine issue, not a code issue. Run `python -m pytest tests/ -q --ignore=tests/test_ml.py`; the floor is **112 passed**.
- Deleting or re-running answer files: `cases/` is the graded output. Iterate in `scratch/cases_try/`, then regenerate `cases/` once.

---

## 7. Commands

```bash
PYTHONPATH=. .venv/Scripts/python -m scripts.setup_graph --check            # connection + schema + queries
PYTHONPATH=. .venv/Scripts/python -m src.agent.run --case HHG-017 --data-dir ./data --out scratch/cases_try/
PYTHONPATH=. .venv/Scripts/python -m src.agent.run --all  --data-dir ./data --out cases/
PYTHONPATH=. .venv/Scripts/python -m src.answer.validator cases/
PYTHONPATH=. .venv/Scripts/python -m pytest tests/ -q --ignore=tests/test_ml.py
LLM_PROSE=0 ...        # disable Groq prose      SEMANTIC_MEMORY switch: not implemented (see §4.3)
```

Reinstalling one or more queries after editing `queries.gsql`:
`PYTHONPATH=. .venv/Scripts/python scratch/reinstall.py <query_name> [...]`

---

## 8. What I'll check when you hand back

1. `git log` / `git diff p0-live-tigergraph..HEAD`: small, explained commits, nothing pushed without the user's say-so.
2. Tests: 112+ passed, excluding `test_ml.py`.
3. `python -m src.answer.validator cases/`: 20 files, 0 violations.
4. The answer files were generated **live**:
   - `tool_calls` > 0 and varying across cases;
   - `written_to_graph: true`, and the `InvestigationCase` vertices exist in TigerGraph;
   - `tokens` > 0 wherever prose ran.
5. SAR dates match the real transaction times, and no invented IDs appear in summaries or SARs.
6. `ClosedCase.notesEmb` is populated for all 5,565 cases, and `similar_prior_cases` returns both pools.
7. No reads of `data_labeled/`, and no edits to the weights, policy config or thresholds.
8. Whether MCP is in the agent path, and how. The brief requires it.
