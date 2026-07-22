"""
Metric-related LLM tools for semantic metric search and execution.

These tools let the LLM agent discover user-defined business metrics,
retrieve their definitions, and execute them against the database.
"""

from typing import Any, Dict, List, Optional, Type

import pandas as pd
from pydantic import BaseModel, Field

from easyq2sql.capabilities.metric_store import MetricStore
from easyq2sql.capabilities.sql_runner import SqlRunner, RunSqlToolArgs
from easyq2sql.components import (
    CardComponent,
    DataFrameComponent,
    RichTextComponent,
    SimpleTextComponent,
    UiComponent,
)
from easyq2sql.core.tool import Tool, ToolContext, ToolResult


class SearchMetricsArgs(BaseModel):
    """Arguments for searching metrics by natural language query."""

    query: str = Field(
        description="Keywords for vector search against metric names, descriptions, "
        "analysis fields, and dimension names. Extract business concepts, "
        "measure names, and calculation terms — do NOT pass the raw user question verbatim."
    )
    limit: int = Field(
        default=3,
        description="Maximum number of matching metrics to return",
    )


class GetMetricDetailArgs(BaseModel):
    """Arguments for retrieving a metric's full definition."""

    metric_id: str = Field(
        description="The ID of the metric to retrieve"
    )


class ListMetricsArgs(BaseModel):
    """Arguments for listing all defined metrics. No parameters needed."""

    pass


class ExecuteMetricArgs(BaseModel):
    """Arguments for executing a metric against the database."""

    metric_id: str = Field(
        description="The ID of the metric to execute"
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional filter conditions, e.g. {'date': '2024-Q4', 'region': 'East'}",
    )
    dimension_values: Optional[List[str]] = Field(
        default=None,
        description="Optional specific dimension values to filter by",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_metric_for_llm(metric) -> str:
    """Format a single metric for LLM consumption, including JOIN info."""
    lines = [
        f"# Metric: {metric.name}({metric.analysis_field})",
    ]
    if metric.description:
        lines.append(f"Description: {metric.description}")

    if metric.dimensions:
        for d in metric.dimensions:
            lines.append(f"##Dimension: {d.name}({d.field_ref})")
            if d.joins:
                join_strs = [
                    f"{j.source_table}.{j.source_column} = {j.target_table}.{j.target_column}"
                    for j in d.joins
                ]
                lines.append(f"Joins: {'; '.join(join_strs)}")

    if metric.generated_sql_template:
        lines.append(f"\nGenerated SQL Template:\n{metric.generated_sql_template}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class SearchMetricsTool(Tool[SearchMetricsArgs]):
    """Search for business metrics by natural language description.

    Uses hybrid search (vector + keyword with RRF fusion).
    Returns up to ``limit`` results (default 1).
    """

    def __init__(self, metric_store: MetricStore):
        self.metric_store = metric_store

    @property
    def name(self) -> str:
        return "search_metrics"

    @property
    def description(self) -> str:
        return (
            "Retrieve relevant pre-defined business metrics for the user's question. "
            "Call once with a keyword query covering all business concepts the user mentioned. "
            "Returns metric names, analysis fields, dimensions, JOIN logic, and SQL templates."
        )

    def get_args_schema(self) -> Type[SearchMetricsArgs]:
        return SearchMetricsArgs

    async def execute(
        self, context: ToolContext, args: SearchMetricsArgs
    ) -> ToolResult:
        """Search metrics with hybrid retrieval + RRF re-rank, return top 1."""
        try:
            results = await self.metric_store.search_metrics(
                query=args.query,
                context=context,
                limit=args.limit,
            )

            if not results:
                no_result_msg = "No matching metrics found."
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
            result_text = "\n\n".join(docs) if docs else "No matching metrics found."

            # Build UI card — detailed format with collapsible card
            detailed_content = "**Retrieved metrics passed to LLM:**\n\n"
            for i, r in enumerate(results, 1):
                m = r.metric
                detailed_content += f"**{i}. {m.name}** (similarity: {r.similarity_score:.6f})\n"
                if m.description:
                    detailed_content += f"- **Description:** {m.description}\n"
                detailed_content += f"- **Field:** `{m.analysis_table}.{m.analysis_field}`\n"
                if m.dimensions:
                    dim_names = [d.name for d in m.dimensions]
                    detailed_content += f"- **Dimensions:** `{'`, `'.join(dim_names)}`\n"
                if m.generated_sql_template:
                    sql_preview = m.generated_sql_template[:200]
                    if len(m.generated_sql_template) > 200:
                        sql_preview += "..."
                    detailed_content += f"- **SQL:** `{sql_preview}`\n"
                detailed_content += "\n"

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title=f"🎯 Metric Search: {len(results)} Metric(s)",
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
            return ToolResult(
                success=False,
                result_for_llm=f"Error searching metrics: {str(e)}",
                error=str(e),
            )


class GetMetricDetailTool(Tool[GetMetricDetailArgs]):
    """Retrieve the full definition of a specific metric including JOINs and SQL template."""

    def __init__(self, metric_store: MetricStore):
        self.metric_store = metric_store

    @property
    def name(self) -> str:
        return "get_metric_detail"

    @property
    def description(self) -> str:
        return (
            "Get the complete definition of a specific metric by its ID. "
            "Returns the metric name, analysis field, dimensions, FK JOINs, "
            "and the auto-generated SQL template. "
            "Use this when you need the full SQL logic for a metric."
        )

    def get_args_schema(self) -> Type[GetMetricDetailArgs]:
        return GetMetricDetailArgs

    async def execute(
        self, context: ToolContext, args: GetMetricDetailArgs
    ) -> ToolResult:
        """Retrieve and format a single metric's full definition with JOIN info."""
        try:
            metric = await self.metric_store.get_metric(args.metric_id, context)

            if metric is None:
                not_found_msg = f"Metric '{args.metric_id}' not found."
                return ToolResult(
                    success=False,
                    result_for_llm=not_found_msg,
                    error=not_found_msg,
                )

            result_text = _format_metric_for_llm(metric)

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title=f"Metric: {metric.name}",
                        content=result_text,
                        markdown=False,
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={"metric_id": metric.id},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error retrieving metric: {str(e)}",
                error=str(e),
            )


class ListMetricsTool(Tool[ListMetricsArgs]):
    """List all defined business metrics."""

    def __init__(self, metric_store: MetricStore):
        self.metric_store = metric_store

    @property
    def name(self) -> str:
        return "list_metrics"

    @property
    def description(self) -> str:
        return (
            "List all pre-defined business metrics. "
            "Use this to discover what metrics are available before deciding "
            "which one to use. Returns a summary of each metric including "
            "dimensions and JOIN relationships."
        )

    def get_args_schema(self) -> Type[ListMetricsArgs]:
        return ListMetricsArgs

    async def execute(
        self, context: ToolContext, args: ListMetricsArgs
    ) -> ToolResult:
        """List all metrics with JOIN info in the summary."""
        try:
            metrics = await self.metric_store.list_metrics(context)

            if not metrics:
                no_metrics_msg = "No metrics have been defined yet."
                return ToolResult(
                    success=True,
                    result_for_llm=no_metrics_msg,
                    ui_component=UiComponent(
                        rich_component=RichTextComponent(content=no_metrics_msg),
                        simple_component=SimpleTextComponent(text=no_metrics_msg),
                    ),
                )

            summaries = []
            for m in metrics:
                summaries.append(_format_metric_for_llm(m))

            result_text = f"Found {len(metrics)} defined metrics:\n\n" + "\n\n".join(summaries)

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title=f"Defined Metrics ({len(metrics)})",
                        content=result_text,
                        markdown=True,
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={"total_metrics": len(metrics)},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error listing metrics: {str(e)}",
                error=str(e),
            )


class ExecuteMetricTool(Tool[ExecuteMetricArgs]):
    """Execute a metric against the database.

    Builds the final SQL from the metric's dimensions and FK JOINs,
    then executes it and returns the results.
    """

    def __init__(self, metric_store: MetricStore, sql_runner: SqlRunner):
        self.metric_store = metric_store
        self.sql_runner = sql_runner

    @property
    def name(self) -> str:
        return "execute_metric"

    @property
    def description(self) -> str:
        return (
            "Execute a pre-defined business metric against the database. "
            "Builds the SQL query from the metric's dimensions and JOINs, "
            "then runs it and returns the results. "
            "Use this after finding a relevant metric with search_metrics."
        )

    def get_args_schema(self) -> Type[ExecuteMetricArgs]:
        return ExecuteMetricArgs

    def _build_metric_sql(self, metric) -> str:
        """Build a SQL query from the metric's dimensions and JOINs.

        Uses COUNT on the analysis_field as the default aggregation.
        Dimension fields are added to SELECT and GROUP BY.
        Dimension JOINs are included in the FROM clause.
        """

        # Use pre-generated SQL template if available
        if metric.generated_sql_template:
            return metric.generated_sql_template

        # SELECT: COUNT on analysis field + dimension fields
        select_parts = [f"COUNT({metric.analysis_field}) AS count"]
        for dim in metric.dimensions:
            if dim.field_ref not in select_parts:
                select_parts.insert(0, dim.field_ref)

        # FROM + JOINs from per-dimension joins
        from_clause = f"FROM {metric.analysis_table}"
        join_clauses = []
        seen_tables = {metric.analysis_table}
        for dim in metric.dimensions:
            for join in dim.joins:
                if join.target_table not in seen_tables:
                    join_clauses.append(
                        f"{join.join_type} {join.target_table} "
                        f"ON {join.source_table}.{join.source_column} = "
                        f"{join.target_table}.{join.target_column}"
                    )
                    seen_tables.add(join.target_table)

        # GROUP BY from dimensions
        group_parts = [dim.field_ref for dim in metric.dimensions]

        sql_parts = [
            "SELECT " + ",\n       ".join(select_parts),
            from_clause,
        ]
        if join_clauses:
            sql_parts.extend(join_clauses)
        if group_parts:
            sql_parts.append("GROUP BY " + ", ".join(group_parts))

        return "\n".join(sql_parts)

    async def execute(
        self, context: ToolContext, args: ExecuteMetricArgs
    ) -> ToolResult:
        """Execute a metric against the database."""
        try:
            metric = await self.metric_store.get_metric(args.metric_id, context)
            if metric is None:
                return ToolResult(
                    success=False,
                    result_for_llm=f"Metric '{args.metric_id}' not found.",
                    error=f"Metric '{args.metric_id}' not found.",
                )

            # Build and execute SQL
            sql = self._build_metric_sql(metric)
            df: pd.DataFrame = await self.sql_runner.run_sql(
                RunSqlToolArgs(sql=sql), context
            )

            # Include metric definition and JOIN info in the result
            header = _format_metric_for_llm(metric)

            if df.empty:
                return ToolResult(
                    success=True,
                    result_for_llm=f"{header}\n\nMetric '{metric.name}' executed. No rows returned.\nSQL: {sql}",
                    ui_component=UiComponent(
                        rich_component=DataFrameComponent(
                            rows=[], columns=[], title=f"Metric: {metric.name}",
                        ),
                        simple_component=SimpleTextComponent(
                            text=f"Metric '{metric.name}': No rows returned."
                        ),
                    ),
                )

            # Format results
            rows = df.to_dict("records")
            csv_preview = df.to_csv(index=False)
            if len(csv_preview) > 2000:
                csv_preview = csv_preview[:2000] + "\n...(truncated)"

            result_text = (
                f"{header}\n\n"
                f"Metric '{metric.name}' results ({len(df)} rows):\n\n"
                f"{csv_preview}\n\n"
                f"Generated SQL:\n{sql}"
            )

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=DataFrameComponent.from_records(
                        records=rows,
                        title=f"Metric: {metric.name}",
                        description=f"{len(df)} rows returned",
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={
                    "metric_id": metric.id,
                    "metric_name": metric.name,
                    "row_count": len(df),
                    "generated_sql": sql,
                },
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error executing metric: {str(e)}",
                error=str(e),
            )
