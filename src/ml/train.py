"""Train the closed-case fraud-prior model.

Two models, per docs/BHAVYA.md Task 1:
  1. `train_baseline()` -- HistGradientBoostingClassifier on features.py's feature vector.
     This is the one that ships. Fit it, calibrate it (calibrate.py), done.
  2. `GNN_STUB` -- deliberately NOT implemented here. See its docstring below for what
     Bhavya builds himself: a per-case subgraph classifier over
     Customer/Card/Transaction/DeviceProfile/BillingRegion. Left as a seam because the
     baseline is the one thing the rest of the pipeline (predict.py, the ledger) needs to
     exist; the GNN is optional upside on top of it (README: "no ML criterion in the
     rubric... helps only insofar as it makes the probability better calibrated").

CRITICAL split rule (handover/06-decisions-and-gotchas.md, "Split by time, never
randomly"): closed cases run Jul-Oct 2016, the exam cases run Nov-Dec 2016. A random
train/val split lets the model see cases chronologically *after* validation cases during
training, which leaks information no real deployment would have and makes the validation
score lie. `time_split()` below is therefore the only split path; a random split requires
the explicit `--allow-random-split` CLI flag, which prints a loud warning before doing it.

CLI:
    python -m src.ml.train --data-dir ./data --out artifacts/
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import classification_report, precision_recall_fscore_support

from src.ml.features import FEATURE_COLUMNS, extract_features

RANDOM_STATE = 42


@dataclass
class SplitResult:
    train_idx: pd.Index
    val_idx: pd.Index
    train_end: pd.Timestamp
    val_end: pd.Timestamp


def time_split(
    cases: pd.DataFrame,
    train_end: str = "2016-09-30",
    val_end: str = "2016-10-31",
    opened_at_col: str = "opened_at",
) -> SplitResult:
    """Split closed cases by `opened_at`, train on everything up to and including
    `train_end`, validate on the window after it through `val_end`.

    This is the ONLY split a case can go through without an explicit opt-out (see
    `random_split_with_warning`). It guarantees no validation case has an `opened_at`
    earlier than any training case's `opened_at` -- i.e. training never sees the future
    relative to what it is validated against.
    """
    opened = pd.to_datetime(cases[opened_at_col], errors="coerce")
    train_end_ts = pd.Timestamp(train_end)
    val_end_ts = pd.Timestamp(val_end)

    train_mask = opened <= train_end_ts
    val_mask = (opened > train_end_ts) & (opened <= val_end_ts)

    train_idx = cases.index[train_mask]
    val_idx = cases.index[val_mask]

    if len(train_idx) == 0 or len(val_idx) == 0:
        raise ValueError(
            f"time_split produced an empty split (train={len(train_idx)}, "
            f"val={len(val_idx)}) -- check train_end/val_end against the data's "
            f"opened_at range: {opened.min()} .. {opened.max()}"
        )

    # Invariant check: every training case's opened_at must be <= every validation
    # case's opened_at. This is the property the whole split exists to guarantee.
    if opened[train_idx].max() > opened[val_idx].min():
        raise AssertionError(
            "time_split invariant violated: a training case opens after a validation "
            "case. This should be unreachable given the mask logic above."
        )

    return SplitResult(train_idx=train_idx, val_idx=val_idx, train_end=train_end_ts, val_end=val_end_ts)


def random_split_with_warning(cases: pd.DataFrame, val_frac: float = 0.2, seed: int = RANDOM_STATE) -> SplitResult:
    """A random train/val split. ONLY reachable via `--allow-random-split` on the CLI.

    Do not use this for real validation numbers. It leaks the future into training (a
    case opened in October can land in the training set while a case opened in August
    lands in validation) and will make the reported precision/recall look better than
    what the model actually achieves on the Nov-Dec exam cases. It exists only for quick
    smoke-testing of the training code path itself, never for a number you'd report.
    """
    warnings.warn(
        "RANDOM SPLIT REQUESTED: this leaks future cases into training and will produce "
        "an optimistic, meaningless validation score. Closed cases run Jul-Oct 2016 and "
        "the exam cases run Nov-Dec 2016 -- only a time-based split (the default) tells "
        "you how the model will behave on cases it hasn't seen yet. Use this flag for "
        "pipeline smoke-testing ONLY, never to report a validation number.",
        stacklevel=2,
    )
    print(
        "!!! WARNING: --allow-random-split is active. This train/val split is random, "
        "not chronological. Reported metrics from this run are NOT a valid estimate of "
        "Nov-Dec performance and must not be quoted as such. !!!",
        file=sys.stderr,
    )
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(cases.index.to_numpy())
    n_val = max(1, int(len(shuffled) * val_frac))
    val_idx = pd.Index(shuffled[:n_val])
    train_idx = pd.Index(shuffled[n_val:])
    opened = pd.to_datetime(cases["opened_at"], errors="coerce")
    return SplitResult(
        train_idx=train_idx,
        val_idx=val_idx,
        train_end=opened.max(),
        val_end=opened.max(),
    )


def _class_weights(y: np.ndarray) -> dict[int, float]:
    """Inverse-frequency class weights for the 4665:900 (confirmed_fraud:cleared)
    imbalance, so the classifier isn't rewarded for the trivial "always predict fraud"
    strategy -- exactly the failure mode docs/BHAVYA.md calls out, since half the exam
    cases are legitimate.
    """
    classes, counts = np.unique(y, return_counts=True)
    n = len(y)
    return {int(c): n / (len(classes) * cnt) for c, cnt in zip(classes, counts)}


def train_baseline(
    train_X: pd.DataFrame,
    train_y: pd.Series,
) -> HistGradientBoostingClassifier:
    """Fit HistGradientBoostingClassifier with class weights for the fraud/cleared
    imbalance. HGB is used over plain LogisticRegression because it handles the
    structural NaNs from features.py natively (native missing-value support), which
    matters here since absence is meaningful and must not be imputed away.
    """
    weights = _class_weights(train_y.to_numpy())
    sample_weight = train_y.map(weights).to_numpy()
    model = HistGradientBoostingClassifier(random_state=RANDOM_STATE)
    model.fit(train_X, train_y, sample_weight=sample_weight)
    return model


def evaluate(model, val_X: pd.DataFrame, val_y: pd.Series, positive_label=1, cleared_label=0) -> dict:
    """Report precision/recall/F1 for BOTH classes, with the `cleared` class broken out
    explicitly per docs/BHAVYA.md ("Report precision/recall on the cleared class
    specifically, not just overall accuracy") -- overall accuracy on a 5:1 imbalanced set
    is dominated by the majority class and hides exactly the failure mode that matters.
    """
    pred = model.predict(val_X)
    precision, recall, f1, support = precision_recall_fscore_support(
        val_y, pred, labels=[cleared_label, positive_label], zero_division=0
    )
    report = {
        "cleared": {
            "precision": float(precision[0]),
            "recall": float(recall[0]),
            "f1": float(f1[0]),
            "support": int(support[0]),
        },
        "confirmed_fraud": {
            "precision": float(precision[1]),
            "recall": float(recall[1]),
            "f1": float(f1[1]),
            "support": int(support[1]),
        },
        "accuracy": float((pred == val_y.to_numpy()).mean()),
        "classification_report": classification_report(
            val_y, pred, labels=[cleared_label, positive_label],
            target_names=["cleared", "confirmed_fraud"], zero_division=0,
        ),
    }
    return report


def GNN_STUB() -> None:
    """Not implemented. This is Bhavya's to build, on purpose (docs/BHAVYA.md Task 1,
    step 2: "Then the GNN, if the baseline is done and checkpoints are green").

    What to implement here when picking this up:
      1. Build a per-case subgraph: for each closed case, pull the Customer, Card(s) in
         `connected_card_ids` + the case's own card_id, the Transactions in `txn_ids`,
         their DeviceProfile (DeviceInfo+OS+browser+screen) and BillingRegion (addr1)
         neighbors, out of TigerGraph (or a local edge-list built the same way from
         transactions.csv/identity.csv if TigerGraph isn't up yet).
      2. Label each subgraph with the case's `outcome` (confirmed_fraud / cleared).
      3. Train a graph classifier -- GraphSAGE or GAT, via PyTorch Geometric -- over
         these subgraphs. The genuine advantage over the HGB baseline is that it sees
         *structure*: a card two hops from a device seen on a known-fraud case, which
         flat tabular features in features.py cannot express.
      4. Time-split exactly as `time_split()` does above -- same Jul-Sep/Oct rule, same
         reason. Don't rebuild a random split for this path.
      5. Calibrate its output through calibrate.py exactly like the baseline; the
         ledger only ever consumes a calibrated probability.
      6. Do NOT add torch / torch-geometric to requirements.txt until this is actually
         being built -- the rest of the pipeline (predict.py, tests) must keep working
         with only pandas/numpy/scikit-learn/matplotlib installed.
    """
    raise NotImplementedError(
        "GNN_STUB is an intentional seam, not a bug. See this function's docstring for "
        "what to build: a per-case subgraph GraphSAGE/GAT classifier over "
        "Customer/Card/Transaction/DeviceProfile/BillingRegion, trained with the same "
        "time_split() used by the baseline. The baseline in train_baseline() is the "
        "model that ships; this is optional upside on top of it."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Directory containing closed_cases_history.csv (and optionally transactions.csv)")
    parser.add_argument("--out", type=Path, default=Path("artifacts"), help="Directory to write the trained model and metrics into")
    parser.add_argument("--train-end", default="2016-09-30", help="Last opened_at date (inclusive) in the training set")
    parser.add_argument("--val-end", default="2016-10-31", help="Last opened_at date (inclusive) in the validation set")
    parser.add_argument(
        "--allow-random-split",
        action="store_true",
        help="Use a RANDOM train/val split instead of the time-based default. Leaks the "
        "future into training -- see random_split_with_warning()'s docstring. Only for "
        "smoke-testing the pipeline, never for a reported validation number.",
    )
    args = parser.parse_args(argv)

    cases_path = args.data_dir / "closed_cases_history.csv"
    if not cases_path.exists():
        print(f"error: {cases_path} not found. Bhavya runs this once the dataset lands.", file=sys.stderr)
        return 1

    cases = pd.read_csv(cases_path)

    txns_path = args.data_dir / "transactions.csv"
    transactions = pd.read_csv(txns_path) if txns_path.exists() else None
    if transactions is None:
        print(f"note: {txns_path} not found -- training on case-level features only "
              f"(txn-derived aggregates will be NaN).", file=sys.stderr)

    X = extract_features(cases, transactions)
    y = (cases["outcome"] == "confirmed_fraud").astype(int)
    y.index = X.index

    if args.allow_random_split:
        split = random_split_with_warning(cases)
    else:
        split = time_split(cases, train_end=args.train_end, val_end=args.val_end)

    train_X, train_y = X.loc[split.train_idx], y.loc[split.train_idx]
    val_X, val_y = X.loc[split.val_idx], y.loc[split.val_idx]

    print(f"train: {len(train_X)} cases (fraud={int(train_y.sum())}, cleared={int((1 - train_y).sum())})")
    print(f"val:   {len(val_X)} cases (fraud={int(val_y.sum())}, cleared={int((1 - val_y).sum())})")

    model = train_baseline(train_X, train_y)
    report = evaluate(model, val_X, val_y)

    print("\n--- validation report ---")
    print(report["classification_report"])
    print(f"cleared class: precision={report['cleared']['precision']:.3f} "
          f"recall={report['cleared']['recall']:.3f} f1={report['cleared']['f1']:.3f}")

    args.out.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(model, args.out / "baseline_model.joblib")
    (args.out / "metrics.json").write_text(
        json.dumps(
            {
                "feature_columns": FEATURE_COLUMNS,
                "train_end": str(split.train_end),
                "val_end": str(split.val_end),
                "n_train": len(train_X),
                "n_val": len(val_X),
                "cleared": report["cleared"],
                "confirmed_fraud": report["confirmed_fraud"],
                "accuracy": report["accuracy"],
                "random_split": bool(args.allow_random_split),
            },
            indent=2,
        )
    )
    print(f"\nwrote {args.out / 'baseline_model.joblib'} and {args.out / 'metrics.json'}")
    print("next: python -m src.ml.calibrate --data-dir", args.data_dir, "--model", args.out / "baseline_model.joblib", "--out", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
