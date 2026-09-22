# PRD — Agentic Fraud Investigation on TigerGraph

**Deadline: 24 September 2026.** Confirmed by Devanshu (TigerGraph DevRel) on Discord.
Today is the 22nd. Two days.

Team: Karan, Vaibhav, Bhavya. Repo: `VaibHUB17/HHgoa4`.

---

## What we are actually delivering

**20 JSON files in `cases/`.** That is the submission. Everything else — the graph, the
agent, the UI, the blog — exists to produce and explain those 20 files.

Each file contains three things:

1. **A case** — the internal investigation record. Also written into TigerGraph as memory.
2. **A SAR** — only when policy demands one. Most cases won't need one.
3. **A next-best-action pair** — what we recommend *before* asking for evidence, and *after*
   it comes back. The recommendation is allowed to change. **Showing that it did is the point.**

Plus: GitHub repo, 3–5 min demo video, technical blog post, social post tagging @TigerGraphDB.

---

## The one thing to understand about this task

It is not a fraud-detection problem. There's no label to predict — the organizers removed
the fraud flag deliberately and confirmed it on Discord: *"that's by design... Deciding those,
with evidence, is the task."*

It's a **judgement-under-uncertainty** problem. The dataset is built so that:

- Every transaction has a `risk_score`, and the README says above 0.7 **most flagged
  transactions turn out to be legitimate**, while some fraud scores near zero.
- **Half the 20 cases are legitimate.** Many look suspicious.
- The correct answer on several cases is "uncertain" — and that earns full credit.

An agent that blocks everything scores badly. An agent that is confidently wrong scores worse
than one that says "I need more evidence, here's what I'd ask for, and here's how my answer
changes depending on the reply."

---

## How the rubric actually breaks down

| Criterion | % | What wins it |
|---|---|---|
| Investigation accuracy | 25 | Right pattern, right verdict, **calibrated** probability, real evidence with real IDs |
| Next best action | 25 | Exact action names, correct approval routes, and a genuine `initial`→`final` change |
| Case summary & explainability | 10 | One JSON a judge can read standalone, every action citing a rule number |
| Agentic design & engineering | 15 | Real tool use, memory, permission enforcement in code |
| Innovation | 15 | Graph doing work a row-by-row classifier couldn't |
| Demo | 10 | 3–5 min, shows the real thing |

**50% is accuracy + NBA, scored per-case across 20 cases.** Those are keyed to exact
identifiers — action names, rule numbers, the pattern enum. Right or wrong, no partial credit.

---

## Architecture

```
case_pack.csv (20 alerts)
        |
        v
  [ LangGraph agent ]
        |
        +--> TigerGraph MCP ---> graph queries (card window, device ring, baseline)
        |                        vector search (prior cases, policy docs)
        |
        +--> detectors -------> 6 pattern detectors -> weighted evidence ledger
        |
        +--> policy engine ---> R1-R10 -> action list + approval route
        |
        v
  snapshot: initial recommendation
        |
        +--> evidence request (customer validation / step-up / analyst)
        |
        v
  snapshot: final recommendation  --> what_changed
        |
        v
  cases/<case_id>.json  +  Case vertex written back to TigerGraph
        |
        v
  Next.js analyst console
```

**Why a graph and not a table.** Three of the five documented fraud patterns are only
visible across entities: a device profile shared between two customers' cards, a billing
region cluster, a recipient email fan-in. The README says it outright — *"some cases can
only be solved by asking what happened on other cards."* Case HHG-014's trigger text is
literally an analyst reporting a shared device across several cards. That's a 2-hop
traversal, and it's where the Innovation score lives.

**Why GraphRAG.** The agent must cite the policy rule behind every action and write a SAR
that stands on its own for a regulator. So policy rules, fraud patterns, and FinCEN guidance
go into TigerGraph as vector-indexed vertices, linked by `GOVERNS`/`PRESCRIBES` edges to the
patterns and actions. Retrieval is graph-filter-then-vector-rank in one query.

**Why case memory matters.** 5,565 closed investigations ship with the dataset (Jul–Oct,
labelled). The exam cases are Nov–Dec. So prior outcomes are legitimately available as
memory. Crucially: 900 of those closed cases were **cleared**, and their notes say why the
alert was a false alarm. We retrieve confirming and exonerating precedent in *separate
pools*, because a merged ranking would bury the 900 under the 4,665 and push every verdict
toward fraud.

---

## Division of work

Contracts are frozen first; then each stream is independent. Nobody waits on anybody.

### Karan — graph, data, detectors
Load the data, build the schema, write the graph queries and the six pattern detectors.
**Contract:** `investigate(case_id) -> {findings, graph_evidence, similar_cases}`
Details: `docs/KARAN.md`

### Vaibhav — policy engine, agent loop, answer assembly
The rule engine, the probability ledger, the LangGraph orchestration, the answer-file
writer and validator. This is the load-bearing 50% of the rubric.
**Contract:** `run_case(case_id, findings, similar_cases) -> answer_json`
Details: `docs/VAIBHAV.md`

### Bhavya — ML, case memory, embeddings
The GNN / classifier over the 5,565 labelled closed cases, feeding a calibrated prior into
the evidence ledger. Plus the embedding pipeline for case memory retrieval.
**Contract:** `prior_probability(case_features) -> float` and `similar_cases(case) -> {confirming, disconfirming}`
Details: `docs/BHAVYA.md`

### Shared (whoever is free)
UI, demo video, blog post, social post.

---

## Schedule

| When | Gate |
|---|---|
| Hour 0–4, together | Savanna up, data loaded, MCP connected, YAML contracts frozen, **one case investigated by hand** |
| Hour 12 | HHG-017 runs end-to-end and passes the validator |
| Hour 24 | All 20 produce schema-valid JSON — **go/no-go** |
| Hour 36 | All 20 pass the validator and look right against the triage table |
| Hour 44 | Demo recorded, blog + social drafted |
| 24 Sept | Submit |

**Do the hour 0–4 manual walkthrough.** The README asks for it explicitly and it's not
busywork: you cannot automate a judgement you have never made yourself once.

---

## Cut list, in order

1. GNN sophistication — a calibrated logistic regression over the closed cases is enough
2. The optional self-monitoring-beyond-20-cases folder (Innovation bonus only)
3. Full regulatory doc corpus — load FinCEN SAR guidance and skip the rest
4. UI polish beyond the case detail screen

**Never cut:** schema conformance, the R1–R10 engine, the initial→final delta, and
false-positive discipline.

---

## How we lose

1. **Blocking everything.** Half the key is legitimate.
2. **Faking the before/after** by computing the answer once and back-filling an "initial".
3. **Vibe confidence** — a bare 0.83 with nothing behind it.
4. **Using the graph as a database** and doing the real work in Python.
5. **Six polished cases instead of twenty.** Partial coverage misses a named requirement.

One more, specific to this dataset: **using the public Kaggle IEEE-CIS files to look up
outcomes is explicit disqualification.** The IDs and amounts here were deliberately
disguised to prevent it. Research the column meanings freely; never join to the original.
