"""
Shared SentenceTransformer model helpers for PostgreSQL stores.

Provides module-level caches so that PostgresSchemaStore,
PostgresAtomicMetricStore, and PostgresAgentMemory can share a single
loaded model instance rather than loading duplicate copies:

* ``EmbeddingHelper`` — bi-encoder for generating pgvector embeddings.
* ``CrossEncoderReranker`` — second-stage re-ranker for search results.

Usage::

    from easyq2sql.integrations.postgres.embedding import (
        EmbeddingHelper,
        CrossEncoderReranker,
    )

    helper = EmbeddingHelper(model_name="sentence-transformers/all-MiniLM-L6-v2")
    embedding = helper.encode("some text")

    reranker = CrossEncoderReranker("BAAI/bge-reranker-base")
    top_indices = reranker.rerank("query", documents, top_n=5)
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Module-level SentenceTransformer cache
# ---------------------------------------------------------------------------

_EMBEDDING_CACHE: Dict[str, "SentenceTransformer"] = {}
_EMBEDDING_CACHE_LOCK = threading.Lock()


def _get_device() -> str:
    """Detect the best available device for model inference.

    Returns ``"cuda"`` if an NVIDIA GPU is available, ``"mps"`` for
    Apple Silicon, or ``"cpu"`` as the fallback.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _get_or_create_model(
    model_name: str,
    device: Optional[str] = None,
):
    """Return a cached SentenceTransformer, creating it if not already loaded.

    Thread-safe: concurrent callers for the same key serialize on a lock
    so the model is only loaded once.
    """
    if device is None:
        device = _get_device()

    cache_key = f"{model_name}__{device}"

    # Fast path: already cached
    if cache_key in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[cache_key]

    with _EMBEDDING_CACHE_LOCK:
        # Double-check under lock
        if cache_key in _EMBEDDING_CACHE:
            return _EMBEDDING_CACHE[cache_key]

        from sentence_transformers import SentenceTransformer

        from .config import MODEL_CACHE_DIR

        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        model_kwargs = {"cache_dir": MODEL_CACHE_DIR}
        try:
            model = SentenceTransformer(model_name, device=device, model_kwargs=model_kwargs, local_files_only=True)
        except Exception:
            model = SentenceTransformer(model_name, device=device, model_kwargs=model_kwargs)
        _EMBEDDING_CACHE[cache_key] = model
        return model


# ---------------------------------------------------------------------------
# EmbeddingHelper
# ---------------------------------------------------------------------------


class EmbeddingHelper:
    """Lazy-loading SentenceTransformer wrapper for generating pgvector embeddings.

    Model instances are cached globally by ``(model_name, device)`` so
    that multiple stores can share a single loaded model.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier.
        Default: ``"sentence-transformers/all-MiniLM-L6-v2"``.
    device:
        Device for inference. Accepts ``"cuda"``, ``"mps"``, ``"cpu"``,
        or ``None`` (auto-detect: CUDA > MPS > CPU).
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: Optional[str] = None,
    ):
        self._model_name = model_name
        self._device = device
        self._dim = None  # lazily detected

    def _get_model(self):
        """Return the cached model, loading it on first access."""
        return _get_or_create_model(self._model_name, self._device)

    def encode(self, text: str) -> list:
        """Return embedding as a Python list. Caller uses ``%s::vector`` in SQL."""
        model = self._get_model()
        return model.encode(text, normalize_embeddings=True).tolist()

    @property
    def embedding_dim(self) -> int:
        """Detect the embedding dimension from the model (e.g. 384 / 768).

        Encodes a short dummy text on first access and caches the result.
        """
        if self._dim is None:
            self._dim = len(self.encode("dim check"))
        return self._dim


# ---------------------------------------------------------------------------
# Module-level Cross-Encoder cache
# ---------------------------------------------------------------------------

_CE_CACHE: Dict[str, "CrossEncoder"] = {}
_CE_CACHE_LOCK = threading.Lock()


def _get_or_create_cross_encoder(
    model_name: str,
    device: Optional[str] = None,
):
    """Return a cached CrossEncoder, creating it if not already loaded.

    Thread-safe: concurrent callers for the same key serialize on a lock
    so the model is only loaded once.
    """
    if device is None:
        device = _get_device()

    cache_key = f"{model_name}__{device}"

    # Fast path: already cached (no lock needed for dict reads in Python)
    if cache_key in _CE_CACHE:
        return _CE_CACHE[cache_key]

    with _CE_CACHE_LOCK:
        # Double-check under lock
        if cache_key in _CE_CACHE:
            return _CE_CACHE[cache_key]

        from sentence_transformers import CrossEncoder

        from .config import MODEL_CACHE_DIR

        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        model_kwargs = {"cache_dir": MODEL_CACHE_DIR}
        try:
            model = CrossEncoder(model_name, device=device, model_kwargs=model_kwargs, local_files_only=True)
        except Exception:
            model = CrossEncoder(model_name, device=device, model_kwargs=model_kwargs)
        _CE_CACHE[cache_key] = model
        return model


# ---------------------------------------------------------------------------
# CrossEncoderReranker
# ---------------------------------------------------------------------------


class CrossEncoderReranker:
    """Lazy-loading Cross-Encoder for re-ranking search results.

    Model instances are cached globally by ``(model_name, device)`` so
    that multiple stores (schema, metric, memory) can share a single
    loaded model.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier.  Defaults to
        ``"cross-encoder/ms-marco-MiniLM-L-6-v2"`` (~80 MB), which
        offers a good speed / accuracy trade-off for re-ranking.
    device:
        Device for inference.  Accepts ``"cuda"``, ``"mps"``, ``"cpu"``,
        or ``None`` (auto-detect: CUDA > MPS > CPU).
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: Optional[str] = None,
    ):
        self._model_name = model_name
        self._device = device
        # Pre-warm the Cross-Encoder in the background so the first
        # rerank() call doesn't hang while downloading the model (~80 MB).
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._executor.submit(self._get_model)

    def _get_model(self):
        """Lazy-load the CrossEncoder (uses module-level cache)."""
        return _get_or_create_cross_encoder(self._model_name, self._device)

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: int,
    ) -> List[int]:
        """Re-rank *documents* against *query* and return top-N indices.

        Parameters
        ----------
        query:
            The user's search query.
        documents:
            Candidate document texts (from RRF first stage).
        top_n:
            Number of top results to return.

        Returns
        -------
        List[int]
            Indices into *documents*, ordered by Cross-Encoder score
            descending, truncated to *top_n*.
        """
        if not documents:
            return []

        model = self._get_model()
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)

        # Sort by score descending, keep top_n
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in ranked[:top_n]]

    def rerank_with_scores(
        self,
        query: str,
        documents: List[str],
        top_n: int,
    ) -> List[tuple[int, float]]:
        """Like :meth:`rerank` but also returns the Cross-Encoder scores.

        Returns a list of ``(original_index, ce_score)`` tuples.
        """
        if not documents:
            return []

        model = self._get_model()
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(idx, float(score)) for idx, score in ranked[:top_n]]
