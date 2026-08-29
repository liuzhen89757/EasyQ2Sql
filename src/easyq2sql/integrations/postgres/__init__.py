"""
PostgreSQL integration for EasyQ2Sql.

Provides PostgreSQL-based implementations of core capabilities:
- PostgresRunner: SQL execution
- PostgresSchemaStore: Schema storage with pgvector search
- PostgresAtomicMetricStore: Atomic metric storage with pgvector search
- PostgresDerivedMetricStore: Derived metric storage with pgvector search
- PostgresAgentMemory: Agent memory with pgvector search

All store implementations use PostgreSQL + pgvector to store both raw data
and vector embeddings in the same database, eliminating the dual-write
(ChromaDB + JSON files) pattern.
"""


def get_device() -> str:
    """Detect the best available device for embeddings.

    Checks for GPU availability and returns the appropriate device string
    for use with SentenceTransformer embedding models.

    Returns:
        'cuda' if NVIDIA GPU available, 'mps' if Apple Silicon, 'cpu' otherwise.
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


from .sql_runner import PostgresRunner
from .schema_store import PostgresSchemaStore
from .atomic_metric_store import PostgresAtomicMetricStore
from .derived_metric_store import PostgresDerivedMetricStore
from .composite_metric_store import PostgresCompositeMetricStore
from .agent_memory import PostgresAgentMemory
from .embedding import EmbeddingHelper, CrossEncoderReranker

__all__ = [
    "PostgresRunner",
    "PostgresSchemaStore",
    "PostgresAtomicMetricStore",
    "PostgresDerivedMetricStore",
    "PostgresCompositeMetricStore",
    "PostgresAgentMemory",
    "EmbeddingHelper",
    "CrossEncoderReranker",
    "get_device",
]
