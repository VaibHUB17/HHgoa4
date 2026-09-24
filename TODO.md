# TODO — what is left, and where

Branch `regen-agentic-live`. Deadline 30 Sept (extended). Repo state at the last commit:

```
194 tests passing
20/20 answer files valid — 0 validator violations
verdicts: 9 legitimate · 10 uncertain · 1 fraud
14/20 cases carry an llm_decision evidence ref
```

Run `python -m scripts.finish_run` to exercise the whole pipeline and re-check all of it
in one command.

---

## 🔴 P0 — before submitting

### 1. Wire the investigation loop into the pipeline
**File:** `src/agent/investigator.py` (built), `src/agent/deps.py` (wiring)

The loop exists — assess → plan → execute → integrate, with the model choosing the next
query from what it has found and deciding when the evidence is enough. It is **not yet
wired into the default run**. `agentic_deps` still uses the shallow single-decision path.

This is the difference between "the LLM can reason over the graph" and "the LLM does
reason over the graph" in the twenty files a judge reads. Directly addresses the stated
requirement for *actual ai reasoning, not deterministic hardcoded reasoning*.

**Check when done:** the evidence trail on a regenerated case should show a multi-step
decision sequence, not one yes/no.

### 2. Demo video (3–5 min) — not recorded
**File:** `docs/DEMO_SCRIPT.md` — beat-by-beat with spoken narration, ready to use.

Order matters: open on a **legitimate** case being correctly cleared (every other team will
open with a dramatic block), then the before/after recommendation change, then HHG-014's
device ring with the live `tg_wcc` query, then the undocumented pattern, then the approval
gate, then the SAR.

**Before recording:** resume the Savanna workspace ten minutes early (suspends after 60
min idle, takes 1–2 min to wake), confirm `cases/` holds real output, check the UI banner
does not say "Fixture data".

### 3. Publish blog + social
**Files:** `docs/BLOG.md`, `docs/SOCIAL.md`

Both drafted. Search for **`[VERIFY]`** — eleven figures are tagged because they were
written while the policy fixes were still landing. Re-run the numbers before publishing:

```bash
python -c "
import json,glob,collections
v=collections.Counter(); llm=sar=chg=0; tok=0; pri=set()
for f in glob.glob('cases/*.json'):
    a=json.load(open(f,encoding='utf-8')); c=a['case']
    v[c['verdict']]+=1; tok+=a.get('tokens',0); pri.update(c['similar_prior_cases'])
    if any('llm_decision' in e.get('ref','') for e in c['evidence']): llm+=1
    if a['sar']['file']: sar+=1
    if a['next_best_actions']['initial']!=a['next_best_actions']['final']: chg+=1
print(dict(v), f'llm={llm}/20 sar={sar} changed={chg}/20 tokens={tok} priors={len(pri)}')"
```

Social must tag **@TigerGraphDB**.

### 4. UI check in a real browser — never done
**Files:** `ui/`

The console builds, typechecks, and serves, but **no human has looked at it**. There is no
browser tooling in this environment, so responsive layout at 390 / 768 / 1440 px is
unverified. The graph explorer and policy sandbox are the likely trouble spots.

```bash
cd ui && npm install && npm run dev    # http://localhost:3000
```

---

## 🟠 P1 — worth doing, not blocking

### 5. `google-genai` is missing from requirements
**File:** `requirements.txt`

`GEMINI_API_KEY` was set but the SDK was not installed, so `embed_query()` raised and
precedent retrieval silently fell back to something cruder — returning confirmed-fraud
neighbours where cleared ones belonged. HHG-003 flipped from `legitimate` (p=0.001,
matching cleared case CC-1589) to `uncertain` (p=0.169, matching confirmed-fraud CC-2935)
on that alone.

A failure that degrades quietly instead of erroring is the dangerous kind. Add the
dependency so nobody rediscovers this at 2am.

### 6. Three detectors are burst-only by design — decide whether to say so
**File:** `src/detectors/patterns.py`

`detect_cnp_burst`, `detect_out_of_region` and `detect_account_takeover` require
multi-transaction bursts, but most real fraud in this dataset is a single transaction:

```
card_not_present_fraud      68.7% are single-transaction   (n=1404)
out_of_region_use           54.7%                          (n=955)
account_takeover            47.9%                          (n=1205)
```

Single-transaction paths were investigated and **deliberately not built**. Probing the
labelled closed cases against `data/transactions.csv` found no discriminator that
separates single-transaction fraud from legitimate activity:

- product-category mismatch: 8% in confirmed fraud vs 12.6% in cleared — inverted, no signal
- `addr1` outside historical set: ~50/50 both ways; it behaves like a merchant billing
  region, not a stable home address
- `risk_score`: fraud mean 0.47, cleared mean 0.88 — cleared cases score *higher*

The pattern label on those cases is not recoverable from the transaction columns. Inventing
a discriminator would cost more on the legitimate half than it could win, and the brief
warns explicitly against over-blocking.

**Decision needed:** either state this openly in the blog as a limitation (defensible, and
honest limitations read well), or accept a weaker discriminator knowing the false-positive
cost. Do not quietly ship a guess.

### 7. Consequence of (6): pattern output is skewed
Every non-legitimate case returns `card_not_present_new_device`, because that detector
needs only `id_15 == 'New'` on one transaction while the others need bursts.

```
historical base rate        our 20 cases
CNP fraud        30.1%      none                        9
account takeover 25.8%      card_not_present_new_device 10
new device       23.1%      undocumented                1
out of region    20.5%
```

Resolves itself if (6) is resolved. Pattern correctness is scored.

---

## ✅ Done today

| | |
|---|---|
| Validator passed contradictory files | Now checks `evidence_requests` against each rule citation structurally. Surfaced 3 defect classes; 28 → 0 violations |
| Customer report treated as a denial | 6 cases recommended blocking a card on someone who never replied. Report is now a dispute, not a denial |
| 7 cases cited R3 with no customer contact | Citations corrected |
| Second undocumented pattern missed | Proxy device ring (CC-2649/2971/2985/3035) now detected. Finding an undocumented pattern is scored |
| Exonerating signals under-used | All 900 cleared cases mined: 80% travel, 18% new phone, 3% isolated amount. Three detectors with negative weights |
| Embeddings silently broken | Diagnosed and fixed; see (5) |
| Savanna outage crashed the run | Connection opened outside its own guard; now degrades |
| HHG-014 filed a SAR on an `uncertain` verdict | §3a forbids it; verdict now follows the evidence |
| "Agentic" mode was theatre | Asked the LLM which tools to query, discarded the answer, ran the deterministic path |
| UI was a generic dark dashboard | Rebuilt: force-directed ring explorer, scrubbable replay, policy sandbox matching the Python to 4 decimal places, rule trace, precedent panel |

Tests 132 → 194.

---

## Where things live

```
docs/HANDOVER_TO_VAIBHAV.md   full narrative, all findings with evidence
docs/REGEN_REVIEW.md          the regeneration run and what changed
docs/BLOG.md                  drafted, [VERIFY] tags on 6 figures
docs/DEMO_SCRIPT.md           drafted, [VERIFY] tags on 4
docs/SOCIAL.md                drafted, [VERIFY] on 1
handover/                     7-part onboarding, written earlier
scripts/finish_run.py         one command: wake, verify, regenerate, validate, report
src/agent/investigator.py     the loop — built, needs wiring (P0 #1)
```

---

## Do not submit until

- [ ] `python -m src.answer.validator cases/ --strict` is clean
- [ ] Repo is public (check in an incognito window)
- [ ] Demo video, blog and social links all resolve for a logged-out visitor
- [ ] Deadline extension confirmed **in writing** — the form is **no-resubmission**, and
      every doc in this repo still carried 24 Sept until today

One person submits, after the other two confirm all four links.
