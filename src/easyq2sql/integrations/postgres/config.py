"""
PostgreSQL store default configuration.

Shared defaults for PostgresAgentMemory, PostgresSchemaStore, and
PostgresMetricStore.  All values can be overridden via constructor
parameters — these are just the out-of-the-box defaults.
"""


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
CE_CANDIDATE_MULTIPLIER: int = 4

# ---------------------------------------------------------------------------
# Table name defaults
# ---------------------------------------------------------------------------

DEFAULT_AGENT_MEMORY_TABLE: str = "agent_memory"
DEFAULT_SCHEMA_STORE_TABLE: str = "schema_store"
DEFAULT_METRIC_STORE_TABLE: str = "metric_store"
