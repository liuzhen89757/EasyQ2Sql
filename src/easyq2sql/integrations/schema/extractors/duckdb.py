"""
DuckDB schema extractor.

Queries information_schema and duckdb_* meta functions to extract
table and column metadata from DuckDB databases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs

from .base import SchemaExtractor

if TYPE_CHECKING:
    from easyq2sql.capabilities.sql_runner import SqlRunner
    from easyq2sql.core.tool import ToolContext


class DuckdbSchemaExtractor(SchemaExtractor):
    """Extracts table schemas from DuckDB databases.

    Uses DuckDB's information_schema and duckdb_tables() for metadata.
    DuckDB has more limited catalog information compared to Postgres/MySQL,
    so some fields (descriptions/comments) will be None.
    """

    async def extract_schemas(
        self,
        sql_runner: "SqlRunner",
        context: "ToolContext",
        database_name: str = "default",
    ) -> List[TableSchema]:
        """Extract all user table schemas from the connected DuckDB database."""

        # Get all tables
        tables_sql = """
            SELECT
                table_schema,
                table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
        """
        tables_df = await sql_runner.run_sql(
            RunSqlToolArgs(sql=tables_sql), context
        )

        # Get all columns
        columns_sql = """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_default,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name, ordinal_position
        """
        columns_df = await sql_runner.run_sql(
            RunSqlToolArgs(sql=columns_sql), context
        )

        # Get primary keys via duckdb_constraints (DuckDB 0.9+)
        try:
            pk_sql = """
                SELECT
                    table_schema,
                    table_name,
                    column_name
                FROM information_schema.key_column_usage
                WHERE constraint_name LIKE '%_pkey'
            """
            pk_df = await sql_runner.run_sql(
                RunSqlToolArgs(sql=pk_sql), context
            )
            pk_set = set()
            for _, pk_row in pk_df.iterrows():
                pk_set.add(
                    (str(pk_row["table_schema"]), str(pk_row["table_name"]), str(pk_row["column_name"]))
                )
        except Exception:
            pk_set = set()

        # Assemble TableSchema objects
        tables: List[TableSchema] = []
        for _, t_row in tables_df.iterrows():
            schema_name = str(t_row.get("table_schema", ""))
            table_name = str(t_row["table_name"])

            # Filter columns for this table
            table_cols_df = columns_df[
                (columns_df["table_schema"] == schema_name)
                & (columns_df["table_name"] == table_name)
            ]

            columns: List[ColumnSchema] = []
            for _, c_row in table_cols_df.iterrows():
                col_name = str(c_row["column_name"])
                is_pk = (schema_name, table_name, col_name) in pk_set

                col = ColumnSchema(
                    name=col_name,
                    data_type=str(c_row["data_type"]),
                    nullable=str(c_row["is_nullable"]) == "YES",
                    default_value=str(c_row["column_default"])
                    if c_row.get("column_default") is not None
                    else None,
                    description=None,
                    is_primary_key=is_pk,
                )
                columns.append(col)

            # Fetch up to 3 sample rows for example values
            qualified = f"{schema_name}.{table_name}" if schema_name else table_name
            await self._fetch_examples(sql_runner, context, qualified, columns)

            table = TableSchema(
                table_name=table_name,
                schema_name=schema_name if schema_name else None,
                database_name=database_name,
                columns=columns,
            )
            tables.append(table)

        return tables
