"""
SQLite schema extractor.

Queries sqlite_master and PRAGMA table_info/table_xinfo to extract
table and column metadata including DDL, primary keys, and foreign keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs

from .base import SchemaExtractor

if TYPE_CHECKING:
    from easyq2sql.capabilities.sql_runner import SqlRunner
    from easyq2sql.core.tool import ToolContext


class SqliteSchemaExtractor(SchemaExtractor):
    """Extracts table schemas from SQLite databases.

    Uses sqlite_master for table listing and DDL, and PRAGMA table_info
    / PRAGMA foreign_key_list for column-level metadata.
    """

    async def extract_schemas(
        self,
        sql_runner: "SqlRunner",
        context: "ToolContext",
        database_name: str = "default",
    ) -> List[TableSchema]:
        """Extract all user table schemas from the connected SQLite database."""

        # Get all user table names and DDL
        tables_sql = """
            SELECT name, sql AS ddl
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
        tables_df = await sql_runner.run_sql(
            RunSqlToolArgs(sql=tables_sql), context
        )

        tables: List[TableSchema] = []
        for _, row in tables_df.iterrows():
            table_name = str(row["name"])
            ddl = str(row.get("ddl", "")) if row.get("ddl") else None

            # Get column info via table-valued PRAGMA (SELECT form avoids DML treatment)
            pragma_sql = f"SELECT * FROM pragma_table_info('{table_name}')"
            cols_df = await sql_runner.run_sql(
                RunSqlToolArgs(sql=pragma_sql), context
            )

            # Get foreign key info via table-valued PRAGMA
            fk_sql = f"SELECT * FROM pragma_foreign_key_list('{table_name}')"
            fk_df = await sql_runner.run_sql(
                RunSqlToolArgs(sql=fk_sql), context
            )

            # Build FK lookup: column_name -> (ref_table, ref_column)
            fk_map = {}
            for _, fk_row in fk_df.iterrows():
                col_name = str(fk_row.get("from", ""))
                ref_table = str(fk_row.get("table", ""))
                ref_col = str(fk_row.get("to", ""))
                if col_name:
                    fk_map[col_name] = (ref_table, ref_col)

            columns: List[ColumnSchema] = []
            for _, c_row in cols_df.iterrows():
                col_name = str(c_row["name"])
                fk_ref = fk_map.get(col_name)
                is_fk = fk_ref is not None

                col = ColumnSchema(
                    name=col_name,
                    data_type=str(c_row.get("type", "TEXT")),
                    nullable=not bool(int(c_row.get("notnull") or 0)),
                    default_value=str(c_row["dflt_value"])
                    if c_row.get("dflt_value") is not None
                    else None,
                    description=None,
                    is_primary_key=bool(int(c_row.get("pk") or 0)),
                    is_foreign_key=is_fk,
                    fk_reference_table=fk_ref[0] if is_fk else None,
                    fk_reference_column=fk_ref[1] if is_fk else None,
                )
                columns.append(col)

            # Fetch up to 3 sample rows for example values
            qualified = f'"{table_name}"'
            await self._fetch_examples(sql_runner, context, qualified, columns)

            table = TableSchema(
                table_name=table_name,
                database_name=database_name,
                columns=columns,
                ddl=ddl,
            )
            tables.append(table)

        return tables
