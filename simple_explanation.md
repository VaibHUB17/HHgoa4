# Simple Explanation — HHGOA Fraud Investigation Hackathon

Written for Bhavya, in plain language. Read this instead of juggling 10 documents.

**Deadline: TODAY, 24 Sept, 11:59 PM IST. One submission. No resubmissions.**

---

## 1. What is this task, really?

Forget "detect fraud." That's not the game. The organizers deliberately removed the
fraud/not-fraud answer from the data. What they actually want to see is:

> **Can your AI agent look at a suspicious transaction, investigate it like a human fraud
> analyst would, admit when it isn't sure, ask for more proof, change its mind when the
> proof comes back, and land on a defensible decision — for 20 different cases?**

Half of the 20 test cases are secretly **legitimate** (nothing wrong happened). An agent
that panics and blocks every card scores badly. An agent that says "uncertain, here's what
I'd check next" on a genuinely ambiguous case gets **full marks** for that — uncertainty is
a valid, rewarded answer here, not a cop-out.

### What you physically hand in
1. A GitHub repo (public)
2. **20 JSON files** in a `cases/` folder — one per case, this is 90% of the grade
3. A 3–5 min demo video
4. A blog post
5. A social media post tagging @TigerGraphDB

Each of the 20 JSON files must contain 3 things for that case:
- **The Case** — what you found, your verdict, evidence, probability of fraud
- **The SAR** (Suspicious Activity Report) — only if the rules say you must file one
- **Next Best Action** — what the bank should do, recorded **twice**: what you'd do
  *before* getting more evidence, and what you'd do *after*. Showing your answer changed
  is literally the point of the "Next Best Action" 25% grading category.

---

## 2. Is HHGOA the same as the "Agentic GraphRAG Hackathon"?

**No — this tripped up multiple people on Discord.** There are two separate hackathons
running at the same time from TigerGraph:
- **Agentic GraphRAG Hackathon** — different dataset, deadline Oct 7, ₹70,000 prize, judged
  by benchmarking RAG vs GraphRAG vs Agentic GraphRAG.
- **HHGOA (Agentic Fraud Investigation)** — **this is us.** IEEE-CIS fraud dataset,
  deadline Sept 24, in-person round in Goa for finalists, ~5-10 teams get selected.

Everything in your repo is correctly scoped to HHGOA. No confusion there.

---

## 3. Where are we actually at, right now?

Good news first: **the entire engineering pipeline is built and tested.** Karan, Vaibhav,
and you (Bhavya) built a real system — this is not a "start from scratch" situation.

| Piece | Status |
|---|---|
| Graph schema + GSQL queries | Written. Never run against a real (live) TigerGraph yet. |
| TigerGraph MCP connection | Built, verified with a `--check` command |
| Fraud pattern detectors (6 patterns) | Done, 21 tests passing |
| Policy engine (the 10 rules, R1–R10) | Done, 27 tests passing, edge cases checked |
| Evidence weighting / probability math | Done and calibrated |
| The agent's decision loop (LangGraph) | Done — it really does change its mind when new evidence comes in |
| Case memory (retrieving similar past cases) | Done, 15 tests |
| SAR (regulator report) writer | Done |
| Answer file format + validator | Done |
| Analyst web UI | Builds and runs locally |
| **Real dataset downloaded** | **Yes — `HHGOA_IEEE_Dataset/`** |
| **Real TigerGraph workspace connected** | **No — no `.env` file exists yet** |
| **The actual 20 answer files (`cases/`)** | **Not generated yet — folder doesn't exist** |
| ML baseline model trained on real data | Not run yet |
| Demo video | Not recorded |

**The honest one-line summary: the machine is built and tested against fake data. It has
never been plugged into the real dataset or a real TigerGraph. That plug-in is the only
thing standing between "well-tested prototype" and "submission."**

This matches exactly what `handover/05-whats-left.md` says — your teammates already know
this and wrote it down. You are not missing information, you're missing **execution against
real data**, which is a few hours of running commands, not writing new code.

---

## 4. Are we aligned with what the Discord/organizers actually said?

Yes, checked line by line. A few specific things confirmed by Devanshu (TigerGraph DevRel)
that your plan already accounts for:

- **"There isn't a final verdict column, decide with evidence — that's the task."** ✅ Your
  whole architecture (evidence ledger, not a classifier) is built exactly for this.
- **"Don't do row-by-row REST upsert, use a GSQL loading job."** ✅ `src/graph/load.py` and
  `scripts/setup_graph.py` are built around GSQL bulk loading, not row-by-row REST — correct.
- **"You can use TigerGraph Community Edition or Savanna, either is fine."** Your plan uses
  Savanna (cloud, no install) — reasonable choice, faster to demo, matches DevRel's answer to
  the credits question ("log in, you get free credits automatically").
- **"You can run the project locally, just show us a demo."** ✅ No public deployment needed.
- **"JEV or other models allowed for routing/scoring, but you need an LLM for actual
  answers."** Your build currently uses **zero LLM calls** — everything (verdict, actions,
  probability) is deterministic/rule-based, and summaries are templated text, not LLM
  prose (`tokens: 0` in every file, noted in your own handover docs). This is a real gap
  against what the organizer said is expected — see Section 6, item 4.
- **Submission is a Google Form, one shot, team lead only.** ✅ already documented.

**No contradictions found. Your plan is aligned.** The one thing to actively fix per the
Discord Q&A is wiring in an actual LLM call somewhere real (see below) — it's explicitly
sanctioned/expected ("you will still need an LLM for the actual answers"), and right now
your system produces zero LLM-generated content.

---

## 5. Are we using prebuilt tools/libraries to move fast, or reinventing things?

Checked — yes, sensibly:
- **TigerGraph MCP** (`tigergraph-mcp` package) — official, used as intended, not reimplemented
- **LangGraph** — used for the agent loop instead of hand-rolling a state machine. Good call;
  it gives you the cyclic "investigate → assess → ask for more → reassess" loop and the
  human-approval-pause feature (`interrupt()`) for free — both of those are explicitly graded
  under "Agentic design."
- **pyTigerGraph** — official Python client, correct choice for loading/querying
- **scikit-learn** — for the ML baseline, no need for anything heavier given the timeline
- Nothing looks reinvented that shouldn't be. No wasted effort here.

---

## 6. The concrete plan for TODAY, in order

Given the deadline is tonight, here is the exact sequence, cheapest/highest-value first.

### Step 0 — Get the real data where the code expects it (5 min)
The code looks for CSVs in `data/`, but your downloaded dataset is in
`HHGOA_IEEE_Dataset/`. Either copy the 4 CSVs over, or point every command at
`--data-dir HHGOA_IEEE_Dataset` instead of the default. Fastest: copy them into `data/`.

### Step 1 — Get TigerGraph Savanna connected (30–60 min)
1. Sign up at https://savanna.tgcloud.io, create a workspace, **turn on Auto Suspend
   immediately**.
2. `cp .env.example .env`, fill in `TG_HOST` (the workspace URL, not savanna.tgcloud.io) and
   the token/secret.
3. `python -m scripts.setup_graph --check` (just tests the connection)
4. `python -m scripts.setup_graph` (creates schema + installs the GSQL queries)
   — budget real time here, GSQL syntax sometimes needs small fixes on a live instance
   that never showed up against fixtures.

### Step 2 — Load the real data into the graph (15–30 min, mostly waiting)
```
python -m src.graph.load --data-dir ./data
```

### Step 3 — Run the ML baseline (optional but assigned to you, Bhavya) (15 min)
```
python -m src.ml.train --data-dir ./data
```
This feeds a calibrated prior probability into the evidence ledger. Not strictly required
to produce valid answer files (the ledger works without it), but improves calibration
scoring. Do this **after** Step 4 works once, not before — don't let it block the exam run.

### Step 4 — Run all 20 real cases (5–15 min)
```
python -m src.agent.run --all --data-dir ./data --out cases/
python -m src.answer.validator cases/
```
Both must exit clean. Check the "Aggregate by verdict" summary — if it's not roughly half
legitimate / half fraud-or-uncertain, something is over-blocking (see the tuning note in
`handover/05-whats-left.md`).

### Step 5 — Sanity-check a handful of files by hand (30 min)
Read 5–10 of the 20 JSON files as if you were a judge. Do the evidence and summary actually
support the verdict? Especially check the 9 `customer_report` cases — several of the small
dollar-amount ones (HHG-003, 008, 009, 011, 016, 018) are likely legitimate recurring
charges (rule R7's trap) — make sure the agent didn't just block them all.

### Step 6 — Close the "no real LLM" gap if there's time (30–60 min)
Per the Discord answer ("you will still need an LLM for the actual answers"), wire an LLM
call into the **prose only** — the `summary` field and/or SAR narrative — without touching
the deterministic verdict/action logic. This is explicitly called out as safe-to-add in
`handover/06-decisions-and-gotchas.md`: "only the wording should change." Skip this if time
is genuinely tight; it's a polish item, not a correctness one.

### Step 7 — Record the demo video (30 min)
Show: one case end-to-end in the UI (pick HHG-017 or HHG-014, both have known interesting
answers per the team's own triage notes), the before/after action change, and one legitimate
case being correctly cleared.

### Step 8 — Publish blog + social post (drafts already exist: `docs/BLOG.md`, `docs/SOCIAL.md`)
Fill in real numbers/screenshots once cases/ is real, then publish.

### Step 9 — Final checklist before hitting submit
- [ ] `python -m src.answer.validator cases/` exits clean, all 20 files present
- [ ] Verdict spread isn't "20x fraud" or "20x legitimate"
- [ ] Repo is actually public (check in incognito)
- [ ] Demo video link works
- [ ] Blog link works
- [ ] Social post live, tags @TigerGraphDB
- [ ] **Freeze the repo an hour before submitting**
- [ ] Submit once: https://forms.gle/yxXzqSULGgZ9VUF56

---

## 7. Any changes needed to the plan itself?

No structural changes needed — the architecture is sound and matches the brief closely.
Two small course-corrections worth calling out to the team:

1. **The "no LLM used anywhere" state is a real, specific gap** against what the organizer
   said on Discord, not just a nice-to-have. It's low-risk to fix (prose-only, doesn't touch
   scored logic) — worth doing if Step 6 time exists.
2. **`card_id` derivation was an assumption** (`C01234-K1` format, built by grouping
   card1–card6 and numbering by first appearance) made before real data existed. Now that
   real data is downloaded, this is the single highest-risk unverified assumption in the
   whole pipeline — a wrong `card_id` scheme would quietly corrupt every case's evidence.
   **Verify this first**, before trusting any output from Step 4.

Everything else — schema, the 10 policy rules, the two-pool memory retrieval, the
approval-routing enforcement in code — is already correctly aligned with both the task doc
and the Discord clarifications.
