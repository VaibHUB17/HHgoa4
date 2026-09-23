# 5. What's left

## Honest status

| Component | State |
|---|---|
| TigerGraph schema + 6 GSQL queries | written, connection configured for Cloud Savanna |
| One-command graph setup | `python -m scripts.setup_graph` — creates schema, installs queries, verifies |
| TigerGraph MCP integration | **done** — `src/graph/mcp.py` bridges 69 tools, verified via `--check` |
| CSV loaders | written, ready for GSQL bulk loading |
| Dataset arrival | **downloaded** (`HHGOA_IEEE_Dataset/`) — unblocked! |
| 6 pattern detectors | done, 21 tests |
| Policy engine R1–R10 | done, 27 tests, boundaries verified |
| Evidence ledger | done, calibrated |
| LangGraph loop + approval gate | done, before/after delta verified working |
| Case memory (two-pool retrieval) | done, 15 tests |
| SAR generator | done, FinCEN structure |
| Answer schema + validator | done |
| ML scaffold & baseline | features, time-split training, calibration, 13 tests |
| Undocumented pattern discovery | **completed by Bhavya** — proxy rings & $500 structuring identified |
| Analyst UI | builds, renders, running on localhost:3000 |
| Runner CLI | done, **all 20 cases run clean** |
| Blog post | drafted — `docs/BLOG.md` |
| Demo script | drafted — `docs/DEMO_SCRIPT.md` |
| Social post | drafted — `docs/SOCIAL.md` |
| **20 real answer files** | awaiting execution against real dataset |
| Demo video | not recorded |

**125 tests pass (100%).**

## Dataset Status: Unblocked!
The full dataset (590k transactions, 144k identities, 5,565 closed cases, 20 exam cases) has been downloaded into `HHGOA_IEEE_Dataset/`.

## Immediate Focus
1. **Load data to TigerGraph Savanna:** Karan runs `scripts.setup_graph` and GSQL loading job.
2. **Train ML baseline:** Bhavya runs `python -m src.ml.train --data-dir ./data`.
3. **Run 20 cases:** Run `python -m src.agent.run --all --data-dir ./data --out cases/` and validate.
4. **Record 3–4 min demo video:** Using the running Next.js UI.

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

### Bhavya — Graph algorithms, Case Memory, Vector Embeddings

Scope updated on 2026-09-24 following Devanshu's explicit Discord advice ("skip the GNN... use TigerGraph's built-in graph algorithms + vector search"):

1. **Task 0: `card_id` derivation check [COMPLETED by Bhavya]**
   Fixed `derive_card_id()` in `src/graph/load.py` to rank by ascending transaction count, reaching 19/20 verified matches against `case_pack.csv`.
2. **Task 3: Read `undocumented` notes [COMPLETED by Bhavya]**
   Identified the two hidden typologies (anonymous proxy rings and $500 velocity structuring / threshold evasion matching HHG-006).
3. **Task 1: Skip the GNN (Per Devanshu's guidance)**
   The organizer explicitly stated: *"On the GNN: I would skip it. It just gives you another score like risk_score, and we don't score a model, we score the investigation and the reasoning. Use TigerGraph's built-in graph algorithms... plus vector search."* GNN seam dropped to focus on scored criteria.
4. **Task 1a: TigerGraph Built-in Graph Algorithms (Louvain & Connected Components)**
   Run `tg_louvain` and `tg_connected_components` on `Card` and `DeviceProfile` to detect shared-device fraud rings (the HHG-014 story and Innovation score).
5. **Task 1b / 2: Vector Search over Case Memory**
   Embed `closed_cases_history.csv` analyst notes using `text-embedding-3-small` (1536-d matching `ClosedCase.notesEmb` in `src/graph/schema.gsql`) and implement two-pool retrieval (top-3 fraud, top-2 cleared).

Files: `src/rag/`, `src/graph/`, `notebooks/`

### Karan — graph, TigerGraph Cloud, demo

1. Savanna workspace + load the data
2. Get the GSQL actually running, fix whatever the live parser rejects
3. Verify `device_neighbors` returns real shared-device rings — that's the HHG-014 story
   and the Innovation score
4. Coordinate with Bhavya on running graph algorithms (Louvain) and embedding loading
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
