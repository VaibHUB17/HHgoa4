"""Load policy, pattern, and regulatory chunks into TigerGraph PolicyChunk vertices.

Embeds chunks using Gemini (task_type=RETRIEVAL_DOCUMENT) and upserts them
into PolicyChunk with their textEmb vector attribute so they can be retrieved
via hybrid GraphRAG.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from src.graph.connection import get_conn
from src.rag.embed import embed_texts, resolve_config
from src.rag.policy_docs import load_all

logger = logging.getLogger(__name__)


def load_policy_docs_to_graph(fetch_reg_docs: bool = True) -> int:
    """Load and embed all policy and regulatory chunks into PolicyChunk vertex on TigerGraph."""
    res = load_all(fetch_reg_docs=fetch_reg_docs)
    cfg = resolve_config()

    texts_to_embed = []
    chunk_records = []

    for pc in res.policy_chunks:
        texts_to_embed.append(pc.text)
        chunk_records.append({
            "chunk_id": pc.chunk_id,
            "rule_id": pc.rule_id,
            "text": pc.text[:4000],
            "citation": pc.citation,
        })

    for pat in res.pattern_chunks:
        texts_to_embed.append(pat.text)
        chunk_records.append({
            "chunk_id": f"pattern:{pat.pattern_id}",
            "rule_id": pat.pattern_id,
            "text": pat.text[:4000],
            "citation": f"Fraud Pattern: {pat.name}",
        })

    for rc in res.reg_chunks:
        texts_to_embed.append(rc.text)
        chunk_records.append({
            "chunk_id": rc.chunk_id,
            "rule_id": "REG",
            "text": rc.text[:4000],
            "citation": rc.source,
        })

    logger.info(f"Embedding {len(texts_to_embed)} policy chunks with {cfg.provider}...")
    vecs = []
    for i in range(0, len(texts_to_embed), 10):
        sub = texts_to_embed[i:i + 10]
        try:
            vecs.extend(embed_texts(sub, cfg=cfg, task_type="RETRIEVAL_DOCUMENT"))
        except Exception as exc:
            logger.warning(f"Could not embed chunk batch {i} ({exc}); falling back to zero vectors")
            vecs.extend([[0.0] * cfg.dimension for _ in sub])


    conn = get_conn()
    payload = []
    for rec, vec in zip(chunk_records, vecs):
        payload.append((
            rec["chunk_id"],
            {
                "rule_id": rec["rule_id"],
                "text": rec["text"],
                "citation": rec["citation"],
                "textEmb": vec,
            }
        ))

    logger.info(f"Upserting {len(payload)} PolicyChunk vertices to TigerGraph...")
    n = conn.upsertVertices("PolicyChunk", payload)
    logger.info(f"Successfully upserted {n} PolicyChunk vertices.")
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = load_policy_docs_to_graph(fetch_reg_docs=True)
    print(f"Upserted {n} PolicyChunk vertices.")
