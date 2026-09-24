# 9. Reasoning audit — what is LLM, what is deterministic, what was hardcoded

Bhavya asked for this directly: *"what has been llm generated vs deterministic"*, and
*"nothing hardcoded except routing graph queries"*. This is the honest accounting,
including the things that were wrong when I looked.

Written 24 Sept after reviewing the live-run commits.

---

## The short answer

| Layer | Who decides | Why that way |
|---|---|---|
| Which graph queries run | **Deterministic**, with an LLM expansion decision | Four core queries always run; the model decides whether to widen to the shared-device neighbourhood |
| Pattern detection | **Deterministic** | Thresholds come from the policy (R5's "3+ under $5 within an hour"). A model guessing at these is less defensible, not more |
| Fraud probability | **Deterministic** | A weighted ledger in a config file. When a judge asks where 0.86 came from, we open `config/evidence_weights.yaml` |
| Which action to take | **Deterministic** | R1–R10 as predicates. The policy is the spec; an LLM paraphrasing it would be worse |
| Approval route | **Deterministic** | A lookup on action and exposure |
| Case summary prose | **LLM** (Groq, Qwen) | Genuine language work |
| SAR narrative | **LLM**, re-validated | Model writes it; every ID is checked against the inputs afterwards |
| Whether to widen the investigation | **LLM** | See below |

The split is deliberate: **the LLM writes and decides where to look; the policy decides
what to do.** An LLM that picks actions is unauditable, and the rubric explicitly rewards
operating within a defined policy.

---

## What was wrong, and what I changed

### 1. The verdict contradicted the actions (fixed)

The live run filed a SAR on HHG-014 while reporting the verdict as `uncertain`.

The case found a **17-card shared-device ring confirmed by `tg_wcc` community detection**,
cited R6 and FinCEN, and recommended `BLOCK_CARD` + `FILE_REPORT`. The probability was
0.8436 — just under the 0.85 band — so the verdict came out `uncertain`.

Policy §3a permits a SAR only when fraud is *"confirmed or strongly suspected."* Filing one
on a case we call uncertain is indefensible on its own terms, and a judge reading that JSON
would spot it immediately.

The root cause: the verdict was derived purely from probability bands. Those bands come
from §6, which governs **when to stop investigating** — they were never a verdict rule.

**Fix** (`src/agent/run.py:_resolve_verdict`): when the agent has both committed to an
irreversible action *and* holds corroboration from more than one independent source, the
verdict follows the evidence. A high score on a single weak signal still reads `uncertain`
— that is the honest answer and is explicitly creditable.

HHG-014 → `fraud`. HHG-016 (one new-device signal at p=0.51) correctly stays `uncertain`.

### 2. The "agentic" mode was cosmetic (fixed)

`agentic_deps()` asked the model to plan which TigerGraph tools to query — then
**discarded the reply** and ran the identical deterministic path. It spent tokens and
inflated `tool_calls` while changing nothing.

This is exactly what Bhavya warned against, and it is worse than not calling an LLM at all:
a reviewer reading that code sees theatre.

**Fix** (`src/agent/deps.py`): the deterministic sweep runs first, then the model decides
whether the findings warrant widening to the shared-device neighbourhood. A `YES` triggers
a real `tg_wcc` query and the model's reasoning is recorded as evidence with a
`llm_decision:` ref, so it is auditable.

The model can only **add** evidence, never suppress it — every detector has already run.
Worst case for a bad answer is one wasted query.

### 3. A Savanna outage crashed the investigation (fixed)

`analyze_device_ring_community()` opened its connection *outside* its own try/except, so a
suspended or out-of-credit workspace raised before the guard. The function's docstring
promised graceful degradation; it did the opposite.

Verified against the real failure — the workspace is down right now, and the function
returns `executed: False` with the reason logged instead of crashing.

### 4. Two tests asserted against impossible conditions (fixed)

One passed a token budget both blocks already fit inside, so it tested a no-op. The other
required the gitignored dataset and failed on any clean checkout. Fixed and skipped
respectively.

---

## Are we hardcoding?

Honestly assessed, rule by rule:

**Not hardcoded — these are the specification.** R1–R10, the 14 action names, the approval
routes, the $2,500 and $1,000 thresholds. These are quoted from the brief. Having an LLM
re-derive them would introduce drift against the thing we are graded on.

**Not hardcoded — these are tunable config.** Evidence weights, the sigmoid constants, the
detector thresholds. All in `config/*.yaml` or named module constants. Changing behaviour
is a YAML edit, which is also what makes the policy auditable.

**Defensible interpretation, documented.** R5 says "materially larger purchase" with no
figure; we use 3× the largest test authorisation. R6 says "one window"; we use 7 days.
These are judgement calls, named as such in
[06-decisions-and-gotchas.md](06-decisions-and-gotchas.md).

**Was genuinely wrong, now fixed.** The discarded-LLM-plan call, and the verdict derived
from bands alone.

---

## Did we use closed_cases_history.csv for pattern insight?

Partly, and this is the weakest part of the submission.

**What we do:** all 5,565 closed cases are retrieved as memory. `analyst_notes` are
embedded, and retrieval pulls **two separate pools** — top 3 `confirmed_fraud` and top 2
`cleared` — so exonerating precedent survives the 5:1 base rate instead of being buried.
Every live case cites at least 5 prior cases; HHG-006 cites 10.

**What we have not done:** nobody has read the `analyst_notes` on the rows where
`pattern == 'undocumented'`. The brief says to read those carefully, and finding an
undocumented pattern is explicitly scored. The mechanism is described in those notes in a
human's own words, and that needs a person reading them, not a model.

`python notebooks/explore_closed_cases.py` prints them. It is the highest value-per-hour
task remaining.

---

## Current live-run results

20 answer files, 0 validator violations.

Before the verdict fix: fraud=1, legitimate=10, uncertain=9.
HHG-014 moves to `fraud` on regeneration, and the two verdict/action contradictions clear.

Nine `uncertain` verdicts is defensible — the dataset is built so that roughly half the
cases are legitimate and several are deliberately ambiguous — but it is worth a second look
once the workspace is back, because `uncertain` is also what a system produces when it is
not finding enough evidence.

---

## Blocked right now

**The Savanna workspace is down.** Every endpoint returns HTTP 500, which matches the
credit exhaustion reported in the group chat. Until it is resumed:

- The 20 answer files cannot be regenerated with the verdict fix
- No live GSQL can be tested
- The demo cannot be recorded against live data

The offline path still runs end to end, so it is the fallback if the workspace does not
come back before the deadline.
