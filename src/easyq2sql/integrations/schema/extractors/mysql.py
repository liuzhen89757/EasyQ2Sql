"""
MySQL schema extractor.

Queries information_schema to extract table and column metadata
including comments, primary keys, foreign keys, and DDL via SHOW CREATE TABLE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs

from .base import SchemaExtractor

if TYPE_CHECKING:
    from easyq2sql.capabilities.sql_runner import SqlRunner
    from easyq2sql.core.tool import ToolContext


class MySqlSchemaExtractor(SchemaExtractor):
    """Extracts table schemas from MySQL databases.

    Uses information_schema for column and constraint metadata, and
    SHOW CREATE TABLE for DDL retrieval.
    """

    @staticmethod
    def _normalize_columns(df):
        """Lowercase DataFrame column names to handle MySQL's case-insensitivity.

        MySQL ``information_schema`` tables return UPPERCASE column names
        (e.g. ``TABLE_NAME``, ``COLUMN_NAME``) when selected without an alias.
        Aliased columns (``AS foo``) retain their declared case. Lowercasing
        everything gives us a uniform, predictable interface.
        """
        if df is not None and len(df.columns) > 0:
            df.columns = [str(c).lower() for c in df.columns]
        return df

    async def extract_schemas(
        self,
        sql_runner: "SqlRunner",
        context: "ToolContext",
        database_name: str = "default",
    ) -> List[TableSchema]:
        """Extract all user table schemas from the connected MySQL database."""

        # Get current database name
        db_sql = "SELECT DATABASE() AS db_name"
        db_df = self._normalize_columns(
            await sql_runner.run_sql(RunSqlToolArgs(sql=db_sql), context)
        )
        db_name = str(db_df.iloc[0]["db_name"]) if len(db_df) > 0 else database_name

        # Query tables with comments
        tables_sql = f"""
            SELECT
                t.table_name,
                t.table_comment AS table_description
            FROM information_schema.tables t
            WHERE t.table_schema = '{db_name}'
              AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_name
        """
        tables_df = self._normalize_columns(
            await sql_runner.run_sql(RunSqlToolArgs(sql=tables_sql), context)
        )

        # Query columns with comments and key info
        columns_sql = f"""
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.column_type,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                c.column_comment AS column_description,
                CASE WHEN c.column_key = 'PRI' THEN TRUE ELSE FALSE END AS is_primary_key
            FROM information_schema.columns c
            WHERE c.table_schema = '{db_name}'
            ORDER BY c.table_name, c.ordinal_position
        """
        columns_df = self._normalize_columns(
            await sql_runner.run_sql(RunSqlToolArgs(sql=columns_sql), context)
        )

        # Query foreign keys
        fk_sql = f"""
            SELECT
                kcu.table_name,
                kcu.column_name,
                kcu.referenced_table_name AS fk_reference_table,
                kcu.referenced_column_name AS fk_reference_column
            FROM information_schema.key_column_usage kcu
            WHERE kcu.table_schema = '{db_name}'
              AND kcu.referenced_table_name IS NOT NULL
        """
        fk_df = self._normalize_columns(
            await sql_runner.run_sql(RunSqlToolArgs(sql=fk_sql), context)
        )

        # Build FK lookup
        fk_map = {}
        for _, fk_row in fk_df.iterrows():
            key = (str(fk_row["table_name"]), str(fk_row["column_name"]))
            fk_map[key] = (
                str(fk_row["fk_reference_table"]),
                str(fk_row["fk_reference_column"]),
            )

        # Assemble TableSchema objects
        tables: List[TableSchema] = []
        for _, t_row in tables_df.iterrows():
            table_name = str(t_row["table_name"])

            # Get DDL via SHOW CREATE TABLE
            ddl_df = self._normalize_columns(
                await sql_runner.run_sql(
                    RunSqlToolArgs(sql=f"SHOW CREATE TABLE `{table_name}`"), context
                )
            )
            ddl = (
                str(ddl_df.iloc[0]["create table"])
                if len(ddl_df) > 0
                else None
            )

            # Filter columns for this table
            table_cols_df = columns_df[
                columns_df["table_name"] == table_name
            ]

            columns: List[ColumnSchema] = []
            for _, c_row in table_cols_df.iterrows():
                col_name = str(c_row["column_name"])
                fk_ref = fk_map.get((table_name, col_name))
                is_fk = fk_ref is not None

                col = ColumnSchema(
                    name=col_name,
                    data_type=str(c_row.get("column_type", c_row["data_type"])),
                    nullable=str(c_row["is_nullable"]) == "YES",
                    default_value=str(c_row["column_default"])
                    if c_row.get("column_default") is not None
                    else None,
                    description=str(c_row["column_description"])
                    if c_row.get("column_description")
                    else None,
                    is_primary_key=bool(c_row["is_primary_key"]),
                    is_foreign_key=is_fk,
                    fk_reference_table=fk_ref[0] if is_fk else None,
                    fk_reference_column=fk_ref[1] if is_fk else None,
                )
                columns.append(col)

            # Fetch up to 3 sample rows for example values
            qualified = f"`{db_name}`.`{table_name}`"
            await self._fetch_examples(sql_runner, context, qualified, columns)

            table = TableSchema(
                table_name=table_name,
                database_name=db_name,
                description=str(t_row["table_description"])
                if t_row.get("table_description")
                else None,
                columns=columns,
                ddl=ddl,
            )
            tables.append(table)

        return tables
