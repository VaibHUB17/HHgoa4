"""Evidence ledger: turns typed evidence keys into a deterministic fraud probability.

Loads config/evidence_weights.yaml once. fraud_probability is never emitted by an LLM —
it is sigmoid(sum of weights of present evidence keys), clipped to [0, 1]. This makes the
number auditable: point a judge at the YAML file.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

_DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "evidence_weights.yaml"


def _load_weights(path: Path | str = _DEFAULT_WEIGHTS_PATH) -> dict[str, float]:
    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, dict] = yaml.safe_load(f)
    return {key: float(spec["w"]) for key, spec in raw.items()}


EVIDENCE_WEIGHTS: dict[str, float] = _load_weights()


class UnknownEvidenceKey(KeyError):
    """Raised by compute_probability() when given a key absent from
    config/evidence_weights.yaml. A typo or an unregistered detector key must not
    silently contribute zero weight and pass unnoticed -- that's exactly how a
    calibration bug ships without anyone catching it."""


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# Calibration constants for fraud_probability = sigmoid(BASELINE + SCALE * sum(weights)).
#
# A raw sigmoid(sum(weights)) puts a case with NO evidence at 0.5 (a coin flip), which is
# wrong: half the exam cases are legitimate, and absence of fraud evidence is (weak)
# evidence of no fraud. It also compresses the realistic range of weight sums into the
# middle of [0,1], making the §6 stop-high (p>=0.85) and stop-low (p<=0.15) criteria
# nearly unreachable.
#
# BASELINE=-1.8, SCALE=4.1 were chosen by solving for the smallest set of constants that
# satisfy six calibration points simultaneously (see tests/test_policy.py::test_ledger_calibration):
#   - no evidence                                              -> p <= 0.15
#   - risk_score_alone only                                    -> p <= 0.25  (§0: a score is never a verdict)
#   - card_testing_sequence + shared_device_across_cards
#       + customer_denies                                      -> 0.82 <= p <= 0.90
#     This is the README's own §3b/Answer-Format worked example (HHG-017), which lands at
#     fraud_probability 0.86 in the spec; with these constants the ledger computes 0.890,
#     inside the same decision band as the spec's anchor.
#   - risk_score_alone + customer_confirms                      -> p <= 0.10  (R3 closes as legitimate)
#   - risk_score_alone + recurring_merchant_match
#       + in_character_for_customer                             -> p <= 0.20  (R7 disputed-but-legitimate)
#   - card_testing_sequence alone                                -> 0.40 <= p <= 0.70
#     Must stay under the R1 0.70 block line: a single strong signal must not, by itself,
#     clear the threshold that would let R1's verify-before-block guard be skipped.
BASELINE = -1.8
SCALE = 4.1


def compute_probability(evidence_keys: Iterable[str], weights: dict[str, float] | None = None) -> float:
    """fraud_probability = sigmoid(BASELINE + SCALE * sum of weights of the given evidence
    keys), clipped [0,1]. See BASELINE/SCALE docstring above for the calibration anchors.

    Raises UnknownEvidenceKey listing every offending key if any key is not in the
    weights config -- a typo or a newly added detector key must fail loudly, not
    silently contribute zero and quietly under-score a case.
    """
    w = weights if weights is not None else EVIDENCE_WEIGHTS
    keys = list(evidence_keys)
    unknown = sorted({k for k in keys if k not in w})
    if unknown:
        raise UnknownEvidenceKey(
            f"evidence key(s) not in evidence_weights.yaml: {unknown}"
        )
    total = sum(w[key] for key in keys)
    p = sigmoid(BASELINE + SCALE * total)
    return min(1.0, max(0.0, p))


def independent_evidence_count(evidence_sources: Iterable[str]) -> int:
    """Count distinct evidence SOURCES, not items.

    Two facts pulled from the same query/source are one independent piece of evidence —
    this gates the §6 stopping rule (>= 2 independent pieces required to stop at p>=0.85
    or p<=0.15). Callers pass the `ref` (or `source`) string of each evidence item; this
    function dedupes and counts distinct values.
    """
    return len({s for s in evidence_sources if s})


def evidence_set_hash(evidence_ids: Iterable[str]) -> str:
    """sha256 of the sorted, deduped evidence-id list.

    Lets a snapshot prove exactly which evidence it was computed from — the "after"
    snapshot must hash to a strict superset of the "before" snapshot's evidence.
    """
    sorted_ids = sorted(set(evidence_ids))
    joined = "|".join(sorted_ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass
class EvidenceLedger:
    """Convenience wrapper bundling keys/sources/ids for one investigation snapshot."""

    keys: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)

    def add(self, key: str, source_ref: str, evidence_id: str) -> None:
        self.keys.append(key)
        self.sources.append(source_ref)
        self.ids.append(evidence_id)

    @property
    def probability(self) -> float:
        return compute_probability(self.keys)

    @property
    def independent_count(self) -> int:
        return independent_evidence_count(self.sources)

    @property
    def hash(self) -> str:
        return evidence_set_hash(self.ids)


def demo() -> None:
    """ponytail: smallest runnable self-check for the money-path logic in this module."""
    assert compute_probability([]) <= 0.15, "no evidence must read as low probability, not a coin flip"
    p_strong = compute_probability(["card_testing_sequence", "shared_device_across_cards"])
    assert p_strong > 0.6
    p_weak = compute_probability(["customer_confirms"])
    assert p_weak < 0.4
    assert independent_evidence_count(["q:a", "q:a", "q:b"]) == 2
    assert independent_evidence_count([]) == 0
    h1 = evidence_set_hash(["T1", "T2"])
    h2 = evidence_set_hash(["T2", "T1"])
    assert h1 == h2, "hash must be order-independent"
    h3 = evidence_set_hash(["T1", "T2", "T3"])
    assert h1 != h3
    try:
        compute_probability(["not_a_real_key"])
        raise AssertionError("expected UnknownEvidenceKey")
    except UnknownEvidenceKey:
        pass
    print("ledger.py self-check OK")


if __name__ == "__main__":
    demo()
