"""Tests for src/ml/*.py -- pytest only, synthetic in-memory data, no CSVs.

Must pass with NO dataset present (data/ is gitignored and ~700MB, never available in
CI). Covers the pure logic: feature extraction shape/columns, the time-split invariant,
that calibration improves Brier score on a deliberately miscalibrated synthetic model,
and that prior_probability() degrades to None with no model artifact.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.calibrate import brier_score, expected_calibration_error, isotonic_calibrate, reliability_table
from src.ml.features import FEATURE_COLUMNS, extract_features
from src.ml.predict import (
    HIGH_THRESHOLD,
    LOW_THRESHOLD,
    MODEL_PRIOR_HIGH_KEY,
    MODEL_PRIOR_LOW_KEY,
    prior_probability,
    to_ledger_key,
)
from src.ml.train import random_split_with_warning, time_split


def _synthetic_cases(n=20, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    opened = pd.date_range("2016-07-01", "2016-10-31", periods=n)
    rows = []
    for i in range(n):
        outcome = "confirmed_fraud" if i % 5 != 0 else "cleared"
        n_txns = int(rng.integers(1, 6))
        rows.append(
            {
                "case_id": f"CC-{i:04d}",
                "customer_id": f"C{i:05d}",
                "card_id": f"C{i:05d}-K1",
                "opened_at": opened[i].strftime("%Y-%m-%d %H:%M:%S"),
                "closed_at": (opened[i] + pd.Timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "outcome": outcome,
                "pattern": "card_testing" if outcome == "confirmed_fraud" else "none",
                "first_fraud_txn_id": f"T{i:06d}",
                "txn_ids": "|".join(f"T{i:06d}{j}" for j in range(n_txns)),
                "n_txns": n_txns,
                "exposure_usd": float(rng.uniform(10, 1000)),
                "connected_card_ids": "" if i % 3 else f"C{i:05d}-K2",
                "actions_taken": "BLOCK_CARD",
                "report_filed": "true" if i % 2 == 0 else "false",
                "analyst_notes": "synthetic note",
            }
        )
    return pd.DataFrame(rows)


# --- features.py --------------------------------------------------------------------


def test_extract_features_produces_documented_columns():
    cases = _synthetic_cases()
    X = extract_features(cases)
    assert list(X.columns) == FEATURE_COLUMNS
    assert len(X) == len(cases)


def test_extract_features_no_transactions_df_leaves_txn_aggregates_nan():
    """Without a joined transactions frame, txn-derived aggregates must be NaN, not 0 --
    absence of the join is not evidence the episode had zero span/spread.
    """
    cases = _synthetic_cases(n=3)
    X = extract_features(cases, transactions=None)
    for col in ("txn_amount_mean", "txn_amount_max", "episode_span_hours", "n_distinct_device_profiles"):
        assert X[col].isna().all(), f"{col} should be all-NaN with no transactions frame"


def test_extract_features_case_level_columns_are_populated():
    cases = _synthetic_cases(n=5)
    X = extract_features(cases)
    assert X["exposure_usd"].notna().all()
    assert X["n_txns"].notna().all()
    assert (X["case_duration_days"] > 0).all()
    # connected_card_ids empty string -> 0 connected cards, not NaN (a real, known zero).
    assert X["n_connected_cards"].notna().all()


def test_extract_features_missing_device_rows_do_not_fabricate_a_shared_ring():
    """A device-less (in_person) transaction must not be coalesced into a fake shared
    device key with every other device-less transaction (handover doc landmine).
    """
    cases = pd.DataFrame(
        [
            {
                "case_id": "CC-0001",
                "opened_at": "2016-07-01 00:00:00",
                "closed_at": "2016-07-02 00:00:00",
                "outcome": "confirmed_fraud",
                "txn_ids": "T1|T2",
                "n_txns": 2,
                "exposure_usd": 100.0,
                "connected_card_ids": "",
                "report_filed": "true",
            }
        ]
    )
    transactions = pd.DataFrame(
        [
            {"TransactionID": "T1", "TransactionAmt": 50.0, "ProductCD": "W", "addr1": 100, "channel": "in_person", "ts": "2016-07-01 00:00:00", "DeviceInfo": np.nan},
            {"TransactionID": "T2", "TransactionAmt": 50.0, "ProductCD": "W", "addr1": 100, "channel": "in_person", "ts": "2016-07-01 01:00:00", "DeviceInfo": np.nan},
        ]
    )
    X = extract_features(cases, transactions)
    # Both txns are device-less (in_person) -> 0 distinct device profiles, a real zero,
    # not NaN and not "1 shared device".
    assert X["n_distinct_device_profiles"].iloc[0] == 0


# --- train.py: time split ------------------------------------------------------------


def test_time_split_never_puts_later_case_in_train_than_validation():
    cases = _synthetic_cases(n=40)
    split = time_split(cases, train_end="2016-09-30", val_end="2016-10-31")
    opened = pd.to_datetime(cases["opened_at"])
    assert len(split.train_idx) > 0
    assert len(split.val_idx) > 0
    # Core invariant: max(train opened_at) <= min(val opened_at).
    assert opened.loc[split.train_idx].max() <= opened.loc[split.val_idx].min()
    # No overlap between the two index sets.
    assert set(split.train_idx).isdisjoint(set(split.val_idx))


def test_time_split_raises_on_empty_split():
    cases = _synthetic_cases(n=5)
    with pytest.raises(ValueError):
        time_split(cases, train_end="2016-01-01", val_end="2016-01-02")


def test_random_split_warns_loudly():
    cases = _synthetic_cases(n=20)
    with pytest.warns(UserWarning, match="leaks future cases"):
        split = random_split_with_warning(cases)
    assert len(split.train_idx) > 0
    assert len(split.val_idx) > 0
    assert set(split.train_idx).isdisjoint(set(split.val_idx))


# --- calibrate.py ----------------------------------------------------------------------


from sklearn.base import BaseEstimator, ClassifierMixin


class _MiscalibratedModel(ClassifierMixin, BaseEstimator):
    """A stand-in classifier whose predict_proba is deliberately overconfident (always
    near 0 or 1) even though the true fraud rate in the synthetic labels is ~0.6 -- a
    textbook miscalibration to check that isotonic calibration measurably improves it.

    Inherits BaseEstimator/ClassifierMixin so it satisfies sklearn's estimator checks
    (CalibratedClassifierCV's FrozenEstimator path validates full estimator conformance,
    not just predict_proba).

    `_estimator_type` is pinned explicitly: sklearn >= 1.6 resolves estimator type through
    `__sklearn_tags__`, and a mixin alone leaves FrozenEstimator reading this as a
    regressor, which then rejects predict_proba.
    """

    _estimator_type = "classifier"

    def __init__(self, raw_scores: np.ndarray | None = None):
        self.raw_scores = raw_scores

    def __sklearn_tags__(self):
        tags = super().__sklearn_tags__()
        tags.estimator_type = "classifier"
        return tags

    def fit(self, X, y=None):
        self.classes_ = np.array([0, 1])
        return self

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def predict_proba(self, X):
        p1 = self.raw_scores
        return np.column_stack([1 - p1, p1])


def test_calibration_improves_brier_score_on_miscalibrated_input():
    rng = np.random.default_rng(1)
    n = 200
    y_true = (rng.uniform(size=n) < 0.6).astype(int)
    # Overconfident scores: push true positives near 1, true negatives near 0, but with
    # enough noise that a monotonic recalibration can still improve things -- pure 0/1
    # scores would make isotonic regression a no-op rather than a genuine improvement.
    base = rng.uniform(0.3, 0.7, size=n)
    raw = np.where(y_true == 1, np.clip(base + 0.35, 0, 1), np.clip(base - 0.35, 0, 1))
    X = pd.DataFrame({"f": rng.normal(size=n)})
    y = pd.Series(y_true)
    model = _MiscalibratedModel(raw).fit(X, y)

    prob_before = model.predict_proba(X)[:, 1]
    brier_before = brier_score(y_true, prob_before)

    calibrated = isotonic_calibrate(model, X, y)
    prob_after = calibrated.predict_proba(X)[:, 1]
    brier_after = brier_score(y_true, prob_after)

    assert brier_after <= brier_before


def test_expected_calibration_error_perfect_case_is_zero():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.0, 0.0, 1.0, 1.0])
    assert expected_calibration_error(y_true, y_prob) == pytest.approx(0.0)


def test_reliability_table_is_text_and_nonempty():
    y_true = np.array([0, 1, 0, 1, 1])
    y_prob = np.array([0.1, 0.9, 0.2, 0.8, 0.6])
    table = reliability_table(y_true, y_prob, n_bins=5)
    assert isinstance(table, str)
    assert "bin" in table
    assert len(table.splitlines()) > 1


# --- predict.py --------------------------------------------------------------------


def test_prior_probability_returns_none_with_no_model_artifact(tmp_path):
    """Must degrade gracefully: no trained model on disk -> None, never a fabricated
    number, so the ledger can omit the signal.
    """
    result = prior_probability({"exposure_usd": 500.0}, artifacts_dir=tmp_path)
    assert result is None


def test_to_ledger_key_none_when_prior_is_none():
    assert to_ledger_key(None) is None


def test_to_ledger_key_maps_high_and_low_and_middle():
    assert to_ledger_key(HIGH_THRESHOLD) == MODEL_PRIOR_HIGH_KEY
    assert to_ledger_key(0.99) == MODEL_PRIOR_HIGH_KEY
    assert to_ledger_key(LOW_THRESHOLD) == MODEL_PRIOR_LOW_KEY
    assert to_ledger_key(0.01) == MODEL_PRIOR_LOW_KEY
    assert to_ledger_key(0.5) is None  # ambiguous middle band contributes nothing
