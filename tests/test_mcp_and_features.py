"""Tests for MCP routing, graph algorithm community detection, and document GraphRAG grounding."""
from __future__ import annotations

import pytest
from src.agent.deps import agentic_deps, offline_deps
from src.graph.algorithms import analyze_device_ring_community
from src.graph.mcp import mcp_run_installed_query
from src.rag.policy_docs import chunk_policy_rules


def test_agentic_deps_factory():
    """Verify agentic_deps returns valid NodeDeps with callable run_detectors."""
    deps = agentic_deps("data")
    assert callable(deps.run_detectors)
    assert callable(deps.write_case_to_graph)
    assert callable(deps.request_evidence)


def test_analyze_device_ring_community_offline_fallback():
    """Verify community detection handles missing graph gracefully."""
    res = analyze_device_ring_community("C13487-K1", "nonexistent_device")
    assert isinstance(res, dict)
    assert res.get("community_id") is None or isinstance(res.get("community_id"), int)


def test_policy_chunking_and_citations():
    """Verify policy rules chunking into citable units."""
    sample_policy = (
        "## Fraud Policy Rules\n\n"
        "**R1. Verification Before Block**\n"
        "Requires customer verification before card block when alert rests on single unconfirmed signal.\n\n"
        "**R6. Multi-Account Ring Mitigation**\n"
        "Mandates card block, case creation, and supervisory escalation for multi-account shared origin rings.\n"
    )
    chunks = chunk_policy_rules(sample_policy)
    assert len(chunks) == 2
    r_ids = {c.rule_id for c in chunks}
    assert "R1" in r_ids
    assert "R6" in r_ids
    for c in chunks:
        assert c.chunk_id.startswith("policy:R")
        assert len(c.text) > 10
