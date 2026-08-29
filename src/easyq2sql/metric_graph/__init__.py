"""
Metric graph extraction service.

Wraps the LightRAG-style structured extraction (engine in
``easyq2sql.metric_graph.engine``) behind the project's own
``LlmService`` interface, and adds helpers to build the LLM input text and the
Table/Field validation set from ``TableSchema`` objects.
"""

import os

from .extract import (
    LlmServiceAdapter,
    MetricGraphExtractor,
    build_extraction_text,
    build_table_field_result,
)

#: Default directory for the runtime extraction draft. The draft and the
#: already-imported list are *runtime state*, not package data, so they live
#: in a fixed runtime directory (``./easyq2sql_data`` by default, the same
#: workspace the file system tools use) rather than next to ``MetricSchema.json``.
#: Override per-deployment via the ``metric_graph_draft_path`` /
#: ``metric_graph_imported_path`` server config keys.
_RUNTIME_DIR: str = os.getenv("METRIC_GRAPH_DATA_DIR") or os.path.join(
    os.getcwd(), "easyq2sql_data"
)

#: Default on-disk path for the extraction draft (entities + relationships).
DEFAULT_DRAFT_PATH: str = os.path.join(_RUNTIME_DIR, "metric_graph_draft.json")

#: Default on-disk path for the already-imported entity-name list.
DEFAULT_IMPORTED_PATH: str = os.path.join(
    _RUNTIME_DIR, "metric_graph_draft_imported.json"
)

__all__ = [
    "LlmServiceAdapter",
    "MetricGraphExtractor",
    "build_extraction_text",
    "build_table_field_result",
    "DEFAULT_DRAFT_PATH",
    "DEFAULT_IMPORTED_PATH",
]
