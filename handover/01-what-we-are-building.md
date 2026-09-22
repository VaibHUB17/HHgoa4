# 1. What we're building

## The task in plain terms

A bank's fraud model flags transactions with a risk score. An analyst then has to decide:
is this actually fraud, and what do we do about it? That decision takes ages — pull the
customer's history, check the device, look for connected cards, read the policy, write it
up.

We're building an agent that does that investigation and produces the analyst's output.

## What we hand in

**20 JSON files**, one per case, in `cases/`. That's the submission. Everything else — the
graph, the UI, the blog — exists to produce and explain those files.

Each file has three parts:

1. **The case** — verdict, fraud pattern, probability, the evidence with real IDs, which
   past cases we looked at. Also written into TigerGraph so later cases can find it.
2. **The SAR** — a regulatory filing. Only when policy demands one. Most cases don't need it.
3. **The next best action** — what the bank should do, who approves it, recorded **twice**:
   once before we asked for more evidence, once after. Plus what changed.

Plus: public repo, 3–5 min demo video, technical blog post, social post tagging
@TigerGraphDB.

## The thing that makes this hard

There is **no fraud label in the data.** The organizers removed it deliberately. Devanshu
confirmed it on Discord: *"that's by design... Deciding those, with evidence, is the task."*

What you get instead:

- Every transaction has a `risk_score` from the bank's model
- The README says above 0.7, **most flagged transactions turn out to be legitimate**
- Some real fraud scores near zero
- **Half the 20 cases are legitimate**

So an agent that treats a high risk score as "fraud" will be wrong constantly. And an agent
that blocks everything to be safe scores badly — that's stated outright in the brief.

The skill being tested is judgement under uncertainty: gather evidence, notice when it's not
enough, ask for more, and be willing to say "I'm not sure."

## How it's graded

| Criterion | % | What actually wins it |
|---|---|---|
| Investigation accuracy | 25 | Right pattern, right verdict, **calibrated** probability, evidence with real IDs |
| Next best action | 25 | Exact action names, correct approval routes, and a genuine `initial` → `final` change |
| Case summary & explainability | 10 | One JSON a judge reads standalone; every action cites a rule number |
| Agentic design | 15 | Real tool use, memory, permissions enforced in code |
| Innovation | 15 | The graph doing work a row-by-row model couldn't |
| Demo | 10 | 3–5 min showing the real thing |

**Half the marks are accuracy + next-best-action, scored per case, 20 times over.** Those
are keyed to exact strings — action names, rule numbers, the pattern enum. Right or wrong,
no partial credit. That's where effort goes.

## The five traps

**1. Blocking everything.** Half the answer key is legitimate. Our defence is real negative
weights in the evidence ledger — a charge matching the customer's own recurring pattern
*reduces* fraud probability.

**2. Faking the before/after.** Computing the answer once, then back-filling a plausible
"initial". We hash the evidence set on each snapshot, so the "after" provably used more
evidence than the "before".

**3. Vibe confidence.** A bare `0.83` with nothing behind it. Our probability comes from a
weighted ledger in a config file — when a judge asks where the number came from, we open
`config/evidence_weights.yaml`.

**4. Using the graph as a database.** Loading into TigerGraph then doing the real work in
Python. Three of the five fraud patterns are only visible *across* entities — a device
shared between two customers' cards. That's the Innovation score.

**5. Six polished cases instead of twenty.** Partial coverage misses a named requirement.

One more, specific to this dataset: **using the public Kaggle IEEE-CIS files to look up
answers is explicit disqualification.** The IDs and amounts were deliberately disguised.
Researching what the columns *mean* is fine; joining to the original file is not.

## The policy we operate under

The brief gives us a bank fraud policy with **14 exact action names** and **10 numbered
rules (R1–R10)**. Both are quoted verbatim in `config/fraud_policy.yaml`. Don't rename
anything — the grader matches strings.

Approval routing, which the agent must respect:

| Route | Meaning | Applies to |
|---|---|---|
| `auto` | Agent may execute | Monitoring, warnings, verification, case creation, escalation |
| `L1` | Team lead approves | `DECLINE_TRANSACTION`; `BLOCK_CARD` when exposure ≤ $2,500 |
| `L2` | Fraud manager approves | `BLOCK_CARD` above $2,500; `BLOCK_ALL_CARDS`; `FILE_REPORT` |

**The agent only ever executes `auto` actions.** Anything that blocks a card or files a
report is recommended with its route stated and left for a human. That's enforced in code
at one chokepoint, not requested in a prompt.
