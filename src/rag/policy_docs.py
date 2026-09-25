"""Chunk and load the grounding documents (RESEARCH.md 6.3, task spec).

Three sources, three chunk shapes:

1. The Fraud Policy inside README.md, chunked BY RULE -- one PolicyChunk per R1-R10,
   never split a rule, so the agent's `reason` field can cite "R5" and have it be one
   whole, citable retrieval unit rather than a fragment.
2. The five known fraud patterns, one Pattern chunk per vertex (card_testing,
   card_not_present_fraud, card_not_present_new_device, out_of_region_use,
   account_takeover).
3. The priority regulatory PDFs named in RESEARCH.md 6.3 / the task: FinCEN SAR
   Narrative Guidance (README names it "the standard for your sar.narrative"), the
   FinCEN Account Takeover Advisory, and the FFIEC Red Flags appendix. FATF docs are
   skipped on purpose -- money-laundering typologies, weakly relevant to card fraud.

Emits PolicyChunk / Pattern / RegChunk records ready for upsert, with GOVERNS
(PolicyChunk -> Pattern), PRESCRIBES (PolicyChunk -> Action), and CITES
(PolicyChunk -> RegChunk) edges wired per RESEARCH.md 6.3. If a PDF won't text-extract,
degrade gracefully: log it in `load_result.failures` and move on -- never crash the
pipeline over one unreachable regulator URL.
"""

from __future__ import annotations

import html
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None  # type: ignore

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_README = _REPO_ROOT / "docs" / "DATASET_README.md"  # organizers' dataset README: policy R1-R10 + patterns

_HTTP_TIMEOUT_S = 20
_USER_AGENT = "Mozilla/5.0 (compatible; HHgoa4-fraud-agent/1.0)"

# Action identifiers from README Fraud Policy section 1 -- used to detect which actions
# a rule PRESCRIBES by scanning the rule's own text for these exact tokens.
_ACTION_IDS = [
    "ALLOW_TRANSACTION", "DECLINE_TRANSACTION", "MONITOR_CONNECTED_CARDS", "MONITOR_CARD",
    "WARN_CUSTOMER", "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH", "BLOCK_ALL_CARDS", "BLOCK_CARD",
    "GENERATE_REPORT", "CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD",
]

# Pattern id -> the policy rule numbers the README's own pattern description cites.
_PATTERN_RULE_REFS = {
    "card_testing": ["R5"],
    "card_not_present_fraud": ["R1", "R2", "R3", "R4"],
    "card_not_present_new_device": ["R1", "R2", "R3", "R4"],
    "out_of_region_use": ["R2", "R3"],
    "account_takeover": [],
}

_PATTERN_NAME_TO_ID = {
    "Card testing": "card_testing",
    "Card-not-present fraud": "card_not_present_fraud",
    "Card-not-present fraud from a new device": "card_not_present_new_device",
    "Out-of-region use": "out_of_region_use",
    "Account takeover": "account_takeover",
}


@dataclass
class PolicyChunk:
    chunk_id: str          # e.g. "policy:R5"
    rule_id: str            # "R1".."R10"
    text: str
    citation: str           # "Fraud Policy R5"
    governs_patterns: list[str] = field(default_factory=list)   # -> Pattern.pattern_id (GOVERNS)
    prescribes_actions: list[str] = field(default_factory=list)  # -> Action id (PRESCRIBES)
    cites_reg_chunks: list[str] = field(default_factory=list)    # -> RegChunk.chunk_id (CITES)


@dataclass
class PatternChunk:
    pattern_id: str          # e.g. "card_testing"
    name: str
    text: str
    rule_refs: list[str] = field(default_factory=list)


@dataclass
class RegChunk:
    chunk_id: str
    source: str              # short name, e.g. "FinCEN SAR Narrative Guidance"
    url: str
    section_idx: int
    text: str


@dataclass
class LoadResult:
    policy_chunks: list[PolicyChunk] = field(default_factory=list)
    pattern_chunks: list[PatternChunk] = field(default_factory=list)
    reg_chunks: list[RegChunk] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)   # human-readable "what went wrong"


# ---------------------------------------------------------------------------
# 1. Fraud Policy, chunked by rule
# ---------------------------------------------------------------------------

_RULE_HEADER_RE = re.compile(r"\*\*(R\d{1,2})\.\s")


def chunk_policy_rules(readme_text: str) -> list[PolicyChunk]:
    """Split the '### 3. Rules' section into one chunk per Rn, never splitting a rule.

    Rules end at the next '**Rn.' header or the next '### ' markdown heading, whichever
    comes first -- this keeps a rule whole even if the surrounding section grows.
    """
    starts = list(_RULE_HEADER_RE.finditer(readme_text))
    chunks: list[PolicyChunk] = []
    for i, m in enumerate(starts):
        rule_id = m.group(1)
        start = m.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(readme_text)
        # also stop at the next markdown heading if it comes before the next rule
        # (guards against picking up trailing "### 3a." content into R10's chunk)
        heading_m = re.search(r"\n#{1,3} ", readme_text[start:end])
        if heading_m:
            end = start + heading_m.start()
        body = readme_text[start:end].strip()

        governs = [pid for pid, refs in _PATTERN_RULE_REFS.items() if rule_id in refs]
        prescribes = [a for a in _ACTION_IDS if re.search(rf"`{a}`", body)]

        chunks.append(PolicyChunk(
            chunk_id=f"policy:{rule_id}",
            rule_id=rule_id,
            text=body,
            citation=f"Fraud Policy {rule_id}",
            governs_patterns=governs,
            prescribes_actions=prescribes,
        ))
    return chunks


# ---------------------------------------------------------------------------
# 2. The five pattern descriptions, one chunk per vertex
# ---------------------------------------------------------------------------

_PATTERN_ITEM_RE = re.compile(
    r"\*\*\d+\.\s(.+?)\.\*\*\s(.+?)(?=\n\*\*\d+\.\s|\n##\s|\Z)", re.DOTALL
)


def chunk_patterns(readme_text: str) -> list[PatternChunk]:
    """One PatternChunk per known pattern, parsed from the '## The five known fraud
    patterns' section's numbered list. Never split a pattern across chunks."""
    section_m = re.search(r"## The five known fraud patterns\n(.+?)\n## ", readme_text, re.DOTALL)
    section = section_m.group(1) if section_m else readme_text

    chunks: list[PatternChunk] = []
    for m in _PATTERN_ITEM_RE.finditer(section):
        name = m.group(1).strip()
        body = m.group(2).strip()
        pattern_id = _PATTERN_NAME_TO_ID.get(name)
        if pattern_id is None:
            continue  # unrecognized heading shape; skip rather than guess an id
        chunks.append(PatternChunk(
            pattern_id=pattern_id,
            name=name,
            text=f"{name}. {body}",
            rule_refs=_PATTERN_RULE_REFS.get(pattern_id, []),
        ))
    return chunks


# ---------------------------------------------------------------------------
# 3. Priority regulatory PDFs
# ---------------------------------------------------------------------------

PRIORITY_REG_DOCS = [
    {
        "source": "FinCEN SAR Narrative Guidance",
        "url": "https://www.fincen.gov/system/files/shared/sar_guidance_narrative.pdf",
    },
    {
        "source": "FinCEN Account Takeover Advisory",
        "url": "https://www.fincen.gov/resources/advisories/fincen-advisory-fin-2011-a016",
    },
    {
        "source": "FFIEC Red Flags Appendix",
        "url": "https://bsaaml.ffiec.gov/manual/Appendices/07",
    },
]

_PDF_LINK_RE = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")


def _strip_html(raw_html: str) -> str:
    """Stdlib-only HTML->text fallback for a regulator page that isn't itself a PDF.
    Not a real parser -- just enough to get readable prose out of a Drupal landing
    page when there's no linked PDF to follow instead."""
    no_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = _TAG_RE.sub(" ", no_scripts)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANKLINES_RE.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _extract_pdf_text(content: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf not installed")
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _fetch(url: str) -> "requests.Response":
    return requests.get(url, timeout=_HTTP_TIMEOUT_S, headers={"User-Agent": _USER_AGENT})


def _chunk_text_by_paragraph(text: str, min_chars: int = 400, max_chars: int = 1800) -> list[str]:
    """Group paragraphs into chunks of roughly min_chars..max_chars so each RegChunk is
    a citable, LLM-context-sized unit rather than one giant blob or one line per chunk."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) > max_chars:
            chunks.append(buf.strip())
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
        if len(buf) >= min_chars and len(buf) >= max_chars * 0.5:
            continue
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def fetch_and_chunk_reg_doc(source: str, url: str) -> tuple[list[RegChunk], str | None]:
    """Fetch one regulatory URL and chunk its text. Returns (chunks, failure_reason).
    failure_reason is None on success; chunks is [] when it failed. Never raises --
    this is the single degrade-gracefully chokepoint for network/extraction errors."""
    if requests is None:
        return [], f"{source}: requests not installed"
    try:
        resp = _fetch(url)
    except Exception as exc:
        return [], f"{source} ({url}): fetch failed: {exc}"

    if resp.status_code != 200:
        return [], f"{source} ({url}): HTTP {resp.status_code}"

    content_type = resp.headers.get("content-type", "")
    text = ""
    try:
        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            text = _extract_pdf_text(resp.content)
        else:
            # HTML landing page: follow a linked PDF if the page has one, else strip tags.
            pdf_links = _PDF_LINK_RE.findall(resp.text)
            if pdf_links:
                pdf_url = pdf_links[0]
                if pdf_url.startswith("/"):
                    m = re.match(r"(https?://[^/]+)", url)
                    pdf_url = (m.group(1) if m else "") + pdf_url
                try:
                    pdf_resp = _fetch(pdf_url)
                    if pdf_resp.status_code == 200:
                        text = _extract_pdf_text(pdf_resp.content)
                except Exception as exc:
                    logger.warning("%s: linked PDF fetch failed (%s), falling back to HTML text", source, exc)
            if not text.strip():
                text = _strip_html(resp.text)
    except Exception as exc:
        return [], f"{source} ({url}): text extraction failed: {exc}"

    if not text.strip():
        return [], f"{source} ({url}): no extractable text"

    pieces = _chunk_text_by_paragraph(text)
    chunks = [
        RegChunk(chunk_id=f"reg:{_slug(source)}:{i}", source=source, url=url, section_idx=i, text=piece)
        for i, piece in enumerate(pieces)
    ]
    return chunks, None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def load_reg_docs(docs: list[dict] = PRIORITY_REG_DOCS) -> tuple[list[RegChunk], list[str]]:
    """Fetch + chunk every doc in `docs`. Never raises: a failing doc is logged into the
    returned failures list and skipped so the rest of the pipeline still runs."""
    all_chunks: list[RegChunk] = []
    failures: list[str] = []
    for doc in docs:
        chunks, failure = fetch_and_chunk_reg_doc(doc["source"], doc["url"])
        if failure:
            logger.warning("policy_docs: %s", failure)
            failures.append(failure)
        all_chunks.extend(chunks)
    return all_chunks, failures


# ---------------------------------------------------------------------------
# CITES wiring: link the SAR-relevant policy chunks (R2, R6, R9 -- the ones that gate
# FILE_REPORT) to the FinCEN SAR Narrative Guidance chunks, since that's the doc the
# README names as "the standard for your sar.narrative".
# ---------------------------------------------------------------------------

_SAR_RELEVANT_RULES = {"R2", "R6", "R9"}


def wire_cites(policy_chunks: list[PolicyChunk], reg_chunks: list[RegChunk]) -> None:
    """Mutates policy_chunks in place, filling cites_reg_chunks for SAR-relevant rules."""
    narrative_chunk_ids = [
        c.chunk_id for c in reg_chunks if c.source == "FinCEN SAR Narrative Guidance"
    ]
    if not narrative_chunk_ids:
        return
    for pc in policy_chunks:
        if pc.rule_id in _SAR_RELEVANT_RULES:
            pc.cites_reg_chunks = narrative_chunk_ids[:1]  # cite the guidance's lead chunk


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_all(readme_path: Path | str = _DEFAULT_README, fetch_reg_docs: bool = True) -> LoadResult:
    """Load and chunk everything: policy rules + patterns from README.md, plus the
    priority regulatory PDFs if fetch_reg_docs is True. Set fetch_reg_docs=False for
    offline/test runs -- no network call is made in that case."""
    readme_text = Path(readme_path).read_text(encoding="utf-8")
    policy_chunks = chunk_policy_rules(readme_text)
    pattern_chunks = chunk_patterns(readme_text)

    reg_chunks: list[RegChunk] = []
    failures: list[str] = []
    if fetch_reg_docs:
        reg_chunks, failures = load_reg_docs()
        wire_cites(policy_chunks, reg_chunks)

    return LoadResult(
        policy_chunks=policy_chunks,
        pattern_chunks=pattern_chunks,
        reg_chunks=reg_chunks,
        failures=failures,
    )


def demo() -> None:
    """Self-check: policy chunked into exactly R1-R10 with no rule split, five patterns
    found, offline mode makes no network call."""
    result = load_all(fetch_reg_docs=False)
    rule_ids = [c.rule_id for c in result.policy_chunks]
    assert rule_ids == [f"R{i}" for i in range(1, 11)], rule_ids
    assert all(c.text.strip() for c in result.policy_chunks)
    assert len(result.pattern_chunks) == 5, [p.pattern_id for p in result.pattern_chunks]
    assert result.reg_chunks == [] and result.failures == []
    r5 = next(c for c in result.policy_chunks if c.rule_id == "R5")
    assert "DECLINE_TRANSACTION" in r5.prescribes_actions
    assert "card_testing" in r5.governs_patterns
    print("policy_docs.py demo OK:", rule_ids, [p.pattern_id for p in result.pattern_chunks])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
