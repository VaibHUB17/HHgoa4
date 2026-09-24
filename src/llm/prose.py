"""LLM prose for the case summary and SAR narrative -- wording only, never decisions.

The verdict, probability, pattern, actions and routes are all computed deterministically
before this module is called; the LLM is handed those finished facts and asked to write
them up. Two guards keep it honest:

- every ID-shaped token in the output (customer / card / closed case / transaction ids)
  must already appear in the facts it was given, otherwise the text is rejected;
- any failure (no key, network error, rejected output) falls back to the deterministic
  template the caller already built, so a flaky model call can never lose a case.

Provider: Groq's OpenAI-compatible endpoint (GROQ_API_KEY / GROQ_BASE_URL / GROQ_MODEL),
default model qwen/qwen3.8-27b -- see docs/VAIBHAV.md P1 for why not gpt-oss / llama.
"""
from __future__ import annotations

import os
import re
import threading

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

_ID_RE = re.compile(r"\b(?:C\d{3,}(?:-K\d+)?|CC-\d{3,}|CASE-[\w-]+|T\d{5,}|HHG-\d{3})\b")
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)

_tokens: dict[str, int] = {}
_lock = threading.Lock()


def tokens_used(case_id: str) -> int:
    with _lock:
        return _tokens.get(case_id, 0)


def reset_tokens(case_id: str) -> None:
    with _lock:
        _tokens[case_id] = 0


def enabled() -> bool:
    return (bool(os.environ.get("GROQ_API_KEY")) and os.environ.get("LLM_PROSE", "1") != "0"
            and "PYTEST_CURRENT_TEST" not in os.environ)  # tests stay offline + deterministic


def _complete(case_id: str, system: str, user: str, max_tokens: int = 700) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"],
                    base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
                    timeout=60)
    resp = client.chat.completions.create(
        model=os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    if resp.usage:
        with _lock:
            _tokens[case_id] = _tokens.get(case_id, 0) + int(resp.usage.total_tokens or 0)
    text = _THINK_RE.sub("", resp.choices[0].message.content or "").strip()
    # a model that swaps ASCII hyphens for U+2011 would corrupt every id (VAIBHAV.md P1)
    return text.replace("‑", "-").replace("‐", "-")


def _ids_ok(text: str, allowed: set[str]) -> bool:
    return all(tok in allowed for tok in _ID_RE.findall(text))


_SYSTEM = (
    "You are a bank fraud investigator writing up a case that has already been decided. "
    "Use only the facts provided. Do not invent any identifier, amount, date, rule or "
    "action, and do not change the verdict, probability or recommended actions. Copy every "
    "identifier exactly as written. Plain prose, no markdown, no bullet points."
)


def write_summary(case_id: str, facts: dict, fallback: str) -> str:
    """3-5 sentence case summary for an analyst: what triggered it, what the graph
    evidence showed, what was asked and what came back, and why these actions."""
    if not enabled():
        return fallback
    lines = [f"{k}: {v}" for k, v in facts.items() if v not in (None, "", [], {})]
    prompt = (
        "Write a 3-5 sentence case summary for a fraud analyst from these facts. State the "
        "verdict and fraud probability, the key evidence, any evidence request and its "
        "result, and why the final actions were chosen, citing each action's route and rules "
        "exactly as paired in final_actions. If the "
        "verdict is uncertain, say what remains unresolved.\n\n" + "\n".join(lines)
    )
    allowed = set(_ID_RE.findall("\n".join(lines))) | {case_id}
    try:
        text = _complete(case_id, _SYSTEM, prompt)
    except Exception:  # noqa: BLE001 -- any provider failure: keep the template
        return fallback
    return text if text and _ids_ok(text, allowed) else fallback


def sar_render_fn(case_id: str):
    """A narrative.generate_sar render_fn: rewrites the deterministic FinCEN template into
    a 6-10 sentence narrative. generate_sar re-validates the IDs afterwards regardless."""
    from src.sar.narrative import _default_render

    def render(facts, subjects, dates) -> str:
        template = _default_render(facts, subjects, dates)
        if not enabled():
            return template
        prompt = (
            "Rewrite this Suspicious Activity Report narrative as 6 to 10 complete sentences "
            "covering who, what, when, where, how and why, in the style of a FinCEN SAR "
            "narrative. Keep every identifier, amount and date exactly as given and add no "
            "new ones. Do not mention internal approval routes (auto/L1/L2) or policy rule "
            "numbers; a SAR describes the activity, not the bank's internal workflow.\n\n" + template
        )
        allowed = set(subjects) | set(facts.affected_txn_ids) | set(_ID_RE.findall(template))
        try:
            text = _complete(case_id, _SYSTEM, prompt)
        except Exception:  # noqa: BLE001
            return template
        return text if text and _ids_ok(text, allowed) else template

    return render
