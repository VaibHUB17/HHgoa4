"""Calibrate the baseline model's fraud probability.

This is the module that earns marks per the README: `fraud_probability` in every answer
file is "scored for calibration", not accuracy. A model that's 85% accurate but always
outputs 0.95 or 0.05 scores worse than one that's 80% accurate and honestly says 0.6 when
unsure (docs/BHAVYA.md, Task 1).

Provides:
  - `platt_calibrate()` / `isotonic_calibrate()` -- thin wrappers around sklearn's
    CalibratedClassifierCV with method="sigmoid" (Platt) or method="isotonic".
  - `brier_score()` -- mean squared error between predicted probability and outcome,
    the standard calibration-quality metric (lower is better).
  - `expected_calibration_error()` -- mean, bin-weighted gap between predicted
    confidence and observed frequency within each bin (lower is better).
  - `reliability_table()` -- prints the same bins as text, so calibration quality is
    readable without opening the PNG.
  - `plot_reliability_curve()` -- saves a before/after reliability diagram to a PNG.

CLI:
    python -m src.ml.calibrate --data-dir ./data --model artifacts/baseline_model.joblib --out artifacts/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV

from src.ml.features import extract_features
from src.ml.train import time_split


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Mean squared error between predicted probability and the 0/1 outcome. 0 is
    perfect, 0.25 is what a constant p=0.5 predictor scores on a balanced set.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    return float(np.mean((y_prob - y_true) ** 2))


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """ECE: bucket predictions into `n_bins` equal-width bins over [0,1], and take the
    bin-size-weighted mean absolute gap between each bin's average predicted probability
    and its observed fraud rate. 0 is perfectly calibrated.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(y_true)
    if n == 0:
        return float("nan")

    ece = 0.0
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        in_bin = (y_prob >= lo) & (y_prob < hi) if hi < 1.0 else (y_prob >= lo) & (y_prob <= hi)
        count = int(in_bin.sum())
        if count == 0:
            continue
        avg_pred = float(y_prob[in_bin].mean())
        avg_true = float(y_true[in_bin].mean())
        ece += (count / n) * abs(avg_pred - avg_true)
    return float(ece)


def reliability_table(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> str:
    """Text rendering of the reliability bins: predicted-probability bin, count, mean
    predicted probability, observed fraud rate. Readable without opening the PNG.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    lines = [f"{'bin':>13} | {'n':>5} | {'mean_pred':>9} | {'observed':>8}"]
    lines.append("-" * len(lines[0]))
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        in_bin = (y_prob >= lo) & (y_prob < hi) if hi < 1.0 else (y_prob >= lo) & (y_prob <= hi)
        count = int(in_bin.sum())
        if count == 0:
            lines.append(f"{lo:5.2f}-{hi:5.2f} | {0:5d} | {'--':>9} | {'--':>8}")
            continue
        mean_pred = float(y_prob[in_bin].mean())
        observed = float(y_true[in_bin].mean())
        lines.append(f"{lo:5.2f}-{hi:5.2f} | {count:5d} | {mean_pred:9.3f} | {observed:8.3f}")
    return "\n".join(lines)


def _prefit(model):
    """Wrap an already-fit estimator so CalibratedClassifierCV calibrates it without
    refitting. sklearn >=1.6 removed `cv="prefit"` in favor of wrapping the estimator in
    `sklearn.frozen.FrozenEstimator`; fall back to the `cv="prefit"` string for older
    sklearn so this keeps working across the versions requirements.txt's `>=1.4` allows.
    """
    try:
        from sklearn.frozen import FrozenEstimator

        return FrozenEstimator(model), {}
    except ImportError:
        return model, {"cv": "prefit"}


def platt_calibrate(model, X: pd.DataFrame, y: pd.Series) -> CalibratedClassifierCV:
    """Platt scaling: fit a logistic curve on top of the base model's scores.
    `model` must already be fit -- see `_prefit()` for how "don't refit the base" is
    expressed across sklearn versions.
    """
    estimator, kwargs = _prefit(model)
    calibrated = CalibratedClassifierCV(estimator, method="sigmoid", **kwargs)
    calibrated.fit(X, y)
    return calibrated


def isotonic_calibrate(model, X: pd.DataFrame, y: pd.Series) -> CalibratedClassifierCV:
    """Isotonic regression calibration: a non-parametric monotonic fit. More flexible
    than Platt, needs more calibration data to avoid overfitting the calibration curve
    itself -- with only ~10% held out for validation, prefer Platt on small splits.
    """
    estimator, kwargs = _prefit(model)
    calibrated = CalibratedClassifierCV(estimator, method="isotonic", **kwargs)
    calibrated.fit(X, y)
    return calibrated


def plot_reliability_curve(
    y_true: np.ndarray,
    prob_before: np.ndarray,
    prob_after: np.ndarray,
    out_path: Path,
    n_bins: int = 10,
) -> None:
    """Save a before/after reliability diagram (predicted probability vs. observed
    fraud rate, plus the perfect-calibration diagonal) to `out_path` as a PNG.
    """
    import matplotlib

    matplotlib.use("Agg")  # headless: no display available in CI / hackathon runners
    import matplotlib.pyplot as plt

    def _binned(y_true, y_prob):
        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
        xs, ys = [], []
        for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
            in_bin = (y_prob >= lo) & (y_prob < hi) if hi < 1.0 else (y_prob >= lo) & (y_prob <= hi)
            if in_bin.sum() == 0:
                continue
            xs.append(float(y_prob[in_bin].mean()))
            ys.append(float(y_true[in_bin].mean()))
        return xs, ys

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="perfect calibration")

    xb, yb = _binned(np.asarray(y_true, dtype=float), np.asarray(prob_before, dtype=float))
    ax.plot(xb, yb, marker="o", label="before calibration")

    xa, ya = _binned(np.asarray(y_true, dtype=float), np.asarray(prob_after, dtype=float))
    ax.plot(xa, ya, marker="o", label="after calibration")

    ax.set_xlabel("mean predicted probability")
    ax.set_ylabel("observed fraud rate")
    ax.set_title("Reliability curve: before vs. after calibration")
    ax.legend()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--model", type=Path, default=Path("artifacts/baseline_model.joblib"))
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    parser.add_argument("--method", choices=["platt", "isotonic"], default="isotonic")
    parser.add_argument("--train-end", default="2016-09-30")
    parser.add_argument("--val-end", default="2016-10-31")
    args = parser.parse_args(argv)

    cases_path = args.data_dir / "closed_cases_history.csv"
    if not cases_path.exists() or not args.model.exists():
        print(f"error: need both {cases_path} and {args.model}. Run train.py first.", file=sys.stderr)
        return 1

    import joblib

    cases = pd.read_csv(cases_path)
    txns_path = args.data_dir / "transactions.csv"
    transactions = pd.read_csv(txns_path) if txns_path.exists() else None

    X = extract_features(cases, transactions)
    y = (cases["outcome"] == "confirmed_fraud").astype(int)
    y.index = X.index

    split = time_split(cases, train_end=args.train_end, val_end=args.val_end)
    val_X, val_y = X.loc[split.val_idx], y.loc[split.val_idx]

    model = joblib.load(args.model)
    prob_before = model.predict_proba(val_X)[:, 1]

    calibrator = platt_calibrate if args.method == "platt" else isotonic_calibrate
    calibrated = calibrator(model, val_X, val_y)
    prob_after = calibrated.predict_proba(val_X)[:, 1]

    y_true = val_y.to_numpy()
    print(f"method: {args.method}")
    print(f"Brier score before: {brier_score(y_true, prob_before):.4f}")
    print(f"Brier score after:  {brier_score(y_true, prob_after):.4f}")
    print(f"ECE before: {expected_calibration_error(y_true, prob_before):.4f}")
    print(f"ECE after:  {expected_calibration_error(y_true, prob_after):.4f}")
    print("\n--- reliability table (before) ---")
    print(reliability_table(y_true, prob_before))
    print("\n--- reliability table (after) ---")
    print(reliability_table(y_true, prob_after))

    args.out.mkdir(parents=True, exist_ok=True)
    joblib.dump(calibrated, args.out / "calibrated_model.joblib")
    plot_reliability_curve(y_true, prob_before, prob_after, args.out / "reliability_curve.png")
    print(f"\nwrote {args.out / 'calibrated_model.joblib'} and {args.out / 'reliability_curve.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
