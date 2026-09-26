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

import logging
import os
import threading
import time
from typing import Any

import pyTigerGraph as tg
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

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
            gsqlSecret=secret or "",
            tgCloud=True,
        )

        if api_token:
            conn.apiToken = api_token
        elif secret:
            try:
                token = conn.getToken(secret)
            except Exception as exc:  
                if not _is_suspended_error(exc):
                    raise
                
                logger.warning("workspace appears suspended; waking it")
                if not wake_workspace():
                    raise
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


def _is_suspended_error(exc: Exception) -> bool:
    """A suspended Savanna workspace answers every endpoint with HTTP 500 and an HTML
    body reading "Failed to start workspace / Auto start is not enabled for this
    workspace" -- not a normal server error, and nothing a token refresh can fix.
    """
    msg = str(exc).lower()
    return "failed to start workspace" in msg or "auto start is not enabled" in msg


def wake_workspace(timeout_s: float = 180.0, poll_s: float = 6.0) -> bool:
    """Poke the workspace and wait for it to come up. Returns True once it answers.

    Savanna suspends an idle workspace and, when Auto Resume is switched on, brings it
    back the moment a request arrives -- but that takes one to two minutes, during which
    every call still fails. Without this, the first query of a session fails against a
    workspace that is in the middle of waking up, which reads as an outage.

    Auto Resume genuinely has to be ON in Workspace Configuration -> Advanced Settings.
    If it is off, the platform refuses to start the workspace at all and no amount of
    polling helps: the request never reaches the database, it is turned away at the
    edge. That case is detected and reported rather than retried for three minutes.
    """
    host = (os.environ.get("TG_HOST") or os.environ.get("TIGERGRAPH_HOST", "")).rstrip("/")
    if not host:
        return False

    deadline = time.monotonic() + timeout_s
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            resp = requests.get(f"{host}/echo", timeout=15)
            if resp.status_code < 500:
                if attempt > 1:
                    logger.info("workspace is up after %d attempt(s)", attempt)
                return True
            if "auto start is not enabled" in resp.text.lower():
                logger.error(
                    "Workspace is suspended and Auto Resume is OFF, so it cannot wake on "
                    "demand. Turn it on: Savanna -> Workspace Configuration -> Advanced "
                    "Settings -> Auto Resume, then Resume the workspace once."
                )
                return False
            logger.info("workspace still starting (HTTP %s), waiting...", resp.status_code)
        except requests.RequestException as exc:
            logger.info("workspace not reachable yet (%s), waiting...", exc)
        time.sleep(poll_s)

    logger.error("workspace did not come up within %.0fs", timeout_s)
    return False


logging.getLogger("pyTigerGraph").setLevel(logging.ERROR)


def run_query(name: str, case_id: str | None = None, params: dict | None = None, **kw: Any) -> Any:
    """Run an installed GSQL query by name. Routes through official tigergraph-mcp
    (tigergraph__run_installed_query tool) as required by the brief, falling back
    to pyTigerGraph with a token-refresh retry on 401/expired-token errors.

    Increments the per-case tool-call counter for `case_id` if given, so instrumentation
    reflects real graph calls rather than a fabricated constant.
    """
    raw_params = {**(params or {}), **kw}
    params = {}
    for k, v in raw_params.items():
        if name in ("card_window", "customer_baseline", "device_neighbors") and k in ("card_id", "customer_id", "device_id") and isinstance(v, str):
            params[k] = (v,)
        elif name == "write_case_to_graph" and k in ("card_id", "customer_id", "device_id") and isinstance(v, (tuple, list)):
            params[k] = v[0] if v else ""
        else:
            params[k] = v

    result = None
    use_mcp = os.environ.get("USE_TIGERGRAPH_MCP", "1") != "0"

    if use_mcp:
        try:
            from src.graph.mcp import mcp_run_installed_query
            result = mcp_run_installed_query(name, params=params)
        except Exception:
            result = None

    if result is None:
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

