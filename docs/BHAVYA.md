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

## Task 1 — the GNN / classifier

You wanted to train a GNN on this. Go ahead. Two honest notes before you start:

- **There is no ML criterion in the rubric.** It scores investigation accuracy, next-best
  action, explainability, agentic design, innovation, demo. A model helps only insofar as it
  makes the *probability* better calibrated, which feeds accuracy.
- **Calibration matters more than accuracy here.** The answer file has a
  `fraud_probability` field and the README says it's "scored for calibration." A model that
  is 85% accurate but always outputs 0.95 or 0.05 scores *worse* than one that's 80%
  accurate and honestly says 0.6 when it's unsure. So: fit the model, then
  **Platt-scale or isotonic-calibrate it on a held-out split**, and check a reliability
  curve. That calibration step is the part that actually earns marks.

Suggested order — ship the simple one first, then upgrade:

1. **Baseline (do this first, it takes an hour).** Logistic regression or gradient boosting
   on per-case features: exposure, n_txns, time span, count of connected cards, channel mix,
   whether a device profile is shared, region diversity. Calibrate it. This alone is a
   usable `prior_probability()`.
2. **Then the GNN, if the baseline is done and checkpoints are green.** Build a per-case
   subgraph (Customer / Card / Transaction / DeviceProfile / BillingRegion) and train a
   GraphSAGE or GAT node/graph classifier over the closed cases. PyTorch Geometric or DGL.
   The genuine advantage over the baseline is that it sees *structure* — a card two hops
   from a known-fraud device — which flat features can't express.

**Important split rule:** the closed cases run July–October, the exam cases November–December.
Split your train/validation **by time**, not randomly. A random split leaks future
information and will make your validation score look far better than reality. The original
Kaggle competition had exactly this trap and it's mirrored here deliberately.

**Watch the class imbalance:** 4,665 vs 900 is roughly 5:1. Don't let the model learn
"always say fraud" — that's the exact failure mode that loses this hackathon, since half the
exam cases are legitimate. Report precision/recall on the *cleared* class specifically, not
just overall accuracy.

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
pip install pandas scikit-learn matplotlib
# later, for the GNN:
pip install torch torch-geometric
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

## If you're short on time

Cut in this order:
1. The GNN (keep the calibrated baseline)
2. Fancy features (exposure + n_txns + shared-device count gets most of the signal)

**Don't cut:** the two-pool retrieval, the calibration step, or reading the undocumented
notes. Those three are the ones tied to actual scored criteria.
