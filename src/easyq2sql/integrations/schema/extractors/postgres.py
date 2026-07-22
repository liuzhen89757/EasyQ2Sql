"""
PostgreSQL schema extractor.

Queries information_schema and pg_catalog to extract table and column
metadata including comments, primary keys, foreign keys, and DDL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs

from .base import SchemaExtractor

if TYPE_CHECKING:
    from easyq2sql.capabilities.sql_runner import SqlRunner
    from easyq2sql.core.tool import ToolContext


class PostgresSchemaExtractor(SchemaExtractor):
    """Extracts table schemas from PostgreSQL databases.

    Uses information_schema.columns for column metadata, pg_catalog
    for table/column comments, and pg_catalog for constraint info.
    """

    async def extract_schemas(
        self,
        sql_runner: "SqlRunner",
        context: "ToolContext",
        database_name: str = "default",
    ) -> List[TableSchema]:
        """Extract all user table schemas from the connected PostgreSQL database."""

        # Query table metadata: names and comments
        tables_sql = """
            SELECT
                t.table_schema,
                t.table_name,
                pg_catalog.obj_description(
                    (quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass,
                    'pg_class'
                ) AS table_description,
                (SELECT pg_catalog.pg_get_userbyid(c.relowner)
                 FROM pg_catalog.pg_class c
                 JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = t.table_schema AND c.relname = t.table_name
                ) AS table_owner
            FROM information_schema.tables t
            WHERE t.table_type = 'BASE TABLE'
              AND t.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY t.table_schema, t.table_name
        """
        tables_df = await sql_runner.run_sql(
            RunSqlToolArgs(sql=tables_sql), context
        )

        # Query column metadata for all user tables
        columns_sql = """
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                pg_catalog.col_description(
                    (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                    c.ordinal_position
                ) AS column_description,
                CASE WHEN pk.column_name IS NOT NULL THEN TRUE ELSE FALSE END AS is_primary_key
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT
                    ku.table_schema,
                    ku.table_name,
                    ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                    ON tc.constraint_name = ku.constraint_name
                    AND tc.table_schema = ku.table_schema
                    AND tc.table_name = ku.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk ON c.table_schema = pk.table_schema
                 AND c.table_name = pk.table_name
                 AND c.column_name = pk.column_name
            WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        columns_df = await sql_runner.run_sql(
            RunSqlToolArgs(sql=columns_sql), context
        )

        # Query foreign key relationships
        fk_sql = """
            SELECT
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS fk_reference_schema,
                ccu.table_name AS fk_reference_table,
                ccu.column_name AS fk_reference_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
        """
        fk_df = await sql_runner.run_sql(
            RunSqlToolArgs(sql=fk_sql), context
        )

        # Build FK lookup: (table_schema, table_name, column_name) -> (ref_table, ref_col)
        fk_map = {}
        for _, row in fk_df.iterrows():
            key = (row["table_schema"], row["table_name"], row["column_name"])
            fk_map[key] = (
                f"{row['fk_reference_schema']}.{row['fk_reference_table']}"
                if row.get("fk_reference_schema")
                else row["fk_reference_table"],
                row["fk_reference_column"],
            )

        # Assemble TableSchema objects
        tables: List[TableSchema] = []
        for _, t_row in tables_df.iterrows():
            schema_name = t_row["table_schema"]
            table_name = t_row["table_name"]

            # Filter columns for this table
            table_cols_df = columns_df[
                (columns_df["table_schema"] == schema_name)
                & (columns_df["table_name"] == table_name)
            ]

            columns: List[ColumnSchema] = []
            for _, c_row in table_cols_df.iterrows():
                fk_ref = fk_map.get((schema_name, table_name, c_row["column_name"]))
                is_fk = fk_ref is not None

                col = ColumnSchema(
                    name=c_row["column_name"],
                    data_type=c_row["data_type"],
                    nullable=c_row["is_nullable"] == "YES",
                    default_value=str(c_row["column_default"])
                    if c_row["column_default"] is not None
                    else None,
                    description=str(c_row["column_description"])
                    if c_row["column_description"]
                    else None,
                    is_primary_key=bool(c_row["is_primary_key"]),
                    is_foreign_key=is_fk,
                    fk_reference_table=fk_ref[0] if is_fk else None,
                    fk_reference_column=fk_ref[1] if is_fk else None,
                )
                columns.append(col)

            # Fetch up to 3 sample rows for example values
            qualified = f"{schema_name}.{table_name}"
            await self._fetch_examples(sql_runner, context, qualified, columns)

            table = TableSchema(
                table_name=table_name,
                schema_name=schema_name,
                database_name=database_name,
                description=str(t_row["table_description"])
                if t_row.get("table_description")
                else None,
                columns=columns,
            )
            tables.append(table)

        return tables
