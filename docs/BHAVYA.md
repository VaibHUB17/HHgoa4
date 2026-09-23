# Bhavya — ML, case memory, embeddings

You're the ML person on this. Here's your scope in plain terms, then the detail.

**In one line:** turn the 5,565 already-solved fraud cases into something that makes the
agent's guesses better on the 20 new ones.

Everything below is yours end to end. Karan does the graph and detectors, Vaibhav does the
policy engine and the agent loop. You don't wait on either of them — you work off the CSV
directly, and hand back two functions.

---

## What you hand back

Two functions. That's the whole contract.

```python
def prior_probability(case_features: dict) -> float:
    """A calibrated fraud probability from the closed-case history. 0-1."""

def similar_cases(case) -> dict:
    """{'confirming': [CC-ids], 'disconfirming': [CC-ids]} — prior cases as memory."""
```

Vaibhav's ledger consumes the first as one weighted signal among several. The second
populates `similar_prior_cases` in every answer file.

---

## Your data

`closed_cases_history.csv` — 5,565 finished investigations, July–October 2016.
**4,665 confirmed fraud, 900 cleared.** This is the only place in the dataset where the
truth is written down.

Columns:
```
case_id, customer_id, card_id, opened_at, closed_at, outcome, pattern,
first_fraud_txn_id, txn_ids (pipe-separated), n_txns, exposure_usd,
connected_card_ids, actions_taken, report_filed, analyst_notes
```

`outcome` is your label: `confirmed_fraud` or `cleared`.
`pattern` is the fraud type, or `none` for cleared cases, or `undocumented`.
`analyst_notes` is free text — a human analyst explaining what happened.

Join to `transactions.csv` on the txn_ids to get features per case.

---

## Task 1 — skip the GNN. Devanshu answered this directly.

**Status: dropped, not deferred.** This was re-scoped on 2026-09-24 after re-reading the
actual Discord thread. Another participant (Melichior) asked the problem-setter this exact
question — train a GNN on `closed_cases_history.csv`, worried about it overfitting since the
closed cases are the only labelled rows. Devanshu's answer, verbatim:

> "On the GNN: I would skip it. It just gives you another score like risk_score, and we
> don't score a model, we score the investigation and the reasoning. Use TigerGraph's
> built-in graph algorithms (community detection, similarity, PageRank, callable from GSQL)
> plus vector search over the closed-case notes so the agent retrieves similar past cases as
> memory. That gives you pattern learning without overfitting, and it's explainable."

That's not a hint, it's the judge telling you what he wants to see instead. Building a GNN
now would spend hours reproducing something the person scoring the submission already said
he doesn't want, on a deadline that's today. **Don't build `src/ml/train.py`'s GNN seam.**

The calibrated baseline (logistic regression / gradient boosting over per-case features,
Platt/isotonic calibrated, time-split) is still worth keeping — it's cheap, it's a legitimate
`prior_probability()` signal, and unlike a GNN it's not what Devanshu waved off. But it's now
**optional polish, not your main task.** Don't run it before real answer files exist; the
evidence ledger works without it (`prior_probability()` returns `None` when no model is
trained, and the ledger just omits that signal).

Your main task is now the thing Devanshu actually named: **graph algorithms + vector search
over case memory.** That's Task 1a/1b below.

### Task 1a — TigerGraph's built-in graph algorithms

`RESEARCH.md` §2.5 already has the calls written — this is execution, not design:

```python
feat = conn.gds.featurizer()
feat.runAlgorithm("tg_louvain", params={"v_type": ["Card", "DeviceProfile"],
                                        "e_type": ["FROM_DEVICE", "DEVICE_OF"]})
feat.runAlgorithm("tg_connected_components", params={...})
feat.runAlgorithm("tg_jaccard_nbor_ss", params={"source": card_id, "e_type": "MADE", "top_k": 10})
```

Louvain / connected components over Card–DeviceProfile finds **device rings** — this is the
HHG-014 story (the analyst-flagged shared-device case) and it's where the Innovation score
actually lives, per Devanshu's own words ("pattern learning without overfitting, and it's
explainable"). Needs a live TigerGraph connection — coordinate with Karan on timing, this
can't run until the graph is loaded.

### Task 1b — vector search over the closed-case notes

This is Task 2 below (case memory). Same thing Devanshu is describing — don't treat it as
separate work from the embeddings task you were already assigned.

---

## Task 2 — case memory retrieval (this one is not optional)

The agent must retrieve similar past cases and cite them. Three signals, blended:

```
score = 0.4 * semantic + 0.4 * structural + 0.2 * pattern_match

semantic   = 1 - cosine_distance/2        # embedding of analyst_notes
structural = min(1.0, shared_entities/3)  # shared card / device / region
pattern    = 1.0 if same pattern else 0
```

**The single most important detail in your whole workstream:**

> Retrieve the two pools **separately**. `top_3` from `confirmed_fraud` and `top_2` from
> `cleared`. Never merge then rank.

Why: the base rate is 5:1. A merged top-5 will almost always be five fraud cases, so the
agent only ever sees incriminating precedent and drifts toward blocking everything. The 900
cleared cases have notes explaining *why the alert was a false alarm* — that's exactly the
evidence that stops us blocking a legitimate customer. Surface it deliberately.

Embed the `analyst_notes` column. OpenAI `text-embedding-3-small` (1536-d) if we have a key,
else `all-MiniLM-L6-v2` (384-d) locally. Store as a vector attribute on the `ClosedCase`
vertex in TigerGraph (v4.2 supports this natively with an HNSW index) so retrieval is one
query instead of two round trips.

---

## Task 3 — read the undocumented-pattern notes by hand [COMPLETED by Bhavya]

Filter `closed_cases_history.csv` to rows where `pattern == 'undocumented'`.
**Status:** Completed on real dataset (all 9 cases analyzed).

### Findings & Mechanism Breakdown:
The 9 undocumented cases fall into two distinct operational fraud typologies:

1. **Anonymous Proxy Shared-Device Ring (`CC-2649`, `CC-2971`, `CC-2985`, `CC-3035`)**
   - **Notes:** *"The purchases came from a Samsung SM-G935F on Chrome for Android behind an anonymous proxy, a device never seen on this account. Two other cardholders reported the same device profile this month. Pattern not matched to a documented typology. Card blocked and reissued."*
   - **Mechanism:** Cross-card credential stuffing / testing leveraging device fingerprint spoofing and proxy rotation.
   - **Action Rule:** Cites R6 (shared origin across cards) and R9 (undocumented pattern).

2. **$500 Velocity Structuring / Authorization Limit Evasion (`CC-3748`, `CC-3841`, `CC-3907`, `CC-4086`, `CC-4124`)**
   - **Notes:** *"Cardholder reported four online purchases within forty minutes, each just under $500, none of which they made. Amounts appear chosen to stay under a $500 authorization threshold. Pattern not matched to a documented typology. Card blocked and reissued."*
   - **Mechanism:** Structuring transactions into ~$480–$495 bursts within short time windows (e.g. 40 minutes) specifically to evade automated fraud velocity holds that trigger at $500.
   - **Key Relevance for Exam Cases:** Look at **HHG-006** ($482.12 customer report) — this directly matches Pattern B!

These findings directly populate the `pattern: "undocumented"` and `pattern_description` fields for relevant exam cases.

**Re-verified against the real dataset on 2026-09-24** (this was written before real data
existed): pulled `analyst_notes` for all 9 real `undocumented` rows straight from
`data/closed_cases_history.csv`. Both mechanisms above are confirmed word-for-word in the
real notes, not hallucinated. Safe to keep exactly as written.

---

## Task 0 — `card_id` derivation was wrong on 10/20 real cases. Fixed.

Not part of your original scope, but it was the single highest-risk unverified assumption
in the whole pipeline (per `handover/06-decisions-and-gotchas.md`) and it directly touches
your case-memory retrieval, so it got fixed today rather than left for Karan to find later.

`src/graph/load.py`'s `derive_card_id()` ranked each customer's distinct `(card1..card6)`
tuples by **first-seen timestamp**. Checked against all 20 real `card_id` values in
`data/case_pack.csv`: **wrong on 10/20 (50%)**. It always promoted the customer's
heaviest-used card to `K1`, because that card naturally appears earliest — backwards.

Fixed to rank by **ascending transaction count** (the customer's *least*-used card tuple is
`K1`), ties broken by first-seen ts. Re-checked against all 20 real cases: **19/20 correct**.
One known exception is documented in the code comment (`HHG-006`/`C07297` — two
fully-populated card tuples close in count, ground truth goes the other direction; no rule
found yet reconciles both that case and the other 19). If you're deriving a card_id for a
customer and it lands in that shape (two tuples, no blank fields, counts within ~2x of each
other), don't trust the K-number — check `case_pack.csv` / `closed_cases_history.csv`
directly for that customer instead.

This matters for you specifically because `similar_cases()`'s structural-match signal
(shared card/device/region between the new case and a closed case) is keyed on `card_id` —
a wrong card_id would have silently broken structural matching on half the exam cases.

---

## Files you own

```
src/ml/features.py      # closed case -> feature vector
src/ml/train.py         # baseline + GNN, time-based split, calibration
src/ml/predict.py       # prior_probability()
src/ml/calibrate.py     # Platt / isotonic + reliability curve
notebooks/              # your exploration, anything goes in here
```

Don't edit anything outside `src/ml/` and `notebooks/` — Karan and Vaibhav are working in
the other directories at the same time.

---

## Getting started

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt   # or: uv sync (pyproject.toml/uv.lock already committed)
# GNN dropped (see Task 1 above) -- no torch/torch-geometric needed.
```

Data goes in `data/` (gitignored — the CSVs are ~700MB, never commit them).

First thing worth doing, before any modelling:

```python
import pandas as pd
cc = pd.read_csv('data/closed_cases_history.csv')
print(cc.outcome.value_counts())
print(cc.pattern.value_counts())
print(cc[cc.pattern == 'undocumented'].analyst_notes.tolist())   # read these
```

---

## API keys — do you need `.env.example`'s paid model fields filled in?

Checked `src/rag/embed.py` and `src/graph/schema.gsql` directly rather than guessing:

- `src/graph/schema.gsql` hardcodes `ClosedCase.notesEmb` and `PolicyChunk.textEmb` as
  `VECTOR ATTRIBUTE ... DIMENSION=1536`. That number is **not** read from config — it's a
  literal in the GSQL schema-change job.
- `src/rag/embed.py` auto-picks OpenAI `text-embedding-3-small` (1536-d) if
  `OPENAI_API_KEY` is set, otherwise silently falls back to local `sentence-transformers`
  `all-MiniLM-L6-v2` (**384-d**).

Those two facts collide: if you don't set `OPENAI_API_KEY`, the code will produce 384-d
vectors and try to upsert them into a 1536-d schema attribute — that fails at write time,
not at embed time, so you'd only find out after Karan's schema is already live. **This is
not a "pick whichever free API you like" situation** — the dimension is load-bearing.

**Decision: use `OPENAI_API_KEY` if there's any credit on the account, full stop.**
5,565 short `analyst_notes` rows at `text-embedding-3-small` pricing is on the order of a
few cents. Zero code changes, zero schema changes, matches what's already wired up.

If there's truly no OpenAI credit anywhere on the team, the fallback is **not** "pick a
different paid provider and point it at the same field" — Groq and OpenRouter are chat/LLM
endpoints, not confirmed to serve `text-embedding-3-small`-compatible embeddings at 1536-d.
The actual fallback already built into the code is local `sentence-transformers`
(384-d) — but then **someone has to change `DIMENSION=1536` to `DIMENSION=384` in both
lines of `src/graph/schema.gsql` before the schema is created**, and it has to happen
before Karan runs `scripts.setup_graph`, not after. Coordinate this with him explicitly;
don't just switch providers on your end and assume it'll work.

**Separately — the `tokens: 0` gap (SAR/summary prose, not embeddings):** this is a
different need with a different fix. Groq's free tier is fine here specifically because
it's OpenAI-API-compatible — the `openai` package already in `pyproject.toml` works against
it with just a `base_url` override, no new dependency. This is Vaibhav's/whoever wires the
narrative generator's call to make, not yours, and it must never touch verdict/action/
probability logic — prose only.

---

## If you're short on time

Cut in this order:
1. The calibrated baseline model entirely (`prior_probability` returning `None` is fine —
   the ledger already handles that gracefully)
2. Fancy features on the baseline, if you keep it at all

**Don't cut:** the two-pool retrieval, the graph algorithms (Louvain/connected-components
for device rings — this is Devanshu's own stated Innovation angle), or the undocumented
notes (already done, just don't delete it). Those are the ones tied to actual scored
criteria and to what the judge explicitly said he wants to see.

## Order of operations, today

1. Coordinate with Karan: is Savanna up yet? `src/agent/deps.py`'s `offline_deps()` only
   reads pre-fabricated JSON fixtures — there is no path from real CSVs to real answer
   files without a live TigerGraph connection. This blocks everything below.
2. Decide the embedding provider (above) *before* Karan runs `scripts.setup_graph` — the
   vector dimension is baked into the schema at creation time.
3. Once the graph is loaded: run `embed_closed_cases()`, upsert into `ClosedCase.notesEmb`.
4. Run the Louvain/connected-components featurizer calls (Task 1a) over Card–DeviceProfile,
   confirm `device_neighbors`-style queries surface real rings (this is the HHG-014 proof).
5. Only then, if time remains: the calibrated baseline model.
