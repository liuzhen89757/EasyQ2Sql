"""
PostgreSQL store default configuration.

Shared defaults for PostgresAgentMemory, PostgresSchemaStore, and
PostgresAtomicMetricStore.  All values can be overridden via constructor
parameters — these are just the out-of-the-box defaults.
"""

import os

# ---------------------------------------------------------------------------
# Local model cache
# ---------------------------------------------------------------------------

#: Project root (4 levels up from this file: postgres -> integrations -> easyq2sql -> src -> root)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

#: Local cache directory for HuggingFace models. Models are downloaded here
#: once and loaded from disk on subsequent runs — no internet needed.
MODEL_CACHE_DIR: str = os.path.join(_PROJECT_ROOT, ".cache", "huggingface")

# ---------------------------------------------------------------------------
# Embedding / retrieval defaults
# ---------------------------------------------------------------------------

#: Bi-encoder model for generating pgvector embeddings.
DEFAULT_EMBEDDING_MODEL: str = "BAAI/bge-base-zh-v1.5"

#: Cross-Encoder model for second-stage re-ranking after RRF fusion.
#: Set to ``None`` to skip Cross-Encoder and use RRF-only ranking.
DEFAULT_CROSS_ENCODER_MODEL: str = "BAAI/bge-reranker-base"

#: Multiplier for RRF candidate pool size when Cross-Encoder is enabled.
#: RRF fetches ``limit * CE_CANDIDATE_MULTIPLIER``, CE re-ranks to ``limit``.
CE_CANDIDATE_MULTIPLIER: int = 2

# ---------------------------------------------------------------------------
# Table name defaults
# ---------------------------------------------------------------------------

DEFAULT_AGENT_MEMORY_TABLE: str = "agent_memory"
DEFAULT_SCHEMA_STORE_TABLE: str = "schema_store"
DEFAULT_ATOMIC_METRIC_TABLE: str = "atomic_metric"
DEFAULT_DERIVED_METRIC_TABLE: str = "derived_metric"
DEFAULT_COMPOSITE_METRIC_TABLE: str = "composite_metric"
