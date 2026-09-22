# 6. Decisions and gotchas

The stuff you can't recover by reading code. Why things are the way they are, what already
went wrong, and where the landmines are.

---

## Bugs already found and fixed

These are here because each one would have silently cost real marks, and because the shape
of them tells you where to look for the next one.

### The recommendation never changed

**Symptom:** `initial` and `final` came out identical on every case. Tests passed, valid
JSON was produced, nothing errored.

**Why it mattered:** the before/after pair is the core of the 25% next-best-action
criterion. Worse, the agent was requesting `step_up_auth` instead of `customer_validation`,
which meant **R2 and R3 could never fire on any case** — the two highest-value rules in the
whole policy, dead.

**Three causes, all fixed:**
1. The investigate loop spun through its iteration cap re-running deduplicated detector
   queries. Re-running a deterministic query can't change anything.
2. The evidence-request type was chosen using R1's 0.70 threshold — but that line governs
   whether you may *block*, not which evidence to *request*.
3. A step-up reply folded no key into the ledger, so even when asked, nothing moved.

**The lesson:** every test passed while the most important behaviour in the submission was
inert. It only surfaced by running the graph and printing both snapshots. **Check outputs,
not just exit codes.**

### Out-of-region logic was inverted

The detector fired when the home region went *quiet*. The brief says the opposite — a
cardholder's normal activity continuing at home *while* purchases appear elsewhere is the
clone signal, because one card can't be in two places. A clean move to a new region is a
holiday.

As written, it would have cleared real cloning and flagged every customer who went on a
trip.

### The probability ledger read every case as a coin flip

`sigmoid(0) = 0.5`, so a case with zero evidence scored 0.5. Everything compressed into
0.3–0.72, which meant the stopping thresholds at 0.15 and 0.85 were **mathematically
unreachable** — the agent could never confidently close anything either way.

Fixed with a negative bias: `sigmoid(-1.8 + 4.1 × Σweights)`. Now no evidence reads as
0.13, and the brief's worked example lands at 0.89 against its stated 0.86.

### A detector emitted a weight key that didn't exist

`multi_region_clone_cluster` was returned by a detector but absent from
`config/evidence_weights.yaml`, so it silently contributed zero. There's now a contract
test that scans the detectors for weight keys and fails if any lack a weight, plus
`compute_probability` raises on unknown keys instead of ignoring them.

### State silently dropped between nodes

`nodes.py` wrote `_customer_response` but `state.py` never declared it. LangGraph merges
state per *declared channel*, so the key vanished between nodes and R2/R3 never saw a
customer reply. If you add a field to the state, **declare it in the TypedDict** or it will
disappear with no error.

---

## Interpretations we had to make

Where the brief is ambiguous. These are judgement calls — if you disagree, say so, but
change them deliberately.

**"Confirmed or strongly suspected" for filing a SAR (§3a).** The verdict enum is only
`fraud` / `legitimate` / `uncertain`. We read it as `verdict == "fraud"`. Firing a SAR on
`uncertain` would contradict R8, which sends uncertain cases to an analyst, not a regulator.

**"Materially larger purchase" (R5).** No figure given. We use 3× the largest test
authorization.

**"One window" for shared origin (R6).** No duration given. 7 days for shared origin;
24 hours for judging whether home-region activity overlaps out-of-region activity.

**`card_id` derivation.** The brief shows `C01234-K1` but never says how it's built. We
group each customer's rows on the full `card1`–`card6` tuple and number by first
appearance. **This is an inference and needs checking against the real ids** once the data
lands — `data/README.md` has the snippet.

**An `uncertain` verdict alongside `BLOCK_CARD`.** Defensible: R2 fires on a customer
denial regardless of probability, and `uncertain` is explicitly a creditable verdict. But
it reads as incoherent unless the case explains itself, so the validator now requires the
summary or `what_changed` to mention the denial.

---

## Design decisions and why

**We load 30 of 393 columns into the graph.** V1–V339 is 85% of the file with no published
meaning. The brief says don't pretend to know what V127 means, so those can't be cited as
evidence — they go to a parquet sidecar instead of bloating every Transaction vertex.

**Case memory retrieves two separate pools.** The closed-case history is 4,665 fraud vs 900
cleared. A single merged top-5 returns five fraud cases nearly every time, so the agent only
sees incriminating precedent and drifts toward blocking. We pull top-3 confirming and top-2
exonerating independently. Given that half the exam cases are legitimate, surfacing "this
looked bad and turned out fine" is as valuable as the opposite.

**`risk_score_alone` is weighted +0.05, almost nothing.** The brief says above 0.7 most
flagged transactions are legitimate and some fraud scores near zero. Treating the model's
score as strong evidence would wreck our calibration score.

**The LLM never picks actions or produces probabilities.** It classifies evidence into the
ledger and writes prose. Actions come from the rule engine; probability from the weighted
ledger. When a judge asks where 0.86 came from, we open a config file.

**Serialization refuses to emit a block without a `ref`.** The answer file's `evidence[]`
needs `{claim, source, ref, entity_ids}`. If provenance is dropped during serialization,
the agent can't fill the field and we lose marks on two criteria. So it's structurally
impossible rather than a convention.

**SAR narratives reject hallucinated IDs.** Every ID in the output must trace to an input.
The brief says fabricated IDs score zero, and a regulator-facing document is the worst place
to invent an account number.

**GSQL loading job, not row-by-row REST.** Straight from TigerGraph's DevRel on Discord:
*"Don't do row-by-row REST. Use a GSQL loading job. 600K rows takes minutes."*

---

## Landmines

**Never coalesce a missing DeviceProfile key to `"None | None"`.** It would cluster every
device-less transaction into one giant fake ring and poison every R6 query. The key is built
from whatever subset of fields is present, with a `completeness` count so weak matches can
be discounted.

**Don't group by `card1`.** It is not unique per physical card — many real cards share a
value. Use the derived `card_id`.

**Split by time, never randomly.** Closed cases are Jul–Oct, exam cases Nov–Dec. A random
split leaks the future. The original Kaggle competition had this exact trap and it's
mirrored here deliberately.

**A missing identity row is a signal, not missing data.** `identity.csv` only covers online
transactions. No identity row means `in_person`.

**Boundary conditions are worth real marks.** The policy says `> $1,000`, `> $500`,
`≤ $2,500`, `< 0.70`, `≥ 0.85`. Match the inequality exactly. There are tests at 2500 and
2501 for precisely this reason.

**Never join to the public Kaggle IEEE-CIS files.** Explicit disqualification. IDs, times
and amounts were deliberately disguised to prevent it. Researching column *semantics* is
fine.

**Don't force artificial evidence requests on clear-cut cases.** The brief marks down
investigations that continue past a defensible decision. `final == initial` with
`what_changed: "nothing"` is a correct answer when the case was never in doubt.

**GSQL nested subqueries vary by version.** Nested `POST-ACCUM`/`FOREACH` is the most likely
thing to break on a live instance. Test early. `SHOW QUERY <name>` after a trial install
tells you the parsed syntax version.

---

## If you change one thing, change it here

| To change... | Edit |
|---|---|
| How much a piece of evidence is worth | `config/evidence_weights.yaml` |
| What actions a rule produces | `config/fraud_policy.yaml` |
| Probability curve shape | `BASELINE` / `SCALE` in `src/policy/ledger.py` |
| Detection thresholds | module constants at the top of `src/detectors/patterns.py` |
| What the agent asks for and when | `_choose_evidence_request_type` in `src/agent/nodes.py` |
| Assumed customer replies | `src/agent/evidence_sim.py` |
| Output checks | `src/answer/validator.py` |

Most behaviour changes should be a YAML edit, not a code edit. That's deliberate — it keeps
the policy auditable and means a judge can read our rules without reading Python.
