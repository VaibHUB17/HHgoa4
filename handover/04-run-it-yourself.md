# 4. Run it yourself

Every command here was run on this machine and produced the output shown. If one fails for
you, that's a real bug — say so rather than working around it.

## Setup (once)

```bash
git clone https://github.com/VaibHUB17/HHgoa4.git
cd HHgoa4

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
```

## Prove it works — no database, no dataset needed

This is the fastest way to see the whole thing move. It runs against captured fixtures, so
it works right now with nothing set up.

```bash
python -m pytest tests/ -q
```
```
105 passed in 1.22s
```

Now run a real investigation:

```bash
python -m src.agent.run --case HHG-017 --offline \
  --data-dir tests/fixtures --fixture-dir tests/fixtures/offline --out /tmp/out
```
```
Running 1 case(s) in opened_at order so an earlier case's evidence is
retrievable as case memory by a later one: HHG-017
HHG-017: wrote /tmp/out/HHG-017.json (OK)
```

Check the output:

```bash
python -m src.answer.validator /tmp/out
```
```
HHG-017.json: OK

1 file(s) checked, 0 total violation(s)
```

Three fixture cases exist — `HHG-017` (fraud), `HHG-003` (legitimate), `HHG-020`
(uncertain). Run all three to see the different outcomes.

## See the thing that earns 25% of the grade

```bash
python -c "
import json
a = json.load(open('/tmp/out/HHG-017.json'))
n = a['next_best_actions']
print('BEFORE:', [x['action'] for x in n['initial']])
print('AFTER :', [x['action'] for x in n['final']])
print('WHY   :', n['what_changed'])
"
```

You should see `VERIFY_WITH_CUSTOMER` before and `BLOCK_CARD` after. That change, driven by
a simulated customer denial, is the core of the submission.

## The UI

```bash
cd ui
npm install
npm run dev
```

Open http://localhost:3000. It'll show a banner saying "Fixture data" because `cases/`
is empty — that's deliberate, so nobody demos fake data by accident.

## Running against real data (once we have it)

**Step 1 — get the dataset.** Put the four organizer CSVs in `data/`:
`transactions.csv`, `identity.csv`, `closed_cases_history.csv`, `case_pack.csv`.
They're ~700MB and gitignored. `data/README.md` has a verification snippet — run it, it
cross-checks the `card_id` format against our derivation.

**Step 2 — get a Savanna workspace.** https://savanna.tgcloud.io, create a workspace, then:

```bash
cp .env.example .env
# fill in TG_HOST (the workspace URL, NOT savanna.tgcloud.io) and TG_API_TOKEN
```

Turn on **Auto Suspend** immediately (Workspace → Edit → Advanced Settings) or idle time
burns the free credits. It takes 1–2 min to resume, so wake it ten minutes before the demo,
not at demo time.

**Step 3 — load the graph.**

```bash
python -m src.graph.load --data-dir ./data
```

**Step 4 — run for real.**

```bash
python -m src.agent.run --all
python -m src.answer.validator cases/
```

## Make targets

```bash
make test        # pytest
make run-one     # single case
make run-all     # all 20
make validate    # check the answer files
make ui          # start the console
```

## When something breaks

**`FileNotFoundError: case_pack.csv not found in .../data`** — expected until the dataset
is downloaded. Add `--data-dir tests/fixtures` to use the case list extracted from the brief.

**`offline fixture missing for case HHG-0XX`** — only 3 of 20 offline fixtures exist. Use
`--case` with one of HHG-017 / HHG-003 / HHG-020, or run against real data.

**401 from TigerGraph mid-session** — tokens expire after about an hour.
`connection.py` retries automatically; if it doesn't, regenerate the secret.

**`npx tsc --noEmit` fails on `PageProps`** — run `npx next typegen` once first. Next 16
generates route types at build time.
