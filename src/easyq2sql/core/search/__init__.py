"""
Hybrid search utilities: keyword scoring, Reciprocal Rank Fusion,
Cross-Encoder re-ranking, and convenience wrappers for ChromaDB collections.

Pipeline::

    vector search ──┐
                     ├── RRF ──→ Cross-Encoder ──→ top-N
    keyword search ──┘

Provides:
- ``tokenize``: simple Unicode-aware tokenizer
- ``keyword_score``: TF-based keyword relevance (0..1)
- ``reciprocal_rank_fusion``: RRF merge of multiple ranked lists
- ``CrossEncoderReranker``: second-stage re-ranker (lazy-loading)
- ``hybrid_search_chromadb``: vector + keyword → RRF → CE for ChromaDB
- ``HybridSearchResult``: Pydantic model for a single hybrid hit
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .cross_encoder import CrossEncoderReranker  # noqa: F401


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class HybridSearchResult(BaseModel):
    """One result from a hybrid (vector + keyword) search."""

    id: str
    document: str
    metadata: Optional[Dict[str, Any]] = None
    vector_score: float  # original vector similarity (0..1)
    keyword_score: float  # keyword relevance (0..1)
    fused_score: float  # RRF fusion score


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


def tokenize(text: str) -> List[str]:
    """Lowercase tokenization on Unicode alphanumeric + underscore boundaries.

    Supports CJK characters (U+4E00–U+9FFF) so Chinese queries are
    split into individual characters for matching.
    """
    return re.findall(r"[a-zA-Z0-9_一-鿿]+", text.lower())


# ---------------------------------------------------------------------------
# Keyword scoring
# ---------------------------------------------------------------------------


def keyword_score(query: str, document: str) -> float:
    """Simple TF-based keyword relevance score.

    Score = *distinct* query terms found in the document divided by
    total distinct query terms.  Gives a 0..1 range that favours
    documents matching more unique query terms.

    For the small document counts typical of schema / metric / memory
    stores this full-scan approach is fast enough and requires no
    external dependencies or index build.
    """
    query_terms = set(tokenize(query))
    if not query_terms:
        return 0.0
    doc_terms = set(tokenize(document))
    matched = query_terms & doc_terms
    return len(matched) / len(query_terms)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    rankings: List[List[Tuple[int, float]]],
    k: int = 60,
) -> List[Tuple[int, float]]:
    """Merge multiple ranked lists with Reciprocal Rank Fusion.

    Each entry in ``rankings`` is a list of ``(doc_index, score)``
    tuples sorted by descending relevance.  ``doc_index`` is a unique
    integer identifying a document across all rankings.

    RRF score for document *d*::

        Σ 1 / (k + rank_of_d_in_ranking)

    Returns a single list of ``(doc_index, fused_score)`` sorted by
    fused score descending.
    """
    rrf_scores: Dict[int, float] = {}

    for ranking in rankings:
        for rank, (doc_index, _score) in enumerate(ranking, start=1):
            rrf_scores[doc_index] = rrf_scores.get(doc_index, 0.0) + 1.0 / (
                k + rank
            )

    fused = [(idx, score) for idx, score in rrf_scores.items()]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


# ---------------------------------------------------------------------------
# ChromaDB hybrid search orchestrator
# ---------------------------------------------------------------------------


def hybrid_search_chromadb(
    collection,
    query: str,
    n_results: int = 30,
    where: Optional[dict] = None,
    rrf_k: int = 60,
    cross_encoder: Optional["CrossEncoderReranker"] = None,
) -> List[HybridSearchResult]:
    """Run vector + keyword hybrid search on a ChromaDB collection.

    Pipeline
    --------
    1. **Vector search** – ``collection.query()`` with 2× oversampling.
    2. **Keyword search** – full ``collection.get()``, score every doc.
    3. **RRF fuse** the two ranked lists → larger candidate set.
    4. **Cross-Encoder re-rank** *(optional)* – re-score top RRF candidates.
    5. Return top *n_results*.

    This is a **blocking (sync)** function meant to be called inside a
    ``ThreadPoolExecutor``, following the existing ChromaDB store pattern.
    """
    # Candidate pool size: feed more into RRF → CE down-selects to n_results
    candidate_pool = n_results * 4 if cross_encoder else n_results

    # -- 1. Vector search --------------------------------------------------
    vec_n = min(candidate_pool * 2, 100)
    vec_results = collection.query(
        query_texts=[query],
        n_results=vec_n,
        where=where,
        include=["metadatas", "distances", "documents"],
    )

    vector_ranked: List[Tuple[int, float]] = []
    doc_index_map: Dict[int, tuple] = {}  # idx → (id, doc, metadata)
    _next_idx = 0

    if vec_results["ids"] and vec_results["ids"][0]:
        for id_, distance, meta, doc in zip(
            vec_results["ids"][0],
            vec_results["distances"][0],
            vec_results["metadatas"][0],
            vec_results["documents"][0],
        ):
            sim = max(0.0, 1.0 - float(distance))  # L2 → similarity
            idx = _next_idx
            _next_idx += 1
            doc_index_map[idx] = (id_, doc or "", meta)
            vector_ranked.append((idx, sim))

    # -- 2. Keyword search (full scan – acceptable for small collections) ---
    all_results = collection.get(
        where=where, include=["metadatas", "documents"]
    )

    kw_ranked: List[Tuple[int, float]] = []

    if all_results["ids"]:
        documents = all_results["documents"] or [""] * len(all_results["ids"])
        metadatas = all_results["metadatas"] or [{}] * len(all_results["ids"])
        for id_, doc, meta in zip(all_results["ids"], documents, metadatas):
            ks = keyword_score(query, doc or "")
            if ks > 0:
                idx = _next_idx
                _next_idx += 1
                doc_index_map[idx] = (id_, doc or "", meta)
                kw_ranked.append((idx, ks))

    kw_ranked.sort(key=lambda x: x[1], reverse=True)

    # -- 3. RRF fusion → candidate set -------------------------------------
    fused = reciprocal_rank_fusion([vector_ranked, kw_ranked], k=rrf_k)
    candidates = fused[:candidate_pool]

    # -- 4. Cross-Encoder re-rank (optional) -------------------------------
    if cross_encoder and len(candidates) > n_results:
        # Extract documents for the candidate set
        candidate_items = [
            (doc_idx, doc_index_map[doc_idx]) for doc_idx, _ in candidates
        ]
        candidate_docs = [item[1][1] for item in candidate_items]  # doc text
        ce_ranked = cross_encoder.rerank(
            query=query, documents=candidate_docs, top_n=n_results
        )
        # Reorder candidates by CE ranking
        candidates = [
            candidates[ce_idx]
            for ce_idx in ce_ranked
            if ce_idx < len(candidates)
        ][:n_results]

    # -- 5. Build result objects -------------------------------------------
    results: List[HybridSearchResult] = []
    for doc_idx, fused_score in candidates[:n_results]:
        id_, doc, meta = doc_index_map[doc_idx]
        vec_score = next((s for i, s in vector_ranked if i == doc_idx), 0.0)
        kw_score = next((s for i, s in kw_ranked if i == doc_idx), 0.0)
        results.append(
            HybridSearchResult(
                id=id_,
                document=doc,
                metadata=meta,
                vector_score=vec_score,
                keyword_score=kw_score,
                fused_score=round(fused_score, 6),
            )
        )

    return results
