"""Builds the LangGraph investigation state machine (RESEARCH.md §5.3).

trigger -> investigate -> gather_evidence -> assess -> (gather_more | decide)
  -> snapshot_initial -> request_evidence -> reassess -> snapshot_final
  -> policy_gate -> explain -> write_case -> emit

`gather_more` loops back to `investigate`. `decide` proceeds to snapshot_initial and onward.

Usage:
    graph = build_graph(NodeDeps(run_detectors=..., write_case_to_graph=..., request_evidence=...))
    cfg = {"configurable": {"thread_id": case_id}}
    result = graph.invoke(init_state, config=cfg)          # may pause at policy_gate
    result = graph.invoke(Command(resume={"approved": True}), config=cfg)  # resume
"""
from __future__ import annotations

from functools import partial

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agent import nodes
from src.agent.state import InvestigationState


def build_graph(deps: nodes.NodeDeps, checkpointer=None):
    """Wires nodes.py functions into a compiled LangGraph graph.

    `deps` carries the injected detector/graph-query/write callables (dependency
    injection keeps this module free of any import on the graph/detector layer, which
    another agent owns). `checkpointer` defaults to an in-memory saver, needed for
    interrupt()/Command(resume=...) to work at all.
    """
    builder = StateGraph(InvestigationState)

    for name in (
        "trigger",
        "investigate",
        "gather_evidence",
        "assess",
        "snapshot_initial",
        "request_evidence",
        "reassess",
        "snapshot_final",
        "policy_gate",
        "explain",
        "write_case",
        "emit",
    ):
        node_fn = getattr(nodes, name)
        builder.add_node(name, partial(node_fn, deps=deps))

    builder.add_edge(START, "trigger")
    builder.add_edge("trigger", "investigate")
    builder.add_edge("investigate", "gather_evidence")
    builder.add_edge("gather_evidence", "assess")
    builder.add_conditional_edges(
        "assess",
        nodes.need_more_evidence,
        {"gather_more": "investigate", "decide": "snapshot_initial"},
    )
    builder.add_edge("snapshot_initial", "request_evidence")
    builder.add_edge("request_evidence", "reassess")
    builder.add_edge("reassess", "snapshot_final")
    builder.add_edge("snapshot_final", "policy_gate")
    builder.add_edge("policy_gate", "explain")
    builder.add_edge("explain", "write_case")
    builder.add_edge("write_case", "emit")
    builder.add_edge("emit", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())
