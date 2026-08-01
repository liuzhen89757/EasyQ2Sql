"""
Capabilities module.

This package contains abstractions for tool capabilities - reusable utilities
that tools can compose via dependency injection.
"""

from .file_system import CommandResult, FileSearchMatch, FileSystem
from .metric_store import (
    JoinClause,
    Metric,
    MetricSearchResult,
    MetricStore,
)
from .schema_store import ColumnSchema, SchemaSearchResult, SchemaStore, TableSchema
from .sql_runner import RunSqlToolArgs, SqlRunner

__all__ = [
    "FileSystem",
    "FileSearchMatch",
    "CommandResult",
    "SqlRunner",
    "RunSqlToolArgs",
    "SchemaStore",
    "TableSchema",
    "ColumnSchema",
    "SchemaSearchResult",
    "MetricStore",
    "Metric",
    "JoinClause",
    "MetricSearchResult",
]
