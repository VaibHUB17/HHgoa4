"""Subgraph -> LLM context serialization (RESEARCH.md 6.6).

Markdown tables per entity type, a 1-2 sentence narrative header, JSON only for
irregular nested bits. Every block is headed with its `ref` (query name + params) and
followed by an `entity_ids` line -- this is enforced structurally, not by convention:
QueryResult.ref is required (non-empty) and render_block() raises if asked to render a
result with no ref. Downstream, the answer file's evidence[] needs
{claim, source, ref, entity_ids} for every claim; if the serializer ever dropped
provenance, the agent would have nothing to put in that field.

Token budget: full detail for <=15 rows, then top-N by risk + one aggregate line for the
remainder. Target 1.5k-3k tokens per case. fit_to_budget() degrades by trimming the
lowest-risk rows first across all blocks until the budget is met.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

try:
    import tiktoken  # type: ignore
except ImportError:
    tiktoken = None  # type: ignore

FULL_DETAIL_ROW_LIMIT = 15


class MissingRefError(ValueError):
    """Raised when a block is asked to render without a ref -- refused, not warned."""


@dataclass
class QueryResult:
    """One retrieval result, ready to serialize into a markdown table block.

    ref: the query name + params that produced this, e.g.
         "query:card_window(card_id=C04570-K1, hours=2)". Required, non-empty.
    rows: list of dicts, one per entity, all with (roughly) the same keys -- the table
         header comes from the union of keys across rows, in first-seen order.
    entity_ids: the IDs this result rests on. Independent of `rows` keys so a caller can
         supply IDs even when a row dict uses a different key name (e.g. "txn_id" vs "id").
    risk_key: which row field to sort/trim by when the budget forces trimming. Higher is
         kept. Rows missing this field sort last (treated as risk 0).
    title: heading text for the block, e.g. "Card window".
    """

    ref: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    title: str = ""
    risk_key: str = "risk_score"

    def __post_init__(self) -> None:
        if not self.ref or not str(self.ref).strip():
            raise MissingRefError("QueryResult.ref must be a non-empty query name+params string")


@dataclass
class NarrativeBlock:
    """A 1-2 sentence prose header. Not a table, no ref/entity_ids requirement -- it's
    scene-setting, not a citable claim."""

    text: str


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def _tiktoken_counter() -> Callable[[str], int] | None:
    if tiktoken is None:
        return None
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        return None


def _estimate_counter() -> Callable[[str], int]:
    # ponytail: 4-chars-per-token is a coarse heuristic, not calibrated to any real
    # tokenizer. Upgrade path: pip install tiktoken (already tried first, above).
    return lambda s: max(1, len(s) // 4)


_COUNT_TOKENS = _tiktoken_counter() or _estimate_counter()


def count_tokens(text: str) -> int:
    return _COUNT_TOKENS(text)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _row_sort_key(row: dict[str, Any], risk_key: str) -> float:
    val = row.get(risk_key)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _fmt_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def render_block(result: QueryResult, row_limit: int = FULL_DETAIL_ROW_LIMIT) -> str:
    """Render one QueryResult as a markdown table block: heading with ref, table (or
    top-N + aggregate line if over row_limit), entity_ids line.

    Raises MissingRefError if result.ref is falsy -- QueryResult's own __post_init__
    already guards construction, but this is re-checked here so a caller that builds a
    QueryResult via object.__new__ or mutates .ref to "" after construction still can't
    slip a provenance-free block through the one function that actually emits text.
    """
    if not result.ref or not str(result.ref).strip():
        raise MissingRefError("Cannot render a block without a ref")

    heading = f"### {result.title or 'Result'} — ref: `{result.ref}`"

    if not result.rows:
        body = "_(no rows)_"
        ids_line = f"*entity_ids: {result.entity_ids}*"
        return f"{heading}\n{body}\n{ids_line}"

    rows = result.rows
    shown = rows
    aggregate_line = ""
    if len(rows) > row_limit:
        ranked = sorted(rows, key=lambda r: _row_sort_key(r, result.risk_key), reverse=True)
        shown = ranked[:row_limit]
        remainder = ranked[row_limit:]
        agg_count = len(remainder)
        agg_vals = [_row_sort_key(r, result.risk_key) for r in remainder]
        agg_avg = sum(agg_vals) / agg_count if agg_count else 0.0
        aggregate_line = f"\n_+{agg_count} more rows omitted, avg {result.risk_key}={agg_avg:.3g}_"

    headers: list[str] = []
    for row in shown:
        for k in row.keys():
            if k not in headers:
                headers.append(k)

    lines = [heading, "| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in shown:
        lines.append("| " + " | ".join(_fmt_cell(row.get(h)) for h in headers) + " |")
    table = "\n".join(lines) + aggregate_line

    ids_line = f"*entity_ids: {result.entity_ids}*"
    return f"{table}\n{ids_line}"


def render_context(
    narrative: NarrativeBlock | str,
    results: Sequence[QueryResult],
    row_limit: int = FULL_DETAIL_ROW_LIMIT,
) -> str:
    """Full LLM context: narrative header + one block per QueryResult, in order."""
    text = narrative.text if isinstance(narrative, NarrativeBlock) else narrative
    parts = [text.strip(), ""]
    for r in results:
        parts.append(render_block(r, row_limit=row_limit))
        parts.append("")
    return "\n".join(parts).strip() + "\n"


# ---------------------------------------------------------------------------
# Token budget fitting
# ---------------------------------------------------------------------------

def fit_to_budget(
    narrative: NarrativeBlock | str,
    results: Sequence[QueryResult],
    max_tokens: int = 3000,
    row_limit: int = FULL_DETAIL_ROW_LIMIT,
) -> tuple[str, list[QueryResult]]:
    """Render context, trimming the lowest-risk rows first (across all blocks, one row
    at a time) until the rendered text fits max_tokens or every block is down to 1 row.

    Returns (rendered_text, trimmed_results) so a caller can inspect what survived.
    Never inline a full prior case here -- callers building ClosedCase QueryResults
    should already be passing one condensed finding sentence per row, not raw case text;
    this function only trims row count, it doesn't summarize cell contents.
    """
    working = [QueryResult(ref=r.ref, rows=list(r.rows), entity_ids=list(r.entity_ids),
                            title=r.title, risk_key=r.risk_key) for r in results]

    text = render_context(narrative, working, row_limit=row_limit)
    while count_tokens(text) > max_tokens:
        # find the globally lowest-risk row across all blocks that still have >1 row
        candidates: list[tuple[float, int, int]] = []  # (risk, block_idx, row_idx)
        for bi, r in enumerate(working):
            if len(r.rows) <= 1:
                continue
            for ri, row in enumerate(r.rows):
                candidates.append((_row_sort_key(row, r.risk_key), bi, ri))
        if not candidates:
            break  # can't trim further; every block is at 1 row (or empty)
        candidates.sort(key=lambda c: c[0])  # lowest risk first
        _, bi, ri = candidates[0]
        del working[bi].rows[ri]
        text = render_context(narrative, working, row_limit=row_limit)

    return text, working


def demo() -> None:
    """Self-check: missing-ref refusal, budget trimming keeps high-risk rows, entity_ids
    round-trip."""
    try:
        QueryResult(ref="", rows=[{"a": 1}])
        raise AssertionError("expected MissingRefError")
    except MissingRefError:
        pass

    rows = [{"txn_id": f"T{i}", "risk_score": i / 20} for i in range(20)]
    qr = QueryResult(ref="query:card_window(card_id=C1, hours=2)", rows=rows,
                      entity_ids=[r["txn_id"] for r in rows], title="Card window")
    text = render_block(qr)
    assert "ref: `query:card_window(card_id=C1, hours=2)`" in text
    assert "entity_ids: ['T0'" in text or "T0" in text

    text2, trimmed = fit_to_budget("Case narrative.", [qr], max_tokens=40)
    remaining_ids = [row["txn_id"] for row in trimmed[0].rows]
    assert count_tokens(text2) <= 40 or len(remaining_ids) == 1
    assert "T19" in remaining_ids  # highest risk kept
    assert "T0" not in remaining_ids  # lowest risk dropped first
    assert len(remaining_ids) < 20
    print("serialize.py demo OK")


if __name__ == "__main__":
    demo()
