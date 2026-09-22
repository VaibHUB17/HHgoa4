"""closed_cases_history.csv row (+ optional joined transactions.csv) -> numeric feature vector.

Feature set is limited to what the README documents as real:
https://.../HHgoa4/README.md  columns for closed_cases_history.csv and transactions.csv.

Missing values here are STRUCTURAL, not random (handover/06-decisions-and-gotchas.md,
"A missing identity row is a signal, not missing data"). We never blanket-fillna(0):
- `in_person` channel transactions have no identity/device row by construction (ProductCD
  == 'W'). A device-profile count of 0 for them is correct, not a gap.
- `connected_card_ids` empty means "no linked cards", which is a real 0.
- Transaction-derived aggregates (amount std, distances, etc.) are NaN when the case's
  txn_ids don't join to any row in the transactions frame (e.g. transactions.csv not
  loaded yet, or a stale/typo'd txn id) -- that NaN must stay NaN so a downstream model
  or the caller can tell "known zero" from "unknown", rather than silently treating
  absence of data as evidence of absence of activity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Documented output column order. Keep this list and FEATURE_COLUMNS in sync -- train.py,
# predict.py and the tests all key off this constant so the feature contract has exactly
# one source of truth.
FEATURE_COLUMNS: list[str] = [
    "exposure_usd",
    "n_txns",
    "case_duration_days",
    "n_connected_cards",
    "report_filed",
    "txn_amount_mean",
    "txn_amount_max",
    "txn_amount_std",
    "n_distinct_product_codes",
    "n_distinct_billing_regions",
    "channel_online_frac",
    "episode_span_hours",
    "n_distinct_device_profiles",
]


def _parse_ids(cell) -> list[str]:
    """Split a pipe-separated id cell into a clean list. NaN/empty -> []."""
    if cell is None or (isinstance(cell, float) and np.isnan(cell)):
        return []
    s = str(cell).strip()
    if not s:
        return []
    return [x for x in s.split("|") if x]


def _txn_aggregates_for_case(txn_ids: list[str], transactions: pd.DataFrame | None) -> dict:
    """Aggregate the joined transaction rows for one case's txn_ids.

    Returns NaN for every aggregate when `transactions` is None, the case has no txn_ids,
    or none of the txn_ids are present in `transactions` -- these are three different
    "we don't know" situations, never coerced to 0.
    """
    empty = {
        "txn_amount_mean": np.nan,
        "txn_amount_max": np.nan,
        "txn_amount_std": np.nan,
        "n_distinct_product_codes": np.nan,
        "n_distinct_billing_regions": np.nan,
        "channel_online_frac": np.nan,
        "episode_span_hours": np.nan,
        "n_distinct_device_profiles": np.nan,
    }
    if transactions is None or not txn_ids:
        return empty

    id_col = "TransactionID" if "TransactionID" in transactions.columns else "transaction_id"
    rows = transactions[transactions[id_col].astype(str).isin(txn_ids)]
    if rows.empty:
        return empty

    out = dict(empty)

    if "TransactionAmt" in rows.columns:
        amt = rows["TransactionAmt"].astype(float)
        out["txn_amount_mean"] = float(amt.mean())
        out["txn_amount_max"] = float(amt.max())
        # std of a single row is NaN by definition (ddof=1, 0 degrees of freedom) --
        # leave it as NaN rather than fabricating a 0, a single-transaction case has no
        # variance to report, that is different from "we measured zero variance".
        out["txn_amount_std"] = float(amt.std()) if len(amt) > 1 else np.nan

    if "ProductCD" in rows.columns:
        out["n_distinct_product_codes"] = int(rows["ProductCD"].nunique(dropna=True))

    if "addr1" in rows.columns:
        out["n_distinct_billing_regions"] = int(rows["addr1"].nunique(dropna=True))

    if "channel" in rows.columns:
        chan = rows["channel"].dropna()
        if len(chan) > 0:
            out["channel_online_frac"] = float((chan == "online").mean())

    if "ts" in rows.columns:
        ts = pd.to_datetime(rows["ts"], errors="coerce").dropna()
        if len(ts) > 0:
            out["episode_span_hours"] = float((ts.max() - ts.min()).total_seconds() / 3600.0)

    if "DeviceInfo" in rows.columns:
        # A device profile is DeviceInfo + OS + browser + screen per the README schema.
        # Missing DeviceInfo means in_person / no identity row -- exclude those rows from
        # the distinct-device count rather than treating NaN as one shared "no device"
        # profile (handover doc: never coalesce a missing device key, it fakes a ring).
        device_cols = [c for c in ("DeviceInfo", "id_30", "id_31", "id_33") if c in rows.columns]
        with_device = rows.dropna(subset=["DeviceInfo"])
        if len(with_device) > 0:
            key = with_device[device_cols].astype(str).agg("|".join, axis=1)
            out["n_distinct_device_profiles"] = int(key.nunique())
        else:
            out["n_distinct_device_profiles"] = 0

    return out


def extract_features(
    cases: pd.DataFrame,
    transactions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Turn closed_cases_history.csv rows into a numeric feature DataFrame.

    Parameters
    ----------
    cases: DataFrame with (at least) the closed_cases_history.csv columns:
        case_id, customer_id, card_id, opened_at, closed_at, outcome, pattern,
        first_fraud_txn_id, txn_ids, n_txns, exposure_usd, connected_card_ids,
        actions_taken, report_filed, analyst_notes
    transactions: optional transactions.csv (or a subset with TransactionID,
        TransactionAmt, ProductCD, addr1, channel, ts, DeviceInfo, ...) to join on
        txn_ids for richer per-episode aggregates. If omitted, the txn-derived columns
        are all NaN -- the case-level columns alone are still returned.

    Returns
    -------
    DataFrame indexed like `cases`, columns == FEATURE_COLUMNS (see module docstring for
    why NaN, not 0, marks "unknown" throughout).
    """
    out = pd.DataFrame(index=cases.index)

    out["exposure_usd"] = pd.to_numeric(cases.get("exposure_usd"), errors="coerce")
    out["n_txns"] = pd.to_numeric(cases.get("n_txns"), errors="coerce")

    opened = pd.to_datetime(cases.get("opened_at"), errors="coerce")
    closed = pd.to_datetime(cases.get("closed_at"), errors="coerce")
    out["case_duration_days"] = (closed - opened).dt.total_seconds() / 86400.0

    if "connected_card_ids" in cases.columns:
        out["n_connected_cards"] = cases["connected_card_ids"].apply(lambda c: len(_parse_ids(c)))
    else:
        out["n_connected_cards"] = np.nan

    if "report_filed" in cases.columns:
        # Structural boolean-ish column (True/False/yes/no/1/0 depending on export). Keep
        # NaN when genuinely absent rather than assuming "not filed".
        def _bool_or_nan(v):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return np.nan
            s = str(v).strip().lower()
            if s in ("true", "yes", "1"):
                return 1.0
            if s in ("false", "no", "0"):
                return 0.0
            return np.nan

        out["report_filed"] = cases["report_filed"].apply(_bool_or_nan)
    else:
        out["report_filed"] = np.nan

    txn_rows = []
    for _, row in cases.iterrows():
        ids = _parse_ids(row.get("txn_ids"))
        txn_rows.append(_txn_aggregates_for_case(ids, transactions))
    txn_df = pd.DataFrame(txn_rows, index=cases.index)
    for col in (
        "txn_amount_mean",
        "txn_amount_max",
        "txn_amount_std",
        "n_distinct_product_codes",
        "n_distinct_billing_regions",
        "channel_online_frac",
        "episode_span_hours",
        "n_distinct_device_profiles",
    ):
        out[col] = txn_df[col]

    return out[FEATURE_COLUMNS]
