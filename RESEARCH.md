# HHGOA — Fraud Investigation Agent: Research & Build Plan

> Working doc for Karan / Vaibhav / Bhavya. Everything here is derived from the real
> `README.md` in this repo plus research. **Read `README.md` first** — it is the spec,
> and it is unusually complete: it defines the schema, the policy, the answer format,
> and all 20 exam cases.

**Status:** spine written; research sections being filled by parallel agents.

---

## 0. TL;DR — what we are actually building

An agent that takes one of 20 alerts and emits **one JSON file per case** into `cases/`.
Each file has three parts: **a case**, **a SAR (only when policy demands it)**, and
**a next-best-action pair (before evidence request / after)**. The case must *also* be
written into TigerGraph as memory.

The thing being tested is not "can you detect fraud." It's:

1. Can you be **right**, including being right that nothing happened — *half the cases are legitimate*.
2. Can you **change your mind** when evidence arrives, and show the delta.
3. Can you stay **inside the policy**, citing rule numbers and routing approvals correctly.

50% of the rubric is `Investigation accuracy` (25%) + `Next best action` (25%).

### The three ways this is lost

| Failure | Why it happens | Guard |
|---|---|---|
| Block everything | Risk score treated as verdict | README: "Above 0.7, most flagged transactions turn out to be legitimate." Calibrate against closed cases. |
| `initial` == `final` on every case | No real evidence loop | Force an evidence request on every case in the 0.30–0.85 band |
| Made-up IDs | LLM hallucinating txn/case IDs | Validate every ID in the output against the CSVs before writing the file. Non-negotiable. |

---

## 1. The spec, compressed

### 1.1 Data files

| File | Rows | Notes |
|---|---|---|
| `transactions.csv` | 590,742 | 393 original Vesta cols + `customer_id`, `ts`, `channel`, `risk_score`. ~708 MB. **No fraud flag.** |
| `identity.csv` | 144,432 | 41 cols, joins on `TransactionID`. Online transactions only. |
| `closed_cases_history.csv` | 5,565 | Jul–Oct. 4,665 `confirmed_fraud`, 900 `cleared`. **This is the agent's starting memory.** |
| `case_pack.csv` | 20 | Nov–Dec. The exam. |

Added columns: `customer_id` (e.g. `C01234`, one customer → several cards, card ids `C01234-K1`),
`ts` (real timestamp, 2016-07-02 → 2016-12-31), `channel` (`in_person` = ProductCD `W`, no identity
record / `online` = everything else), `risk_score` (0–1, model output).

> **Disqualification rule:** `TransactionID`, `card1`, `TransactionDT`, `TransactionAmt` were
> disguised. Do **not** use the public Kaggle IEEE-CIS files to recover outcomes. Column
> *semantics* research is fine; *joining* to the public file is not.

### 1.2 The 14 actions (exact identifiers — must match)

`ALLOW_TRANSACTION` · `DECLINE_TRANSACTION` · `MONITOR_CARD` · `MONITOR_CONNECTED_CARDS` ·
`WARN_CUSTOMER` · `VERIFY_WITH_CUSTOMER` · `STEP_UP_AUTH` · `BLOCK_CARD` · `BLOCK_ALL_CARDS` ·
`GENERATE_REPORT` · `CREATE_CASE` · `FILE_REPORT` · `ESCALATE_TO_ANALYST` · `CLOSE_NO_FRAUD`

### 1.3 Approval routing

| Route | Applies to |
|---|---|
| `auto` | ALLOW_TRANSACTION, MONITOR_CARD, MONITOR_CONNECTED_CARDS, WARN_CUSTOMER, VERIFY_WITH_CUSTOMER, STEP_UP_AUTH, GENERATE_REPORT, CREATE_CASE, ESCALATE_TO_ANALYST, CLOSE_NO_FRAUD |
| `L1` | DECLINE_TRANSACTION; BLOCK_CARD when exposure ≤ $2,500 |
| `L2` | BLOCK_CARD when exposure > $2,500; BLOCK_ALL_CARDS always; FILE_REPORT always |

The agent **executes** only `auto`. `L1`/`L2` are recommended with the route stated.

### 1.4 The decision thresholds (these are given, not chosen)

| Threshold | Meaning | Source |
|---|---|---|
| `p < 0.70` on a single signal | Must `VERIFY_WITH_CUSTOMER` / `STEP_UP_AUTH` before any block | R1 |
| `p ≥ 0.30` | Open a case | §3a |
| `uncertain` + exposure > $500 | `ESCALATE_TO_ANALYST` | R8 |
| `p ≥ 0.85` or `p ≤ 0.15`, with ≥2 independent evidence items | Stop investigating | §6 |
| exposure > $1,000 **or** shared device/region/other-customer fraud **or** coordinated/undocumented | SAR required | §3a |
| exposure > $2,500 | BLOCK_CARD escalates L1 → L2 | §2 |

### 1.5 Rules R1–R10 (paraphrased; cite by number in every `reason`)

- **R1** Weak single signal + p < 0.70 → verify/step-up before blocking.
- **R2** Customer denies → `BLOCK_CARD` + `CREATE_CASE`; add `FILE_REPORT` if exposure > $1,000 or shared device / other card's fraud.
- **R3** Customer confirms → `CLOSE_NO_FRAUD`.
- **R4** No reply in 24h → `MONITOR_CARD` + `DECLINE_TRANSACTION`; escalate if exposure > $500.
- **R5** Card testing (3+ small online auths within an hour, then larger) → `DECLINE_TRANSACTION` + `STEP_UP_AUTH`; if a >$100 purchase already cleared → `BLOCK_CARD`.
- **R6** Shared origin across cards → name the shared element, `CREATE_CASE` + `FILE_REPORT` + `MONITOR_CONNECTED_CARDS`.
- **R7** Disputed but matches the customer's own recurring pattern → `CREATE_CASE` + `VERIFY_WITH_CUSTOMER` + `WARN_CUSTOMER`. **Do not block.**
- **R8** Uncertain + exposure > $500, or conflicting evidence → `ESCALATE_TO_ANALYST`.
- **R9** Undocumented pattern with coordinated/repeated abuse → `CREATE_CASE` + `FILE_REPORT` + `ESCALATE_TO_ANALYST`, describe in own words.
- **R10** Never `BLOCK_ALL_CARDS` unless ≥2 cards confirmed fraud or credentials confirmed compromised.

> R7 is the trap. Several of the 9 `customer_report` cases are almost certainly legitimate
> recurring charges the customer forgot. An agent that blocks on every dispute fails R7 and
> bleeds accuracy.

### 1.6 Pattern enum

`card_testing` · `card_not_present_fraud` · `card_not_present_new_device` ·
`out_of_region_use` · `account_takeover` · `undocumented` · `none`

`undocumented` requires `pattern_description` (2–3 sentences). **Finding one is explicitly scored.**
The closed cases include `undocumented` rows whose `analyst_notes` the README tells us to read
carefully — that's where the unnamed pattern is described.

### 1.7 Graph schema (README's suggestion — our starting point)

**Vertices:** `Customer`, `Card`, `Transaction`, `DeviceProfile` (DeviceInfo + OS + browser + screen),
`EmailDomain`, `BillingRegion`, `ClosedCase`
*(+ our own `Case`, `Pattern`, `PolicyChunk` — see §3)*

**Edges:**
```
Customer    -OWNS->            Card
Card        -MADE->            Transaction
Transaction -FROM_DEVICE->     DeviceProfile      (online only, from identity.csv)
Transaction -PURCHASER_EMAIL-> EmailDomain
Transaction -BILLED_IN->       BillingRegion      (addr1)
Transaction -NEXT->            Transaction        (time-ordered within a card)
ClosedCase  -INVOLVES->        Transaction
ClosedCase  -ON_CARD->         Card
ClosedCase  -CONNECTED_TO->    Card
```

### 1.8 Answer file — required shape

`cases/<case_id>.json`, 20 files. **Missing fields score zero for that part.**

```
case_id
case {
  status                    open | closed_fraud | closed_legitimate | escalated
  verdict                   fraud | legitimate | uncertain
  fraud_probability         0-1   (scored for CALIBRATION, be honest)
  pattern                   <enum>
  pattern_description       required iff pattern == undocumented
  affected_txn_ids[]        every txn in the episode, incl. the flagged one
  first_suspicious_txn_id
  connected_card_ids[]
  connected_device_profiles[]
  exposure_usd              sum of |amount| over affected_txn_ids
  evidence[]                { claim, source: graph|document|customer|external, ref, entity_ids[] }
  similar_prior_cases[]     closed-case IDs actually retrieved, e.g. ["CC-0141"]
  summary                   2-6 sentences
  written_to_graph          bool
  graph_case_id
}
evidence_requests[]         { type: customer_validation|step_up_auth|analyst_info,
                              asked_after_step: int, assumed_response: str }
next_best_actions {
  initial[]                 { action, route, reason(cite Rn) }   BEFORE evidence came back
  final[]                   same shape                            AFTER assumed responses
  what_changed              1-2 sentences, or "nothing"
}
sar {
  file, reason, narrative (6-12 sentences), subjects[], total_amount_usd, activity_dates[2]
}
stop_reason
tool_calls, tokens, latency_s
```

Invariants to assert before writing any file:
- `sar.file == ("FILE_REPORT" in [a.action for a in final])`
- `verdict == legitimate` ⟹ `affected_txn_ids == []`, `exposure_usd == 0`, `sar.file == false`
- `exposure_usd == sum(|amt| for t in affected_txn_ids)`
- every ID exists in the dataset
- every `route` matches the §2 table given the exposure
- `evidence_requests == []` ⟹ `final == initial` and `what_changed == "nothing"`

### 1.9 The 20 cases

| Trigger | Count | Likely path |
|---|---|---|
| `risk_score` | 10 | R1 first — score alone is a single signal. Verify before block. |
| `customer_report` | 9 | R2 / R3 / R7 fork. Check recurring-charge history *before* believing the dispute. |
| `analyst_request` | 1 | HHG-014 — explicitly a shared-device ring. R6 + R9 territory. |

<!-- FILL: per-case triage table -->

---

## 2. TigerGraph

### 2.1 Savanna vs Community Edition → **use Savanna**

| | Savanna | Community Edition |
|---|---|---|
| Setup | signup at tgcloud.io, managed workspace, no install | Docker / bare Linux, request free dev license |
| Free tier | free credits, sizing ≈ 1.5× raw data loaded | unlimited, bounded by your laptop |
| Vector (v4.2+) | ships by default | must pull a ≥4.2 image specifically |
| Auto-suspend | Workspace → Edit → Advanced Settings | n/a |

590k rows is nothing for TigerGraph. Savanna wins on zero install friction and on shipping
v4.2 vectors by default, which we need for GraphRAG.

> **Two operational gotchas:** turn on Auto Suspend the moment you provision, or overnight
> idle burns credits. And a suspended workspace needs ~1–2 min to resume — **resume it 10
> minutes before the demo, not at demo time.**

Fallback if credits run out: Community Edition in Docker on whoever has the beefiest laptop.
Same GSQL/pyTigerGraph code, except vector features need a ≥4.2 image.

### 2.2 Loading — slice first, then bulk load

**Do not load all 393 columns.** Three tiers:

| Tier | Columns | Where |
|---|---|---|
| 1 — graph structure | TransactionID, TransactionAmt, ts, channel, risk_score, ProductCD, card1–card6, addr1, addr2, dist1, dist2, P_emaildomain, R_emaildomain, customer_id + identity's DeviceType, DeviceInfo, id_15, id_23, id_30, id_31, id_33, id_34 | TigerGraph |
| 2 — scalar evidence | C1–C14, D1–D15, M1–M9 (38 cols) | TigerGraph, as Transaction attrs |
| 3 — opaque | **V1–V339** | **Parquet sidecar, NOT the graph** |

V-columns are 85% of the column count, have no confirmed semantics, and the README itself
says *"say so in your evidence rather than pretending to know what V127 means."* They can't
be cited as evidence, so they don't belong in the graph. Parquet keyed on TransactionID;
pull on demand only if an anomaly pass flags something.

```python
dtype_map = {
    'TransactionID': 'int32', 'customer_id': 'category', 'card_id': 'category',
    'TransactionAmt': 'float32', 'risk_score': 'float32',
    'ProductCD': 'category', 'channel': 'category',
    **{f'card{i}': 'category' for i in range(1, 7)},
    'addr1': 'category', 'addr2': 'category',
    'dist1': 'float32', 'dist2': 'float32',
    'P_emaildomain': 'category', 'R_emaildomain': 'category',
    **{f'C{i}': 'float32' for i in range(1, 15)},    # NaNs present -> float not int
    **{f'D{i}': 'float32' for i in range(1, 16)},
    **{f'M{i}': 'category' for i in range(1, 10)},   # T/F/NaN -> category not object
}
chunks = pd.read_csv('transactions.csv', usecols=TIER12, dtype=dtype_map,
                     parse_dates=['ts'], chunksize=100_000)
slim = pd.concat(chunks, ignore_index=True)
slim.to_csv('txn_slim.csv', index=False)
```

float64→float32 halves numerics; object→category is 5–10× on the ~30 low-cardinality string
columns. Chunking caps peak RSS.

**GSQL `LOADING JOB` beats pyTigerGraph upsert for the bulk load** — it streams server-side
and parallelizes, where `upsertVertexDataFrame` pays HTTP batching overhead per chunk over
Savanna's network hop. Use upsert only for incremental writes (the agent creating a Case).

```gsql
CREATE LOADING JOB load_fraud FOR GRAPH FraudGraph {
  DEFINE FILENAME f_txn = "txn_slim.csv";

  LOAD f_txn TO VERTEX Transaction VALUES (
        $"TransactionID", $"ts", $"TransactionAmt",
        $"ProductCD", $"channel", $"risk_score"
      ) USING header="true", separator=",";

  LOAD f_txn TO VERTEX DeviceProfile VALUES (
        gsql_concat($"DeviceInfo","|",$"id_30","|",$"id_31","|",$"id_33")
      ) USING header="true", separator=",";
  LOAD f_txn TO VERTEX EmailDomain   VALUES ($"P_emaildomain") USING header="true";
  LOAD f_txn TO VERTEX BillingRegion VALUES ($"addr1")         USING header="true";

  LOAD f_txn TO EDGE MADE            VALUES ($"card_id", $"TransactionID") USING header="true";
  LOAD f_txn TO EDGE FROM_DEVICE     VALUES ($"TransactionID",
        gsql_concat($"DeviceInfo","|",$"id_30","|",$"id_31","|",$"id_33")) USING header="true";
  LOAD f_txn TO EDGE PURCHASER_EMAIL VALUES ($"TransactionID", $"P_emaildomain") USING header="true";
  LOAD f_txn TO EDGE BILLED_IN       VALUES ($"TransactionID", $"addr1") USING header="true";
}
RUN LOADING JOB load_fraud
```

`Transaction -NEXT-> Transaction` is **derived, not loaded** — build it post-load with a GSQL
query that sorts each card's transactions by `ts` and links consecutive pairs.

### 2.3 Schema DDL

```gsql
CREATE VERTEX Customer      (PRIMARY_ID customer_id STRING)
CREATE VERTEX Card          (PRIMARY_ID card_id STRING, card4 STRING, card6 STRING)
CREATE VERTEX Transaction   (PRIMARY_ID txn_id STRING, ts DATETIME, amount DOUBLE,
                             product_cd STRING, channel STRING, risk_score DOUBLE,
                             dist1 DOUBLE, dist2 DOUBLE
                             /* + selected C*/D*/M* as scalars */)
CREATE VERTEX DeviceProfile (PRIMARY_ID device_key STRING, completeness INT)
CREATE VERTEX EmailDomain   (PRIMARY_ID domain STRING)
CREATE VERTEX BillingRegion (PRIMARY_ID region_id STRING, country_code STRING)
CREATE VERTEX ProductCategory (PRIMARY_ID product_cd STRING)
CREATE VERTEX ClosedCase    (PRIMARY_ID case_id STRING, outcome STRING, pattern STRING,
                             exposure_usd DOUBLE, analyst_notes STRING,
                             opened_at DATETIME, closed_at DATETIME)
CREATE VERTEX Case          (PRIMARY_ID case_id STRING, /* same shape, agent-written */ ...)

CREATE DIRECTED EDGE OWNS            (FROM Customer, TO Card)              WITH REVERSE_EDGE="OWNED_BY"
CREATE DIRECTED EDGE MADE            (FROM Card, TO Transaction)           WITH REVERSE_EDGE="MADE_BY"
CREATE DIRECTED EDGE FROM_DEVICE     (FROM Transaction, TO DeviceProfile)  WITH REVERSE_EDGE="DEVICE_OF"
CREATE DIRECTED EDGE PURCHASER_EMAIL (FROM Transaction, TO EmailDomain)    WITH REVERSE_EDGE="EMAIL_OF"
CREATE DIRECTED EDGE RECIPIENT_EMAIL (FROM Transaction, TO EmailDomain)    WITH REVERSE_EDGE="RECIPIENT_OF"
CREATE DIRECTED EDGE BILLED_IN       (FROM Transaction, TO BillingRegion)  WITH REVERSE_EDGE="REGION_OF"
CREATE DIRECTED EDGE IN_CATEGORY     (FROM Transaction, TO ProductCategory) WITH REVERSE_EDGE="CATEGORY_OF"
CREATE DIRECTED EDGE NEXT            (FROM Transaction, TO Transaction)
CREATE DIRECTED EDGE INVOLVES        (FROM ClosedCase, TO Transaction)     WITH REVERSE_EDGE="INVOLVED_IN"
CREATE DIRECTED EDGE ON_CARD         (FROM ClosedCase, TO Card)            WITH REVERSE_EDGE="HAS_CASE"
CREATE DIRECTED EDGE CONNECTED_TO    (FROM ClosedCase, TO Card)            WITH REVERSE_EDGE="CONNECTED_FROM"
```

`REVERSE_EDGE` matters specifically for `device_neighbors` (traverse `DEVICE_OF` back from a
DeviceProfile) and `prior_cases_for_entities` (traverse `HAS_CASE` back from a Card).

### 2.4 The four core queries

```gsql
// 1. card_window — the card-testing detector's input
CREATE QUERY card_window(VERTEX<Card> card_id, DATETIME anchor, INT hours) SYNTAX v2 {
  seed = {card_id};
  txns = SELECT t FROM seed:c -(MADE:e)- Transaction:t
         WHERE abs(datetime_diff(t.ts, anchor)) <= hours * 3600
         ORDER BY t.ts ASC;
  PRINT txns[txns.txn_id, txns.ts, txns.amount, txns.channel,
             txns.product_cd, txns.risk_score];
}
```
Post-process in Python: flag if ≥3 online txns under $5 in any rolling 1-hour sub-window,
followed by a materially larger one. That's R5.

```gsql
// 2. device_neighbors — the shared-device ring query (HHG-014 needs this)
CREATE QUERY device_neighbors(VERTEX<DeviceProfile> device_id) SYNTAX v2 {
  dev   = {device_id};
  txns  = SELECT t  FROM dev   -(DEVICE_OF:e)-  Transaction:t;
  cards = SELECT c  FROM txns:t -(MADE_BY:e2)-  Card:c;
  custs = SELECT cu FROM cards:c -(OWNED_BY:e3)- Customer:cu;
  cases = SELECT cc FROM cards:c -(HAS_CASE:e4)- ClosedCase:cc;
  PRINT cards, custs, cases[cases.case_id, cases.outcome, cases.pattern];
}
```

```gsql
// 3. customer_baseline — is this transaction out of character?
CREATE QUERY customer_baseline(VERTEX<Customer> customer_id) SYNTAX v2 {
  SetAccum<STRING> @@regions, @@products, @@channels;
  SumAccum<INT>    @@n;
  ListAccum<DOUBLE> @@amounts;
  cust = {customer_id};
  txns = SELECT t FROM cust -(OWNS:e1)- Card:c -(MADE:e2)- Transaction:t
         ACCUM @@n += 1, @@amounts += t.amount,
               @@products += t.product_cd, @@channels += t.channel;
  regs = SELECT r FROM txns:t -(REGION_OF:e3)- BillingRegion:r
         ACCUM @@regions += r.region_id;
  PRINT @@n, @@amounts, @@products, @@channels, @@regions;
  // percentiles computed client-side — GSQL has no PERCENTILE_CONT
}
```

```gsql
// 4. prior_cases_for_entities — case memory retrieval
CREATE QUERY prior_cases_for_entities(SET<VERTEX<Card>> cards,
                                      SET<VERTEX<DeviceProfile>> devs,
                                      SET<VERTEX<BillingRegion>> regs) SYNTAX v2 {
  SetAccum<VERTEX<ClosedCase>> @@cases;
  c1 = SELECT cc FROM cards -(HAS_CASE:e1)-       ClosedCase:cc ACCUM @@cases += cc;
  c2 = SELECT cc FROM cards -(CONNECTED_FROM:e2)- ClosedCase:cc ACCUM @@cases += cc;
  c3 = SELECT cc FROM devs  -(DEVICE_OF:e3)- Transaction:t  -(INVOLVED_IN:e4)- ClosedCase:cc
       ACCUM @@cases += cc;
  c4 = SELECT cc FROM regs  -(REGION_OF:e5)- Transaction:t2 -(INVOLVED_IN:e6)- ClosedCase:cc
       ACCUM @@cases += cc;
  result = {@@cases};
  PRINT result[result.case_id, result.outcome, result.pattern,
               result.exposure_usd, result.opened_at];
}
```

> **Version trap:** nested subqueries inside `POST-ACCUM`/`FOREACH` are the single most
> likely thing to need reshaping between GSQL syntax versions. Test these early, not on demo
> day. Check with `SHOW QUERY <name>` after a trial install.

### 2.5 Graph algorithms

Easiest path is the pyTigerGraph Featurizer — it auto-fetches and installs from GitHub:

```python
feat = conn.gds.featurizer()
feat.runAlgorithm("tg_louvain", params={"v_type": ["Card","DeviceProfile"],
                                        "e_type": ["FROM_DEVICE","DEVICE_OF"]})   # device rings
feat.runAlgorithm("tg_connected_components", params={...})                        # ring components
feat.runAlgorithm("tg_jaccard_nbor_ss", params={"source": card_id,
                                                "e_type": "MADE", "top_k": 10})   # card similarity
```

Mapping: Louvain / Connected Components over Card–DeviceProfile → **device rings**;
Jaccard over shared devices/emails → **account linkage**; k-core → dense clusters;
shortest path → link explanation for the analyst UI.

### 2.6 pyTigerGraph gotchas

```python
conn = tg.TigerGraphConnection(host="https://<workspace>.i.tgcloud.io", graphname="FraudGraph")
secret = conn.createSecret()      # save it; don't regenerate every run
conn.getToken(secret)
res = conn.runInstalledQuery("card_window", params={...}, timeout=32000)
```

- **Token expiry** ~1h by default → silent 401s mid-session. Wrap calls in a retry that
  re-calls `getToken(secret)`, or set a longer `lifetime=`.
- **Host is the workspace URL** `https://<workspace>.i.tgcloud.io`, not `savanna.tgcloud.io`.
  Copy it exactly from the connection panel.
- **`timeout=` is milliseconds**; the server default `RESTPP.Factory.DefaultQueryTimeoutSec`
  is seconds. Default is 16s — raise it for cold-workspace runs.
- **`attributes={graph_attr: df_column}`** — easy to reverse, and a reversed map silently
  upserts garbage rather than erroring.
- **No DDL wrapper** — schema changes go through `conn.gsql(open("schema.gsql").read())`.
- Use installed (compiled) queries for anything the agent calls repeatedly;
  `runInterpretedQuery` is for dev iteration only.

---

---

## 3. Graph schema — final design

<!-- FILL: column -> vertex/edge/attribute mapping, reduced column set, DeviceProfile key
     construction, what to add beyond the README's suggestion -->

---

## 4. The data: columns, entities, patterns

<!-- FILL: Vesta column semantics, the five patterns as detection heuristics with
     thresholds, candidate undocumented patterns, loading strategy -->

---

## 5. Agent architecture

### 5.1 Framework: LangGraph

Picked because the two things the rubric scores under "agentic design" — a **cyclic
investigate→assess→gather-more loop** and a **human approval gate** — are native primitives,
not things we hand-roll. OpenAI Agents SDK and CrewAI would both force us to build exactly
those two on day 1.

| | LangGraph | OpenAI Agents SDK | CrewAI | Hand-rolled |
|---|---|---|---|---|
| Cyclic state machine | **native** (conditional edges) | imperative handoffs | linear crews | you build it |
| HITL interrupt | **native** `interrupt()` + `Command(resume=)` | none | none | manual |
| Checkpointing | **native** savers | none | convo history only | manual |
| 2-day speed | moderate | fast-but-then-slow | fast, wrong shape | slowest |

`langchain-mcp-adapters` bridges the TigerGraph MCP tools in one call, so MCP tools and our
own `@tool` functions end up indistinguishable in the same tool list.

### 5.2 TigerGraph MCP

```bash
pip install tigergraph-mcp          # needs Python 3.10+, TigerGraph 4.1+ (4.2+ for vectors)
pip install "tigergraph-mcp[llm]"   # adds generate_gsql / generate_cypher
```

`.env` — Savanna:
```env
TG_HOST=https://your-instance.i.tgcloud.io
TG_GRAPHNAME=FraudGraph
TG_TGCLOUD=true
TG_API_TOKEN=...
```

`.env` — Community Edition:
```env
TG_HOST=http://localhost
TG_GRAPHNAME=FraudGraph
TG_USERNAME=tigergraph
TG_PASSWORD=tigergraph
TG_RESTPP_PORT=9000
TG_GS_PORT=14240
TG_TGCLOUD=false
```

Auth precedence `TG_API_TOKEN` > `TG_JWT_TOKEN` > user/pass.

It exposes ~69 tools under a `tigergraph__` prefix. We only need a handful:
`run_installed_query`, `run_query`, `get_neighbors`, `get_node`, `get_node_edges`,
`search_top_k_similarity`, `gsql`. Use `discover_tools` rather than dumping all 69 schemas
into the agent's context.

**Blast-radius control — worth a demo callout:**
```bash
tigergraph-mcp --allowed-tools read-only   # investigation phase can't mutate the graph
```

Bridge into LangGraph:
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from dotenv import dotenv_values

client = MultiServerMCPClient({"tg": {
    "transport": "stdio", "command": "tigergraph-mcp",
    "args": ["-vv"], "env": dotenv_values(".env"),
}})
async with client.session("tg") as session:
    mcp_tools = await load_mcp_tools(session)

all_tools = mcp_tools + [case_create, case_update, verify_with_customer, ...]
```

> Caveat from research: the tool list was read off GitHub's rendered README. Spot-check
> against `tigergraph-mcp --help` once installed.

### 5.3 The investigation state machine

```
START -> trigger -> investigate -> gather_evidence -> assess
                        ^                               |
                        |                               v
                        +------- need_more? ---- [request_evidence]
                                                        |
                                                   snapshot_initial
                                                        |
                                                        v
                                                  reassess -> decide
                                                        |
                                                   snapshot_final
                                                        |
                                            policy_gate -> [approval interrupt]
                                                        |
                                    explain -> write_case_to_graph -> emit_json -> END
```

State carries: `case_id`, `trigger`, `evidence[]`, `ledger` (see §7), `p_fraud`, `pattern`,
`affected_txns[]`, `exposure`, `snapshots[]`, `prior_cases[]`.

```python
class InvestigationState(TypedDict):
    case_id: str
    trigger: dict                  # from case_pack.csv
    evidence: list[dict]           # {claim, source, ref, entity_ids}
    ledger: list[dict]             # weighted evidence items, see §7
    p_fraud: float
    pattern: str
    affected_txn_ids: list[str]
    exposure_usd: float
    snapshots: list[dict]          # initial / final recommendation snapshots
    prior_cases: list[str]
    evidence_requests: list[dict]
```

Loop-back edge:
```python
def need_more_evidence(state) -> Literal["gather_more", "decide"]:
    p = state["p_fraud"]
    if p >= 0.85 or p <= 0.15:                 # README §6 stopping rule
        if independent_evidence_count(state) >= 2:
            return "decide"
    if state["loops"] >= MAX_LOOPS:
        return "decide"
    return "gather_more"

builder.add_conditional_edges("assess", need_more_evidence,
                              {"gather_more": "investigate", "decide": "decide"})
```

### 5.4 Approval gate

`interrupt()` over static breakpoints — it lets us attach the proposed action + evidence as
a payload for the reviewer UI.

```python
from langgraph.types import interrupt, Command

def policy_gate(state):
    pending = [a for a in state["final_actions"] if a["route"] in ("L1", "L2")]
    if not pending:
        return {"approved": True}
    decision = interrupt({"case_id": state["case_id"], "pending": pending,
                          "p_fraud": state["p_fraud"], "exposure": state["exposure_usd"]})
    return {"approved": decision["approved"]}
```

```python
cfg = {"configurable": {"thread_id": case_id}}
graph.invoke(init, config=cfg)                          # pauses
graph.invoke(Command(resume={"approved": True}), cfg)   # resumes
```

> **Gotcha:** on resume the node **re-executes from the top**. Keep side effects out of any
> node containing an `interrupt()` — idempotent reads only before the call.

### 5.5 Tool inventory + permission tiers

| Tool | Tier |
|---|---|
| `card_window(card_id, hours)` | read |
| `device_neighbors(device_id)` | read |
| `customer_baseline(customer_id)` | read |
| `prior_cases_for_entities(...)` | read |
| `search_similar_cases(text, k)` | read (vector) |
| `retrieve_policy(topic)` | read (vector) |
| `case_create` / `case_update` | agent_write |
| `write_case_to_graph(case_json)` | agent_write |
| `verify_with_customer`, `step_up_auth`, `monitor_card`, `warn_customer` | auto — executable |
| `decline_transaction` | **L1** |
| `block_card` | **L1 ≤$2,500 / L2 >$2,500** |
| `block_all_cards`, `file_report` | **L2** |

Enforcement is a single chokepoint in harness code, never a prompt instruction:

```python
def dispatch(action, exposure_usd, approved=False):
    route = resolve_route(action, exposure_usd)      # §8, from the README's §2 table
    if route == "auto":
        return Executed(action)
    if not approved:
        return PendingApproval(action, route=route)  # recorded in the answer file, NOT run
    return Executed(action)
```

The state machine *is* the authorization boundary: `L1`/`L2` tools are only reachable from
the `act` node, which is only reachable after `policy_gate` resumes with `approved: True`.

---

---

## 6. GraphRAG & case memory

### 6.1 Which GraphRAG

**Retrieve subgraph → serialize → prompt.** Not Microsoft GraphRAG, not DRIFT.

Reason: MS GraphRAG's core value is *LLM-extracting a graph out of unstructured prose*. Our
data is already a graph. Community detection + hierarchical summaries answer "tell me about
this whole corpus"; we answer "is this specific transaction fraud." That's local-search
shaped, minus the community layer. The README's own wording — "retrieving evidence from the
graph and text from documents, and giving both to the LLM" — describes exactly the
lightweight version.

Cite MS GraphRAG local search as the conceptual model in the blog post. Don't build it.

Same call on **TigerGraph CoPilot / GraphRAG-the-product** (repo: `tigergraph/graphrag`):
it's a separate deployable with its own config surface. Hand-roll the hybrid query instead —
it's the same idea, far less setup, and it's *our* code to demo.

### 6.2 TigerGraph v4.2 vector attributes — verified syntax

Native vector attrs with automatic HNSW indexing, cosine by default.
Docs: https://docs.tigergraph.com/gsql-ref/4.2/vector/ · TigerVector paper: ACM SIGMOD 2025.

```gsql
CREATE GLOBAL SCHEMA_CHANGE JOB add_embeddings {
  ALTER VERTEX ClosedCase   ADD VECTOR ATTRIBUTE notesEmb(DIMENSION=1536, METRIC="COSINE");
  ALTER VERTEX PolicyChunk  ADD VECTOR ATTRIBUTE textEmb(DIMENSION=1536, METRIC="COSINE");
}
RUN GLOBAL SCHEMA_CHANGE JOB add_embeddings
```

```
vectorSearch(vectorAttributes, queryVector, k, optionalParam)
```
`optionalParam` supports `candidate_set` (restrict ANN to a prior vertex set), `ef`
(HNSW exploration), `distance_map` (capture distances into a `MapAccum<Vertex,Float>`).

**The headline move — graph filter then vector rank, one round trip:**

```gsql
CREATE OR REPLACE QUERY similar_prior_cases(VERTEX<DeviceProfile> dev,
                                            LIST<float> qvec, INT k) SYNTAX v3 {
  MapAccum<Vertex, Float> @@dist;

  // 1. structural: closed cases reachable from this device's cards
  c1 = SELECT cc
       FROM (d:DeviceProfile {id: dev})<-[:FROM_DEVICE]-(:Transaction)
            <-[:MADE]-(:Card)<-[:ON_CARD]-(cc:ClosedCase);

  // 2. vector rank *within* that candidate set only
  v = vectorSearch({ClosedCase.notesEmb}, qvec, k,
                   {candidate_set: c1, distance_map: @@dist});
  PRINT v WITH VECTOR; PRINT @@dist;
}
```

This is the "why TigerGraph and not a vector DB bolted onto Postgres" argument. Say it out
loud in the demo.

**Fallback if the provisioned instance is pre-4.2:** external FAISS/Chroma keyed by vertex
id; retrieval becomes two round trips (ANN → ids → `WHERE v.id IN (...)`). Functionally
fine, loses the single-query trick. **Check the version first — this decision gates §6.4.**

### 6.3 Document grounding

Corpus is tiny: the Fraud Policy (rules R1–R10 + the action/route tables, all inside
`README.md`), the five pattern descriptions, and whichever FinCEN/FATF/FFIEC PDFs we pull.
Dozens of vertices, not millions — so option (a), in TigerGraph, with zero scaling downside.

Chunk the policy **by rule**, not by token window: one chunk per `Rn` so a chunk *is* a
citable unit and the agent's `reason` field can say "R5" and have it be a real retrieval hit.

```gsql
CREATE VERTEX PolicyChunk (PRIMARY_ID chunk_id STRING, rule_id STRING,
                           text STRING, citation STRING)
  WITH primary_id_as_attribute="true"
CREATE VERTEX Pattern (PRIMARY_ID pattern_id STRING, name STRING, description STRING)
CREATE VERTEX RegRef (PRIMARY_ID reg_id STRING, citation STRING, summary STRING)

CREATE DIRECTED EDGE GOVERNS   (FROM PolicyChunk, TO Pattern)
CREATE DIRECTED EDGE JUSTIFIES (FROM PolicyChunk, TO Action)
CREATE DIRECTED EDGE CITES     (FROM PolicyChunk, TO RegRef)
```

`GOVERNS`/`JUSTIFIES` are what let the agent traverse from an identified pattern to the rule
that governs it to the action it licenses — one hop, not a second retrieval call. That
traversal *is* the citation chain in the `reason` field.

FinCEN's **SAR Narrative Guidance** is named in the README as "the standard for your
`sar.narrative`". Pull it, extract the who/what/when/where/how/why structure, and template
the narrative off it. The README's own example SAR is 8 sentences and hits all six — use it
as the shape reference.

### 6.4 Case memory — built on `closed_cases_history.csv`

We do **not** design memory from scratch. 5,565 closed investigations ship with the dataset
and the README calls them "your agent's starting memory." They're Jul–Oct; the exam cases
are Nov–Dec, so memory is strictly in the past. No leakage.

Ingest maps directly onto the README's suggested vertices:

```
ClosedCase(case_id CC-xxxx, customer_id, card_id, opened_at, closed_at,
           outcome, pattern, exposure_usd, n_txns, actions_taken,
           report_filed, analyst_notes, notesEmb)
  -INVOLVES->     Transaction   (explode txn_ids on "|")
  -ON_CARD->      Card          (card_id)
  -CONNECTED_TO-> Card          (explode connected_card_ids)
```

`analyst_notes` is the embedding target — it's the only free text in the dataset.

> **Highest-value text in the whole dataset:** the `analyst_notes` on rows where
> `pattern == 'undocumented'`. The README says analysts confirmed these as fraud but
> couldn't match a known pattern, and tells us to "read those notes carefully." The
> undocumented pattern that's explicitly scored is described in there. **Read every one of
> them by hand before writing detector code.**

**Retrieve exonerating precedent, not just incriminating.** 900 of the 5,565 are `cleared`
with `pattern = none` and notes explaining why the alert was a false alarm. Given "half the
cases are legitimate," a memory layer that only surfaces confirmed fraud will push every
verdict upward. Retrieval must return both, and the ledger must weight a matching *cleared*
precedent **negatively**.

### 6.5 Blended retrieval score

Three signals:

| Signal | How | Query |
|---|---|---|
| (i) semantic | cosine on `ClosedCase.notesEmb` vs the new case's narrative | `vectorSearch` |
| (ii) structural | shared Card / DeviceProfile / BillingRegion between the new alert and a closed case | `INVOLVES` / `CONNECTED_TO` traversal |
| (iii) pattern | same provisional pattern classification | `MATCHES_PATTERN` |

```
score(cc) = 0.4 * semantic(cc) + 0.4 * structural(cc) + 0.2 * pattern_match(cc)

structural(cc) = min(1.0, shared_entity_count / 3)
semantic(cc)   = 1 - (cosine_distance / 2)
sign(cc)       = +1 if cc.outcome == 'confirmed_fraud' else -1     # <- exonerating precedent
```

Structural gets equal weight to semantic because a reused device *is* the fraud signal here
— arguably stronger than narrative similarity for ring detection.

Shape: vector search for ~20 candidates, then run the structural/pattern traversals
**restricted to those 20** (`candidate_set`, or `WHERE cc.case_id IN (...)`) to avoid a
full-graph scan. Blend and sort app-side, or `HeapAccum<Tuple<VERTEX,FLOAT>>(5, score DESC)`
server-side if we want it in one query for the demo.

**Retrieve the two pools SEPARATELY — do not merge-then-rank.** The base rate is 4,665
confirmed vs 900 cleared. A single merged top-K silently buries exonerating precedent under
the 5:1 majority, which is exactly how an agent ends up blocking legitimate customers.

```python
confirming    = top_3(score, where outcome == "confirmed_fraud")
disconfirming = top_2(score, where outcome == "cleared")
similar_prior_cases = dedupe(confirming + disconfirming)
```

Both pools go into the prompt, and the agent's reasoning must state why it weighted one over
the other. This is the direct countermeasure to the README's stated trap.

Retrieved IDs populate the answer file's `similar_prior_cases`.

### 6.5b Writing our own cases back — same vertex shape

`written_to_graph` / `graph_case_id` are required fields. Write agent cases with the **same
shape as ClosedCase** so future retrieval needs no separate code path:

```gsql
CREATE OR REPLACE QUERY write_case_to_graph(
    STRING case_id, STRING customer_id, STRING card_id, DATETIME opened_at,
    STRING outcome, STRING pattern, STRING first_txn, LIST<STRING> txn_ids,
    FLOAT exposure, LIST<STRING> connected_cards, STRING actions_taken,
    BOOL report_filed, STRING analyst_notes, LIST<float> notes_vec) SYNTAX v3 {
  INSERT INTO ClosedCase VALUES (case_id, customer_id, card_id, opened_at, now(),
      outcome, pattern, first_txn, txn_ids.size(), exposure,
      actions_taken, report_filed, analyst_notes, notes_vec);
  FOREACH t IN txn_ids        DO INSERT INTO INVOLVES     VALUES (case_id, t); END;
  INSERT INTO ON_CARD VALUES (case_id, card_id);
  FOREACH c IN connected_cards DO INSERT INTO CONNECTED_TO VALUES (case_id, c); END;
}
```

Run the 20 cases **in `opened_at` order** so an earlier case is retrievable as memory by a
later one. That's a free demo beat.

### 6.5c SAR narrative template (FinCEN who/what/when/where/how/why)

```
[WHO]   customer_id, card_id(s), connected_card_ids, device profile(s)
[WHAT]  the pattern — amounts, sequence, product-code deviation from history
[WHEN]  exact ts range, first to last affected txn
[WHERE] channel (online/in_person), billing region if out-of-region
[HOW]   mechanism, e.g. "small test authorizations preceding a larger purchase"
[WHY]   why not innocently explainable — what confirmed it (denial, shared device
        with a prior confirmed case), exposure, connected cards placed under monitoring
```

Field mapping: `sar.subjects` = every ID named; `sar.total_amount_usd` = `exposure_usd`;
`sar.activity_dates` = `[min(ts), max(ts)]` over `affected_txn_ids`. 6–12 sentences.

> Doc-loading priority given 2 days: **FinCEN SAR Narrative Guidance** (the README names it
> as the standard), the **Account Takeover Advisory** (maps to our `account_takeover`
> pattern), and the **FFIEC Red Flags appendix**. Skip the FATF documents — they're about
> money laundering typologies, weakly relevant to card fraud.

### 6.6 Subgraph serialization — with provenance

Format: **markdown tables per entity type + a 1–2 sentence narrative header.** Tables beat
JSON by ~30–40% on tokens for homogeneous rows (shared headers vs repeated keys) and LLMs
parse them reliably. JSON only for irregular nested pieces. Narrative prose is for the *UI*,
not the prompt.

**Hard requirement:** every block carries the query that produced it and the entity IDs it
rests on. The answer file's `evidence[]` needs `{claim, source, ref, entity_ids}` — if the
serialization drops provenance, the agent literally cannot fill the field and we lose points
on two criteria at once. So each table is headed with its `ref`:

```markdown
### Card window — ref: `query:card_window(card_id=C04570-K1, hours=2)`
| txn_id | ts | amount | channel | product | risk_score |
|---|---|---|---|---|---|
| 3450627 | 11-12 00:14 | $2.10 | online | C | 0.31 |
| 3450628 | 11-12 00:29 | $1.85 | online | C | 0.28 |
| 3450629 | 11-12 00:46 | $100.09 | online | C | 0.57 |
*entity_ids: [3450627, 3450628, 3450629]*

### Device neighbours — ref: `query:device_neighbors(device_id=...)`
| card_id | customer | first_seen | txns | prior_case |
|---|---|---|---|---|
| C09933-K2 | C09933 | 11-10 | 4 | CC-0141 (confirmed_fraud) |
*entity_ids: [C09933-K2, CC-0141]*
```

**Token budget: 1.5k–3k tokens** for the full injected context per case.
- Full detail for ≤15 rows; beyond that, top-N by risk + one aggregate line for the rest.
- Never inline a full prior case — one condensed finding sentence + the similarity
  justification. If the agent wants more, that's a second tool call (`get_case_detail`),
  which is itself a nice demo beat.
- Drop columns that don't change the decision.

### 6.7 Demo beats that prove memory works

1. **Same-device escalation.** Agent is at medium confidence on velocity alone. Memory
   returns a closed case sharing the device profile, `confirmed_fraud`. Confidence jumps,
   recommendation flips from verify → block, rationale cites the closed case ID. Do this first.
2. **False-positive suppression.** Pattern matches a closed case but **no shared entities**
   and that case resolved `cleared`. Blended score stays low, agent says so explicitly and
   recommends monitoring rather than blocking. This proves the blend discriminates rather
   than just counting priors — it's what a judge will probe in Q&A.
3. **Cross-case entity discovery.** Two cases whose narratives look unrelated (different
   customers, different products) but share one device via the graph. Pure structural query,
   no vector involvement. This is the one a vector-only RAG system cannot do — say that out loud.

---

---

## 7. Uncertainty & next-best-action

> This section plus §8 is the 50% of the rubric. Everything else is support.

### 7.1 Confidence is a ledger, not a vibe

The LLM **classifies evidence into the ledger and narrates**. It never emits the probability
number. `fraud_probability` is a deterministic function of typed evidence, which means we
can point a judge at a config file when they ask where 0.72 came from.

```yaml
# evidence_weights.yaml
card_testing_sequence:      { w: +0.35, req: "3+ sub-$5 online auths <1hr + larger purchase, one card" }  # R5
shared_device_across_cards: { w: +0.30, req: "DeviceProfile on 2+ customers/cards" }                      # R6
customer_denies:            { w: +0.30 }                                                                   # R2
shared_region_cluster:      { w: +0.25, req: "addr1 cluster across many cards, short window" }            # R6
cnp_burst_pattern:          { w: +0.20, req: "2-4 unusual online purchases <48h, category mismatch" }
out_of_region_pattern:      { w: +0.20, req: "addr1 outside customer's historical set, multi-day" }
closed_case_match:          { w: +0.20, req: "device/region/email matches a confirmed_fraud ClosedCase" }
new_device_marker:          { w: +0.15, req: "id_15 == New for this customer/card" }
proxy_flag:                 { w: +0.10, req: "id_23 in (anonymous, hidden)" }
risk_score_alone:           { w: +0.05, note: "policy §0 says it is not a verdict" }

# negative / exonerating — as important as the positives
recurring_merchant_match:   { w: -0.25 }   # R7 disputed-but-legitimate
cleared_precedent_match:    { w: -0.20 }   # a `cleared` ClosedCase matches on device/region
in_character_for_customer:  { w: -0.20 }   # amount/product/region all inside baseline
customer_confirms:          { w: -0.90 }   # R3 — effectively closes as legitimate
```

`fraud_probability = sigmoid(Σ w)`, clipped [0,1].

**`risk_score` gets almost no standalone weight on purpose.** The README states that above
0.7 most flagged transactions are legitimate and some fraud scores near zero. Treating it as
a strong prior would actively damage the calibration score. It's a reason to look, not
evidence.

### 7.2 Bands come from the policy's own numbers

No invented cutoffs. Every boundary is citable to a rule:

| Anchor | Value | Gates |
|---|---|---|
| Case creation | `p ≥ 0.30` | `CREATE_CASE`, regardless of final verdict (§3a) |
| R1 block guard | `p < 0.70` on a single signal | forces `VERIFY_WITH_CUSTOMER` / `STEP_UP_AUTH` before any block |
| R8 escalate | `uncertain` AND exposure > $500 | forces `ESCALATE_TO_ANALYST` |
| Stop-high | `p ≥ 0.85` + ≥2 independent evidence | close as fraud |
| Stop-low | `p ≤ 0.15` + ≥2 independent evidence | close as legitimate |
| SAR (§3a) | fraud/strong suspicion AND (exposure > $1,000 OR shared device/region/other-customer OR R9) | `FILE_REPORT` |
| Route split | exposure ≤ $2,500 → L1, > $2,500 → L2 | `BLOCK_CARD` approval route |

### 7.3 Forcing the recommendation to actually change

```python
def can_stop(p, independent_evidence_count, verification_settled):
    if verification_settled:
        return True
    if independent_evidence_count >= 2 and (p >= 0.85 or p <= 0.15):
        return True
    return False

# orchestrator invariant, enforced in code not in a prompt:
if not can_stop(...) and not evidence_requests:
    raise MustRequestEvidence
```

This turns a fuzzy rubric line into a unit-testable assertion we can run over all 20 cases
before submitting.

**Scope cut:** the README asks for the *action* to evolve with a stated reason
(`initial` / `final` / `what_changed`). It does **not** ask for a before/after probability
pair — `case.fraud_probability` is a single final number. Don't build a probability audit
trail the schema doesn't score.

Internal → external mapping:

| Internal | Answer file field |
|---|---|
| snapshot before evidence | `next_best_actions.initial[]` |
| the fetch | `evidence_requests[]` (`type`, `asked_after_step`, `assumed_response`) |
| snapshot after evidence | `next_best_actions.final[]` |
| delta narrative | `next_best_actions.what_changed` |

Keep an `evidence_set` hash on each internal snapshot. It's cheap and it proves the "after"
confidence was computed from strictly more evidence than the "before" — a judge reading the
JSON can verify the delta is causally tied to the new evidence rather than a re-roll.

### 7.4 Which evidence to request

Only three request types exist (§5), so this is rule-driven, not a general EVOI computation:

| Situation | Request | Why |
|---|---|---|
| Single signal, `p < 0.70` | `customer_validation` | Resolves the R2 / R3 / R7 fork — the highest-leverage branch in the whole policy |
| New device, no denial yet, session legitimacy ambiguous | `step_up_auth` | Cheapest signal that separates "new phone" from "takeover" |
| `uncertain` + exposure > $500 | not a request — it **is** `ESCALATE_TO_ANALYST` (R8) | |

State the `assumed_response` explicitly and make it *reasonable given the evidence*, not
merely convenient for the narrative. Judges can check this.

---

## 8. Policy engine

```yaml
# fraud_policy.yaml — exact identifiers, do not rename
actions:
  ALLOW_TRANSACTION:       { route: auto }
  DECLINE_TRANSACTION:     { route: L1 }
  MONITOR_CARD:            { route: auto }
  MONITOR_CONNECTED_CARDS: { route: auto }
  WARN_CUSTOMER:           { route: auto }
  VERIFY_WITH_CUSTOMER:    { route: auto }
  STEP_UP_AUTH:            { route: auto }
  BLOCK_CARD:
    route_by_exposure: { "<=2500": L1, ">2500": L2 }
  BLOCK_ALL_CARDS:         { route: L2, guard: "R10" }
  GENERATE_REPORT:         { route: auto }
  CREATE_CASE:             { route: auto }
  FILE_REPORT:             { route: L2 }
  ESCALATE_TO_ANALYST:     { route: auto }
  CLOSE_NO_FRAUD:          { route: auto }

rules:
  R1:
    predicate: "single_signal AND fraud_probability < 0.70"
    actions: [VERIFY_WITH_CUSTOMER, STEP_UP_AUTH]     # pick one by context
    note: "must precede any block"
  R2:
    predicate: "customer_validation requested AND response == deny"
    actions: [BLOCK_CARD, CREATE_CASE]
    add_if: { when: "exposure_usd > 1000 OR shared_device_profile OR other_card_fraud",
              add: [FILE_REPORT] }
  R3:
    predicate: "response == confirm"
    actions: [CLOSE_NO_FRAUD]
  R4:
    predicate: "no_reply_within_24h"
    actions: [MONITOR_CARD, DECLINE_TRANSACTION]
    add_if: { when: "exposure_usd > 500", add: [ESCALATE_TO_ANALYST] }
  R5:
    predicate: "3+ sub-$5 online auths within 1hr on one card, then a larger purchase"
    actions: [DECLINE_TRANSACTION, STEP_UP_AUTH]
    override: { when: "purchase > $100 already cleared", actions: [BLOCK_CARD] }
  R6:
    predicate: "shared device_profile OR billing_region OR recipient_email across cards in one window"
    actions: [CREATE_CASE, FILE_REPORT, MONITOR_CONNECTED_CARDS]
    must: "name the shared element explicitly in evidence"
  R7:
    predicate: "dispute matches the customer's own recurring pattern (merchant, amount, monthly)"
    actions: [CREATE_CASE, VERIFY_WITH_CUSTOMER, WARN_CUSTOMER]
    forbid: [BLOCK_CARD, DECLINE_TRANSACTION]
  R8:
    predicate: "verdict == uncertain AND exposure_usd > 500, OR evidence conflicts"
    actions: [ESCALATE_TO_ANALYST]
  R9:
    predicate: "fits none of the 5 patterns AND coordinated/repeated abuse across customers"
    actions: [CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST]
    pattern: undocumented
    must: "pattern_description, 2-3 sentences"
  R10:
    predicate: "BLOCK_ALL_CARDS proposed"
    guard: "2+ cards confirmed fraud OR credentials confirmed compromised"
    else: "downgrade to BLOCK_CARD on the specific card"

case_lifecycle:
  create_case_when: "fraud_probability >= 0.30 OR evidence_requested OR customer_disputes"
  sar_trigger: "verdict in (fraud, strongly_suspected) AND
                (exposure_usd > 1000 OR shared_device_or_region_or_other_customer_fraud
                 OR pattern == undocumented)"
```

The permission model is **not role-based** — it's simpler than that:
**`auto` = the agent may execute. `L1`/`L2` = the agent may only recommend, and must state
the route.**

```python
ROUTES = {...}  # from the yaml above

def finalize_action(action, exposure_usd=None):
    route = ("L1" if exposure_usd <= 2500 else "L2") if action == "BLOCK_CARD" \
            else ROUTES[action]
    return {"action": action, "route": route, "executed": route == "auto"}
```

Order actions by what happens first (the README says so explicitly).

---

## 9. Build plan

<!-- FILL: 48h plan, three workstreams, interfaces, cut-list -->

---

## 10. Demo, blog, submission checklist

<!-- FILL -->
