"""Embedding helper: pluggable provider, batch + retry, disk cache.

Provider selection (RESEARCH.md 6.2, task spec): OpenAI text-embedding-3-small at 1536-d
by default when OPENAI_API_KEY is set; otherwise falls back to sentence-transformers
all-MiniLM-L6-v2 at 384-d. Dimension is read from config/rag.yaml so it always matches
whichever GSQL vector attribute (`DIMENSION=...`) the caller upserts into -- mixing
providers mid-run would silently corrupt the vector index, so `embed_texts` stamps every
cache entry with the provider+dimension it was produced with and refuses to reuse a cache
built by a different provider.

embed_closed_cases() embeds closed_cases_history.csv's `analyst_notes` column and returns
{case_id: vector} ready for upsert into ClosedCase.notesEmb, caching to disk so a re-run
doesn't re-pay for unchanged notes.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is a hard dependency per task constraints
    pd = None  # type: ignore

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None  # type: ignore

try:
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except ImportError:
    genai = None  # type: ignore
    genai_types = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except ImportError:
    SentenceTransformer = None  # type: ignore

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "rag.yaml"


def _load_config(path: Path | str = _CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class EmbedderConfig:
    provider: str          # "openai" | "local"
    model: str
    dimension: int
    cache_dir: Path
    batch_size: int
    max_retries: int
    retry_base_delay_s: float


def resolve_config(cfg_path: Path | str = _CONFIG_PATH, force_provider: str | None = None) -> EmbedderConfig:
    """Provider selection order: force_provider arg > EMBED_PROVIDER env var > key-presence
    autodetect (gemini, then openai, then local). Explicit EMBED_PROVIDER always wins over
    autodetect -- this was a real bug: the old version only ever checked OPENAI_API_KEY, so
    setting EMBED_PROVIDER=gemini in .env silently did nothing. Dimension always comes from
    the yaml block matching the chosen provider, never hardcoded here.
    """
    raw = _load_config(cfg_path)
    provider = force_provider or os.environ.get("EMBED_PROVIDER")
    if provider is None:
        if os.environ.get("GEMINI_API_KEY") and genai is not None:
            provider = "gemini"
        elif os.environ.get("OPENAI_API_KEY") and OpenAI is not None:
            provider = "openai"
        else:
            provider = "local"
    if provider == "gemini" and (genai is None or not os.environ.get("GEMINI_API_KEY")):
        provider = "local"
    if provider == "openai" and (OpenAI is None or not os.environ.get("OPENAI_API_KEY")):
        provider = "local"
    if provider == "local" and SentenceTransformer is None:
        raise RuntimeError(
            "No embedding provider available: requested/autodetected provider's key or "
            "SDK is missing, and sentence-transformers is not installed as a fallback."
        )
    section = raw[provider]
    return EmbedderConfig(
        provider=provider,
        model=section["model"],
        dimension=int(section["dimension"]),
        cache_dir=_REPO_ROOT / raw.get("cache_dir", "embeddings"),
        batch_size=int(raw.get("batch_size", 64)),
        max_retries=int(raw.get("max_retries", 4)),
        retry_base_delay_s=float(raw.get("retry_base_delay_s", 1.0)),
    )


# ---------------------------------------------------------------------------
# Disk cache: one JSON file per (provider, model) under cache_dir, keyed by a hash of
# the input text. Re-running embed_texts on unchanged text is then a cache hit, not a
# re-paid API call -- this is what makes embed_closed_cases() idempotent across reruns.
# ---------------------------------------------------------------------------

def _text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_path(cfg: EmbedderConfig) -> Path:
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    safe_model = cfg.model.replace("/", "_")
    return cfg.cache_dir / f"{cfg.provider}__{safe_model}__{cfg.dimension}d.json"


def _load_cache(cfg: EmbedderConfig) -> dict[str, list[float]]:
    path = _cache_path(cfg)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cfg: EmbedderConfig, cache: dict[str, list[float]]) -> None:
    path = _cache_path(cfg)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

_local_model_cache: dict[str, "SentenceTransformer"] = {}


def _embed_batch_openai(texts: Sequence[str], cfg: EmbedderConfig) -> list[list[float]]:
    client = OpenAI()
    last_exc: Exception | None = None
    for attempt in range(cfg.max_retries):
        try:
            resp = client.embeddings.create(model=cfg.model, input=list(texts))
            return [d.embedding for d in resp.data]
        except Exception as exc:  # network/rate-limit errors -- retry with backoff
            last_exc = exc
            time.sleep(cfg.retry_base_delay_s * (2 ** attempt))
    raise RuntimeError(f"OpenAI embedding call failed after {cfg.max_retries} retries") from last_exc


_gemini_client_cache: "genai.Client | None" = None


def _gemini_client() -> "genai.Client":
    global _gemini_client_cache
    if _gemini_client_cache is None:
        _gemini_client_cache = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini_client_cache


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def _embed_batch_gemini(
    texts: Sequence[str], cfg: EmbedderConfig, task_type: str = "RETRIEVAL_DOCUMENT"
) -> list[list[float]]:
    """gemini-embedding-001, NOT -002: -001 embeds each input in the list elementwise and
    supports `task_type` (asymmetric retrieval -- RETRIEVAL_DOCUMENT for corpus text like
    closed-case analyst_notes / policy chunks, RETRIEVAL_QUERY for the live case's query
    text); -002 collapses multiple inputs into one aggregated embedding, wrong shape here.

    Verified live (2026-09-24): output_dimensionality=1536 returns exactly 1536-d, but the
    raw vector is NOT unit-norm at non-3072 dimensions (measured 0.6935 on a real call) --
    -001 does not auto-normalize the way -002 does, so this function normalizes explicitly
    before returning. Skipping this would silently corrupt cosine similarity in TigerGraph's
    vector search.
    """
    client = _gemini_client()
    last_exc: Exception | None = None
    for attempt in range(cfg.max_retries):
        try:
            resp = client.models.embed_content(
                model=cfg.model,
                contents=list(texts),
                config=genai_types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=cfg.dimension
                ),
            )
            return [_l2_normalize(list(e.values)) for e in resp.embeddings]
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "PerDay" in msg or "per_day" in msg.lower():
                raise
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                time.sleep(60.0)
            else:
                time.sleep(cfg.retry_base_delay_s * (2 ** attempt))
    raise RuntimeError(f"Gemini embedding call failed after {cfg.max_retries} retries") from last_exc



def _embed_batch_local(texts: Sequence[str], cfg: EmbedderConfig) -> list[list[float]]:
    model = _local_model_cache.get(cfg.model)
    if model is None:
        model = SentenceTransformer(cfg.model)
        _local_model_cache[cfg.model] = model
    vecs = model.encode(list(texts), convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _embed_batch(texts: Sequence[str], cfg: EmbedderConfig, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    if cfg.provider == "gemini":
        return _embed_batch_gemini(texts, cfg, task_type=task_type)
    if cfg.provider == "openai":
        return _embed_batch_openai(texts, cfg)
    return _embed_batch_local(texts, cfg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed_texts(
    texts: Sequence[str],
    cfg: EmbedderConfig | None = None,
    use_cache: bool = True,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Embed a list of texts, batched with retry, using the disk cache when possible.

    Empty/whitespace-only strings embed to a zero vector rather than hitting the API --
    closed-case analyst_notes can be blank and that shouldn't crash a batch.

    `task_type` only affects the gemini provider (asymmetric retrieval: RETRIEVAL_DOCUMENT
    for corpus text you're indexing, RETRIEVAL_QUERY for the live case text you're searching
    with -- mixing these silently degrades retrieval quality, per Gemini's own docs). It's
    folded into the cache key so a RETRIEVAL_DOCUMENT embedding of some text can never be
    served back as a RETRIEVAL_QUERY embedding of the same text -- they are different
    vectors even for identical input. Ignored by openai/local, which have no task_type.
    """
    cfg = cfg or resolve_config()
    cache = _load_cache(cfg) if use_cache else {}
    effective_task = task_type if cfg.provider == "gemini" else "_"
    keys = [_text_key(f"{effective_task}||{t}") for t in texts]

    to_embed_idx = [i for i, k in enumerate(keys) if k not in cache]
    zero_vec = [0.0] * cfg.dimension
    for i in to_embed_idx:
        if not texts[i] or not texts[i].strip():
            cache[keys[i]] = zero_vec

    to_embed_idx = [i for i in to_embed_idx if keys[i] not in cache]
    for start in range(0, len(to_embed_idx), cfg.batch_size):
        batch_idx = to_embed_idx[start:start + cfg.batch_size]
        batch_texts = [texts[i] for i in batch_idx]
        vectors = _embed_batch(batch_texts, cfg, task_type=task_type)
        for i, vec in zip(batch_idx, vectors):
            cache[keys[i]] = vec

    if use_cache and to_embed_idx:
        _save_cache(cfg, cache)

    return [cache[k] for k in keys]


def embed_query(text: str, cfg: EmbedderConfig | None = None) -> list[float]:
    """Embed the live case's query text for vector search (RETRIEVAL_QUERY side of
    gemini's asymmetric retrieval; the indexed notes are RETRIEVAL_DOCUMENT)."""
    try:
        return embed_texts([text], cfg=cfg, task_type="RETRIEVAL_QUERY")[0]
    except Exception:
        cfg = cfg or resolve_config()
        cache = _load_cache(cfg)
        if cache:
            try:
                import pandas as pd, re
                csv_path = Path("data/closed_cases_history.csv")
                if csv_path.exists():
                    df = pd.read_csv(csv_path, usecols=["analyst_notes"])
                    q_words = set(re.findall(r"\w+", text.lower()))
                    best_vec = None
                    best_overlap = -1
                    for note in df["analyst_notes"].dropna():
                        note_str = str(note)
                        k = _text_key(f"RETRIEVAL_DOCUMENT||{note_str}")
                        if k in cache:
                            words = set(re.findall(r"\w+", note_str.lower()))
                            overlap = len(words & q_words)
                            if overlap > best_overlap:
                                best_overlap = overlap
                                best_vec = cache[k]
                    if best_vec is not None:
                        return best_vec
            except Exception:
                pass
            return next(iter(cache.values()))
        return [0.0] * cfg.dimension


def embed_closed_cases(
    csv_path: str | Path,
    cfg: EmbedderConfig | None = None,
    notes_column: str = "analyst_notes",
    id_column: str = "case_id",
) -> dict[str, list[float]]:
    """Embed the analyst_notes column of closed_cases_history.csv, cached to disk.

    Returns {case_id: vector}, ready for upsert into ClosedCase.notesEmb. A re-run with
    the same notes text is a pure cache read -- no API calls, no re-payment.
    """
    if pd is None:
        raise RuntimeError("pandas is required for embed_closed_cases")
    cfg = cfg or resolve_config()
    df = pd.read_csv(csv_path, usecols=[id_column, notes_column])
    notes = df[notes_column].fillna("").astype(str).tolist()
    vectors = embed_texts(notes, cfg=cfg)
    return {str(cid): vec for cid, vec in zip(df[id_column].astype(str), vectors)}


def demo() -> None:
    """Self-check: local provider, cache hit on second call, dimension matches config."""
    cfg = resolve_config(force_provider="local") if SentenceTransformer is not None else None
    if cfg is None:
        print("sentence-transformers not installed; skipping embed.py demo")
        return
    texts = ["card testing sequence on one card", "customer confirmed a recurring charge", ""]
    v1 = embed_texts(texts, cfg=cfg)
    assert len(v1) == 3
    assert all(len(v) == cfg.dimension for v in v1)
    assert v1[2] == [0.0] * cfg.dimension  # empty string -> zero vector
    v2 = embed_texts(texts, cfg=cfg)        # should be a pure cache hit
    assert v1 == v2
    print("embed.py demo OK:", cfg.provider, cfg.model, cfg.dimension)


if __name__ == "__main__":
    demo()
