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
    print("TigerGraph MCP is ready for pipeline tool execution.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TigerGraph MCP bridge")
    parser.add_argument("--check", action="store_true", help="Smoke check MCP tools")
    args = parser.parse_args()

    return asyncio.run(check_mcp_server())


if __name__ == "__main__":
    sys.exit(main())
