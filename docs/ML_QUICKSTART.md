# ML quickstart

Full scope: `docs/BHAVYA.md`. This is just the commands.

## The three commands, once `data/closed_cases_history.csv` lands

```bash
# 1. First-hour exploration -- outcome counts, patterns, exposure, and (most important)
#    every analyst_notes where pattern == 'undocumented'. Read that section yourself.
python notebooks/explore_closed_cases.py

# 2. Train the baseline (HistGradientBoostingClassifier, time-based split, class-weighted).
python -m src.ml.train --data-dir ./data --out artifacts/

# 3. Calibrate it (isotonic by default) and get the reliability curve.
python -m src.ml.calibrate --data-dir ./data --model artifacts/baseline_model.joblib --out artifacts/
```

## What each one outputs

- **`explore_closed_cases.py`**: prints to stdout only. Four sections: outcome counts,
  pattern distribution, exposure distribution by outcome/pattern, and every
  `undocumented`-pattern case's `analyst_notes` in full.
- **`train.py`**: `artifacts/baseline_model.joblib` (fitted classifier) and
  `artifacts/metrics.json` (train/val sizes, precision/recall/F1 for the `cleared` class
  specifically, accuracy). Prints the same report to stdout. Split is by `opened_at`
  (train ≤ Sep 30, validate Oct) by default -- a random split requires
  `--allow-random-split` and prints a loud warning, because it leaks Nov/Dec-shaped
  future information into training and lies about validation performance.
- **`calibrate.py`**: `artifacts/calibrated_model.joblib` (what `predict.py` loads) and
  `artifacts/reliability_curve.png`. Prints Brier score and expected calibration error
  (ECE) before/after, plus a text `reliability_table()` so you don't need to open the PNG.

## Reading the reliability curve

X-axis: mean predicted probability within a bin. Y-axis: observed fraud rate within that
same bin. The dashed diagonal is perfect calibration. "before calibration" sitting above
the diagonal at low-predicted-probability bins (or below it at high bins) means the raw
model is overconfident there; "after calibration" hugging the diagonal is the goal. The
text table (`reliability_table()`, also printed by `calibrate.py`) shows the same thing
as rows: bin range, count, mean predicted probability, observed rate -- a bin where
`mean_pred` and `observed` are far apart is where the model is miscalibrated.

## The handback contract

```python
from src.ml.predict import prior_probability, to_ledger_key

p = prior_probability(case_features)   # float in [0,1], or None if no model trained yet
key = to_ledger_key(p)                 # "model_prior_high" / "model_prior_low" / None
```

`None` means "no opinion" -- omit the evidence key, don't substitute a guess. See
`src/ml/predict.py` docstrings for the full contract and how `to_ledger_key` thresholds
were chosen to stay clear of the policy's own 0.70/0.85/0.15 decision lines.
