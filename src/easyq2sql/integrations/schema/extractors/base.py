"""
Schema extractor capability interface.

Defines the contract for extracting DDL and table/column metadata
from database system catalogs.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
    from easyq2sql.capabilities.sql_runner import SqlRunner
    from easyq2sql.core.tool import ToolContext

logger = logging.getLogger(__name__)


class SchemaExtractor(ABC):
    """Abstract base class for database schema extraction.

    Implementations query database-specific system tables
    (information_schema, pg_catalog, sqlite_master, etc.) to
    produce structured TableSchema objects.
    """

    @abstractmethod
    async def extract_schemas(
        self,
        sql_runner: "SqlRunner",
        context: "ToolContext",
        database_name: str = "default",
    ) -> List["TableSchema"]:
        """Extract all table schemas from the connected database.

        Args:
            sql_runner: The SQL runner connected to the target database.
            context: Tool execution context.
            database_name: Logical name for this database.

        Returns:
            List of TableSchema objects, one per table found.
        """
        pass

    @staticmethod
    async def _fetch_examples(
        sql_runner: "SqlRunner",
        context: "ToolContext",
        qualified_table: str,
        columns: List["ColumnSchema"],
    ) -> None:
        """Fetch up to 3 sample rows and map values to ColumnSchema.examples.

        Args:
            sql_runner: The SQL runner connected to the target database.
            context: Tool execution context.
            qualified_table: Fully qualified table name for the SQL query
                (e.g. ``"public.orders"``, ``"`mydb`.`orders`"``).
            columns: List of ColumnSchema objects to populate with examples.
        """
        from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs

        try:
            sample_df = await sql_runner.run_sql(
                RunSqlToolArgs(sql=f"SELECT * FROM {qualified_table} LIMIT 3"),
                context,
            )
            if sample_df.empty:
                return
            for col in columns:
                if col.name in sample_df.columns:
                    vals = sample_df[col.name].dropna().tolist()
                    col.examples = [str(v) for v in vals] if vals else None
        except Exception:
            logger.debug(
                "Failed to fetch examples for %s", qualified_table, exc_info=True
            )
