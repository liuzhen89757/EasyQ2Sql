"""Generic SQL query execution tool with dependency injection."""

from typing import Any, Dict, List, Optional, Type, cast
import uuid
from easyq2sql.core.tool import Tool, ToolContext, ToolResult
from easyq2sql.components import (
    UiComponent,
    DataFrameComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)
from easyq2sql.capabilities.sql_runner import SqlRunner, RunSqlToolArgs
from easyq2sql.capabilities.file_system import FileSystem
from easyq2sql.integrations.local import LocalFileSystem


class RunSqlTool(Tool[RunSqlToolArgs]):
    """Tool that executes SQL queries using an injected SqlRunner implementation."""

    def __init__(
        self,
        sql_runner: SqlRunner,
        file_system: Optional[FileSystem] = None,
        custom_tool_name: Optional[str] = None,
        custom_tool_description: Optional[str] = None,
    ):
        """Initialize the tool with a SqlRunner implementation.

        Args:
            sql_runner: SqlRunner implementation that handles actual query execution
            file_system: FileSystem implementation for saving results (defaults to LocalFileSystem)
            custom_tool_name: Optional custom name for the tool (overrides default "run_sql")
            custom_tool_description: Optional custom description for the tool (overrides default description)
        """
        self.sql_runner = sql_runner
        self.file_system = file_system or LocalFileSystem()
        self._custom_name = custom_tool_name
        self._custom_description = custom_tool_description

    @property
    def name(self) -> str:
        return self._custom_name if self._custom_name else "run_sql"

    @property
    def description(self) -> str:
        return (
            self._custom_description
            if self._custom_description
            else "Execute SQL queries against the configured database"
        )

    def get_args_schema(self) -> Type[RunSqlToolArgs]:
        return RunSqlToolArgs

    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        """Execute a SQL query using the injected SqlRunner."""
        try:
            # Use the injected SqlRunner to execute the query
            df = await self.sql_runner.run_sql(args, context)

            # Determine query type
            query_type = args.sql.strip().upper().split()[0]

            if query_type == "SELECT":
                # Handle SELECT queries with results
                if df.empty:
                    result = "Query executed successfully. No rows returned."
                    ui_component = UiComponent(
                        rich_component=DataFrameComponent(
                            rows=[],
                            columns=[],
                            title="Query Results",
                            description="No rows returned",
                        ),
                        simple_component=SimpleTextComponent(text=result),
                    )
                    metadata = {
                        "row_count": 0,
                        "columns": [],
                        "query_type": query_type,
                        "results": [],
                    }
                else:
                    # Convert DataFrame to records
                    results_data = df.to_dict("records")
                    columns = df.columns.tolist()
                    row_count = len(df)

                    # Write FULL DataFrame to CSV file for frontend export,
                    # and a companion .sql file so the SQL can be retrieved
                    # later by filename reference.
                    file_id = str(uuid.uuid4())[:8]
                    filename = f"query_results_{file_id}.csv"
                    sql_filename = f"query_results_{file_id}.sql"
                    csv_content = df.to_csv(index=False)
                    await self.file_system.write_file(
                        filename, csv_content, context, overwrite=True
                    )
                    await self.file_system.write_file(
                        sql_filename, args.sql, context, overwrite=True
                    )

                    # Build result_for_llm: at most 20 rows so we stay within
                    # the LLM context window. The full dataset is available in
                    # the CSV file and the frontend DataFrame component.
                    MAX_LLM_ROWS = 20
                    if row_count > MAX_LLM_ROWS:
                        truncated_df = df.head(MAX_LLM_ROWS)
                        results_preview = truncated_df.to_csv(index=False)
                        results_preview += (
                            f"\n(Showing first {MAX_LLM_ROWS} of {row_count} rows. "
                            f"Full results saved to {filename}. "
                            "DO NOT summarize — use visualize_data with the filename for charts.)"
                        )
                    else:
                        results_preview = csv_content

                    # Include the SQL prominently so the LLM can reference
                    # it in the final summary.
                    result = (
                        f"\n{results_preview}\n\n"
                        f"Results saved to file: {filename}\n"
                        f"SQL saved to file: {sql_filename}\n\n"
                        f"**IMPORTANT: FOR VISUALIZE_DATA USE FILENAME: {filename}; TO RETRIEVE THE EXACT SQL LATER USE FILENAME: {sql_filename}**\n"
                    )

                    # Create DataFrame component for UI
                    dataframe_component = DataFrameComponent.from_records(
                        records=cast(List[Dict[str, Any]], results_data),
                        title="Query Results",
                        description=f"SQL query returned {row_count} rows with {len(columns)} columns",
                    )

                    ui_component = UiComponent(
                        rich_component=dataframe_component,
                        simple_component=SimpleTextComponent(text=result),
                    )

                    metadata = {
                        "row_count": row_count,
                        "columns": columns,
                        "query_type": query_type,
                        "results": results_data,
                        "output_file": filename,
                        "sql_file": sql_filename,
                    }
            else:
                # For non-SELECT queries (INSERT, UPDATE, DELETE, etc.)
                # The SqlRunner should return a DataFrame with affected row count
                rows_affected = len(df) if not df.empty else 0
                result = (
                    f"Query executed successfully. {rows_affected} row(s) affected."
                )

                metadata = {"rows_affected": rows_affected, "query_type": query_type}
                ui_component = UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION, level="success", message=result
                    ),
                    simple_component=SimpleTextComponent(text=result),
                )

            return ToolResult(
                success=True,
                result_for_llm=result,
                ui_component=ui_component,
                metadata=metadata,
            )

        except Exception as e:
            error_message = f"Error executing query: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=str(e),
                metadata={"error_type": "sql_error"},
            )
