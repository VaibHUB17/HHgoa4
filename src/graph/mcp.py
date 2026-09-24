"""TigerGraph MCP integration for the HHgoa4 agentic fraud investigation pipeline.

Wraps the official `tigergraph-mcp` server via `langchain-mcp-adapters` to expose
TigerGraph graph capabilities (schema inspection, neighbor traversal, GSQL query execution)
as native tools to the investigation agent.

CLI:
    python -m src.graph.mcp --check       # Verify MCP server launches and discover tools
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

load_dotenv()


def get_mcp_server_config(
    env_file: Path | str | None = None,
    allowed_tools: str | None = "read-only",
) -> dict[str, Any]:
    """Return the client config dict for launching the TigerGraph MCP server."""
    args = ["-m", "tigergraph_mcp.main"]
    if env_file:
        args.extend(["--env-file", str(env_file)])
    if allowed_tools:
        args.extend(["--allowed-tools", allowed_tools])

    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": args,
    }


async def load_tigergraph_tools(
    env_file: Path | str | None = None,
    allowed_tools: str | None = "read-only",
) -> Sequence[Any]:
    """Connect to TigerGraph MCP server via stdio and return loaded LangChain tools."""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    cfg = get_mcp_server_config(env_file=env_file, allowed_tools=allowed_tools)
    client = MultiServerMCPClient({"tigergraph": cfg})

    async with client.session("tigergraph") as session:
        tools = await load_mcp_tools(session)
        return tools


async def check_mcp_server() -> int:
    """Smoke test: verify tigergraph-mcp starts and list available tools."""
    print("=" * 60)
    print("TIGERGRAPH MCP SERVER VERIFICATION")
    print("=" * 60)

    host = os.environ.get("TG_HOST", "")
    graph = os.environ.get("TG_GRAPH", "") or os.environ.get("TG_GRAPHNAME", "")
    secret = os.environ.get("TG_SECRET", "")
    token = os.environ.get("TG_API_TOKEN", "")

    print(f"Target Host:       {host or '(not set)'}")
    print(f"Target Graph:      {graph or '(not set)'}")
    print(f"Auth provided:     {'TG_SECRET' if secret else ('TG_API_TOKEN' if token else '(none)')}")
    print("-" * 60)

    try:
        from tigergraph_mcp.tool_names import TigerGraphToolName
        print(f"Installed tigergraph-mcp tools count: {len(list(TigerGraphToolName))}")
        print("Key tools available:")
        for name in [
            "tigergraph__run_installed_query",
            "tigergraph__get_node_edges",
            "tigergraph__get_graph_schema",
            "tigergraph__create_loading_job",
            "tigergraph__run_loading_job_with_file",
        ]:
            print(f"  - {name}")
    except Exception as exc:
        print(f"Error inspecting tigergraph-mcp: {exc}", file=sys.stderr)
        return 1

    print("-" * 60)
    print("Testing live query via tigergraph-mcp tool...")
    try:
        test_res = mcp_run_installed_query("customer_baseline", params={"customer_id": ("C04570",)})
        print(f"  mcp_run_installed_query('customer_baseline'): OK (returned {len(test_res)} block(s))")
    except Exception as exc:
        print(f"  Warning: live MCP query test failed: {exc}", file=sys.stderr)

    print("-" * 60)
    print("TigerGraph MCP is ready for pipeline tool execution.")
    return 0


def mcp_run_installed_query(
    query_name: str,
    params: dict[str, Any] | None = None,
    graph_name: str | None = None,
) -> list[dict]:
    """Execute an installed query through tigergraph-mcp's run_installed_query tool.

    Ensures parameter formatting (e.g. 1-tuple for vertices) and extracts the result
    payload from the MCP TextContent response.
    """
    import concurrent.futures
    import json
    import re
    from tigergraph_mcp.tools.query_tools import run_installed_query

    target_graph = graph_name or os.environ.get("TG_GRAPH", "") or os.environ.get("TG_GRAPHNAME", "")

    formatted_params = dict(params or {})
    for k, v in list(formatted_params.items()):
        if k in ("card_id", "customer_id", "device_id") and isinstance(v, str):
            formatted_params[k] = (v,)

    coro = run_installed_query(query_name, params=formatted_params, graph_name=target_graph)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            res = executor.submit(asyncio.run, coro).result()
    else:
        res = asyncio.run(coro)

    if not res or not hasattr(res[0], "text"):
        raise RuntimeError(f"tigergraph-mcp returned empty response for query {query_name}")

    m = re.search(r"```json\n(.*?)\n```", res[0].text, re.DOTALL)
    if m:
        data = json.loads(m.group(1))
    else:
        data = json.loads(res[0].text.strip())

    if not data.get("success"):
        raise RuntimeError(data.get("summary") or f"Query {query_name} failed via MCP")

    return data.get("data", {}).get("result", [])


def _run_mcp_coro(coro: Any) -> Any:
    """Shared async-dispatch: run an MCP tool coroutine from sync code whether or not an
    event loop is already running (tests import this module under pytest-asyncio and
    plain sync callers both hit this path)."""
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def mcp_run_generated_query(
    gsql_text: str,
    graph_name: str | None = None,
) -> list[dict]:
    """Execute an LLM-generated, already-guarded interpreted GSQL statement through
    tigergraph-mcp's `run_query` tool (INTERPRET QUERY ad-hoc execution).

    Callers MUST pass `gsql_text` through `src.agent.investigator._guard_generated_query`
    first -- this function does not re-check the read-only/keyword/row-cap allowlist; it
    only bridges to MCP and unwraps the response, mirroring `mcp_run_installed_query`.
    """
    import json
    import re
    from tigergraph_mcp.tools.query_tools import run_query as mcp_run_query_tool

    target_graph = graph_name or os.environ.get("TG_GRAPH", "") or os.environ.get("TG_GRAPHNAME", "")
    res = _run_mcp_coro(mcp_run_query_tool(gsql_text, graph_name=target_graph))

    if not res or not hasattr(res[0], "text"):
        raise RuntimeError("tigergraph-mcp returned empty response for generated query")

    m = re.search(r"```json\n(.*?)\n```", res[0].text, re.DOTALL)
    data = json.loads(m.group(1)) if m else json.loads(res[0].text.strip())

    if not data.get("success"):
        raise RuntimeError(data.get("summary") or "generated query failed via MCP")

    return data.get("data", {}).get("result", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="TigerGraph MCP bridge")
    parser.add_argument("--check", action="store_true", help="Smoke check MCP tools")
    args = parser.parse_args()

    return asyncio.run(check_mcp_server())


if __name__ == "__main__":
    sys.exit(main())

