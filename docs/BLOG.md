<!--
SOURCING NOTES (for whoever publishes this):

FINAL VERIFIED, 25 Sept, against cases/*.json regenerated post-fix against the live
TigerGraph Savanna graph (validator: 20/20 pass, 0 violations):
  verdicts: {'legitimate': 9, 'uncertain': 10, 'fraud': 1}
  llm_decision refs (includes the confidence-gate entries added this pass): 13/20 cases
  sar.file=true: 1 case (HHG-014)
  next_best_actions initial != final: 4/20 cases
  total LLM tokens: 97,673
  distinct prior cases cited: 89

The R2/R4 policy defect mentioned in earlier drafts (HHG-004/006/016 recommending
BLOCK_CARD under the customer-denial rule on a "no reply" response) is RESOLVED —
none of the three cite R2 or BLOCK_CARD in the current run. As a direct consequence,
HHG-006 (the earlier before/after worked example) now correctly shows NO change
between initial and final — the fix removed a false positive, not a feature. The
before/after worked example below is HHG-014 instead, which does have a real,
un-buggy before/after and is also the live shared-device-ring / tg_wcc / SAR case.

Two more bugs were found and fixed this same pass (see bugs.md): a pattern-priority
bug (HHG-014 mislabeled as a generic single-card pattern instead of `undocumented`
despite being an 18-customer ring) and a device-id hallucination (an LLM plan step
proposing a raw dataset column name like `id_15` as a real device id, now guarded
before it reaches the database). Two features were added: a verbose per-case trace
file (`cases/traces/<id>.trace.md`) labelling every evidence item by mechanism, and
an explicit confidence field on the agent's own stop/continue decision. Neither fix
nor feature changed any case's verdict or fraud_probability — verified across all 20
cases plus 3 independent re-runs of one case to rule out run-to-run flakiness.
-->

# Judgement under uncertainty: an agent that knows when not to act

*Built at the TigerGraph Agentic Fraud Investigation Hackathon by Team ORNG. Code: [github.com/VaibHUB17/HHgoa4](https://github.com/VaibHUB17/HHgoa4) — live analyst console: [h-hgoa4.vercel.app](https://h-hgoa4.vercel.app/). We had a lot of help from Devanshu at TigerGraph, who answered our questions in the Discord at midnight and talked us out of at least one genuinely bad idea.*

<!-- IMAGE: place the system architecture overview image here, right below the intro paragraph -->
<!-- PROMPT: "Clean dark-mode technical architecture diagram. Flow from left to right: a box labeled 'LangGraph State Machine' with arrows going to a box labeled 'TigerGraph Savanna (590k transactions)', then to a box labeled 'Pattern Detectors + Confidence Scorer', then to a box labeled 'JSON Case File'. Below the main flow, a smaller feedback arrow from the Case File back to TigerGraph labeled 'written back as precedent'. Minimalist, dark background, teal and white labels, no photos, diagram style only." -->

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

Run against the live TigerGraph Savanna instance, this resolves to 9 legitimate, 10 uncertain, 1
fraud across 20 cases; 1 files a SAR; 13 carry a real `llm_decision` evidence ref (the model
choosing to widen an investigation, or explicitly stating its confidence before stopping); 4 have a
recommendation that changed between the initial and final snapshot; total LLM spend is 97,673
tokens; 89 distinct prior closed cases are cited as memory. Every one of those numbers comes from
the answer files themselves, not a summary we wrote by hand.

The ten uncertain verdicts deserve a word. Uncertain does not mean the agent gave up. It means the evidence was real but not strong enough to cross either threshold — not enough to close confidently as legitimate, not enough to recommend blocking. Every one of the ten carries a stated probability, a list of the specific signals that pushed it in each direction, and a next action. Uncertain with reasons is a more honest answer than a forced verdict would be in the same situation. A fraud manager reading one of those files knows exactly what the agent found and exactly why it stopped where it did.

## The architecture, and the one line we drew through the middle of it

Every design decision in this system follows from one rule: **the LLM decides where to look and when to stop. It never decides what is true.**

Concretely, the investigation is a twelve-node LangGraph state machine:

```
trigger -> investigate -> gather_evidence -> assess -> (gather_more | decide)
        -> snapshot_initial -> request_evidence -> reassess -> snapshot_final
        -> policy_gate -> explain -> write_case -> emit
```

`gather_more` loops back to `investigate`. Of those twelve nodes, the LLM participates in exactly three activities: choosing which graph query to run next, classifying returned rows into a fixed vocabulary of evidence keys, and writing prose. The probability comes from a weighted ledger. The verdict comes from thresholds on that probability. The actions come from ten numbered policy rules (R1–R10) in a YAML file, resolving to fourteen exact action identifiers and three approval routes. None of those three are reachable by a model token.

That boundary is what makes the system auditable, and it's enforced by structure rather than by instruction. The prompts do say "you never state a verdict or probability" — but more importantly, there is no code path by which an assess-step reply could reach `compute_probability`. The function signature only accepts ledger keys.

### How the agent actually talks to the graph

Graph access goes through **TigerGraph's MCP server** (`tigergraph-mcp`), not raw driver calls. Every installed-query call routes through `mcp_run_installed_query` first, falling back to `pyTigerGraph` with a token-refresh retry only if MCP errors — Savanna tokens expire after about an hour, which produces silent 401s mid-run if you don't wrap for it.

There are six precompiled GSQL queries, and they're exposed to the model as a tool inventory with typed parameters:

```
card_window(card_id, anchor, hours)
device_neighbors(device_id, anchor, hours)
customer_baseline(customer_id)
prior_cases_for_entities(cards, devs)
similar_prior_cases(qvec, pool, k)
```

This is a deliberate architectural choice worth naming, because the alternative was available and we rejected it. `tigergraph-mcp[llm]` ships `generate_gsql` — natural-language-to-GSQL. It's genuinely impressive, and we do not use it on the graded path. Precompiled queries are pre-vetted, installed, and fast; a generated query is unvalidated GSQL executing against a live graph. For twenty cases that get scored, "the LLM picks from a vetted inventory" is the right risk posture.

But we didn't want to lose the open-ended capability entirely, so the model can propose an ad-hoc read-only traversal when nothing in the inventory fits — and every such request passes a guard before touching the database:

- Statement allowlist: must begin with `SELECT`, or an `INTERPRET QUERY (...) FOR GRAPH ... { }` wrapper whose body does
- Keyword blocklist, whole-word: `INSERT UPDATE DELETE DROP CREATE ALTER GRANT REVOKE TRUNCATE REPLACE`
- A mandatory `LIMIT`, capped at 200 rows
- A hard 20-second timeout on a worker thread

And the part we're most pleased with: **a rejected query is logged verbatim into the evidence list as an artifact of the agent's behaviour, not swallowed.** If the model proposes something illegal, the case file says so, with the query text. Failures are evidence too.

### The loop that makes depth real

One hop dressed up as reasoning is not an investigation. `investigate()` runs a bounded **Assess → Plan → Execute → Integrate** cycle:

1. **Assess** — given evidence so far, is this enough for a defensible conclusion, or what specifically is missing? Returns `CONTINUE` with a target entity and a question, or `CONCLUDE`.
2. **Plan** — pick a query and its parameters, or propose a guarded traversal.
3. **Execute** — run it through MCP.
4. **Integrate** — flatten rows into `{claim, source, ref, entity_ids}` and fold them in.

Then reassess. It terminates on `CONCLUDE`, on `max_depth`, or — the condition that matters most in practice — on an **evidence fingerprint** showing the last query returned nothing new. Re-running a deterministic query against an unchanged snapshot cannot change the picture, so detecting that and stopping is the difference between an agent and a while-loop burning tokens.

When the LLM is unavailable, the loop does not quietly run a fixed query sequence and call it agentic. It runs one grounding query, sets `llm_available=False`, and writes the reason into `stop_reason`. A degraded run is visible in the output rather than disguised as reasoning — we hit exactly this when we exhausted a daily token quota mid-verification, and the honest failure mode is why we noticed immediately instead of shipping twenty quietly-worse case files.

### GraphRAG: filter on the graph, then rank by vector

The case-memory retrieval is the piece we'd point at first if asked what's technically interesting here, because it's a hybrid rather than a bolted-on vector store.

Both `ClosedCase.notesEmb` and `PolicyChunk.textEmb` are native TigerGraph vector attributes — 1536-dimensional, HNSW-indexed, cosine metric — so the vectors live *on the vertices*, inside the same database as the edges. That makes the interesting query shape possible: **narrow to a structurally-relevant candidate set by traversing the graph, then rank within that set by vector similarity.**

```gsql
v = vectorSearch({ClosedCase.notesEmb}, qvec, k,
                 {candidate_set: cand, distance_map: @@dist});
```

`cand` is the output of a graph traversal. A pure vector store can give you "notes that read similarly." This gives you "notes that read similarly *among cases that share an entity with this alert*" — and it's one query, not a round trip between two systems.

The embedding path is `gemini-embedding-001` at `output_dimensionality=1536` to match the schema exactly, with `task_type` correctly split between `RETRIEVAL_DOCUMENT` at index time and `RETRIEVAL_QUERY` at search time (and the cache key folds in the task type, so a document vector can never be served back as a query vector for identical text). One non-obvious gotcha cost us real time: **Gemini embeddings are not unit-norm at any dimensionality below 3072.** We measured 0.6935. Cosine distance against un-normalized vectors silently produces garbage rankings — no error, just quietly wrong neighbours. We L2-normalize explicitly before upsert.

Scoring blends all three signals rather than trusting any one: `0.4 × semantic + 0.4 × structural + 0.2 × pattern_match`, where structural is `min(1, shared_entities / 3)` and semantic is `1 - cosine_distance / 2`.

## Why we had to load data differently than you'd expect

The original dataset is 590,742 transactions with over 400 columns. If you tried to push all of that into a graph database as-is you would get a bloated graph full of engineered features nobody can interpret and a load process that would time out halfway through. So we built a three step slice before any data touched TigerGraph.

First, we extracted only the columns that mean something structurally: transaction timestamps, amounts, card identifiers, device info, email domains, billing regions. That became a slimmed CSV we called txn_slim which a GSQL loading job could bulk ingest in one shot via TigerGraph's DDL endpoint. Second, the 339 engineered feature columns (labeled V1 through V339 with no published meaning) went into a local Parquet sidecar on disk, never into the graph, because the brief itself says not to pretend you know what unlabeled features mean. Third, we derived NEXT edges, the chronological chain of transactions per card, from the slim file as a separate edge list. The GSQL loading job then pulled all four files simultaneously server side, so TigerGraph did the join work, not our laptop.

The card ID reconstruction was its own adventure. The dataset gives you card1 through card6 as separate fields but no actual card identifier. The bank's own case files use a format like C07297-K1. We spent a meaningful amount of time figuring out the ranking rule: it turned out to be ascending transaction count per customer, fewest transactions gets K1. We verified it against all 20 known card IDs in the exam set and got 19 of 20 right. The one exception is a customer with two cards almost identical in usage count, which no simple rule handles cleanly, and we documented that clearly rather than pretending it works perfectly.

<!-- IMAGE: place a data pipeline flow image here, after the loading section -->
<!-- PROMPT: "Clean technical flow diagram on dark background. Three labeled boxes in a row: 'transactions.csv (590k rows, 400+ cols)' arrow to 'slice: keep structural columns only' arrow to 'txn_slim.csv'. Below that row, a branch arrow labeled 'V1-V339 columns' going to a box labeled 'Parquet sidecar (local, never in graph)'. Then from txn_slim.csv, an arrow to a box labeled 'GSQL LOADING JOB' and then to 'TigerGraph Savanna graph'. Minimalist, dark mode, teal and white, diagram only." -->

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

<!-- IMAGE: place the graph schema diagram here -->
<!-- PROMPT: "Graph database schema diagram, dark background, node-and-edge style. Nodes labeled: Customer, Card, Transaction, DeviceProfile, BillingRegion, EmailDomain, ProductCategory, ClosedCase. Directed edges between them labeled: OWNS (Customer to Card), MADE (Card to Transaction), FROM_DEVICE (Transaction to DeviceProfile), BILLED_IN (Transaction to BillingRegion), PURCHASER_EMAIL and RECIPIENT_EMAIL (Transaction to EmailDomain), IN_CATEGORY (Transaction to ProductCategory), INVOLVES (ClosedCase to Transaction). Minimalist, teal nodes on dark background, white edge labels." -->

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
purchases in thirty minutes: $478.95, $456.96, $488.04, $482.12), and the live evidence cites all
five precedent case IDs plus FinCEN guidance on structured transactions designed to evade
authorization thresholds.

<!-- IMAGE: place an image here showing the undocumented pattern -->
<!-- PROMPT: "Timeline chart showing 4 online transactions on one card within 30 minutes. Each transaction shown as a dot on a horizontal timeline with the amount labeled: $478.95, $456.96, $488.04, $482.12. A horizontal red dashed line at $500 labeled 'authorization ceiling'. Below the chart, text: 'Authorization threshold structuring: amounts chosen to stay just under the limit'. Dark background, teal and red accents, clean infographic style." -->

## The before/after mechanic

The clearest way to show judgement under uncertainty is to show it changing over an investigation,
not just render a single verdict. HHG-014 is the live worked example — a card transaction from a
device marked new for that account, which the agent's own investigation escalates into a confirmed
18-customer shared-device ring, corroborated independently by TigerGraph's `tg_wcc` community
detection algorithm. What `tg_wcc` actually returned was a single connected component spanning 18 different customer accounts, all linked by sharing the same physical device at some point. The algorithm does not know anything about fraud. It just finds groups of nodes that are connected to each other and labels them. In this case the group it found happened to be a ring of accounts all touched by the same compromised device, which is exactly the kind of signal you cannot see by looking at one transaction at a time. The agent used that finding as hard evidence under policy rule R6, which covers shared device activity, and it changed the recommended actions accordingly.

<!-- IMAGE: place a ring visualization here -->
<!-- PROMPT: "Graph visualization showing 18 circular nodes, each labeled 'Customer', arranged in a loose ring. All 18 nodes connect through edges to a central node labeled 'DeviceProfile (shared device)'. The central node is highlighted in red. The surrounding customer nodes are in teal. Edges are thin white lines. Background is dark. Title text at top: 'tg_wcc found: 18-customer shared device ring'. Clean, node-link diagram style." -->

```
initial   p=0.61   CREATE_CASE (auto, R6), FILE_REPORT (L2, R6), MONITOR_CONNECTED_CARDS (auto, R6)
          -> evidence request: customer_validation
          -> assumed reply: "No reply received from the customer within the 24-hour window."
final     p=0.61   MONITOR_CARD (auto, R4), DECLINE_TRANSACTION (L1, R4),
                    CREATE_CASE (auto, R6), FILE_REPORT (L2, R6), MONITOR_CONNECTED_CARDS (auto, R6)
```

The non-reply doesn't erase the ring evidence; it adds to it under R4 (unconfirmed customer
response), on top of everything the shared-device finding already justified under R6. Recording
both states, and stating what changed and why, is worth a quarter of the grade under the
next-best-action criterion. It's also the honest thing to do independent of scoring: a fraud
investigation is a sequence of decisions under changing information, not a single classification.
In the current live run 4 of 20 cases change between initial and final; the other 16 correctly stay
put, because a case that was never in doubt shouldn't manufacture a change to look busy — and that
count itself moved when we fixed a bug (below) that had been inflating it with a false positive.

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

<!-- IMAGE: place the permission routing diagram here -->
<!-- PROMPT: "Flowchart on dark background. At the top: a box labeled 'Agent recommends action'. Arrow goes down to a diamond labeled 'What route?'. Three arrows branch out: left arrow labeled 'auto' goes to a green box 'Execute immediately'. Middle arrow labeled 'L1 (team lead)' goes to a yellow box 'Pause, wait for approval'. Right arrow labeled 'L2 (fraud manager)' goes to an orange box 'Pause, wait for approval'. All three paths end with a box labeled 'Result written to case file'. Minimalist flowchart, dark mode, teal and green and orange accents." -->

## The confidence gate: we took the idea and not the dependency

Halfway through the build we had a question nobody on the team could answer cleanly. The pattern detectors give you signals. The scorer turns those signals into a number. But how does the agent decide whether it has *enough* signal to hand off, versus needing to go dig further first? Thresholding the probability alone is mechanical, and it misses the case where signals are contradictory rather than merely weak.

The idea we wanted came from [jevlike](https://github.com/vinnylarouge/jevlike): a single-pass uncertainty classification that runs *before* you apply deterministic rules. Instead of asking "is the probability past the threshold," you first ask "are these input signals coherent enough that the threshold means what I think it means." We pitched it to Devanshu in the Discord, and his answer shaped the design: good fit, just keep it advisory — let it decide whether to act or gather more, and let the graph evidence drive the verdict.

What we shipped is that pattern implemented directly in our own assess step, not the library itself. Being straight about this, because it's the more interesting engineering outcome: once we'd written down what we actually needed — one bounded LLM call, returning `{decision: CONTINUE|CONCLUDE, confidence: low|medium|high, reasoning}`, structurally unable to touch the verdict — it was a JSON contract on a prompt we already had, not a new dependency. So the agent's assess step now carries an explicit confidence field, a `CONCLUDE` at low confidence is treated as a contradiction (it continues instead, unless it's hit the depth limit), and every stop decision is recorded as an `llm_decision:confidence_gate` evidence entry so it shows up in the trace file rather than vanishing into a log line.

The advisory boundary isn't a convention, it's structural: the probability function only ever reads the evidence ledger's weighted keys, and the confidence entry deliberately contributes no ledger key. It can change *how long the agent investigates*. It cannot move the number by even one decimal place. We verified that rather than asserting it — running the same twenty cases with the gate active produced byte-identical verdicts and probabilities to the run without it.

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

The third cost us a model choice, and we only caught it because we tested for it specifically rather than trusting a benchmark. Our first pick for prose generation was `gpt-oss-120b` on Groq — bigger, strong numbers. Then a narrative came back with a card ID that looked right and wasn't. The model silently substitutes **Unicode non-breaking hyphens (U+2011) for ASCII hyphens (U+002D)**. Every card ID in this dataset has the shape `C07297-K1`. Rendered in a SAR narrative, `C07297‑K1` is visually identical and byte-wise a different string — which means it trips our own hallucinated-ID guard, because that ID genuinely does not exist in the source data. We confirmed it with a direct "repeat this string exactly" test. The same model also burns hidden reasoning tokens (155 of 370 completion tokens in one trial) and returns empty strings if `max_tokens` is set below its reasoning budget. We switched to `qwen/qwen3.8-27b`: no hyphen corruption, roughly half the latency, no hidden reasoning overhead, equivalent narrative quality. A model that quietly corrupts identifiers is disqualifying for a system whose entire value proposition is that every ID traces back to source data.

A smaller bug: an out-of-region detector for card cloning fired when home-region activity went
*quiet*, rather than when it *continued alongside* new-region activity — the actual clone signal,
since one card can't be in two places at once. As written it would have cleared genuine cloning and
flagged every customer who went on holiday.

Three more surfaced in a late verification pass, all in the same family: output that was structurally valid and semantically wrong. Pattern classification used "whichever detector fires first," so a confirmed 18-customer device ring got labelled with a generic single-card pattern instead of the `undocumented` category it actually earned — fixed with an explicit priority ranking rather than a special case for that one card. The plan step, asked to look up a device, would sometimes hallucinate a plausible-looking identifier out of a raw dataset *column name* it had seen in context (`id_15`, the "New/Found device" flag column, used as though it were a device key) — the query correctly returned nothing and the row was correctly discarded, so it corrupted nothing, but it burned a step; fixed by listing the real entity IDs seen so far in the prompt and guarding the parameter shape before it reaches the database. And one found in a `git diff --stat` thirty seconds before committing: a case file's diff was 2,869 lines when it should have been a few dozen, because an installed query re-run at depth had flattened a busy customer's entire transaction history into 2,794 entity IDs on a single evidence item. Valid data, valid JSON, passing tests, useless as evidence. Capped at the same 200-row limit the ad-hoc guard already enforced, with the true count preserved in the claim text so nothing is silently dropped.

The through-line in every one of them: **not a single one was a crash, and the test suite was green for all of them.** 194 tests pass and a schema validator reports zero violations across all twenty case files — both necessary, neither remotely sufficient. Each bug was found by running real cases end to end against the live graph and reading the output the way a reviewer would. Which is also why the last thing we built was the trace file: if the failure mode of this system is "plausible and wrong," then the artifact that matters most is the one that makes every step legible enough to argue with.

## What we'd improve with more time

Fraud probability is calibrated against one anchor — the brief's worked example plus rough base
rates from the closed-case history — and should be fit against a proper held-out split of the 5,565
closed cases instead, respecting the same time boundary as the exam split (never a random split: the closed cases run July–October and the exam cases November–December, so a random split leaks the future).

Ring detection runs as hand-written windowed queries plus `tg_wcc` when the model decides a case
warrants widening. TigerGraph ships Louvain community detection, PageRank, and Jaccard similarity as first-class GSQL calls, and we wired only weakly-connected-components. Louvain in particular would likely separate a genuine coordinated ring from an artifact of shared infrastructure — a corporate proxy, a device fingerprint generic enough that two strangers collide on it — which is precisely the distinction our windowed queries handle with a hand-tuned threshold instead.

We also under-built the document side. Policy and regulatory text is embedded and retrieved through `PolicyChunk.textEmb` and genuinely cited in the case files, but it's a flat chunk index over three sources. The version we designed and didn't ship had typed `RegChunk` and `Pattern` vertices with `GOVERNS`/`PRESCRIBES`/`CITES` edges, so a pattern classification could traverse directly to the rules that govern it rather than relying on vector proximity to surface the right chunk. The simpler thing works and is cited; the richer thing would have been defensible as graph-native document grounding rather than RAG sitting next to a graph.

## The human part

This was a real hackathon sprint with real infrastructure chaos. We missed our first submission window because a data load failed halfway through. The graph schema went through three rewrites. One of us was debugging a silent embedding failure at 2am while the other was reverse engineering the bank's card ID numbering scheme from 20 rows of ground truth data.

The Discord with Devanshu was genuinely useful in a way that documentation almost never is. When we asked about using a GNN he did not just say no, he explained precisely why it would give us a score that would not help us score the investigation, and told us what to use instead. When we asked about jevlike he read the GitHub link and gave us a one sentence answer that told us exactly how to fit it in without overengineering it. That kind of feedback in real time during a build is hard to come by.

If you want to see the actual output, every one of the 20 case files is in the repo under `cases/`, along with a `cases/traces/` trace file that shows the step-by-step reasoning for each one — labelled by which mechanism produced each piece of evidence, so you don't have to take any of the above on faith. The full build is at [github.com/VaibHUB17/HHgoa4](https://github.com/VaibHUB17/HHgoa4), and the analyst console that reads those files is deployed at [h-hgoa4.vercel.app](https://h-hgoa4.vercel.app/).
