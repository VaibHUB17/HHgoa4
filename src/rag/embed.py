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
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is a hard dependency per task constraints
    pd = None  # type: ignore

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None  # type: ignore

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
    """Pick openai (has OPENAI_API_KEY and the SDK importable) unless local is forced
    or unavailable, in which case fall back to sentence-transformers. Dimension always
    comes from the yaml block matching the chosen provider, never hardcoded here.
    """
    raw = _load_config(cfg_path)
    provider = force_provider
    if provider is None:
        has_key = bool(os.environ.get("OPENAI_API_KEY"))
        provider = "openai" if (has_key and OpenAI is not None) else "local"
    if provider == "openai" and (OpenAI is None or not os.environ.get("OPENAI_API_KEY")):
        provider = "local"
    if provider == "local" and SentenceTransformer is None:
        raise RuntimeError(
            "No embedding provider available: OPENAI_API_KEY unset/openai package missing, "
            "and sentence-transformers is not installed."
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


def _embed_batch_local(texts: Sequence[str], cfg: EmbedderConfig) -> list[list[float]]:
    model = _local_model_cache.get(cfg.model)
    if model is None:
        model = SentenceTransformer(cfg.model)
        _local_model_cache[cfg.model] = model
    vecs = model.encode(list(texts), convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _embed_batch(texts: Sequence[str], cfg: EmbedderConfig) -> list[list[float]]:
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
) -> list[list[float]]:
    """Embed a list of texts, batched with retry, using the disk cache when possible.

    Empty/whitespace-only strings embed to a zero vector rather than hitting the API --
    closed-case analyst_notes can be blank and that shouldn't crash a batch.
    """
    cfg = cfg or resolve_config()
    cache = _load_cache(cfg) if use_cache else {}
    keys = [_text_key(t) for t in texts]

    to_embed_idx = [i for i, k in enumerate(keys) if k not in cache]
    zero_vec = [0.0] * cfg.dimension
    for i in to_embed_idx:
        if not texts[i] or not texts[i].strip():
            cache[keys[i]] = zero_vec

    to_embed_idx = [i for i in to_embed_idx if keys[i] not in cache]
    for start in range(0, len(to_embed_idx), cfg.batch_size):
        batch_idx = to_embed_idx[start:start + cfg.batch_size]
        batch_texts = [texts[i] for i in batch_idx]
        vectors = _embed_batch(batch_texts, cfg)
        for i, vec in zip(batch_idx, vectors):
            cache[keys[i]] = vec

    if use_cache and to_embed_idx:
        _save_cache(cfg, cache)

    return [cache[k] for k in keys]


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
