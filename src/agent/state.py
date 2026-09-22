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
