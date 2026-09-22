"""The handback contract (docs/BHAVYA.md): a calibrated fraud prior for the ledger.

    def prior_probability(case_features: dict) -> float

Loads the calibrated model from artifacts/calibrate.py's output. `src/policy/ledger.py`
consumes this as one weighted signal among many (see EVIDENCE_WEIGHTS in
config/evidence_weights.yaml) -- it is never the sole basis for a decision.

Graceful degradation is load-bearing here, not a nicety: if no trained model exists yet
(the common case before the dataset lands, or mid-hackathon before train.py has been run),
`prior_probability` returns `None`, not a fabricated number. The ledger's contract is to
omit an absent evidence key entirely (see EvidenceLedger.add / compute_probability in
ledger.py, which raises on unknown keys rather than accepting a placeholder) -- a fake
0.5 would silently and wrongly shift every case's fraud_probability. `None` is the only
correct "I don't have an opinion" signal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.ml.features import FEATURE_COLUMNS

_DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
_DEFAULT_MODEL_NAME = "calibrated_model.joblib"

# Ledger key vocabulary this module maps into. Coordinate any change here with
# config/evidence_weights.yaml -- keep weights modest (handover doc: "the model is one
# signal among several, and the existing calibration is already anchored; do not blow it
# up"). These thresholds are deliberately wide of the R1 0.70 block line and the section-6
# 0.85/0.15 stop lines, so the model prior alone can never single-handedly cross either.
MODEL_PRIOR_HIGH_KEY = "model_prior_high"
MODEL_PRIOR_LOW_KEY = "model_prior_low"
HIGH_THRESHOLD = 0.70
LOW_THRESHOLD = 0.15


def _model_path(artifacts_dir: Path | str | None) -> Path:
    base = Path(artifacts_dir) if artifacts_dir is not None else _DEFAULT_ARTIFACTS_DIR
    return base / _DEFAULT_MODEL_NAME


def prior_probability(case_features: dict[str, Any], artifacts_dir: Path | str | None = None) -> float | None:
    """A calibrated fraud probability for one case, or None if no trained model exists.

    Parameters
    ----------
    case_features: dict keyed by (a subset of) FEATURE_COLUMNS from features.py, e.g.
        {"exposure_usd": 850.0, "n_txns": 4, "case_duration_days": 2.0, ...}.
        Missing keys are treated as NaN (features.py's own "absence is structural, not
        zero" contract) -- the underlying HistGradientBoostingClassifier has native NaN
        support and does not need them imputed.
    artifacts_dir: override for where to look for the trained model. Defaults to
        <repo_root>/artifacts, matching train.py/calibrate.py's --out default.

    Returns
    -------
    float in [0, 1], or None when artifacts/calibrated_model.joblib does not exist yet.
    Callers (the ledger / evidence classifier) must check for None and simply omit the
    model_prior_* evidence key rather than substituting a guess.
    """
    path = _model_path(artifacts_dir)
    if not path.exists():
        return None

    import joblib

    model = joblib.load(path)
    row = {col: case_features.get(col) for col in FEATURE_COLUMNS}
    X = pd.DataFrame([row], columns=FEATURE_COLUMNS)
    proba = model.predict_proba(X)[0]
    # predict_proba columns follow the fitted classes_ order; class 1 == confirmed_fraud
    # by construction in train.py (y = outcome == "confirmed_fraud").
    classes = list(model.classes_)
    fraud_idx = classes.index(1) if 1 in classes else int(len(classes) > 1)
    return float(proba[fraud_idx])


def to_ledger_key(p: float | None) -> str | None:
    """Map a prior probability into the evidence-ledger vocabulary.

    Returns None (meaning: contribute no evidence key) when `p` is None or falls in the
    ambiguous middle band [LOW_THRESHOLD, HIGH_THRESHOLD] -- a mediocre model prior isn't
    worth spending an evidence slot on, and per the calibration doc in ledger.py the
    thresholds are set well clear of the ledger's own R1/0.85/0.15 decision lines so this
    signal can only ever corroborate, never single-handedly decide.

    Add MODEL_PRIOR_HIGH_KEY / MODEL_PRIOR_LOW_KEY to config/evidence_weights.yaml with
    modest weights (e.g. in the 0.10-0.15 range, comparable to new_device_marker) before
    wiring this into the live ledger -- this module intentionally does not choose a
    weight for you, that's a policy decision Vaibhav/Karan's evidence_weights.yaml owns.
    """
    if p is None:
        return None
    if p >= HIGH_THRESHOLD:
        return MODEL_PRIOR_HIGH_KEY
    if p <= LOW_THRESHOLD:
        return MODEL_PRIOR_LOW_KEY
    return None
