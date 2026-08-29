"""
Neo4j metric graph graph-schema constants.

The entity-type and relationship vocabulary is owned by the capability layer
(``easyq2sql.capabilities.metric_graph_store``) and re-exported here, so every
backend and every consumer agrees on the same strings. Only the Neo4j-specific
labels and index settings are defined locally.

Connection credentials (URI / username / password / workspace) are read from
the ``NEO4J_*`` environment variables by the application entry point
(``MyAgent.py``), not here.
"""

from easyq2sql.capabilities.metric_graph_store import (
    ENTITY_TYPE_ATOMIC as TYPE_ATOMIC,
)
from easyq2sql.capabilities.metric_graph_store import (
    ENTITY_TYPE_COMPOSITE as TYPE_COMPOSITE,
)
from easyq2sql.capabilities.metric_graph_store import (
    ENTITY_TYPE_DERIVED as TYPE_DERIVED,
)
from easyq2sql.capabilities.metric_graph_store import (
    REL_DERIVED_FROM,  # 派生指标 -> 原子指标
    REL_USES,  # 复合指标 -> 派生指标
)

# ---------------------------------------------------------------------------
# Graph schema
# ---------------------------------------------------------------------------

#: Fixed label applied to every metric node (used by the fulltext index).
METRIC_NODE_LABEL: str = "MetricNode"

#: Per-type labels (English, for filtering; Chinese label kept as a property).
ATOMIC_LABEL: str = "AtomicMetric"
DERIVED_LABEL: str = "DerivedMetric"
COMPOSITE_LABEL: str = "CompositeMetric"

#: Fulltext index name (global within the Neo4j database).
FULLTEXT_INDEX_NAME: str = "metric_node_fulltext"

#: Fulltext analyzer — 'cjk' tokenizes Chinese text.
FULLTEXT_ANALYZER: str = "cjk"

__all__ = [
    "TYPE_ATOMIC",
    "TYPE_DERIVED",
    "TYPE_COMPOSITE",
    "REL_DERIVED_FROM",
    "REL_USES",
    "METRIC_NODE_LABEL",
    "ATOMIC_LABEL",
    "DERIVED_LABEL",
    "COMPOSITE_LABEL",
    "FULLTEXT_INDEX_NAME",
    "FULLTEXT_ANALYZER",
]
