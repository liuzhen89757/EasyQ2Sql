"""
Tool that retrieves the SQL query used to generate a CSV result file.

Each run_sql call writes a companion ``.sql`` file alongside the ``.csv``.
This tool reads that ``.sql`` file so the LLM can recover the exact SQL
that produced a given result set — useful for including SQL in the final
summary even after context trimming.
"""

from typing import Type

from easyq2sql.capabilities.file_system import FileSystem
from easyq2sql.components import RichTextComponent, SimpleTextComponent, UiComponent
from easyq2sql.core.tool import Tool, ToolContext, ToolResult
from easyq2sql.integrations.local import LocalFileSystem
from pydantic import BaseModel, Field


class GetSqlForFileArgs(BaseModel):
    """Arguments for retrieving SQL by result filename."""

    filename: str = Field(
        description=(
            "The CSV filename returned by run_sql (e.g. 'query_results_abc123.csv'). "
            "The tool will read the companion .sql file to return the SQL."
        ),
    )


class GetSqlForFileTool(Tool[GetSqlForFileArgs]):
    """Retrieve the SQL that was used to generate a CSV result file.

    When ``run_sql`` executes, it writes two files:
    - ``query_results_{id}.csv`` — the result data
    - ``query_results_{id}.sql`` — the SQL query

    Use this tool to recover the SQL for inclusion in your final summary.
    """

    def __init__(self, file_system: FileSystem | None = None):
        self.file_system = file_system or LocalFileSystem()

    @property
    def name(self) -> str:
        return "get_sql_for_file"

    @property
    def description(self) -> str:
        return (
            "Retrieve the exact SQL query that was executed to produce a CSV "
            "result file. Pass the CSV filename (e.g. 'query_results_abc123.csv') "
            "and the tool returns the corresponding SQL. "
            "Use this BEFORE writing your final summary to include the actual "
            "SQL statements that answered the user's question."
        )

    def get_args_schema(self) -> Type[GetSqlForFileArgs]:
        return GetSqlForFileArgs

    async def execute(
        self, context: ToolContext, args: GetSqlForFileArgs
    ) -> ToolResult:
        try:
            # Derive the companion .sql filename from the .csv filename
            csv_name = args.filename
            if csv_name.endswith(".csv"):
                sql_name = csv_name[:-4] + ".sql"
            else:
                sql_name = csv_name + ".sql"

            sql = await self.file_system.read_file(sql_name, context)

            result_text = f"SQL for {csv_name}:\n```sql\n{sql}\n```"

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=RichTextComponent(content=result_text, markdown=True),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={"filename": csv_name, "sql_file": sql_name},
            )

        except FileNotFoundError:
            error_msg = (
                f"SQL companion file for '{args.filename}' not found. "
                "The file may not exist or the query was not a SELECT."
            )
            return ToolResult(
                success=False,
                result_for_llm=error_msg,
                ui_component=UiComponent(
                    rich_component=RichTextComponent(content=error_msg),
                    simple_component=SimpleTextComponent(text=error_msg),
                ),
                error=error_msg,
            )
        except Exception as e:
            error_msg = f"Error retrieving SQL for '{args.filename}': {e}"
            return ToolResult(
                success=False,
                result_for_llm=error_msg,
                ui_component=UiComponent(
                    rich_component=RichTextComponent(content=error_msg),
                    simple_component=SimpleTextComponent(text=error_msg),
                ),
                error=str(e),
            )
