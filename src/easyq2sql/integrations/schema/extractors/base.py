"""
Schema extractor capability interface.

Defines the contract for extracting DDL and table/column metadata
from database system catalogs.
"""

from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
    from easyq2sql.capabilities.sql_runner import SqlRunner
    from easyq2sql.core.tool import ToolContext

logger = logging.getLogger(__name__)


def _is_missing(value) -> bool:
    """Return True when a value is absent (``None`` or ``NaN``)."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


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

    # ------------------------------------------------------------------
    # Value range inference
    # ------------------------------------------------------------------

    #: data_type base tokens (after normalisation) that map to a min/max range.
    _NUMERIC_TYPES = frozenset({
        "int", "integer", "bigint", "smallint", "tinyint", "mediumint",
        "int2", "int4", "int8", "serial", "bigserial", "smallserial",
        "numeric", "decimal", "number", "float", "float4", "float8",
        "double", "double precision", "real", "money",
    })

    _TEMPORAL_TYPES = frozenset({
        "date", "datetime", "timestamp", "timestamptz", "time", "timetz",
        "timestamp without time zone", "timestamp with time zone",
        "time without time zone", "time with time zone", "year",
    })

    _BOOLEAN_TYPES = frozenset({"boolean", "bool", "bit"})

    _TEXT_TYPES = frozenset({
        "text", "varchar", "char", "character", "character varying",
        "nvarchar", "nchar", "string", "uuid", "enum", "set", "citext",
        "name", "bpchar",
    })

    #: Maximum number of distinct values listed for categorical columns.
    _DISTINCT_LIMIT = 10

    @staticmethod
    def _normalize_data_type(data_type: str) -> str:
        """Strip a raw data_type down to a comparable base token.

        ``VARCHAR(20)`` → ``varchar``, ``int(11) unsigned`` → ``int``,
        ``timestamp without time zone`` → ``timestamp without time zone``.
        """
        base = (data_type or "").strip().lower()
        # Strip MySQL modifiers ("int(11) unsigned" -> "int(11)") before the
        # parenthesised size, so "(11)" is left at the end for the next pass.
        base = re.sub(r"\s+(unsigned|signed|zerofill)\s*$", "", base).strip()
        base = re.sub(r"\([^)]*\)$", "", base).strip()
        return base

    @classmethod
    def _classify_data_type(cls, data_type: str) -> str:
        """Classify a data_type into ``numeric``/``temporal``/``boolean``/``text``/``other``."""
        base = cls._normalize_data_type(data_type)
        if base in cls._NUMERIC_TYPES:
            return "numeric"
        if base in cls._TEMPORAL_TYPES:
            return "temporal"
        if base in cls._BOOLEAN_TYPES:
            return "boolean"
        if base in cls._TEXT_TYPES:
            return "text"
        return "other"

    @staticmethod
    async def _fetch_value_ranges(
        sql_runner: "SqlRunner",
        context: "ToolContext",
        qualified_table: str,
        columns: List["ColumnSchema"],
        quote_ident=None,
    ) -> None:
        """Populate ``ColumnSchema.value_range`` from the actual column data.

        Rules by column type (see :meth:`_classify_data_type`):

        - numeric / temporal: ``MIN(col) ~ MAX(col)``
        - text / boolean:     distinct values, listed only when ≤ 10, else left empty
        - other:              skipped

        Numeric/temporal columns are aggregated in a single query; each
        text/boolean column uses one ``SELECT DISTINCT ... LIMIT 11`` query.
        """
        from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs

        if quote_ident is None:
            quote_ident = lambda n: f'"{n}"'

        minmax_cols = [
            c for c in columns
            if SchemaExtractor._classify_data_type(c.data_type) in ("numeric", "temporal")
        ]
        categorical_cols = [
            c for c in columns
            if SchemaExtractor._classify_data_type(c.data_type) in ("text", "boolean")
        ]

        try:
            # --- numeric / temporal: MIN ~ MAX in one aggregate pass ---
            if minmax_cols:
                exprs = []
                for i, col in enumerate(minmax_cols):
                    ident = quote_ident(col.name)
                    exprs.append(f"MIN({ident}) AS min_{i}")
                    exprs.append(f"MAX({ident}) AS max_{i}")
                sql = f"SELECT {', '.join(exprs)} FROM {qualified_table}"
                df = await sql_runner.run_sql(RunSqlToolArgs(sql=sql), context)
                if not df.empty:
                    row = df.iloc[0]
                    for i, col in enumerate(minmax_cols):
                        mn = row.get(f"min_{i}")
                        mx = row.get(f"max_{i}")
                        if _is_missing(mn) or _is_missing(mx):
                            continue
                        col.value_range = f"{mn} ~ {mx}"

            # --- text / boolean: distinct values (≤ limit) ---
            for col in categorical_cols:
                ident = quote_ident(col.name)
                sql = (
                    f"SELECT DISTINCT {ident} FROM {qualified_table} "
                    f"WHERE {ident} IS NOT NULL "
                    f"ORDER BY {ident} LIMIT {SchemaExtractor._DISTINCT_LIMIT + 1}"
                )
                df = await sql_runner.run_sql(RunSqlToolArgs(sql=sql), context)
                if df.empty:
                    continue
                values = [str(v) for v in df.iloc[:, 0].dropna().tolist()]
                if values and len(values) <= SchemaExtractor._DISTINCT_LIMIT:
                    col.value_range = "[" + ", ".join(values) + "]"
        except Exception:
            logger.debug(
                "Failed to fetch value ranges for %s", qualified_table, exc_info=True
            )
