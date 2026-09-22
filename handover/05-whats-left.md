# 5. What's left

## Honest status

| Component | State |
|---|---|
| TigerGraph schema + 6 GSQL queries | written, **never run on a live instance** |
| CSV loaders | written, **never run** — no dataset |
| 6 pattern detectors | done, 21 tests |
| Policy engine R1–R10 | done, 27 tests, boundaries verified |
| Evidence ledger | done, calibrated |
| LangGraph loop + approval gate | done, before/after delta verified working |
| Case memory (two-pool retrieval) | done, 15 tests |
| SAR generator | done, FinCEN structure |
| Answer schema + validator | done, 15 tests |
| Analyst UI | builds, renders, runs on fixtures |
| Runner CLI | done, works offline |
| **20 answer files** | **not produced — blocked on data** |
| Demo video | not started |
| Blog post | not started |
| Social post | not started |

105 tests pass. The pipeline runs end to end. But it has only ever seen three hand-built
fixture cases, never the real dataset, and never a real TigerGraph.

## Two things block everything

**1. Download the dataset** → `data/`. Nothing runs for real without it.

**2. Create a Savanna workspace.** The GSQL has never been executed. There will be syntax
issues — nested subqueries in `POST-ACCUM` are the usual suspect and vary by GSQL version.
Budget an hour for this, not ten minutes.

Until both exist, nobody can produce a single real answer file. **Whoever is free, do
these first.**

## Who picks up what

### Vaibhav — backend, policy, answer quality

The engine is built and tested; what it needs now is contact with reality.

1. **Run all 20 cases once the data lands** and read the summary table. If more than ~12
   come out `fraud`, we're over-blocking and the ledger weights need tuning — half the
   cases are supposed to be legitimate.
2. **Tune the weights** in `config/evidence_weights.yaml` against the closed-case history.
   The calibration is currently anchored to one worked example from the brief; with 5,565
   labelled cases you can do much better.
3. **Read 10 real answer files end to end** as if you were a judge. Does the summary make
   sense? Does the evidence support the verdict? That's the 10% explainability criterion and
   no test can check it.
4. **Wire an LLM for the narrative text** if there's time. Right now `tokens: 0` in every
   file because summaries are templated — honest, but an LLM would write better prose. The
   policy decisions must stay deterministic; only the wording should change.

Files: `config/`, `src/policy/`, `src/agent/`, `src/answer/`

### Bhavya — ML, calibration, case memory

1. **Read the `undocumented` analyst notes by hand.** Filter
   `closed_cases_history.csv` to `pattern == 'undocumented'` and read them. Finding an
   undocumented pattern is explicitly scored, and the mechanism is described in those notes
   in a human's own words. This needs a person, not a model. Probably the highest
   value-per-hour task in the project.
2. **Baseline classifier first**, then the GNN. Logistic regression or gradient boosting on
   per-case features (exposure, n_txns, time span, connected cards, shared device, region
   diversity). An hour's work, immediately usable.
3. **Calibrate it** — Platt scaling or isotonic, then plot a reliability curve.
   `fraud_probability` is scored for calibration, not accuracy. A model that's 85% accurate
   but always says 0.95 scores worse than one that's 80% accurate and honestly says 0.6.
4. **Split by time, not randomly.** Closed cases are Jul–Oct, exam cases Nov–Dec. A random
   split leaks the future and your validation score will lie to you.
5. **Watch the 5:1 imbalance.** Report precision/recall on the *cleared* class specifically.
6. Then the GNN if steps 1–5 are done: per-case subgraph, GraphSAGE or GAT, PyTorch
   Geometric.

Hand back: `prior_probability(case_features) -> float` — Vaibhav folds it into the ledger
as one more weighted signal.

Files: `src/ml/` (yours to create), `notebooks/`

### Karan — graph, TigerGraph, demo

1. Savanna workspace + load the data
2. Get the GSQL actually running, fix whatever the live parser rejects
3. Verify `device_neighbors` returns real shared-device rings — that's the HHG-014 story
   and the Innovation score
4. Cross-check the derived `card_id` against the real ones in `case_pack.csv`
5. Demo video

## Known gaps worth fixing if there's time

- **Only 3 of 20 offline fixtures exist.** Fine once real data lands; add more if we want a
  fuller offline demo.
- **`tokens: 0` in every answer file.** Honest — no LLM is called. Would change if we wire
  one for narrative text.
- **UI approve/reject doesn't persist.** Local state only. Correct scope, but worth knowing
  before demoing it.
- **Nobody has looked at the UI in a browser.** It builds and the DOM has the right content,
  but no Playwright was available, so the visual layout at 390/768/1440px is unverified.
- **`similar_prior_cases` confirming/disconfirming split in the UI** is a text heuristic —
  the answer schema has no structured field for a prior case's outcome.

## Before submitting — one shot, no resubmissions

- [ ] All 20 files in `cases/`, `python -m src.answer.validator cases/` exits clean
- [ ] Verdict spread looks sane (not 20 frauds)
- [ ] Repo is public — check in an incognito window
- [ ] Demo video uploaded, link works
- [ ] Blog post published, link works
- [ ] Social post live, tags @TigerGraphDB
- [ ] **Freeze the repo an hour before submitting** — a late push that breaks the build
      can't be undone
- [ ] One person submits, other two have confirmed all four links

Form: https://forms.gle/yxXzqSULGgZ9VUF56
Deadline: **24 Sept, 11:59 PM IST**
