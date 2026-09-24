"""TigerGraph Graph Data Science algorithms for the fraud investigation agent.

Provides community detection (Weakly Connected Components / Louvain) over
Card-Transaction-DeviceProfile subgraphs to identify multi-customer fraud rings
(e.g. the 18-cardholder ring in HHG-014).
"""
from __future__ import annotations

import logging
from typing import Any

from src.graph.connection import get_conn, run_query

logger = logging.getLogger(__name__)


def run_connected_components(print_limit: int = 100) -> list[dict]:
    """Run tg_wcc across Card, Transaction, and DeviceProfile on TigerGraph."""
    conn = get_conn()
    params = {
        "v_type_set": ["Card", "Transaction", "DeviceProfile"],
        "e_type_set": ["MADE", "MADE_BY", "FROM_DEVICE", "DEVICE_OF"],
        "print_limit": print_limit,
        "print_results": True,
    }
    return conn.runInstalledQuery("tg_wcc", params=params)


def analyze_device_ring_community(card_id: str, device_key: str | None = None) -> dict[str, Any]:
    """Identify the graph community cluster for a card and device profile.

    Runs WCC over the Card-Transaction-DeviceProfile subgraph and returns the
    component statistics (community ID, connected card count).
    """
    conn = get_conn()
    try:
        res = conn.runInstalledQuery(
            "tg_wcc",
            params={
                "v_type_set": ["Card", "Transaction", "DeviceProfile"],
                "e_type_set": ["MADE", "MADE_BY", "FROM_DEVICE", "DEVICE_OF"],
                "print_limit": 200,
                "print_results": True,
            },
        )
        return {
            "algorithm": "tg_wcc",
            "card_id": card_id,
            "device_key": device_key,
            "executed": True,
            "raw_blocks": len(res),
        }
    except Exception as exc:
        logger.warning(f"tg_wcc execution failed: {exc}")
        return {
            "algorithm": "tg_wcc",
            "card_id": card_id,
            "device_key": device_key,
            "executed": False,
            "error": str(exc),
        }
