"""One-command TigerGraph setup: schema, queries, and a connection smoke test.

Run this once against a fresh Savanna workspace before loading any data. It fails loudly
and specifically rather than half-succeeding, because a partially-created schema is worse
than none: you end up debugging a query against vertices that do not exist.

    python -m scripts.setup_graph --check          # connection only, changes nothing
    python -m scripts.setup_graph                  # create schema + install queries
    python -m scripts.setup_graph --drop-first     # wipe and recreate (destructive)

The GSQL in src/graph/ has never been run against a live instance, so expect the first
run to surface syntax issues. Nested subqueries inside POST-ACCUM/FOREACH are the usual
suspect and vary between GSQL versions. This script prints the exact failing statement so
you can fix it in place rather than guessing.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "graph" / "schema.gsql"
QUERIES = ROOT / "src" / "graph" / "queries.gsql"

EXPECTED_VERTICES = {
    "Customer", "Card", "Transaction", "DeviceProfile", "EmailDomain",
    "BillingRegion", "ProductCategory", "ClosedCase", "InvestigationCase", "PolicyChunk",
}
EXPECTED_QUERIES = {
    "card_window", "device_neighbors", "customer_baseline",
    "prior_cases_for_entities", "similar_prior_cases", "write_case_to_graph",
}


def _die(msg: str, hint: str = "") -> None:
    print(f"\n  FAILED: {msg}", file=sys.stderr)
    if hint:
        print(f"  hint:   {hint}", file=sys.stderr)
    sys.exit(1)


def connect():
    """Open a connection, or explain precisely what is missing."""
    try:
        from src.graph.connection import get_conn
    except ImportError as e:
        _die(f"cannot import the connection helper ({e})",
             "pip install -r requirements.txt")
    try:
        return get_conn()
    except Exception as e:  # noqa: BLE001 - we want the real message surfaced
        _die(
            f"could not connect to TigerGraph: {e}",
            "check .env — TG_HOST must be the workspace URL "
            "(https://<workspace>.i.tgcloud.io), not savanna.tgcloud.io, and the "
            "workspace must be resumed (it takes 1-2 minutes to wake).",
        )


_STMT_START = re.compile(r"^\s*(CREATE|RUN|INSTALL|USE|DROP|BEGIN|END)\b", re.I)


def split_statements(gsql: str) -> list[str]:
    """Split a .gsql file into statements we can run one at a time.

    Run individually so a failure names the statement that broke instead of dumping the
    whole file back at you.

    A statement ends at the next top-level keyword, where "top level" means outside any
    bracket. Tracking both () and {} matters: a CREATE VERTEX spans several lines inside
    parentheses, and a CREATE QUERY body sits inside braces. Splitting purely on line
    prefixes tears both apart and sends the engine malformed fragments.
    """
    lines = [
        ln for ln in gsql.splitlines()
        if ln.strip() and not ln.strip().startswith(("#", "//"))
    ]
    blocks: list[str] = []
    buf: list[str] = []
    depth = 0
    for line in lines:
        if depth == 0 and buf and _STMT_START.match(line):
            blocks.append("\n".join(buf))
            buf = []
        buf.append(line)
        depth += line.count("(") - line.count(")") + line.count("{") - line.count("}")
    if buf:
        blocks.append("\n".join(buf))
    return [b.strip() for b in blocks if b.strip()]


_GSQL_FAIL = re.compile(
    r"(semantic check fails|syntax error|encountered \"|failed to|does not exist|"
    r"is not defined|type check error|error:|exception)", re.I)


def run_gsql(conn, stmt: str, label: str, graph: str | None = None) -> str:
    """Run one statement, optionally inside a graph. pyTigerGraph's gsql() returns the
    server's text output even when the statement was rejected, so failure is detected
    from that text rather than from an exception alone."""
    body = f"USE GRAPH {graph}\n{stmt}" if graph else stmt
    first = stmt.strip().splitlines()[0][:70]
    try:
        out = str(conn.gsql(body))
    except Exception as e:  # noqa: BLE001
        out = f"exception: {e}"
    low = out.lower()
    if "already exist" in low or "is used by another object" in low:
        print(f"    {label} skip {first}  (already exists)")
        return out
    if _GSQL_FAIL.search(out):
        print(f"    {label} FAIL {first}", file=sys.stderr)
        _die(
            f"statement was rejected:\n\n{body}\n\n{out}",
            "GSQL syntax varies by version. Nested subqueries inside "
            "POST-ACCUM/FOREACH are the most common incompatibility.",
        )
    print(f"    {label} ok   {first}")
    return out


def run_statements(conn, statements: list[str], label: str, graph: str | None = None) -> None:
    print(f"\n  {label}: {len(statements)} statement(s)")
    for i, stmt in enumerate(statements, 1):
        run_gsql(conn, stmt, f"[{i:>2}/{len(statements)}]", graph)


def run_file(conn, path: Path, label: str, graph: str) -> None:
    """Schema: global vertex/edge types first, then CREATE GRAPH over them, then the
    vector schema-change job. Queries: each created inside the graph, then installed."""
    if not path.exists():
        _die(f"{path} not found")
    statements = split_statements(path.read_text(encoding="utf-8"))
    if path == SCHEMA:
        types = [s for s in statements if "SCHEMA_CHANGE" not in s.upper()]
        vector_job = [s for s in statements if "SCHEMA_CHANGE" in s.upper()]
        run_statements(conn, types, "schema types")
        existing = str(conn.gsql("SHOW GRAPH *"))
        if f"Graph {graph}(" in existing:
            print(f"    graph {graph} already exists")
        else:
            run_gsql(conn, f"CREATE GRAPH {graph}(*)", "[graph]")
        run_statements(conn, vector_job, "vector attributes")
    else:
        run_statements(conn, statements, label, graph)
        print("\n  installing queries (a few minutes on first install)")
        run_gsql(conn, "INSTALL QUERY ALL", "[install]", graph)


def verify(conn) -> None:
    """Confirm the graph really holds what we think it does."""
    print("\n  verifying")
    try:
        schema = conn.getSchema()
    except Exception as e:  # noqa: BLE001
        _die(f"could not read the schema back: {e}")

    got_v = {v["Name"] for v in schema.get("VertexTypes", [])}
    missing_v = EXPECTED_VERTICES - got_v
    print(f"    vertices: {len(got_v)} present"
          + (f", MISSING {sorted(missing_v)}" if missing_v else ""))

    try:
        installed = set(conn.getInstalledQueries())
    except Exception:  # noqa: BLE001
        installed = set()
    got_q = {q.split("/")[-1] for q in installed}
    missing_q = EXPECTED_QUERIES - got_q
    print(f"    queries:  {len(EXPECTED_QUERIES - missing_q)}/{len(EXPECTED_QUERIES)} installed"
          + (f", MISSING {sorted(missing_q)}" if missing_q else ""))

    if missing_v or missing_q:
        _die("setup is incomplete — see the missing items above")
    print("\n  graph is ready. Next: python -m src.graph.load --data-dir ./data")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="test the connection and report state, change nothing")
    ap.add_argument("--drop-first", action="store_true",
                    help="DESTRUCTIVE: drop the existing graph before creating it")
    args = ap.parse_args()

    print("TigerGraph setup")
    conn = connect()
    print(f"  connected: {getattr(conn, 'host', '?')}  graph={getattr(conn, 'graphname', '?')}")

    if args.check:
        verify(conn)
        return 0

    if args.drop_first:
        name = getattr(conn, "graphname", "")
        reply = input(f"  DROP ALL of graph '{name}'? This deletes loaded data. Type the "
                      f"graph name to confirm: ")
        if reply.strip() != name:
            print("  aborted.")
            return 1
        try:
            conn.gsql(f"DROP GRAPH {name}")
            print(f"  dropped {name}")
        except Exception as e:  # noqa: BLE001
            print(f"  drop skipped: {e}")

    graph = getattr(conn, "graphname", "")
    run_file(conn, SCHEMA, "schema", graph)
    run_file(conn, QUERIES, "queries", graph)
    verify(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
