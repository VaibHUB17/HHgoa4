"""LangGraph state for the investigation graph, per RESEARCH.md §5.3."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


class InvestigationState(TypedDict):
    case_id: str
    trigger: dict                  # from case_pack.csv
    evidence: list[dict]           # {claim, source, ref, entity_ids}
    ledger: list[dict]             # weighted evidence items (keys into evidence_weights.yaml)
    p_fraud: float
    pattern: str
    affected_txn_ids: list[str]
    exposure_usd: float
    snapshots: list[dict]          # RecommendationSnapshot.__dict__ entries, initial / final
    prior_cases: list[str]
    evidence_requests: list[dict]
    loops: int                     # gather_evidence <-> assess iteration count, caps MAX_LOOPS
    approved: bool                 # set by policy_gate after interrupt()/resume
    graph_case_id: str             # set by write_case
    written_to_graph: bool         # set by write_case

    # "deny" | "confirm" | None. Written by request_evidence, read by _build_snapshot to
    # populate CaseState.customer_response, which is what R2 and R3 key off. Must stay
    # declared here: LangGraph merges state per declared channel, so an undeclared key is
    # silently dropped between nodes and both rules stop firing.
    _customer_response: str | None

    # True when the most recent `investigate` pass actually added something new to the
    # ledger; False once a re-investigation pass returns an empty delta (deps.py's
    # run_detectors dedups deterministic re-queries). need_more_evidence reads this to
    # stop looping back to `investigate` once another pass cannot change p_fraud. Same
    # declared-channel requirement as _customer_response above.
    _ledger_grew_this_pass: bool


@dataclass
class RecommendationSnapshot:
    """Internal record of one next-best-action recommendation at a point in the
    investigation. Two of these exist per case: one taken before any evidence request
    (snapshot_initial), one after (snapshot_final). Maps onto next_best_actions.initial /
    .final in the answer file; evidence_set_hash lets a reader verify the "final" snapshot
    was computed from a strict superset of the "initial" snapshot's evidence.
    """

    action_list: list[dict] = field(default_factory=list)  # [{action, route, reason}, ...]
    probability: float = 0.0
    exposure_usd: float = 0.0
    evidence_set_hash: str = ""
    timestamp: str = ""  # ISO 8601
    phase: str = ""      # "initial" | "final"
