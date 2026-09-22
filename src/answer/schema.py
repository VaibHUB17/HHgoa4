"""Answer-file dataclasses, matching README.md's "Answer Format" section field-for-field.

Nothing invented, nothing omitted. `to_json()` emits exactly the README's field names and
top-level ordering: case_id, case, evidence_requests, next_best_actions, sar, stop_reason,
tool_calls, tokens, latency_s.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["fraud", "legitimate", "uncertain"]
Status = Literal["open", "closed_fraud", "closed_legitimate", "escalated"]
Pattern = Literal[
    "card_testing",
    "card_not_present_fraud",
    "card_not_present_new_device",
    "out_of_region_use",
    "account_takeover",
    "undocumented",
    "none",
]
EvidenceSource = Literal["graph", "document", "customer", "external"]
EvidenceRequestType = Literal["customer_validation", "step_up_auth", "analyst_info"]
ActionRoute = Literal["auto", "L1", "L2"]

PATTERN_VALUES = frozenset(
    (
        "card_testing",
        "card_not_present_fraud",
        "card_not_present_new_device",
        "out_of_region_use",
        "account_takeover",
        "undocumented",
        "none",
    )
)
VERDICT_VALUES = frozenset(("fraud", "legitimate", "uncertain"))
STATUS_VALUES = frozenset(("open", "closed_fraud", "closed_legitimate", "escalated"))


@dataclass
class Evidence:
    claim: str
    source: EvidenceSource
    ref: str
    entity_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "source": self.source,
            "ref": self.ref,
            "entity_ids": list(self.entity_ids),
        }


@dataclass
class Case:
    status: Status
    verdict: Verdict
    fraud_probability: float
    pattern: Pattern
    pattern_description: str
    affected_txn_ids: list[str]
    first_suspicious_txn_id: str
    connected_card_ids: list[str]
    connected_device_profiles: list[str]
    exposure_usd: float
    evidence: list[Evidence]
    similar_prior_cases: list[str]
    summary: str
    written_to_graph: bool
    graph_case_id: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "verdict": self.verdict,
            "fraud_probability": self.fraud_probability,
            "pattern": self.pattern,
            "pattern_description": self.pattern_description,
            "affected_txn_ids": list(self.affected_txn_ids),
            "first_suspicious_txn_id": self.first_suspicious_txn_id,
            "connected_card_ids": list(self.connected_card_ids),
            "connected_device_profiles": list(self.connected_device_profiles),
            "exposure_usd": self.exposure_usd,
            "evidence": [e.to_dict() for e in self.evidence],
            "similar_prior_cases": list(self.similar_prior_cases),
            "summary": self.summary,
            "written_to_graph": self.written_to_graph,
            "graph_case_id": self.graph_case_id,
        }


@dataclass
class EvidenceRequest:
    type: EvidenceRequestType
    asked_after_step: int
    assumed_response: str

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "asked_after_step": self.asked_after_step,
            "assumed_response": self.assumed_response,
        }


@dataclass
class NextAction:
    action: str
    route: ActionRoute
    reason: str

    def to_dict(self) -> dict:
        return {"action": self.action, "route": self.route, "reason": self.reason}


@dataclass
class NextBestActions:
    initial: list[NextAction]
    final: list[NextAction]
    what_changed: str

    def to_dict(self) -> dict:
        return {
            "initial": [a.to_dict() for a in self.initial],
            "final": [a.to_dict() for a in self.final],
            "what_changed": self.what_changed,
        }


@dataclass
class Sar:
    file: bool
    reason: str
    narrative: str
    subjects: list[str]
    total_amount_usd: float
    activity_dates: list[str]

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "reason": self.reason,
            "narrative": self.narrative,
            "subjects": list(self.subjects),
            "total_amount_usd": self.total_amount_usd,
            "activity_dates": list(self.activity_dates),
        }


@dataclass
class AnswerFile:
    case_id: str
    case: Case
    evidence_requests: list[EvidenceRequest]
    next_best_actions: NextBestActions
    sar: Sar
    stop_reason: str
    tool_calls: int
    tokens: int
    latency_s: float

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "case": self.case.to_dict(),
            "evidence_requests": [r.to_dict() for r in self.evidence_requests],
            "next_best_actions": self.next_best_actions.to_dict(),
            "sar": self.sar.to_dict(),
            "stop_reason": self.stop_reason,
            "tool_calls": self.tool_calls,
            "tokens": self.tokens,
            "latency_s": self.latency_s,
        }

    def to_json(self, indent: int = 2) -> str:
        """Emits exactly the README's field names and ordering (dict insertion order
        in to_dict() matches the README's "Top level" table top-to-bottom)."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def demo() -> None:
    """ponytail: smallest runnable self-check — round-trips the README's own worked example
    shape and confirms field ordering survives to_json()."""
    case = Case(
        status="closed_fraud",
        verdict="fraud",
        fraud_probability=0.86,
        pattern="card_testing",
        pattern_description="",
        affected_txn_ids=["T0412877"],
        first_suspicious_txn_id="T0412877",
        connected_card_ids=["C00877-K1"],
        connected_device_profiles=["dev1"],
        exposure_usd=268.43,
        evidence=[Evidence(claim="x", source="graph", ref="query:card_window", entity_ids=["T0412877"])],
        similar_prior_cases=["CC-0141"],
        summary="summary",
        written_to_graph=True,
        graph_case_id="CASE-2016-1187",
    )
    nba = NextBestActions(
        initial=[NextAction(action="VERIFY_WITH_CUSTOMER", route="auto", reason="R1")],
        final=[NextAction(action="BLOCK_CARD", route="L1", reason="R2")],
        what_changed="Customer denial raised probability.",
    )
    sar = Sar(file=True, reason="R2", narrative="narrative", subjects=["C00377"], total_amount_usd=268.43,
              activity_dates=["2016-11-14", "2016-11-14"])
    ans = AnswerFile(
        case_id="HHG-017",
        case=case,
        evidence_requests=[EvidenceRequest(type="customer_validation", asked_after_step=4,
                                            assumed_response="denied")],
        next_best_actions=nba,
        sar=sar,
        stop_reason="settled",
        tool_calls=9,
        tokens=12480,
        latency_s=18.7,
    )
    d = ans.to_dict()
    top_level_order = list(d.keys())
    assert top_level_order == [
        "case_id", "case", "evidence_requests", "next_best_actions", "sar",
        "stop_reason", "tool_calls", "tokens", "latency_s",
    ]
    parsed = json.loads(ans.to_json())
    assert parsed["case"]["pattern"] == "card_testing"
    assert parsed["sar"]["file"] is True
    print("schema.py self-check OK")


if __name__ == "__main__":
    demo()
