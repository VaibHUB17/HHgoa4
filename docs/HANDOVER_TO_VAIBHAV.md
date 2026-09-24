# Handover — 24 Sept, branch `regen-agentic-live`

Written for Vaibhav. Answers your three questions, lists every defect found, and says
exactly what is left. Deadline is now 30 Sept.

---

## 1. Is the pipeline working end to end?

**Yes.** Live against Savanna with the real dataset:

| | |
|---|---|
| Transaction | 590,742 |
| Card | 14,780 |
| Customer | 13,553 |
| DeviceProfile | 9,704 |
| ClosedCase | 5,565 |
| PolicyChunk | 56 |

6/6 GSQL queries installed, MCP routing works, `tg_wcc` community detection runs, 20
answer files generate. Your P0 load is correct.

One operational note: the workspace suspends after 60 minutes idle. Auto Resume is now on,
but it still takes 1–2 minutes to wake. `src/graph/connection.py` handles this — it detects
the suspend response, waits, and retries rather than failing the whole batch.

## 2. Deterministic or agentic?

**Honestly: still mostly deterministic.** I am not going to dress this up.

| Layer | Today |
|---|---|
| Which graph queries run | Fixed sequence |
| Pattern detection | Deterministic thresholds |
| Probability | Weighted ledger, `sigmoid(-1.8 + 4.1 · Σw)` |
| Action selection | R1–R10 rule engine |
| Approval routing | Lookup on action + exposure |
| Prose (summaries, SAR) | LLM (Groq) |
| Whether to widen the search | LLM — but one shallow yes/no |

The LLM decides *where to look* and writes prose. The policy decides *what to do*. That
boundary is deliberate and worth keeping — the rubric rewards operating within a defined
policy, and a model that picks actions is unauditable.

What is **not** yet true is the depth you asked for. `src/agent/investigator.py` is being
built to replace the single yes/no with a real assess → plan → execute → integrate loop
where the model chooses the next query from what it has found, follows the chain two and
three hops out, and decides for itself when the evidence is sufficient. Also a guarded path
for LLM-generated GSQL through MCP (read-only, statement allowlist, row cap, every
generated query logged into the evidence trail).

I told that agent explicitly: **no hardcoded fallback.** If the LLM is unavailable the run
must surface `llm_available=False` rather than quietly running a fixed sequence and
claiming it was agentic.

## 3. What is left

### 🔴 Defect 1 — detectors require bursts, but most real fraud is a single transaction

The most damaging finding of the day. Measured across all 4,665 confirmed-fraud closed
cases:

```
pattern                        median n_txns   % exactly 1 txn
card_not_present_fraud              1.0             68.7%   (n=1404)
out_of_region_use                   1.0             54.7%   (n=955)
account_takeover                    2.0             47.9%   (n=1205)
card_not_present_new_device         2.0             45.9%   (n=1076)
card_testing                       17.0              0.0%   (n=16)
undocumented                        4.0              0.0%   (n=9)
```

Pulled the rows to confirm at ground level:
- CC-0001 (`card_not_present_fraud`): one txn, $155.43, ProductCD C, online
- CC-0008 (`account_takeover`): one txn, $49.04, ProductCD W, in_person
- CC-0002 (`out_of_region_use`): one txn, $117.05, addr1=476.0, in_person

Our thresholds: `cnp_burst` needs 2–4 purchases in 48h, `out_of_region` needs multi-day
regional activity, `account_takeover` needs 2+ cards breaking together. **None can fire on
a single transaction**, so three of five detectors are structurally unable to detect the
majority of the fraud they are named after.

Consequence: every non-legitimate case collapses to `card_not_present_new_device`, which
needs only `id_15 == 'New'` on one transaction.

```
historical base rate          our 20 cases
CNP fraud          30.1%      none                        10
account takeover   25.8%      card_not_present_new_device  9
new device         23.1%      undocumented                 1
out of region      20.5%
```

`card_testing` (median 17 txns) and the structuring pattern (median 4) are correctly
burst-shaped — do not touch those thresholds.

**Fix in progress:** single-transaction paths alongside the burst paths, calibrated against
the 1,404 / 955 / 1,205 labelled examples rather than by intuition.

### 🔴 Defect 2 — rule citations do not match the recorded evidence

Three distinct bugs, found by the hardened validator. **24 violations across 14 of 20
files.**

**2a. R2 cited on a no-reply** — 6 cases: HHG-003, 004, 008, 009, 011, 016.
R2 is "customer denies". The recorded `assumed_response` is *"No reply received from the
customer within the 24-hour window."* That is R4, which produces MONITOR_CARD +
DECLINE_TRANSACTION. HHG-004 and HHG-016 recommend **BLOCK_CARD**; HHG-006 also files a
SAR. Blocking a card because someone did not answer the phone is a policy breach and
exactly the over-blocking the brief warns about.

Root cause, `src/agent/nodes.py` ~line 100:
```python
"_customer_response": "deny" if reported else None,
```
Any `customer_report` trigger is treated as a confirmed denial from the first node. Nothing
resets it when the real reply arrives, so R2 fires and R4 never gets a chance. **A customer
reporting a charge is a dispute, not a denial under validation.** The policy engine itself
is correct — `rule_r2` properly requires `customer_response == "deny"`. The bug is upstream.

**2b. R3 cited with no customer contact at all** — 7 cases: HHG-001, 005, 007, 010, 012,
017, 019. All close as legitimate citing R3 ("customer confirms"), but
`evidence_requests` is empty. They were closed on graph evidence alone. The verdict may
well be right; the citation is not.

**2c. Spurious R2 alongside R7** — 5 cases cite `"R2, R7"` on CREATE_CASE where the
response was a no-reply. R7 alone justifies it; the R2 citation is wrong.

### 🟠 Defect 3 — a second undocumented pattern was never built

The 9 `undocumented` analyst notes contain **two** distinct mechanisms, not one:

1. **Threshold structuring** (CC-3748, 3841, 3907, 4086, 4124) — four purchases in forty
   minutes, each just under a $500 authorisation ceiling. ✅ detector exists.
2. **Proxy device ring** (CC-2649, 2971, 2985, 3035) — ❌ **no detector.** Samsung
   SM-G935F, Chrome for Android, **behind an anonymous proxy**, device never seen on the
   account, and *two other cardholders independently reported the same device profile that
   month*.

The second is not plain `card_not_present_new_device` — the undocumented element is proxy
concealment combined with independent corroboration from unrelated cardholders. Relevant to
HHG-014, which involves a Samsung SM-G935F across 17 cards. Finding an undocumented pattern
is explicitly scored.

### 🟠 Defect 4 — exonerating signals under-used

All 900 cleared cases are risk-score false positives. Three mechanisms:

```
716x (80%)  cardholder confirmed TRAVEL to the billing region
158x (18%)  cardholder confirmed the purchase from a NEW PHONE
 26x ( 3%)  amount unusual but consistent with stated intent
```

Travel is the single largest false-positive source in the dataset, which is why
`detect_out_of_region`'s concurrency discriminator matters so much: a clone cannot be in
two places, a trip is a clean sequential move. And 158 cleared cases are literally "new
phone" — more reason `new_device_marker` (+0.15) must never be sufficient alone.

Exonerating detectors are being added with negative weights proportional to those shares.

---

## What I fixed today

- **The "agentic" mode was theatre** — it asked the LLM which tools to query, **discarded
  the answer**, and ran the deterministic path. Now the decision fires a real `tg_wcc`
  query and its reasoning is recorded as evidence with an `llm_decision:` ref.
- **HHG-014 filed a SAR while calling the verdict `uncertain`** — §3a forbids that.
- **Embeddings were silently broken.** `GEMINI_API_KEY` was set but `google-genai` was not
  installed, so `embed_query()` raised and precedent retrieval fell back to something
  cruder, returning confirmed-fraud neighbours where cleared ones belonged. HHG-003 flipped
  from `legitimate` (p=0.001, cleared case CC-1589) to `uncertain` (p=0.169, confirmed
  fraud CC-2935) on that alone. **`google-genai` needs to go in `requirements.txt`** — a
  failure that degrades quietly instead of erroring is the dangerous kind.
- **A Savanna outage crashed the whole investigation** — connection opened outside its own
  try/except.
- **The validator passed contradictory files.** It grepped prose for "denial"; now it
  checks `evidence_requests[].assumed_response` structurally and cross-references every
  rule citation. That is what surfaced defects 2a–2c.
- Whole UI rebuilt and made interactive (force-directed ring explorer, scrubbable replay,
  policy sandbox verified matching the Python to four decimal places, rule trace, precedent
  panel).

Tests: 132 → 159 and rising.

---

## Suggested order from here

1. **`nodes.py` dispute-vs-denial** (defect 2a) — smallest diff, clears 6 cases
2. **Single-transaction detector paths** (defect 1) — largest accuracy gain
3. **R3 citation** (defect 2b) — 7 cases, probably a citation fix not a verdict change
4. **Proxy device ring detector** (defect 3) — scored
5. Regenerate, then `python -m src.answer.validator cases/ --strict` must be clean
6. Demo video, blog numbers, social

`python -m scripts.finish_run` runs the whole pipeline and re-checks all of this in one
command.

**Do not submit** until the validator is clean and the extension is confirmed in writing —
the form is no-resubmission.
