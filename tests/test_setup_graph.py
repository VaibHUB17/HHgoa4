"""The GSQL splitter has to survive real multi-line DDL.

Splitting on line prefixes alone tears a CREATE VERTEX apart at its parentheses and
merges the six queries into two, which would send the engine malformed fragments and
produce errors that look nothing like the real problem. These tests pin the bracket
tracking that prevents that.
"""
from pathlib import Path

from scripts.setup_graph import EXPECTED_QUERIES, EXPECTED_VERTICES, split_statements

ROOT = Path(__file__).resolve().parents[1]


def test_multiline_vertex_stays_one_statement():
    gsql = """
CREATE VERTEX Customer (
    PRIMARY_ID customer_id STRING,
    name STRING
)
CREATE VERTEX Card (
    PRIMARY_ID card_id STRING
)
"""
    out = split_statements(gsql)
    assert len(out) == 2
    assert out[0].startswith("CREATE VERTEX Customer")
    assert "PRIMARY_ID customer_id" in out[0]
    assert out[1].startswith("CREATE VERTEX Card")


def test_query_body_with_braces_stays_one_statement():
    gsql = """
CREATE QUERY a(INT x) SYNTAX v2 {
  SumAccum<INT> @@n;
  PRINT @@n;
}
CREATE QUERY b(INT y) SYNTAX v2 {
  PRINT y;
}
"""
    out = split_statements(gsql)
    assert len(out) == 2, f"brace-bounded query bodies were split: {out}"
    assert out[0].count("{") == out[0].count("}")


def test_comments_and_blank_lines_dropped():
    out = split_statements("# a comment\n\n// another\nCREATE VERTEX V (PRIMARY_ID i STRING)\n")
    assert len(out) == 1
    assert out[0].startswith("CREATE VERTEX V")


def test_real_schema_file_yields_every_expected_vertex():
    stmts = split_statements((ROOT / "src" / "graph" / "schema.gsql").read_text(encoding="utf-8"))
    created = {
        s.split("CREATE VERTEX", 1)[1].split("(", 1)[0].strip()
        for s in stmts if s.upper().startswith("CREATE VERTEX")
    }
    assert EXPECTED_VERTICES <= created, f"missing: {sorted(EXPECTED_VERTICES - created)}"


def test_real_queries_file_yields_exactly_the_expected_queries():
    stmts = split_statements((ROOT / "src" / "graph" / "queries.gsql").read_text(encoding="utf-8"))
    names = set()
    for s in stmts:
        head = s.split("(", 1)[0]
        for marker in ("CREATE OR REPLACE QUERY", "CREATE QUERY"):
            if head.upper().startswith(marker):
                names.add(head[len(marker):].strip())
                break
    assert names == EXPECTED_QUERIES, f"got {sorted(names)}"
