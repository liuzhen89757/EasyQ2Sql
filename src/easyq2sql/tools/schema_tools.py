"""
Schema-related LLM tools for semantic table search.

These tools let the LLM agent discover relevant database tables
by searching the SchemaStore with natural language queries.
"""

from typing import Type

from pydantic import BaseModel, Field

from easyq2sql.capabilities.schema_store import SchemaStore
from easyq2sql.components import (
    CardComponent,
    RichTextComponent,
    SimpleTextComponent,
    UiComponent,
)
from easyq2sql.core.tool import Tool, ToolContext, ToolResult


class SearchTableSchemaArgs(BaseModel):
    """Arguments for searching table schemas by natural language query."""

    query: str = Field(
        description="Keywords for vector search against table descriptions, column names, "
        "and DDL metadata. Extract core entities, column-like attributes, and domain terms "
        "from the user's question — do NOT pass the raw question verbatim. "
        "Think: what table/column names would a DBA have documented?"
    )
    limit: int = Field(
        default=3,
        description="Maximum number of matching tables to return",
    )


class SearchTableSchemaTool(Tool[SearchTableSchemaArgs]):
    """Tool that lets the LLM search for relevant database tables by description.

    Uses hybrid search (vector + keyword with RRF fusion) to find tables whose
    names, descriptions, and column metadata match the user's intent.
    Returns up to ``limit`` results (default 3).
    """

    def __init__(self, schema_store: SchemaStore):
        """Initialize the tool with a SchemaStore implementation.

        Args:
            schema_store: SchemaStore implementation for table metadata retrieval.
        """
        self.schema_store = schema_store

    @property
    def name(self) -> str:
        return "search_table_schema"

    @property
    def description(self) -> str:
        return (
            "Retrieve relevant database table schemas for the user's question. "
            "Call once with a keyword query covering all entities the user mentioned. "
            "Returns table names, columns, types, primary/foreign keys, and descriptions."
        )

    def get_args_schema(self) -> Type[SearchTableSchemaArgs]:
        return SearchTableSchemaArgs

    async def execute(
        self, context: ToolContext, args: SearchTableSchemaArgs
    ) -> ToolResult:
        """Search table schemas with hybrid retrieval + RRF re-rank, return top 3."""
        try:
            results = await self.schema_store.search_tables(
                query=args.query,
                context=context,
                limit=args.limit,
            )

            if not results:
                no_result_msg = (
                    "No matching tables found. Try broadening your search query."
                )
                return ToolResult(
                    success=True,
                    result_for_llm=no_result_msg,
                    ui_component=UiComponent(
                        rich_component=RichTextComponent(content=no_result_msg),
                        simple_component=SimpleTextComponent(text=no_result_msg),
                    ),
                )

            # Hybrid search results already re-ranked & truncated by the store
            docs = [r.document_text for r in results if r.document_text]
            result_text = "\n\n".join(docs) if docs else "No matching tables found."

            # Build UI card — detailed format with collapsible card
            detailed_content = "**Retrieved schemas passed to LLM:**\n\n"
            for i, r in enumerate(results, 1):
                detailed_content += f"**{i}. {r.table.table_name}** (similarity: {r.similarity_score:.6f})\n"
                if r.table.description:
                    detailed_content += f"- **Description:** {r.table.description}\n"
                if r.table.database_name:
                    detailed_content += f"- **Database:** {r.table.database_name}\n"
                # Column summary
                col_names = [c.name for c in r.table.columns]
                if col_names:
                    detailed_content += f"- **Columns ({len(col_names)}):** `{'`, `'.join(col_names[:20])}`"
                    if len(col_names) > 20:
                        detailed_content += f" ... (+{len(col_names) - 20} more)"
                    detailed_content += "\n"
                if r.table.row_count_estimate:
                    detailed_content += f"- **Est. rows:** {r.table.row_count_estimate}\n"
                detailed_content += "\n"

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title=f"📋 Schema Search: {len(results)} Table(s)",
                        content=detailed_content.strip(),
                        icon="🔍",
                        status="info",
                        collapsible=True,
                        collapsed=True,
                        markdown=True,
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={"match_count": len(results)},
            )

        except Exception as e:
            error_message = f"Error searching table schemas: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                error=str(e),
            )
