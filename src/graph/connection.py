"""pyTigerGraph connection helper for the HHgoa4 fraud-investigation agent.

Reads TG_HOST / TG_GRAPHNAME / TG_USERNAME / TG_PASSWORD / TG_API_TOKEN from the
environment via python-dotenv. Wraps installed-query calls with a token-refresh-on-401
retry (RESEARCH.md §2.6: "Token expiry ~1h by default -> silent 401s mid-session. Wrap
calls in a retry that re-calls getToken(secret)."), and counts tool calls per case_id so
the answer file's top-level `tool_calls` field (README Answer Format) can be filled with
real numbers instead of a guess.

UNCERTAIN: not run against a live TigerGraph instance. The retry-on-401 approach follows
RESEARCH.md's documented gotcha; pyTigerGraph's exact exception type for an expired token
(TigerGraphException with a 401-shaped message, historically) is asserted defensively
below rather than assumed to be a clean HTTPError.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()

_conn: tg.TigerGraphConnection | None = None
_conn_lock = threading.Lock()

# Per-case tool-call counters. Call counter_reset(case_id) at the start of each
# investigation and counter_get(case_id) when assembling the answer file's tool_calls field.
_call_counts: dict[str, int] = {}
_call_counts_lock = threading.Lock()


def counter_reset(case_id: str) -> None:
    with _call_counts_lock:
        _call_counts[case_id] = 0


def counter_get(case_id: str) -> int:
    with _call_counts_lock:
        return _call_counts.get(case_id, 0)


def _counter_increment(case_id: str | None) -> None:
    if case_id is None:
        return
    with _call_counts_lock:
        _call_counts[case_id] = _call_counts.get(case_id, 0) + 1


def get_conn(force_new: bool = False) -> tg.TigerGraphConnection:
    """Return a cached, authenticated TigerGraph Cloud (Savanna) connection.

    Reads TigerGraph Cloud configuration strictly from environment (.env):
      - TG_HOST: Cloud solution endpoint (e.g. https://your-workspace.i.tgcloud.io)
      - TG_GRAPH: Target graph name in Savanna (or TG_GRAPHNAME)
      - TG_USERNAME: User name (default: tigergraph)
      - TG_PASSWORD: Password for the cloud instance
      - TG_SECRET: GSQL Secret generated for the graph on Savanna
      - TG_API_TOKEN: Long-lived API token (if provided directly)
      - TG_TGCLOUD: True
    """
    global _conn
    with _conn_lock:
        if _conn is not None and not force_new:
            return _conn

        host = (os.environ.get("TG_HOST") or os.environ.get("TIGERGRAPH_HOST", "")).rstrip("/")
        if not host:
            raise KeyError("TG_HOST must be set in .env (e.g. https://<workspace>.i.tgcloud.io)")

        graphname = os.environ.get("TG_GRAPH") or os.environ.get("TG_GRAPHNAME")
        if not graphname:
            raise KeyError("TG_GRAPH must be set in .env (e.g. FraudInvestigation)")

        username = os.environ.get("TG_USERNAME", "tigergraph")
        password = os.environ.get("TG_PASSWORD", "tigergraph")
        secret = os.environ.get("TG_SECRET")
        api_token = os.environ.get("TG_API_TOKEN")

        conn = tg.TigerGraphConnection(
            host=host,
            graphname=graphname,
            username=username,
            password=password,
            tgCloud=True,
        )

        if api_token:
            conn.apiToken = api_token
        elif secret:
            token = conn.getToken(secret)
            conn.apiToken = token[0] if isinstance(token, tuple) else token
        else:
            raise ValueError(
                "TigerGraph Cloud requires either TG_SECRET (to generate a session token) "
                "or TG_API_TOKEN set in .env."
            )

        _conn = conn
        return _conn


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "401" in msg or "authoriz" in msg or "token" in msg and "expir" in msg


def run_query(name: str, case_id: str | None = None, **params: Any) -> Any:
    """Run an installed GSQL query by name, parsed as JSON, with a one-shot
    token-refresh retry on 401/expired-token errors (RESEARCH.md §2.6).

    Increments the per-case tool-call counter for `case_id` if given, so instrumentation
    reflects real graph calls rather than a fabricated constant (RESEARCH.md §10.1 flags
    "tool_calls identical across all 20 files looks fabricated" as a submission red flag).
    """
    conn = get_conn()
    try:
        result = conn.runInstalledQuery(name, params=params, timeout=32000)
    except Exception as exc:  # pyTigerGraph raises TigerGraphException / requests errors
        if not _is_auth_error(exc):
            raise
        conn = get_conn(force_new=True)
        result = conn.runInstalledQuery(name, params=params, timeout=32000)

    _counter_increment(case_id)
    return result
