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
