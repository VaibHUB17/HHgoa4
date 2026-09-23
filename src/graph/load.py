"""Three-tier CSV loading for the HHgoa4 fraud-investigation agent.

Source: RESEARCH.md §2.2 (tiered loading), §3 (DeviceProfile key construction, never
coalescing to "None | None"), §6.4 (ClosedCase ingestion exploding txn_ids and
connected_card_ids on "|"), §2.6 (bulk load via GSQL LOADING JOB, pyTigerGraph upsert
only for incremental writes).

CLI:
    python -m src.graph.load --data-dir ./data --run-loading-job

Tier 1 (graph structure) + Tier 2 (scalar evidence, C1-C14/D1-D15/M1-M9) are sliced from
transactions.csv (joined to identity.csv where present) into txn_slim.csv, which a GSQL
LOADING JOB bulk-loads server-side. Tier 3 (V1-V339) goes to a parquet sidecar keyed on
TransactionID, never into the graph -- see schema.gsql's comment on why.

UNCERTAIN: not run against the actual transactions.csv/identity.csv (not present in this
checkout). Column names and dtypes follow README.md's documented schema and
RESEARCH.md's dtype_map exactly; nullable-int edge cases (e.g. an int column that turns
out to have NaNs after all) would need the same float32-not-int treatment RESEARCH.md
already applies to C1-C14.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier definitions (RESEARCH.md §2.2)
# ---------------------------------------------------------------------------

TIER1_TXN_COLS = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "dist1", "dist2",
    "P_emaildomain", "R_emaildomain",
    "customer_id", "ts", "channel", "risk_score",
]
TIER2_TXN_COLS = (
    [f"C{i}" for i in range(1, 15)]
    + [f"D{i}" for i in range(1, 16)]
    + [f"M{i}" for i in range(1, 10)]
)
TIER1_IDENTITY_COLS = [
    "TransactionID", "DeviceType", "DeviceInfo",
    "id_15", "id_23", "id_30", "id_31", "id_33", "id_34",
]
TIER3_V_COLS = [f"V{i}" for i in range(1, 340)]

DTYPE_MAP: dict[str, str] = {
    "TransactionID": "int32",
    "customer_id": "category",
    "card_id": "category",
    "TransactionAmt": "float32",
    "risk_score": "float32",
    "ProductCD": "category",
    "channel": "category",
    **{f"card{i}": "category" for i in range(1, 7)},
    "addr1": "category",
    "addr2": "category",
    "dist1": "float32",
    "dist2": "float32",
    "P_emaildomain": "category",
    "R_emaildomain": "category",
    **{f"C{i}": "float32" for i in range(1, 15)},   # NaNs present -> float not int
    **{f"D{i}": "float32" for i in range(1, 16)},
    **{f"M{i}": "category" for i in range(1, 10)},  # T/F/NaN -> category not object
    "DeviceType": "category",
    "DeviceInfo": "category",
    "id_15": "category",
    "id_23": "category",
    "id_30": "category",
    "id_31": "category",
    "id_33": "category",
    "id_34": "category",
}

CHUNK_SIZE = 100_000


# ---------------------------------------------------------------------------
# card_id derivation
# ---------------------------------------------------------------------------
#
# UNCERTAINTY (flagged per task instructions, not silently assumed): neither README.md
# nor RESEARCH.md specifies how `card_id` (e.g. "C01234-K1", referenced throughout
# case_pack.csv, closed_cases_history.csv, and RESEARCH.md's own loading-job snippet) is
# derived from the raw card1-card6 columns. README.md says only that customer_id is
# "derived from the card issuer field" and that "one customer can have several cards."
# RESEARCH.md separately warns "card1 is NOT unique per physical card" and "Don't group
# by card1. It's not unique per card... Use the provided card_id" -- but card_id is not
# actually provided as a raw column in transactions.csv per the documented column list
# (only TransactionID/TransactionDT/TransactionAmt/ProductCD/card1-6/addr1-2/dist1-2/
# emaildomains/C/D/M/V + the four added columns customer_id/ts/channel/risk_score).
#
# Since case_pack.csv and closed_cases_history.csv DO carry ground-truth card_id values
# for the 20 exam cases and 5,565 closed cases, the safe approach is: those files are the
# source of truth for card_id on the rows they cover, and derive_card_id() below is a
# best-effort fallback for the remaining ~585k transactions.csv rows that need a card_id
# to build MADE edges at all.
#
# VERIFIED against real data (2026-09-24, Bhavya): the K-numbering is NOT first-seen
# chronological order. The OLD rule (rank by first-seen ts) was checked against all 20
# real case_pack.csv rows and was WRONG on 10/20 (50%) -- it always promotes the
# customer's heaviest-used card to K1 because it appears earliest, which is backwards.
#
# Replacement rule -- rank each customer's distinct (card1..card6) tuples by ASCENDING
# transaction count (fewest transactions = K1), ties broken by first-seen ts for
# determinism -- checked against all 20 real case_pack.csv rows: 19/20 correct.
#
# The one exception (HHG-006, customer C07297): two fully-populated tuples differing
# only in card5 (98 vs 163 transactions, both active through the full period), where
# ground truth assigns K1 to the *more*-used tuple -- the opposite direction from every
# other multi-card case checked, where the sparser tuple was always K1. No rule found
# so far explains both this case and the other 19 simultaneously; ascending-count wins
# on volume (19 vs 10 under the old rule) and is the better default, but this specific
# shape -- two tuples close in count, both fully populated, differing in one minor
# subfield -- is a known blind spot. If a customer's derived card_id lands in this shape,
# don't trust the K-number without checking case_pack.csv/closed_cases_history.csv
# directly for that customer.
#
# Re-run this check (see git history for the verification script) after the schema/load
# actually runs against the full dataset in TigerGraph, in case a larger sample surfaces
# a better rule.
# ---------------------------------------------------------------------------

CARD_TUPLE_COLS = ["card1", "card2", "card3", "card4", "card5", "card6"]


def derive_card_id(df: "pd.DataFrame") -> "pd.Series":
    """Best-effort card_id derivation: customer_id + rank-by-ascending-transaction-count
    index of each distinct (card1..card6) tuple within that customer (ties broken by
    first-seen ts). See module-level VERIFIED note above -- confirmed against 4
    independent known card_ids in case_pack.csv; not exhaustively validated.
    """
    key = df["customer_id"].astype(str) + "||" + df[CARD_TUPLE_COLS].astype(str).agg("|".join, axis=1)
    first_seen = df.groupby(key)["ts"].transform("min")
    txn_count = df.groupby(key)["ts"].transform("count")
    tmp = pd.DataFrame(
        {"customer_id": df["customer_id"], "key": key, "count": txn_count, "first_seen": first_seen}
    )
    distinct = tmp.drop_duplicates("key").sort_values(["customer_id", "count", "first_seen"])
    distinct["k_index"] = distinct.groupby("customer_id").cumcount() + 1
    key_to_k = dict(zip(distinct["key"], distinct["k_index"]))
    k_index = key.map(key_to_k)
    return df["customer_id"].astype(str) + "-K" + k_index.astype(str)


# ---------------------------------------------------------------------------
# DeviceProfile key construction (RESEARCH.md §3)
# ---------------------------------------------------------------------------

def device_profile_key(row: "pd.Series") -> tuple[str | None, int]:
    """Build the DeviceProfile key from whatever subset of components is present.

    Returns (key, completeness) where completeness is the count of non-null components
    used (1-4). Returns (None, 0) when nothing is present -- callers MUST skip emitting a
    DeviceProfile / FROM_DEVICE edge in that case rather than coalescing to a placeholder
    string like "None | None", which would silently cluster every device-less row into one
    fake ring and poison every shared-device (R6) query (RESEARCH.md §3 trap).

    identity.csv covers online transactions only, so a row with no identity join at all
    (in_person / channel == "W") never reaches this function with real data -- callers
    should skip device-profile construction entirely for such rows, not call this with an
    all-NaN row and expect it to correctly return (None, 0). It does, but skipping upstream
    is cheaper and matches "the absence is the signal, don't impute it away" (RESEARCH.md §4.5).
    """
    parts = [row.get("DeviceInfo"), row.get("id_30"), row.get("id_31"), row.get("id_33")]
    parts = [str(p).strip() for p in parts if pd.notna(p) and str(p).strip()]
    if not parts:
        return None, 0
    return " | ".join(parts), len(parts)


# ---------------------------------------------------------------------------
# Tier 1 + 2: slice transactions.csv (+identity.csv) -> txn_slim.csv
# ---------------------------------------------------------------------------

def _build_card_id_lookup(transactions_csv: Path) -> "pd.Series":
    """Pre-pass over just TransactionID/customer_id/ts/card1-6 (narrow enough to load
    whole) to derive a globally-consistent card_id per TransactionID before the main
    chunked slice. card_id numbering (the "K1", "K2", ... suffix) must be consistent
    across a customer's entire transaction history, which a per-chunk derivation cannot
    guarantee since one customer's rows can land in different 100k-row chunks. Returns a
    Series indexed by TransactionID.
    """
    narrow_cols = ["TransactionID", "customer_id", "ts"] + CARD_TUPLE_COLS
    narrow = pd.read_csv(
        transactions_csv,
        usecols=narrow_cols,
        dtype={"TransactionID": "int32", "customer_id": "category",
               **{c: "category" for c in CARD_TUPLE_COLS}},
        parse_dates=["ts"],
    )
    narrow["card_id"] = derive_card_id(narrow)
    return narrow.set_index("TransactionID")["card_id"]


def slice_txn_slim(transactions_csv: Path, identity_csv: Path, out_csv: Path) -> None:
    """Slice Tier 1 + Tier 2 columns from transactions.csv, left-joined to identity.csv
    on TransactionID, chunked to cap peak RSS, written to a single txn_slim.csv.

    Also computes device_key/device_completeness per row here (rather than deferring to
    a separate pass) so the LOADING JOB can load DeviceProfile vertices/edges directly
    from txn_slim.csv without a second file. card_id is derived globally first (see
    _build_card_id_lookup) since its "K1"/"K2" numbering must be consistent across a
    customer's full history, not just within one chunk.
    """
    logger.info("Loading identity.csv (%s) for join", identity_csv)
    identity = pd.read_csv(
        identity_csv,
        usecols=TIER1_IDENTITY_COLS,
        dtype={k: v for k, v in DTYPE_MAP.items() if k in TIER1_IDENTITY_COLS},
    )

    logger.info("Deriving card_id globally (see UNCERTAINTY note above derive_card_id)")
    card_id_lookup = _build_card_id_lookup(transactions_csv)

    usecols = TIER1_TXN_COLS + TIER2_TXN_COLS
    dtype = {k: v for k, v in DTYPE_MAP.items() if k in usecols}

    first_chunk = True
    n_rows = 0
    reader = pd.read_csv(
        transactions_csv,
        usecols=usecols,
        dtype=dtype,
        parse_dates=["ts"],
        chunksize=CHUNK_SIZE,
    )
    for chunk in reader:
        merged = chunk.merge(identity, on="TransactionID", how="left")
        keys = merged.apply(device_profile_key, axis=1, result_type="expand")
        merged["device_key"] = keys[0]
        merged["device_completeness"] = keys[1].astype("int32")
        merged["card_id"] = merged["TransactionID"].map(card_id_lookup)

        merged.to_csv(out_csv, mode="w" if first_chunk else "a", header=first_chunk, index=False)
        first_chunk = False
        n_rows += len(merged)
        logger.info("Wrote %d rows so far", n_rows)

    logger.info("txn_slim.csv complete: %d rows -> %s", n_rows, out_csv)


# ---------------------------------------------------------------------------
# Tier 3: V1-V339 -> parquet sidecar
# ---------------------------------------------------------------------------

def slice_v_columns_parquet(transactions_csv: Path, out_parquet: Path) -> None:
    """Slice TransactionID + V1-V339 to a parquet sidecar. Chunked read, single parquet
    write via pyarrow (pandas' default engine) -- acceptable for ~590k rows x 340 cols,
    no need for a streaming parquet writer at this size.
    """
    usecols = ["TransactionID"] + TIER3_V_COLS
    dtype = {"TransactionID": "int32", **{c: "float32" for c in TIER3_V_COLS}}

    chunks = pd.read_csv(transactions_csv, usecols=usecols, dtype=dtype, chunksize=CHUNK_SIZE)
    df = pd.concat(chunks, ignore_index=True)
    df.to_parquet(out_parquet, index=False)
    logger.info("V-columns parquet sidecar: %d rows -> %s", len(df), out_parquet)


# ---------------------------------------------------------------------------
# NEXT edges: time-ordered per card
# ---------------------------------------------------------------------------

def derive_next_edges(txn_slim_csv: Path, out_csv: Path) -> None:
    """Derive Transaction -NEXT-> Transaction edges: consecutive pairs ordered by ts
    within each card_id. Written as a plain (from_txn_id, to_txn_id) CSV for a small
    LOADING JOB / upsertEdgeDataFrame pass -- NEXT is derived, not loaded from source data
    (RESEARCH.md §2.2).

    Loads only the columns needed (TransactionID, ts, card_id) rather than the full slim
    file, since this can run as a second pass after slice_txn_slim without re-reading
    every Tier 1+2 column.
    """
    df = pd.read_csv(txn_slim_csv, usecols=["TransactionID", "ts", "card_id"], parse_dates=["ts"])
    df = df.sort_values(["card_id", "ts"])
    df["to_txn_id"] = df.groupby("card_id")["TransactionID"].shift(-1)
    edges = df.dropna(subset=["to_txn_id"])[["TransactionID", "to_txn_id"]]
    edges = edges.rename(columns={"TransactionID": "from_txn_id"})
    edges["to_txn_id"] = edges["to_txn_id"].astype("int64")
    edges.to_csv(out_csv, index=False)
    logger.info("NEXT edges: %d -> %s", len(edges), out_csv)


# ---------------------------------------------------------------------------
# closed_cases_history.csv -> ClosedCase vertices, exploding "|"-separated lists
# ---------------------------------------------------------------------------

def slice_closed_cases(closed_cases_csv: Path, out_vertices_csv: Path,
                        out_involves_csv: Path, out_connected_csv: Path) -> None:
    """Load closed_cases_history.csv, explode txn_ids and connected_card_ids on "|" into
    separate edge-list CSVs, write the ClosedCase vertex CSV as-is (minus the exploded
    columns). RESEARCH.md §6.4.
    """
    df = pd.read_csv(closed_cases_csv, dtype=str)
    df["n_txns"] = pd.to_numeric(df["n_txns"], errors="coerce").astype("Int64")
    df["exposure_usd"] = pd.to_numeric(df["exposure_usd"], errors="coerce").astype("float32")
    df["report_filed"] = df["report_filed"].astype(str).str.lower().isin(["true", "1", "yes"])

    involves_rows = []
    connected_rows = []
    for case_id, txn_ids, connected in zip(df["case_id"], df["txn_ids"], df["connected_card_ids"]):
        for t in str(txn_ids).split("|"):
            t = t.strip()
            if t:
                involves_rows.append({"case_id": case_id, "txn_id": t})
        if pd.notna(connected):
            for c in str(connected).split("|"):
                c = c.strip()
                if c:
                    connected_rows.append({"case_id": case_id, "card_id": c})

    vertex_cols = [c for c in df.columns if c not in ("txn_ids", "connected_card_ids")]
    df[vertex_cols].to_csv(out_vertices_csv, index=False)
    pd.DataFrame(involves_rows).to_csv(out_involves_csv, index=False)
    pd.DataFrame(connected_rows).to_csv(out_connected_csv, index=False)
    logger.info(
        "ClosedCase: %d cases, %d INVOLVES edges, %d CONNECTED_TO edges",
        len(df), len(involves_rows), len(connected_rows),
    )


# ---------------------------------------------------------------------------
# GSQL LOADING JOB (bulk) vs pyTigerGraph upsert (incremental)
# ---------------------------------------------------------------------------

LOADING_JOB_GSQL = """\
CREATE LOADING JOB load_fraud FOR GRAPH FraudGraph {{
  DEFINE FILENAME f_txn = "{txn_slim}";
  DEFINE FILENAME f_next = "{next_edges}";
  DEFINE FILENAME f_case = "{case_vertices}";
  DEFINE FILENAME f_case_involves = "{case_involves}";
  DEFINE FILENAME f_case_connected = "{case_connected}";

  LOAD f_txn TO VERTEX Customer VALUES ($"customer_id") USING header="true", separator=",";
  LOAD f_txn TO VERTEX Card VALUES ($"card_id", $"card4", $"card6") USING header="true", separator=",";
  LOAD f_txn TO VERTEX Transaction VALUES (
        $"TransactionID", $"ts", $"TransactionAmt", $"ProductCD", $"channel", $"risk_score",
        $"dist1", $"dist2", $"C1", $"C2", $"D1", $"D15", $"M4", $"M6", $"id_15", $"id_23"
      ) USING header="true", separator=",";
  LOAD f_txn TO VERTEX DeviceProfile VALUES ($"device_key", $"device_completeness")
      WHERE $"device_key" != "" USING header="true", separator=",";
  LOAD f_txn TO VERTEX EmailDomain VALUES ($"P_emaildomain") USING header="true", separator=",";
  LOAD f_txn TO VERTEX BillingRegion VALUES ($"addr1", $"addr2") USING header="true", separator=",";
  LOAD f_txn TO VERTEX ProductCategory VALUES ($"ProductCD") USING header="true", separator=",";

  LOAD f_txn TO EDGE OWNS            VALUES ($"customer_id", $"card_id") USING header="true", separator=",";
  LOAD f_txn TO EDGE MADE            VALUES ($"card_id", $"TransactionID") USING header="true", separator=",";
  LOAD f_txn TO EDGE FROM_DEVICE     VALUES ($"TransactionID", $"device_key")
      WHERE $"device_key" != "" USING header="true", separator=",";
  LOAD f_txn TO EDGE PURCHASER_EMAIL VALUES ($"TransactionID", $"P_emaildomain") USING header="true", separator=",";
  LOAD f_txn TO EDGE RECIPIENT_EMAIL VALUES ($"TransactionID", $"R_emaildomain")
      WHERE $"R_emaildomain" != "" USING header="true", separator=",";
  LOAD f_txn TO EDGE BILLED_IN       VALUES ($"TransactionID", $"addr1") USING header="true", separator=",";
  LOAD f_txn TO EDGE IN_CATEGORY     VALUES ($"TransactionID", $"ProductCD") USING header="true", separator=",";

  LOAD f_next TO EDGE NEXT VALUES ($"from_txn_id", $"to_txn_id") USING header="true", separator=",";

  LOAD f_case TO VERTEX ClosedCase VALUES (
        $"case_id", $"customer_id", $"card_id", $"outcome", $"pattern",
        $"first_fraud_txn_id", $"n_txns", $"exposure_usd", $"actions_taken",
        $"report_filed", $"analyst_notes", $"opened_at", $"closed_at"
      ) USING header="true", separator=",";
  LOAD f_case_involves  TO EDGE INVOLVES     VALUES ($"case_id", $"txn_id")  USING header="true", separator=",";
  LOAD f_case           TO EDGE ON_CARD      VALUES ($"case_id", $"card_id") USING header="true", separator=",";
  LOAD f_case_connected TO EDGE CONNECTED_TO VALUES ($"case_id", $"card_id") USING header="true", separator=",";
}}
RUN LOADING JOB load_fraud
"""


def run_loading_job(conn, data_dir: Path) -> None:
    """Bulk-load via a GSQL LOADING JOB, per TigerGraph DevRel guidance quoted in
    RESEARCH.md §2.2: "Don't do row-by-row REST. Use a GSQL loading job." Server paths
    are relative to the GSQL server's file staging area -- callers are expected to have
    already uploaded/placed the sliced CSVs there (out of scope for this function; the
    conn.gsql() call below assumes `data_dir` is reachable by the server process, which
    holds for Community Edition local installs and for Savanna after an explicit upload
    step not automated here).
    """
    job_gsql = LOADING_JOB_GSQL.format(
        txn_slim=str(data_dir / "txn_slim.csv"),
        next_edges=str(data_dir / "next_edges.csv"),
        case_vertices=str(data_dir / "closed_case_vertices.csv"),
        case_involves=str(data_dir / "closed_case_involves.csv"),
        case_connected=str(data_dir / "closed_case_connected.csv"),
    )
    conn.gsql(job_gsql)


def upsert_incremental(conn, vertex_type: str, attributes: dict) -> None:
    """Incremental single-vertex/edge write path (e.g. the agent creating a Case at
    investigation time). NOT used for the bulk historical load -- see run_loading_job.
    Thin wrapper kept here so callers don't need to know pyTigerGraph's upsertVertex
    signature directly; real Case-vertex writes belong to write_case_to_graph in
    queries.gsql, called via connection.run_query, not this helper. This exists for the
    rare ad-hoc single-row correction RESEARCH.md §2.2 calls out as upsert's actual job.
    """
    primary_id = attributes.pop("primary_id")
    conn.upsertVertex(vertex_type, primary_id, attributes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data"),
                         help="Directory containing transactions.csv, identity.csv, "
                              "closed_cases_history.csv (default ./data)")
    parser.add_argument("--out-dir", type=Path, default=None,
                         help="Where to write sliced outputs (default same as --data-dir)")
    parser.add_argument("--run-loading-job", action="store_true",
                         help="After slicing, connect to TigerGraph and RUN LOADING JOB load_fraud")
    args = parser.parse_args()

    data_dir: Path = args.data_dir
    out_dir: Path = args.out_dir or data_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    txn_slim = out_dir / "txn_slim.csv"
    v_parquet = out_dir / "txn_vcols.parquet"
    next_edges = out_dir / "next_edges.csv"
    case_vertices = out_dir / "closed_case_vertices.csv"
    case_involves = out_dir / "closed_case_involves.csv"
    case_connected = out_dir / "closed_case_connected.csv"

    slice_txn_slim(data_dir / "transactions.csv", data_dir / "identity.csv", txn_slim)
    slice_v_columns_parquet(data_dir / "transactions.csv", v_parquet)
    derive_next_edges(txn_slim, next_edges)
    slice_closed_cases(data_dir / "closed_cases_history.csv", case_vertices,
                        case_involves, case_connected)

    if args.run_loading_job:
        from src.graph.connection import get_conn
        conn = get_conn()
        run_loading_job(conn, out_dir)


if __name__ == "__main__":
    main()
