# Agentic Fraud Investigation on TigerGraph

An AI agent that investigates card-fraud alerts, decides what the bank should do, and
changes its mind when new evidence arrives — with every recommendation traced back to a
policy rule and an approval route.

Built for the TigerGraph × Hacker House Goa task. The dataset spec, fraud policy, and answer
format are in [README.md](README.md); that file is the brief, this one is the project.

---

## The problem

20 fraud alerts, no labels. Every transaction carries a risk score from the bank's model,
and the score is unreliable in both directions — above 0.7 most flagged transactions turn
out to be legitimate, and some real fraud scores near zero. **Half the 20 cases are
legitimate.** An agent that blocks everything fails.

So the task isn't classification. It's judgement under uncertainty: gather evidence from a
graph, work out whether there's enough of it to act, ask for more when there isn't, and
produce a decision a human could defend to a regulator.

## What the agent produces

One JSON file per case in `cases/`, each containing:

1. **A case** — verdict, pattern, probability, evidence with IDs, prior cases retrieved.
   Also written back into TigerGraph so later investigations can find it.
2. **A SAR** — a regulatory filing, but only when policy requires one. Most cases don't.
3. **A next-best-action pair** — what we recommend *before* asking for evidence, and *after*
   the reply. Plus what changed between them.

## How it works

```
alert -> investigate -> assess -> need more evidence? -> yes -> ask -> reassess
                          ^                                              |
                          +----------------------------------------------+
                                                                         no
                                                                          v
                                        policy engine -> approval gate -> answer file
```

The graph does the work a row-by-row classifier can't: finding the other cards that share a
device profile, the region cluster, the recipient email. Three of the five documented fraud
patterns are only visible across entities.

The policy engine is a rule engine, not a prompt. R1–R10 from the bank's policy as
predicates returning ordered action lists, with approval routes resolved from the action and
the exposure. The LLM classifies evidence and writes prose; it never picks the action and
never emits the probability.

Confidence comes from a weighted evidence ledger in a config file — so when a judge asks
where 0.86 came from, there's an answer that isn't "the model felt strongly."

## Layout

```
README.md              the task brief (from the organizers)
PROJECT.md             this file
RESEARCH.md            architecture research and decisions, with sources
docs/PRD.md            what we're building and why
docs/{KARAN,VAIBHAV,BHAVYA}.md   per-person scope and contracts

config/                fraud_policy.yaml, evidence_weights.yaml — the contracts
src/graph/             schema, GSQL queries, loaders
src/detectors/         the six fraud-pattern detectors
src/policy/            rule engine + probability ledger
src/agent/             LangGraph orchestration
src/rag/               case memory, retrieval, subgraph serialization
src/sar/               SAR narrative generation
src/answer/            answer-file schema and validator
src/ml/                classifier over the 5,565 closed cases
ui/                    Next.js analyst console
cases/                 the 20 answer files (the submission)
```

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your Savanna workspace URL and credentials

python -m src.graph.load --data ./data      # load the CSVs into TigerGraph
python -m src.agent.run --case HHG-017      # investigate one case
python -m src.agent.run --all               # all 20
python -m src.answer.validator cases/       # check before submitting

cd ui && npm install && npm run dev         # analyst console
```

Data files aren't committed — they're ~700MB and belong to the organizers. Put
`transactions.csv`, `identity.csv`, `closed_cases_history.csv` and `case_pack.csv` in
`data/`.

## Design decisions worth knowing

**We load 30 of 393 columns into the graph.** The V1–V339 block is 85% of the file with no
published meaning; the brief says not to pretend we know what V127 means, so those can't be
cited as evidence and don't earn a place in the graph. They go to a Parquet sidecar.

**Case memory retrieves exonerating precedent separately.** The closed-case history is 4,665
confirmed fraud against 900 cleared. A single merged ranking would return five fraud cases
every time and push every verdict upward. We pull the two pools independently so the agent
sees the cases that argue *against* fraud too.

**The agent executes `auto` actions only.** Anything that blocks a card or files a report is
recommended with its approval route stated and left for a human. That's enforced at a single
chokepoint in code, not requested in a prompt.

**Probability is bounded away from the middle.** No evidence means a low prior, not a coin
flip — otherwise the stopping thresholds at 0.15 and 0.85 are unreachable and the agent can
never confidently close anything.

## Interpretations we had to make

Where the brief is ambiguous, here's how we read it and why. Flagged so a judge sees the
reasoning rather than guessing at ours.

**"Confirmed or strongly suspected" for filing a SAR (§3a).** The verdict enum only has
`fraud` / `legitimate` / `uncertain` — there's no separate "strongly suspected" state. We
read it as `verdict == "fraud"`. Firing a SAR on `uncertain` would contradict R8, which
routes uncertain cases to an analyst rather than to a regulator.

**"Materially larger purchase" in the card-testing rule (R5).** No figure given. We use 3×
the largest test authorization, as a named constant rather than a buried magic number.

**"One window" for shared-origin detection (R6).** No duration given. We use 7 days for
shared origin, and a 24-hour concurrency window for judging whether home-region activity
overlaps out-of-region activity.

**`card_id` derivation.** The brief shows ids like `C01234-K1` but never says how they're
built from `card1`–`card6`. We group each customer's rows on the full six-column tuple and
number them by first appearance. This needs cross-checking against the real ids in
`case_pack.csv` once the data is downloaded — `data/README.md` has the check.

## Limitations

Written down honestly rather than discovered by a judge:

- **Customer and analyst replies are simulated.** The dataset doesn't provide them. Each
  case records the assumption made in `evidence_requests[].assumed_response`.
- **Column semantics are inferred.** Vesta never published what C3 or D15 or V127 mean. Where
  the agent uses them it says so rather than inventing a meaning.
- **Fraud probability is calibrated against one anchor** — the worked example in the brief —
  plus the closed-case base rates. With more time we'd fit it properly against a held-out
  split of the closed cases.
- **The graph is a snapshot.** No streaming ingest; the agent investigates against data
  loaded once.
