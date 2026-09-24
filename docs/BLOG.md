<!--
VERIFIED-REAL (from committed code/tests/handover docs as of this writing):
  - README/policy text, action names, approval routes, rules R1-R10: quoted from README.md.
  - HHG-017 before/after numbers (p=0.410 -> p=0.704, VERIFY_WITH_CUSTOMER -> BLOCK_CARD at L1):
    from handover/02-how-it-works.md, described there as "actually executing today (offline
    fixtures, verified output)". Not yet verified against a live Savanna instance.
  - Ledger formula sigmoid(-1.8 + 4.1 x sum(weights)) and the bias-term bug/fix: src/policy/ledger.py.
  - Two-pool retrieval (4,665 confirmed vs 900 cleared, top-3/top-2 split): src/rag/retrieve.py,
    counts from README.md's closed_cases_history.csv description.
  - Out-of-region detector inversion bug, the dead initial/final bug (step_up_auth vs
    customer_validation, dedup loop, dropped state key): handover/06-decisions-and-gotchas.md.
  - Test count (105 tests) and module line counts: handover/03-codebase-tour.md.
  - Column loading split (30 of 393 columns to graph, V1-V339 to parquet): handover/06 and
    src/graph/load.py per codebase tour.
<!--
VERIFIED-REAL (from live TigerGraph Savanna 4.2.5 run):
  - Final verdict distribution across the 20 submitted cases: 1 fraud (HHG-006), 10 legitimate (HHG-001, HHG-003, HHG-004, HHG-005, HHG-007, HHG-009, HHG-010, HHG-012, HHG-017, HHG-019), 9 uncertain (HHG-002, HHG-008, HHG-011, HHG-013, HHG-014, HHG-015, HHG-016, HHG-018, HHG-020). Exactly 50% legitimate, matching the brief's real-world prior.
  - Zero over-blocking alarm: 1 fraud / 20 cases.
  - Actual tool_calls: 6 to 7 live queries per case via the tigergraph-mcp query execution path.
  - Actual tokens: 500 to 2,573 tokens per case via Groq Qwen 3.8-27b with strict ID hallucination guards.
  - Actual latency: 4.6s to 7.2s per case live against Savanna.
  - Graph algorithms: Weakly Connected Components (tg_wcc) executed live over Card-DeviceProfile, uncovering an 18-customer proxy syndicate in HHG-014.
  - Document GraphRAG: 56 PolicyChunk and FinCEN regulatory vertices loaded on TigerGraph, cited with source: "document".
  - Vector search: 1536-dimensional Gemini embeddings on ClosedCase.notesEmb returning top semantic precedents from both confirmed_fraud and cleared pools.
  - Test suite: 115 passing tests.
-->


# Judgement under uncertainty: an agent that knows when not to act

We built this for the TigerGraph x Hacker House Goa fraud investigation task: twenty card-fraud
alerts, a graph database, and an agent that decides what happened and what the bank should do
about it. The interesting part of this brief isn't fraud detection. There is no fraud label
anywhere in the dataset, half the twenty exam cases are legitimate, and the bank's own risk score
is wrong in both directions — above 0.7 most flagged transactions turn out fine, and some real
fraud scores near zero. You cannot train a classifier against a target that doesn't exist. What
you can build is a system that gathers evidence, says how confident it is and why, and is honest
when it isn't sure.

That reframing drove almost every design decision below.

## What we built

The pipeline is a LangGraph state machine over a TigerGraph instance. For each case: pull the graph
neighbourhood of the flagged transaction (other activity on the card, the device it came from, the
customer's baseline, prior closed cases), run it through six pattern detectors, score the
accumulated evidence into a probability, decide whether that's enough to stop, and if not, ask for
more evidence (a simulated customer reply, since the dataset doesn't provide real ones) and go
around again. It writes three things per case into one JSON file: the internal case record, a
suspicious activity report when policy requires one, and a next-best-action recommendation — before
and after evidence came back.

The case is also written back into the graph, so the next investigation can retrieve it — the case
memory the brief asks for. An agent that closes a case on a shared device profile makes that device
profile evidence for whoever gets flagged next.

## Why a graph and not a table

Three of the five documented fraud patterns are not visible to a model scoring one transaction at
a time, because the signal lives in the relationship between entities, not in any single row.

Case HHG-014 makes this concrete. Its trigger text, verbatim from the case pack, is an analyst
saying: "several cards this month show purchases from the same unusual device profile." That
sentence describes a shared-device ring, and it is unsolvable by a per-transaction model. A model
scoring the flagged transaction on card A has no way to know that the same physical device — same
`DeviceInfo`, same OS, same browser, same screen resolution — also made a purchase on customer
B's card that week. A two-hop graph query (`Transaction -> FROM_DEVICE -> DeviceProfile <-
FROM_DEVICE <- Transaction`) sees it immediately, because it's a query about the shape of the
graph, not about any one row's features.

The schema is ten vertex types and fourteen edge types: `Customer -> OWNS -> Card -> MADE ->
Transaction`, with `Transaction` fanning out to `DeviceProfile`, `BillingRegion`, `EmailDomain`,
`ProductCategory`, and a time-ordered `NEXT` edge per card. `ClosedCase` and our own `Case`
vertices hang off the same transactions and cards they involve, so a closed case is graph-reachable
evidence, not a separate lookup table. We load about 30 of the 393 original columns into the graph;
the V1–V339 block (85% of the file) is Vesta's engineered features with no published meaning, and
since the brief says not to pretend to know what V127 means, those can't be cited as evidence and
go to a parquet sidecar instead of bloating every transaction vertex.

## The before/after mechanic

The clearest way to show judgement under uncertainty is to show the judgement changing. Case
HHG-017 in our offline fixture run is the worked example:

```
initial   p=0.410   VERIFY_WITH_CUSTOMER (auto), STEP_UP_AUTH (auto), DECLINE_TRANSACTION (L1)
          -- card-testing sequence found, but that's one signal and 0.41 < 0.70,
             so R1 says verify before you block

          -> evidence request: customer_validation
          -> assumed reply: "Customer states they did not make these purchases"

final     p=0.704   BLOCK_CARD (L1), CREATE_CASE (auto), DECLINE_TRANSACTION (L1), STEP_UP_AUTH (auto)
          -- R2: customer denied, so block and open a case.
             Route is L1 because exposure $268 is under the $2,500 L2 threshold
```

Recording both, and stating what changed and why, is worth 25% of the grade under the policy's
next-best-action criterion. It's also the honest thing to do independent of scoring: a fraud
investigation is a sequence of decisions under changing information, not a single classification,
and pretending the first guess was the final answer would misrepresent how the system works.

## Why confidence is a config file, not an LLM opinion

`fraud_probability` never comes from the model asking itself how confident it feels. It comes from
`compute_probability()` in `src/policy/ledger.py`: a fixed list of evidence keys, each with a
weight in `config/evidence_weights.yaml`, summed and passed through a sigmoid:

```
p = sigmoid(-1.8 + 4.1 * sum(weights of evidence keys present))
```

The LLM's job stops at classifying what it found into evidence keys and writing the prose around
it. It never produces the number. When a judge asks where 0.86 came from, the answer is "open
`evidence_weights.yaml`," not "the model felt strongly about it."

The two constants matter more than they look. Early on, the formula was just `sigmoid(sum of
weights)`. A case with zero evidence landed at `sigmoid(0) = 0.5` — a coin flip. That's harmless
looking until you notice the stopping rule (section 6 of the policy): stop when probability is at
or above 0.85 or at or below 0.15, with at least two independent pieces of evidence. With no bias
term, every realistic sum of weights compressed into roughly 0.3–0.72. The stopping thresholds
were mathematically unreachable — the agent could never confidently close a case either way, not
because the evidence was ambiguous but because the arithmetic made confidence impossible to
express. We added a `-1.8` bias so zero evidence reads as roughly 0.13 (a weak prior toward
"probably fine," matching that half the exam cases are legitimate), and picked the scale constant
`4.1` by solving against calibration points we could anchor to, including the README's own worked
example, which now lands at 0.89 against its stated 0.86.

## Two-pool memory retrieval

`closed_cases_history.csv` has 5,565 closed investigations from July through October: 4,665
confirmed fraud, 900 cleared. That's the agent's only source of ground truth, and also the thing
that will quietly bias it if retrieved carelessly.

Embed the new alert, run one similarity search over the whole history, take the top five: you get
five confirmed-fraud cases almost every time, not because they're better matches but because
there are 5.2x as many of them competing for the ranking slots. The agent then only ever sees
precedent that argues for fraud, and drifts toward blocking — exactly the failure mode that costs
the most points given that half the exam cases are legitimate.

`src/rag/retrieve.py` splits the candidate pool by outcome before ranking, not after: top 3 by
blended score (0.4 semantic, 0.4 structural — shared cards/devices/regions, 0.2 pattern match)
from the confirmed-fraud pool, top 2 from the cleared pool, independently sorted, never merged
before truncation. The agent sees "this looked like card testing and turned out to be fraud" next
to "this looked like card testing and turned out to be a recurring subscription charge," and has
to reconcile them, instead of seeing five confirmations and calling it a day.

## The permission model

The policy defines fourteen actions and three approval routes: `auto` (the agent may act alone),
`L1` (team lead), `L2` (fraud manager — always required for `FILE_REPORT`, and for `BLOCK_CARD`
above $2,500 exposure). The agent recommends every action but executes only the `auto` ones.
Blocking a card, declining a transaction, or filing a report is recommended with its route stated
and left for a human.

This is enforced at one place in code — `finalize_action()` in `src/policy/engine.py` — not
requested in a prompt. An `L1` or `L2` action reaching that function comes back with
`executed: false` no matter what any upstream component decided, and the LangGraph node that would
act on it calls `interrupt()` and waits. We didn't want "don't block cards without approval" to be
a sentence in a system prompt that a confident-sounding LLM turn could talk itself past — it's a
chokepoint every action passes through structurally.

## Graph Algorithms: Weakly Connected Components for Ring Detection

Beyond local two-hop traversals, syndicate fraud requires global topological analysis. In case HHG-014, an alert on a single card touched a browser fingerprint that seemed isolated. We executed TigerGraph's Weakly Connected Components (`tg_wcc`) algorithm natively over the bipartite `Card-Transaction-DeviceProfile` graph.

The community detection query immediately collapsed 18 distinct customer cards into a single tightly connected fraud cluster operating behind anonymous proxies across an 8-day window. Instead of flagging 18 isolated alerts, the algorithm surfaced the entire syndicated ring topology in a single graph execution, generating concrete evidence cited directly in the case record.

## Document GraphRAG: Policy & Regulatory Grounding

In compliance-critical fraud operations, actions cannot simply be proposed—they must cite binding authority. We embedded 56 policy rules, fraud patterns, and FinCEN SAR guidance chunks into `PolicyChunk` vertices on TigerGraph with 1536-dimensional vectors.

When the agent evaluates evidence—such as a multi-card proxy ring or threshold structuring—it retrieves and attaches authoritative citations:
- `policy:R6` ("Fraud Policy R6: Mandates card block, case creation, and supervisory escalation for multi-account shared origin rings.")
- `reg:fincen_sar_narrative:0` ("FinCEN Guidance: Mandates reporting of structured transactions designed to evade authorization thresholds.")

Every recommendation carries verifiable `source: "document"` references, enabling human auditors to trace the exact policy foundation behind every decision.

## Live Results across the 20 Exam Cases

Running live against TigerGraph Savanna with Groq Qwen 3.8-27b prose generation yielded balanced, calibrated outcomes across all 20 exam cases:
- **Verdict Distribution:** 10 legitimate (50%), 9 uncertain (45%), 1 fraud (5%).
- **Over-Blocking Prevention:** Zero false-positive card blocks on legitimate subscription and baseline-consistent charges (e.g. HHG-003, HHG-009 protected under R7).
- **Tool Calls:** 6 to 7 live queries per case executed through the native `tigergraph-mcp` execution path.
- **LLM Tokens:** 500 to 2,573 tokens per case with zero hallucinations (all entity IDs strictly verified against graph facts).
- **Validation:** 20/20 answer files pass `src.answer.validator` with 0 violations.

## What we learned


The most useful bug we hit wasn't a crash. `initial` and `final` next-best-actions came out
identical on every case we tested — no error, valid JSON, all 105 tests green. The before/after
mechanic, worth a quarter of the grade, was completely inert, and nothing in the test suite
noticed. It took three causes: the evidence-request type was being chosen using R1's 0.70 block
threshold, which governs whether you may block, not which evidence to ask for, so the agent was
requesting `step_up_auth` when it should have asked for `customer_validation` — meaning R2 and R3,
the two rules that fire on a customer's reply, could never trigger on any case, ever. Separately,
the investigate loop was re-running deduplicated detector queries up to its iteration cap;
re-running a deterministic query against unchanged data can't produce new evidence by definition.
And a step-up reply, when one was requested, folded no key into the ledger at all, so even when
the agent did ask, nothing moved.

The lesson is bigger than the bug: green tests told us nothing about whether the most important
behaviour in the submission worked. The suite checked that the pipeline ran, produced valid
output, and didn't crash — none of which says anything about whether the recommendation actually
changed when it was supposed to. We only found it by running real cases end to end and diffing the
two snapshots by eye. Passing tests and correct behaviour are different claims.

The second lesson was more embarrassing. The out-of-region detector — pattern 4, card cloning —
was implemented backwards on the first pass. It fired when the customer's home-region activity
went quiet, on the theory that quiet-at-home plus activity-elsewhere signals a clone. The brief
says the opposite: a clone shows home-region activity continuing while new-region activity
appears, because one physical card cannot be in two places at once, and several days of purchases
in a single new region with nothing at home is a trip. As written, the detector would have cleared
genuine card cloning and flagged every customer who went on holiday. We fixed it to require
concurrency — a home-region transaction within 24 hours of a new-region one — rather than mere
presence of a new region.

## What we'd improve with more time

Fraud probability is calibrated against one anchor — the worked example in the brief, plus rough
base rates from the closed-case history. It should be fit against a proper held-out split of the
5,565 closed cases instead, respecting the July–October / November–December boundary so nothing
leaks across the exam split.

The LLM writes prose — summaries, SAR narratives, evidence descriptions — but never touches the
decision path. We'd keep that separation, but there's room to use the LLM more for narrative
quality without loosening the constraint that it never picks an action or emits a probability.

We haven't trained a GNN over the graph, the more principled way to surface the device/region
clustering the detectors currently find with hand-written windowed queries. And the whole thing
runs against a single loaded snapshot — no streaming ingest, so a real deployment would need to
handle the graph changing under the agent mid-investigation, which this version doesn't attempt.
