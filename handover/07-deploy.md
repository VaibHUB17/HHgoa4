# 7. Deploy and demo

How to run this locally, host the UI so judges can click it, and record the demo without
anything falling over.

Every command here was run on this machine. Where something is untested, it says so.

---

## The three ways to run it

| Mode | Needs | Use it for |
|---|---|---|
| **Offline** | nothing | Development, tests, a demo when Savanna is down |
| **Local live** | Savanna workspace + dataset | Producing the real 20 answer files |
| **Hosted UI** | the 20 answer files | Giving judges a link they can click |

---

## 1. Offline — works right now

No database, no dataset, no credentials.

```bash
pip install -r requirements.txt
python -m pytest tests/ -q
```
```
125 passed
```

Run all 20 cases:

```bash
python -m src.agent.run --all --offline \
  --data-dir tests/fixtures --fixture-dir tests/fixtures/offline --out /tmp/out
```

You'll see a loud warning per case. **That's correct** — these fixtures are fabricated, and
the validator rejects any answer file built from them. Read the synthetic-data guard section
in [05-whats-left.md](05-whats-left.md).

This mode is our insurance. If Savanna is unreachable on demo day, the pipeline still
demonstrably runs, and you say plainly that it's fixture data.

---

## 2. Local live — the real thing

### Prerequisites

- Python 3.11+
- Node 20+ (for the UI)
- A Savanna workspace: https://savanna.tgcloud.io
- The four organizer CSVs in `data/`

### Setup

```bash
cp .env.example .env
```

Fill in:
```env
TG_HOST=https://<your-workspace>.i.tgcloud.io   # NOT savanna.tgcloud.io
TG_GRAPHNAME=FraudGraph
TG_TGCLOUD=true
TG_API_TOKEN=<from the workspace connection panel>
```

**Turn on Auto Suspend immediately** (Workspace → Edit → Advanced Settings). Idle time burns
the free credits overnight.

### Bring the graph up

```bash
python -m scripts.setup_graph --check    # connection only, changes nothing
python -m scripts.setup_graph            # schema + queries + verification
python -m src.graph.load --data-dir ./data
```

**Budget an hour for `setup_graph`, not ten minutes.** The GSQL has never run on a live
instance. The script reports the exact statement the engine rejected rather than failing
vaguely. Nested subqueries inside `POST-ACCUM`/`FOREACH` are the usual version
incompatibility.

Loading 590k transactions takes a few minutes via the GSQL loading job. It is not
row-by-row REST, which would take hours.

### Produce the submission

```bash
python -m src.agent.run --all          # writes cases/*.json
python -m src.answer.validator cases/  # must print 0 violations
```

If the validator says "generated from synthetic fixtures", you ran the offline path by
mistake. Drop `--offline`.

---

## 3. Hosted UI — the link for judges

The UI reads `cases/*.json` **at build time** and falls back to `ui/fixtures/` when that
directory is empty. So the order matters: generate the answer files first, then build.

**Verified locally:** with 20 files in `cases/`, `npm run build` pre-renders all 20 case
pages (24 routes total). With `cases/` empty it generates 3 fixture pages and shows a
"Fixture data" banner.

```bash
# 1. make sure cases/ holds the REAL answer files
ls cases/*.json | wc -l        # expect 20

# 2. build
cd ui
npm install
npm run build
npm start                      # http://localhost:3000
```

### Deploying to Vercel

Untested — nobody has deployed this yet. The shape of it:

```bash
cd ui
npx vercel
```

Two things that will bite:

1. **Root directory must be `ui/`**, not the repo root.
2. **`cases/` lives one level above `ui/`.** `data.ts` resolves
   `path.join(process.cwd(), "..", "cases")`. Vercel only uploads the project root by
   default, so the parent directory won't be there and the build will silently fall back to
   fixtures — which the banner will announce on the deployed site.

   Fix before deploying: copy the answer files inside `ui/` and point at them, e.g.
   `cp -r cases ui/public-cases` and adjust `CASES_DIR`. Or just accept that the hosted
   version shows fixtures and demo the real thing locally.

**Recommendation:** don't deploy under time pressure. A local `npm start` during the
recording is lower risk, and the submission asks for a repo and a video, not a live URL.
If you do deploy, check the banner on the live site says nothing about fixtures.

---

## Demo-day checklist

Work through this in order, an hour before recording.

**Infrastructure**
- [ ] Resume the Savanna workspace — it takes 1–2 minutes to wake. Do it ten minutes early.
- [ ] `python -m scripts.setup_graph --check` returns clean
- [ ] `python -m src.answer.validator cases/` → 0 violations

**Content**
- [ ] `ls cases/*.json | wc -l` → 20
- [ ] No file contains `_synthetic_source` — `grep -l _synthetic_source cases/*.json` returns nothing
- [ ] Verdict spread is sane, not 20 frauds. Roughly half should be legitimate.
- [ ] Open one case and read it as a judge would. Does the summary make sense?

**UI**
- [ ] `cd ui && npm run build` passes
- [ ] The banner does **not** say "Fixture data"
- [ ] Case detail shows the before/after delta with different actions in each column

**Recording**
- [ ] Browser zoom at 100%, window ~1440px wide
- [ ] Terminal font large enough to read in a compressed video
- [ ] Close notifications and anything with personal data in it
- [ ] Have the case IDs ready: a legitimate one, HHG-017 for the flip, HHG-014 for the ring

Beat order and narration are in [../docs/DEMO_SCRIPT.md](../docs/DEMO_SCRIPT.md).

---

## If something breaks mid-demo

**Savanna won't wake or times out.** Switch to offline and say so:
```bash
python -m src.agent.run --case HHG-017 --offline \
  --data-dir tests/fixtures --fixture-dir tests/fixtures/offline --out /tmp/demo
```
Naming it honestly costs you less than a judge noticing.

**The UI shows fixture data.** `cases/` was empty when you built. Regenerate and rebuild —
the UI reads at build time, not runtime.

**A GSQL query fails on the live instance.** Expected the first time. `setup_graph` names
the failing statement. Nested subqueries are the usual culprit; flatten into two chained
`SELECT` blocks.

**401 mid-session.** Tokens expire after about an hour. `connection.py` retries; if it
doesn't, regenerate the secret.

---

## Submission — one shot, no resubmissions

Form: https://forms.gle/yxXzqSULGgZ9VUF56
Deadline: **24 Sept, 11:59 PM IST**

Have all four ready before opening the form:
- [ ] Public repo — check it in an incognito window
- [ ] Demo video link, opens for someone not logged in
- [ ] Blog post link
- [ ] Social post link, tagging @TigerGraphDB

**Freeze the repo an hour before submitting.** A late push that breaks the build can't be
undone. One person submits; the other two confirm all four links work first.
