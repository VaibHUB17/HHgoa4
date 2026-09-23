# Karan — submission readiness (queue updated 2026-09-24)

**Read this section first — your scope changed.** Since you haven't been reachable, all the
coding work below (Savanna setup, schema, loading, queries, detectors) has been
consolidated into `docs/VAIBHAV.md` so it happens in one place without duplicated or
conflicting effort — see its P0 section, which absorbs everything in Parts 1–5 of this file.
The technical content below is kept as reference/backup, not deleted — if you do pick this
back up, coordinate with Vaibhav on what's already done before touching `src/graph/` or
`src/detectors/` so work doesn't collide.

**Your active queue now is submission readiness** — the things that are genuinely nobody's
job until someone claims them, and that don't block on anything except the real answer
files existing (which P0 in `docs/VAIBHAV.md` produces):

1. **UI verification in an actual browser.** `handover/05-whats-left.md` flags this
   explicitly: nobody has looked at the UI in a browser — it builds and the DOM has the
   right content, but the visual layout at 390px (mobile), 768px (tablet), and 1440px
   (desktop) has never been checked. Run `cd ui && npm install && npm run dev`, open
   http://localhost:3000, and actually look at it at all three widths. Fix anything broken;
   flag anything you're unsure about rather than shipping it silently wrong.
2. **Demo video (3–5 min).** Not recorded yet. Show the agent working end to end on at
   least one case — the before/after next-best-action change is the single most
   important beat to include (it's 25% of the rubric), plus one legitimate case being
   correctly cleared (proves the agent doesn't just block everything). `docs/DEMO_SCRIPT.md`
   has a draft outline — use it, don't start from a blank page.
3. **Blog post — finalize with real data.** `docs/BLOG.md` is drafted but needs real
   numbers and screenshots once `cases/` has genuine output from a live TigerGraph run,
   not fixture placeholders. Don't publish until P0 in `docs/VAIBHAV.md` is confirmed green.
4. **Social post.** Publish on X or LinkedIn, must tag **@TigerGraphDB**, link to the blog
   post or demo. `docs/SOCIAL.md` has a draft.
5. **The submission form — do NOT touch this until two things are both true.**
   https://forms.gle/yxXzqSULGgZ9VUF56 is a **no-resubmission** form: submitting early on a
   stale understanding of the deadline is unrecoverable, and worse than any other mistake
   in this document. Wait until:
   (a) P0 through P3 in `docs/VAIBHAV.md` are all green, **and**
   (b) the extended deadline is confirmed **in writing, directly from Devanshu** — every
   doc in this repo still says 24 Sept 11:59 PM IST, and the extension mentioned in this
   session's chat has not been independently verified anywhere. Get that confirmation
   before this item becomes actionable at all.
   Once both hold: **one person submits** (team lead), after the other two confirm all four
   links (repo, video, blog, social) actually work.

None of these five block on you personally doing the coding work — they're yours to own in
parallel with whatever's happening in `docs/VAIBHAV.md`. If you come back before the
technical work is done, the highest-value thing to pick up is verifying `device_neighbors`
against the live graph (Part 4 below, the HHG-014 ring story) since that's the single
query most likely to need a live-instance fix, per its own version-trap note.

---

## Reference — original scope, kept for continuity if you pick graph work back up

You own TigerGraph and everything that reads from it.

**In one line:** get 590k transactions into a graph, and write the queries that find fraud
patterns a row-by-row classifier can't see.

---

## What you hand back

```python
def investigate(case_id: str) -> dict:
    """{'findings': [Finding], 'graph_evidence': [QueryResult], 'similar_cases': {...}}"""
```

Vaibhav's policy engine consumes it. Every `QueryResult` must carry the query name+params
(`ref`) and the entity IDs it rests on — the answer file's `evidence[]` requires that
provenance, and if you drop it the agent can't fill the field.

---

## Part 1 — Savanna setup (do this first, everything blocks on it)

Sign up at https://savanna.tgcloud.io, create a workspace.

**Turn on Auto Suspend immediately** (Workspace → Edit → Advanced Settings), or idle
overnight burns our free credits. It takes 1–2 minutes to resume — **resume it ten minutes
before the demo, not at demo time.**

### Connection Settings (.env) — Pure TigerGraph Cloud (Savanna)
We are running on TigerGraph Cloud (Savanna at https://tgcloud.io). No local Docker fallback.

Here are the exact keys required in `.env`:
```env
# TigerGraph Cloud (Savanna)
TG_HOST=https://YOUR-CLUSTER-URL.i.tgcloud.io
TG_GRAPH=FraudInvestigation
TG_USERNAME=tigergraph
TG_PASSWORD=your_password
TG_SECRET=YOUR_GSQL_SECRET
TG_API_TOKEN=
TG_TGCLOUD=true
```

**How to get these from tgcloud.io:**
1. **TG_HOST**: Go to My Solutions / My Graphs → Click your solution → Copy URL (e.g. `https://fraud-detection-xxxx.i.tgcloud.io`). **Critical:** Do NOT include a trailing slash `/`.
2. **TG_GRAPH**: The name of the graph you create in Savanna (e.g. `FraudInvestigation`).
3. **TG_SECRET**: Under Solution Details / Security / GraphStudio, create and copy your GSQL Secret.
4. **TG_USERNAME** & **TG_PASSWORD**: Your TigerGraph Cloud database user and password.
5. **TG_TGCLOUD**: Set to `true`.

### TigerGraph MCP Integration
The agent interacts with the graph through the official TigerGraph MCP server (`tigergraph-mcp`).
`src/graph/mcp.py` bridges MCP tools into our LangGraph pipeline.

1. Test MCP configuration directly:
```bash
python -m src.graph.mcp --check
```
2. Run standalone MCP server:
```bash
tigergraph-mcp --env-file .env --allowed-tools read-only -vv
```
*`--allowed-tools read-only` ensures the investigation phase cannot mutate graph state, proving strict policy controls to judges.*

---

## Part 2 — loading the data

`transactions.csv` is ~708MB with **393 columns**. Don't load all of them.

Three tiers:

| Tier | Columns | Where it goes |
|---|---|---|
| 1 — structure | TransactionID, amount, ts, channel, risk_score, ProductCD, card1–6, addr1/2, dist1/2, emails, customer_id + identity's DeviceType/DeviceInfo/id_15/id_23/id_30/id_31/id_33/id_34 | TigerGraph |
| 2 — evidence scalars | C1–C14, D1–D15, M1–M9 | TigerGraph, as Transaction attributes |
| 3 — opaque | **V1–V339** | **Parquet sidecar, NOT the graph** |

The V-columns are 85% of the file, have no published meaning, and the README explicitly says
*"say so in your evidence rather than pretending to know what V127 means."* They can't be
cited as evidence, so they don't earn their place in the graph.

**Use a GSQL LOADING JOB, not row-by-row REST.** Confirmed directly by Devanshu on Discord:
*"Don't do row-by-row REST. Use a GSQL loading job, TigerGraph's bulk path. 600K rows takes
minutes."* Savanna's workspace Load Data tool will build one for you from an uploaded CSV, or
go through MCP with `tigergraph__create_loading_job` + `run_loading_job_with_file`.

Use pyTigerGraph upsert **only** for incremental writes (the agent creating a Case vertex).

Pre-slice with pandas before uploading — `dtype` map with float32 and category types, read in
chunks. Full code is in `RESEARCH.md` §2.2.

---

## Part 3 — schema

Start from the README's suggested schema, then add five things it leaves out:

| Add | Why |
|---|---|
| `RECIPIENT_EMAIL` edge (`R_emaildomain`) | R6 names "the same recipient email" as a shared-origin signal |
| `ProductCategory` vertex | R5 and pattern 2 both ask "a category this card has never used" — 1 hop instead of a scan |
| `country_code` on BillingRegion (`addr2`) | `addr1` is only unique within a country |
| `dist1`/`dist2` as Transaction scalars | distance-from-home corroborates out-of-region |
| C/D/M columns as Transaction scalars | real signals the agent should be able to cite |

**DeviceProfile key** = `DeviceInfo | id_30 | id_31 | id_33`, built from whatever subset is
present, with a `completeness` count (1–4) so a 2-field match can be discounted.

> **Trap that would poison every ring query:** never coalesce an all-missing key to the
> string `"None | None"`. That clusters every device-less row into one giant fake ring.

Remember `identity.csv` only covers online transactions — a missing identity row is the
`in_person` signal, not a data problem.

Full DDL in `RESEARCH.md` §2.3.

---

## Part 4 — the queries

Four core installed queries (full GSQL in `RESEARCH.md` §2.4):

1. **`card_window(card_id, anchor, hours)`** — time-ordered transactions around the flagged
   one. Feeds card-testing detection.
2. **`device_neighbors(device_id)`** — every other card/customer on the same device profile,
   plus any closed cases touching them. **This is the ring query.** HHG-014's trigger is
   literally an analyst saying several cards share a device profile. Get this one right; it
   carries the Innovation score.
3. **`customer_baseline(customer_id)`** — the cardholder's normal: regions, product codes,
   amount percentiles, channels. Needed to judge whether anything is out of character.
4. **`prior_cases_for_entities(cards, devices, regions)`** — case memory retrieval.

Plus `write_case_to_graph()` so the agent's own cases become memory for later ones.

> **Version trap:** nested subqueries inside `POST-ACCUM`/`FOREACH` are the thing most
> likely to need reshaping between GSQL syntax versions. Test these on day one, not demo
> day. `SHOW QUERY <name>` after a trial install tells you the parsed syntax version.

---

## Part 5 — the six detectors

Pure functions over query results. Each returns `Finding(pattern, evidence, weight_keys,
entity_ids, ref)`.

| Detector | Fires when |
|---|---|
| `card_testing` | ≥3 online auths under $5 within 1hr on one card, then a larger purchase |
| `cnp_burst` | 2–4 unusual online purchases within 48h, product category outside the card's history |
| `new_device` | `id_15 == 'New'` for this account, stronger with `id_23` proxy flag |
| `out_of_region` | `addr1` outside the customer's historical set **and home region still active concurrently** |
| `account_takeover` | multiple cards of one customer each break their own history at once |
| `shared_origin` | same device / region / recipient email across 2+ customers in a window (R6, and the route to `undocumented`) |

Two subtleties that decide real cases:

- **Out-of-region:** several days of purchases in one new region is a *trip*, not a clone.
  The fraud tell is the home region staying active at the same time. Without that check
  you'll flag every holiday.
- **Account takeover is customer-centric** where the others are card-centric. That's the
  structural discriminator.

**Write the near-miss tests, not just the positive ones.** Two small auths instead of three
must not fire. A new region without concurrent home activity must not fire. Half the exam
cases are legitimate — the false-positive tests are the ones protecting our score.

---

## Files you own

```
src/graph/schema.gsql
src/graph/queries.gsql
src/graph/load.py
src/graph/connection.py
src/detectors/patterns.py
tests/test_detectors.py
```

Don't edit outside these — Vaibhav and Bhavya are working concurrently.

---

## pyTigerGraph gotchas that will cost you an hour each

- **Tokens expire (~1h).** You get silent 401s mid-session. Wrap calls in a retry that
  re-calls `getToken(secret)`.
- **`timeout=` is milliseconds**, the server default is 16 *seconds*. Raise it for cold
  workspace runs.
- **`attributes={graph_attr: df_column}`** — reversing this map silently upserts garbage
  instead of erroring.
- **No DDL wrapper** — schema changes go through `conn.gsql(open("schema.gsql").read())`.
- Installed (compiled) queries for anything called repeatedly; `runInterpretedQuery` is for
  dev iteration only.

---

## Order of work

1. Savanna up + Auto Suspend on
2. Schema loaded, 1000-row sample in, sanity-check a traversal
3. Full load, then verify counts (590,742 transactions / 144,432 identity / 5,565 cases)
4. The four queries, installed and tested from Python
5. Detectors with near-miss tests
6. `write_case_to_graph`

Sanity check once loaded: run `device_neighbors` on a device that appears on several cards
and confirm it returns the other cards. If that works, the ring story works.
