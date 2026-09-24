<!--
SOURCING NOTES (for whoever publishes this):

VERIFIED-REAL, from running the checker script against cases/*.json on the
regen-agentic-live branch, 24 Sept, against the live TigerGraph Savanna graph:
  verdicts: {'legitimate': 9, 'uncertain': 10, 'fraud': 1}
  llm_decision refs: 12/20 cases
  sar.file=true: 2 cases
  next_best_actions initial != final: 10/20 cases
  total LLM tokens: 20,365
  distinct prior cases cited: 89

This matches docs/REGEN_REVIEW.md exactly, so it is the current state of
cases/ as of this writing, not a stale number.

[VERIFY] tags below mark anything that depends on:
  (a) the open R2/R4 policy defect (docs/REGEN_REVIEW.md) — HHG-004, HHG-006,
      HHG-016 currently recommend BLOCK_CARD citing R2 on a "no reply"
      customer response, which should be R4. Another agent is fixing this on
      this branch concurrently, so re-run the checker script before
      publishing and re-verify every case ID and number named below.
  (b) graph vertex/query counts, which the task brief says may shift.

CONTRADICTION FOUND, not silently resolved: the previous draft of this blog
post used HHG-017's offline-fixture run (p=0.41 -> p=0.70, VERIFY_WITH_CUSTOMER
-> BLOCK_CARD) as its worked before/after example. In the live run, HHG-017
does not change at all (what_changed: "nothing", stays legitimate throughout,
p=0.082). That example has been replaced below with HHG-006, which does
change in the live data and is independently the undocumented-pattern case.
HHG-006 is however one of the three cases touched by the open R2/R4 defect
above, so its exact action list is marked [VERIFY] too.
-->

# Judgement under uncertainty: an agent that knows when not to act

We built this for a TigerGraph fraud-investigation hackathon: twenty card-fraud alerts, a graph
database, and an agent that has to decide what happened and what the bank should do about it. The
interesting part of this brief is not fraud detection. There is no fraud label anywhere in the
dataset. Half the twenty exam cases are legitimate by construction, and the bank's own risk score is
wrong in both directions — above 0.7 most flagged transactions turn out fine, and some real fraud
scores near zero. You cannot train a classifier against a target that doesn't exist. What you can
build is a system that gathers evidence, states how confident it is and why, and is honest when it
isn't sure. That reframing drove most of the decisions below.

## What we built

The pipeline is a LangGraph state machine over a TigerGraph instance. For each case: pull the graph
neighbourhood of the flagged transaction (other activity on the card, the device it came from, the
customer's baseline, prior closed cases), run it through pattern detectors, score the accumulated
evidence into a probability, decide whether that's enough to stop, and if not, ask for more evidence
(a simulated customer reply, since the dataset doesn't provide real ones) and go around again. It
writes three things per case into one JSON file: the case record, a SAR when policy requires one,
and a next-best-action recommendation — before and after the evidence came back. The case is also
written back into the graph as precedent for the next investigation: closing a case on a shared
device profile makes that profile evidence for whoever gets flagged next.

**Live, `[VERIFY]` before publishing:** the current run resolves to 9 legitimate, 10 uncertain, 1
fraud across 20 cases; 2 file a SAR; 12 carry a real `llm_decision` evidence ref (the model chose to
widen the investigation); 10 have a recommendation that changed between initial and final; total
LLM spend is 20,365 tokens; 89 distinct prior closed cases are cited. Another agent is fixing a
policy defect on this branch concurrently (see below), so re-run the checker before quoting these
publicly.

## Why a graph and not a table

Some fraud patterns in this brief are invisible to a model scoring one transaction at a time,
because the signal lives in the relationship between entities, not in any single row. One case turns
on an analyst's note saying, in substance, that several cards that month show purchases from the
same unusual device profile — a shared-device ring. A model scoring the flagged transaction on card
A has no way to know the same physical device also made a purchase on a different customer's card
that week. A two-hop graph query
(`Transaction -> FROM_DEVICE -> DeviceProfile <- FROM_DEVICE <- Transaction`) sees it immediately,
because it's a query about the shape of the graph, not any one row's features.

The schema is built around `Customer -> OWNS -> Card -> MADE -> Transaction`, fanning out to
`DeviceProfile`, `BillingRegion`, `EmailDomain`, and `ProductCategory`. Closed cases hang off the
same transactions and cards they involve, so a closed case is graph-reachable evidence, not a
separate lookup table. We load a minority of the original transaction columns; the bulk of the file
is engineered features with no published meaning, and since the brief says not to pretend to know
what an unlabelled feature means, those stay out of the graph entirely. Fully loaded: 590,742
Transaction, 14,780 Card, 13,553 Customer, 9,704 DeviceProfile, 5,565 ClosedCase, and 56 PolicyChunk
vertices, six installed GSQL queries, and TigerGraph's `tg_wcc` community detection algorithm.

## Two-pool memory retrieval, and a pattern the labels missed

`closed_cases_history.csv` has 5,565 closed investigations: 4,665 confirmed fraud, 900 cleared —
the agent's only source of ground truth, and the thing that will quietly bias it if retrieved
carelessly. Run one similarity search over the whole history and take the top five, and you get
five confirmed-fraud cases almost every time, not because they're better matches but because there
are more than five of them competing for every ranking slot. The agent then only sees precedent that
argues for fraud, and drifts toward blocking — the failure mode that costs the most points given
that half the exam cases are legitimate. The retrieval layer splits the candidate pool by outcome
before ranking, not after: a handful of top matches from the confirmed-fraud pool, a couple from the
cleared pool, independently sorted, never merged before truncation. The agent sees "this looked like
card testing and turned out to be fraud" next to "this looked like card testing and turned out to be
a recurring subscription charge," and has to reconcile them.

Nine rows in that file carry `pattern == undocumented` — the label pipeline that tagged the other
5,556 rows had no name for whatever these were. The brief scores finding a pattern the labels
missed, and the mechanism is readable directly in the analyst's own words once you read all nine
notes by hand rather than expect a model to summarize them. Five of the nine — CC-3748, CC-3841,
CC-3907, CC-4086, CC-4124 — describe the same shape: several online purchases on one card within
about half an hour, each priced just under $500. The notes name it themselves: amounts chosen to
stay under a $500 authorization ceiling that would otherwise trigger stronger verification. That's
authorization-threshold structuring, not one of the five documented patterns in the brief. We wrote
a detector for it — three or more online purchases within an hour, each between $450 and $500 — and
cited the five historical cases wherever it fires. It fires on HHG-006 in the exam set (four online
purchases in thirty minutes, at $478.95, $451.33, and neighbouring values), `[VERIFY]` current live
evidence cites all five precedent IDs plus FinCEN guidance on structured transactions designed to
evade authorization thresholds.

## The before/after mechanic

The clearest way to show judgement under uncertainty is to show it changing over an investigation,
not just render a single verdict. HHG-006 is the live worked example, `[VERIFY]` against the R2/R4
defect noted below before quoting exact figures:

```
initial   p~0.70   ESCALATE_TO_ANALYST  (structuring pattern found, single trigger source)
          -> evidence request: customer_validation
          -> assumed reply: "No reply received from the customer within the 24-hour window."
final     BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2), ESCALATE_TO_ANALYST (auto)
```

Recording both states, and stating what changed and why, is worth a quarter of the grade under the
next-best-action criterion. It's also the honest thing to do independent of scoring: a fraud
investigation is a sequence of decisions under changing information, not a single classification.
In the live run 10 of 20 cases change between initial and final; the other 10 correctly stay put,
because a case that was never in doubt shouldn't manufacture a change to look busy.

## Why confidence is a config file, not an LLM opinion

`fraud_probability` never comes from the model asking itself how confident it feels. It comes from
a fixed list of evidence keys, each with a weight in a config file, summed and passed through a
sigmoid: `p = sigmoid(bias + scale * sum(weights of evidence keys present))`. The LLM classifies
what it found into evidence keys and writes the prose around it; it never produces the number. When
someone asks where a probability came from, the answer is "open the weights file," not "the model
felt strongly about it."

The bias constant matters more than it looks. Early on there was none, so zero evidence landed at
`sigmoid(0) = 0.5` — a coin flip. That's harmless-looking until you notice the stopping rule: stop
at or above 0.85 probability or at or below 0.15. With no bias term every realistic sum of weights
compressed into a narrow middle band, so those thresholds were mathematically unreachable — the
agent could never confidently close a case either way, not because the evidence was ambiguous but
because the arithmetic made confidence impossible to express. A negative bias term fixed it: zero
evidence now reads as a weak prior toward "probably fine," and the brief's worked example lands
within a couple of points of its stated value.

## The permission model

The policy defines a set of actions and three approval routes: actions the agent may take alone,
actions that need a team lead, and actions that always need a fraud manager (filing a report, or
blocking a card above a dollar threshold). The agent recommends every action but executes only the
ones it's allowed to take alone; blocking a card, declining a transaction, or filing a report is
recommended with its route stated and left for a human. This is enforced at one place in code, not
requested in a prompt — an action needing approval that reaches that function comes back marked
not-executed no matter what any upstream component decided, and the graph node that would act on it
pauses and waits. We didn't want "don't block cards without approval" to be a sentence in a prompt a
confident-sounding model turn could talk itself past; it's a structural chokepoint.

## What we learned

The most useful bug we hit was not a crash. `initial` and `final` next-best-actions came out
identical on every case in an early run — no error, valid JSON, every test green. The before/after
mechanic, worth a quarter of the grade, was completely inert, and nothing in the test suite noticed.
Three causes: the evidence-request type was chosen using the single-signal block threshold, which
governs whether you may block, not which evidence to ask for, so the two rules that fire on a
customer's reply could never trigger; the investigation loop re-ran deduplicated detector queries up
to its cap, and a deterministic query against unchanged data can't produce new evidence by
definition; and a follow-up reply, when requested, wasn't folded back into the evidence ledger at
all. Green tests told us nothing about whether the most important behaviour worked — we only found
it by running real cases end to end and diffing the snapshots by eye.

The second was a silent degradation, worse than a crash because nothing tells you it happened.
`GEMINI_API_KEY` was set correctly, but the embedding SDK it depends on wasn't installed.
`embed_query()` raised, retrieval caught the exception, and silently fell back to a cruder path that
returned confirmed-fraud neighbours where the working path returns cleared ones — every case still
produced valid output, no error anywhere in the logs. One case shows it cleanly: with the same
evidence, the broken path matched a confirmed-fraud precedent and landed at `uncertain` (p=0.169);
once the SDK was installed, the same case matched a cleared precedent and landed at `legitimate`
(p=0.001). Same inputs, opposite verdict, nothing in the run ever said "embeddings are broken." A
missing dependency that degrades quietly instead of erroring out is the dangerous kind, because
every downstream signal looks internally consistent and is simply wrong.

A smaller bug: an out-of-region detector for card cloning fired when home-region activity went
*quiet*, rather than when it *continued alongside* new-region activity — the actual clone signal,
since one card can't be in two places at once. As written it would have cleared genuine cloning and
flagged every customer who went on holiday.

## What we'd improve with more time

Fraud probability is calibrated against one anchor — the brief's worked example plus rough base
rates from the closed-case history — and should be fit against a proper held-out split of the 5,565
closed cases instead, respecting the same time boundary as the exam split. Ring detection runs as
hand-written windowed queries plus TigerGraph's `tg_wcc` when the model decides a case warrants
widening; a trained graph model would be more principled, though harder to explain to a judge in
one sentence, which matters for a system whose whole pitch is auditability.

And there's a known, currently open defect worth naming rather than hiding: three cases in the live
run recommend blocking a card citing the customer-denial rule when the actual simulated reply was
"no reply within 24 hours" — a different, lower-severity rule should have fired instead, because a
customer *reporting* a charge is treated as a customer *denying* it from the moment the case is
triggered. `[VERIFY]` whether this is fixed before quoting any per-case action list from this run.
