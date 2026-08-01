"""
Metric-related LLM tools for semantic metric search and execution.

The LLM only sees metric tools. Terminology mapping and dimension lookup
are resolved internally by ``SearchMetricsTool`` — the LLM is unaware of
the underlying terminology / dimension stores.
"""

from typing import Any, Dict, List, Optional, Type

import pandas as pd
from pydantic import BaseModel, Field

from easyq2sql.capabilities.metric_store import MetricStore
from easyq2sql.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from easyq2sql.components import (
    CardComponent,
    DataFrameComponent,
    RichTextComponent,
    SimpleTextComponent,
    UiComponent,
)
from easyq2sql.core.tool import Tool, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------


class DimensionFilter(BaseModel):
    """A categorical dimension extracted from the user's question.

    Dimensions are qualitative attributes used to filter, group, or label data.
    They are NOT numeric measures — those go in ``metric``.
    """

    name: str = Field(
        description="Dimension name — the categorical attribute referenced by "
        "the user. May be a filter key (WHERE), a grouping column (GROUP BY), "
        "or a descriptive label to include in output (e.g. fund manager name, "
        "product code, time period)."
    )
    value: Optional[str] = Field(
        default=None,
        description="Dimension value — only set when the user specifies a "
        "concrete filter condition. Leave as None for grouping keys and "
        "descriptive label columns.",
    )


class SearchMetricsArgs(BaseModel):
    """Structured metric + dimension search parameters.

    **Metric**: numeric, measurable, computable (SUM/AVG/COUNT).
    **Dimension**: categorical, used for filtering, grouping, or labeling.
    """

    metric: str = Field(
        description="The metric (numeric measure) to search for. "
        "Extract the core computable concept from the user's question."
    )
    dimensions: List[DimensionFilter] = Field(
        default_factory=list,
        description="Categorical dimensions referenced by the user. "
        "Set ``value`` only for filter conditions; omit for grouping keys "
        "and label columns."
    )
    limit: int = Field(
        default=5,
        description="Maximum number of matching results to return",
    )


class GetMetricDetailArgs(BaseModel):
    """Arguments for retrieving a metric's full definition."""

    metric_id: str = Field(description="The ID of the metric to retrieve")


class ListMetricsArgs(BaseModel):
    """Arguments for listing all defined metrics. No parameters needed."""
    pass


class ExecuteMetricArgs(BaseModel):
    """Arguments for executing a metric against the database."""

    metric_id: str = Field(description="The ID of the metric to execute")
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


def _format_metric_for_llm(metric, display_name: str | None = None) -> str:
    """Format a single metric for LLM consumption."""
    lines = [f"# Metric: {display_name or metric.name}"]
    if metric.business_definition:
        lines.append(f"Business Definition: {metric.business_definition}")
    if metric.calculation_logic:
        lines.append(f"Calculation: {metric.calculation_logic}")
    if metric.data_source:
        lines.append(f"Data Source: {metric.data_source}")
    if metric.analysis_field:
        lines.append(f"Analysis Field: {metric.analysis_field}")
    return "\n".join(lines)


def _format_dimension_for_llm(dim, display_name: str | None = None) -> str:
    """Format a single dimension for LLM consumption."""
    lines = [f"# Dimension: {display_name or dim.name}"]
    if dim.business_definition:
        lines.append(f"Business Definition: {dim.business_definition}")
    if dim.data_source:
        lines.append(f"Data Source: {dim.data_source}")
    if dim.field_ref:
        lines.append(f"Analysis Field: {dim.field_ref}")
    if dim.value_range:
        lines.append(f"Value Range: {dim.value_range}")
    if dim.joins:
        join_strs = []
        for j in dim.joins:
            src = j.source_column if j.source_column.startswith(j.source_table + ".") else f"{j.source_table}.{j.source_column}"
            tgt = j.target_column if j.target_column.startswith(j.target_table + ".") else f"{j.target_table}.{j.target_column}"
            join_strs.append(f"{src} = {tgt}")
        lines.append(f"Joins: {'; '.join(join_strs)}")
    return "\n".join(lines)


def _format_metric_with_dimensions(metric, dimensions: List, display_name: str | None = None) -> str:
    """Format a metric with all its linked dimensions."""
    lines = [f"# Metric: {display_name or metric.name}"]
    if metric.business_definition:
        lines.append(f"Business Definition: {metric.business_definition}")
    if metric.calculation_logic:
        lines.append(f"Calculation Logic: {metric.calculation_logic}")
    if metric.data_source:
        lines.append(f"Data Source: {metric.data_source}")
    if metric.analysis_field:
        lines.append(f"Analysis Field: {metric.analysis_field}")
    for dim in dimensions:
        lines.append(f"##Dimension: {dim.name}({dim.field_ref})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class SearchMetricsTool(Tool[SearchMetricsArgs]):
    """Search for business metrics, dimensions, and terminology.

    **This is the LLM's only entry point.** Internally:
    1. Terminology mapping search
    2. Resolve matched terms → metrics/dimensions
    3. Fallback: direct metric + dimension search
    4. Assemble structured results

    Returns metric definitions with their linked dimensions and JOIN info.
    """

    def __init__(
        self,
        metric_store: MetricStore,
        terminology_store=None,
        dimension_store=None,
    ):
        self.metric_store = metric_store
        self.terminology_store = terminology_store
        self.dimension_store = dimension_store

    @property
    def name(self) -> str:
        return "search_metrics"

    @property
    def description(self) -> str:
        return (
            "Search business metrics and dimensions. "
            "Returns metric definitions, analysis fields, JOIN logic, and SQL templates. "
            "\n\n"
            "**Call this tool ONLY after search_saved_correct_tool_uses returned no usable SQL.** "
            "Wait for search_saved_correct_tool_uses result first — do NOT call both in parallel."
        )

    def get_args_schema(self) -> Type[SearchMetricsArgs]:
        return SearchMetricsArgs

    @staticmethod
    def _build_search_query(metric: str, dimensions: List[DimensionFilter]) -> str:
        """Combine metric and dimension filters into a structured query string.

        Format::

            # metric: FundReturnMean
            # dimensions: market||Shenzhen          (filter: name + value)
            # dimensions: region                     (group/label: name only)
        """
        lines = [f"# metric: {metric}"]
        for dim in dimensions:
            if dim.value:
                lines.append(f"# dimensions: {dim.name}|{dim.value}")
            else:
                lines.append(f"# dimensions: {dim.name}")
        return "\n".join(lines)

    async def execute(
        self, context: ToolContext, args: SearchMetricsArgs
    ) -> ToolResult:
        """Search metrics with terminology resolution + fallback."""
        try:
            result_parts: List[str] = []
            match_count = 0

            search_query = self._build_search_query(args.metric, args.dimensions)

            # --- Step 1: Terminology search ---
            term_results = []
            if self.terminology_store:
                try:
                    term_results = await self.terminology_store.search_terminology(
                        query=search_query,
                        context=context,
                        limit=args.limit * 2,
                    )
                except Exception:
                    pass  # Fail-open: fall through to direct search

            if term_results:
                metric_ids_seen = set()
                dim_ids_seen = set()

                for tr in term_results:
                    entry = tr.entry

                    if entry.target_type == "metric":
                        if entry.target_id in metric_ids_seen:
                            continue
                        metric_ids_seen.add(entry.target_id)

                        metric = await self.metric_store.get_metric(
                            entry.target_id, context
                        )
                        if metric is None:
                            continue

                        # Fetch linked dimensions
                        dims = []
                        if self.dimension_store:
                            try:
                                dims = await self.dimension_store.get_dimensions_by_metric(
                                    metric.id, context
                                )
                            except Exception:
                                pass

                        formatted = _format_metric_with_dimensions(metric, dims, display_name=entry.term_text)
                        first_line, _, rest = formatted.partition("\n")
                        result_parts.append(f"{first_line} [similarity: {tr.similarity_score:.4f}]\n{rest}" if rest else f"{first_line} [similarity: {tr.similarity_score:.4f}]")
                        match_count += 1

                    elif entry.target_type == "dimension":
                        if entry.target_id in dim_ids_seen:
                            continue
                        dim_ids_seen.add(entry.target_id)

                        if self.dimension_store:
                            try:
                                dim = await self.dimension_store.get_dimension(
                                    entry.target_id, context
                                )
                                if dim is None:
                                    continue
                                formatted = _format_dimension_for_llm(dim, display_name=entry.term_text)
                                first_line, _, rest = formatted.partition("\n")
                                result_parts.append(f"{first_line} [similarity: {tr.similarity_score:.4f}]\n{rest}" if rest else f"{first_line} [similarity: {tr.similarity_score:.4f}]")
                                match_count += 1
                            except Exception:
                                pass

                    # Step 1 limit enforcement — term_results are sorted by
                    # similarity; stop once we have enough matches.
                    if match_count >= args.limit:
                        break

            # --- Step 2: Fallback — direct metric search ---
            if not result_parts:
                metric_results = await self.metric_store.search_metrics(
                    query=search_query,
                    context=context,
                    limit=args.limit,
                )

                for mr in metric_results:
                    metric = mr.metric
                    # Fetch linked dimensions
                    dims = []
                    if self.dimension_store:
                        try:
                            dims = await self.dimension_store.get_dimensions_by_metric(
                                metric.id, context
                            )
                        except Exception:
                            pass

                    formatted = _format_metric_with_dimensions(metric, dims)
                    first_line, _, rest = formatted.partition("\n")
                    result_parts.append(f"{first_line} [similarity: {mr.similarity_score:.4f}]\n{rest}" if rest else f"{first_line} [similarity: {mr.similarity_score:.4f}]")
                    match_count += 1

            # --- Step 3: Also search dimensions directly as fallback ---
            if self.dimension_store and (not result_parts or len(result_parts) < args.limit):
                try:
                    dim_results = await self.dimension_store.search_dimensions(
                        query=search_query,
                        context=context,
                        limit=max(2, args.limit - len(result_parts)),
                    )
                    for dr in dim_results:
                        dim = dr.dimension
                        formatted = _format_dimension_for_llm(dim)
                        if formatted not in result_parts:
                            first_line, _, rest = formatted.partition("\n")
                            result_parts.append(f"{first_line} [similarity: {dr.similarity_score:.4f}]\n{rest}" if rest else f"{first_line} [similarity: {dr.similarity_score:.4f}]")
                            match_count += 1
                except Exception:
                    pass

            # --- Step 4: Assemble results ---
            if not result_parts:
                no_result_msg = "No matching metrics, dimensions, or terminology found."
                return ToolResult(
                    success=True,
                    result_for_llm=no_result_msg,
                    ui_component=UiComponent(
                        rich_component=RichTextComponent(content=no_result_msg),
                        simple_component=SimpleTextComponent(text=no_result_msg),
                    ),
                )

            result_text = "\n\n".join(result_parts)

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title=f"📊 Metric Search · {match_count} results",
                        content=result_text,
                        icon="🔍",
                        status="info",
                        collapsible=True,
                        collapsed=True,
                        markdown=True,
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={"match_count": match_count},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error searching metrics: {str(e)}",
                error=str(e),
            )


class GetMetricDetailTool(Tool[GetMetricDetailArgs]):
    """Retrieve the full definition of a specific metric including its dimensions."""

    def __init__(self, metric_store: MetricStore, dimension_store=None):
        self.metric_store = metric_store
        self.dimension_store = dimension_store

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
        """Retrieve and format a single metric's full definition with dimensions."""
        try:
            metric = await self.metric_store.get_metric(args.metric_id, context)
            if metric is None:
                not_found_msg = f"Metric '{args.metric_id}' not found."
                return ToolResult(
                    success=False,
                    result_for_llm=not_found_msg,
                    error=not_found_msg,
                )

            # Fetch linked dimensions
            dims = []
            if self.dimension_store:
                try:
                    dims = await self.dimension_store.get_dimensions_by_metric(
                        metric.id, context
                    )
                except Exception:
                    pass

            result_text = _format_metric_with_dimensions(metric, dims)

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
            "which one to use. Returns a summary of each metric."
        )

    def get_args_schema(self) -> Type[ListMetricsArgs]:
        return ListMetricsArgs

    async def execute(
        self, context: ToolContext, args: ListMetricsArgs
    ) -> ToolResult:
        """List all metrics."""
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

            summaries = [_format_metric_for_llm(m) for m in metrics]
            result_text = f"Found {len(metrics)} defined metrics:\n\n" + "\n\n".join(summaries)

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title="Defined Metrics",
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

    def __init__(
        self,
        metric_store: MetricStore,
        sql_runner: SqlRunner,
        dimension_store=None,
    ):
        self.metric_store = metric_store
        self.sql_runner = sql_runner
        self.dimension_store = dimension_store

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

    async def _get_dimensions(self, metric, context: ToolContext) -> List:
        """Fetch dimensions for a metric using the given context."""
        if self.dimension_store:
            try:
                return await self.dimension_store.get_dimensions_by_metric(
                    metric.id, context
                )
            except Exception:
                pass
        return []

    def _build_metric_sql(self, metric, dimensions: List) -> str:
        """Build a SQL query from the metric and its dimensions."""
        # Alias derived from metric name
        alias = metric.name.replace(" ", "_").lower()

        # SELECT: use calculation_logic if defined, else select field directly
        calc = metric.calculation_logic.strip() if metric.calculation_logic else None
        if calc:
            select_parts = [f"{calc}({metric.analysis_field}) AS {alias}"]
        else:
            select_parts = [f"{metric.analysis_field} AS {alias}"]

        for dim in dimensions:
            if dim.field_ref not in select_parts:
                select_parts.insert(0, dim.field_ref)

        # FROM + JOINs
        from_clause = f"FROM {metric.data_source}"
        join_clauses = []
        seen_tables = {metric.data_source}
        for dim in dimensions:
            for join in dim.joins:
                if join.target_table not in seen_tables:
                    join_clauses.append(
                        f"{join.join_type} {join.target_table} "
                        f"ON {join.source_table}.{join.source_column} = "
                        f"{join.target_table}.{join.target_column}"
                    )
                    seen_tables.add(join.target_table)

        # GROUP BY: only needed when an aggregate function is present
        group_parts = []
        if calc and dimensions:
            group_parts = [dim.field_ref for dim in dimensions]

        sql_parts = ["SELECT " + ",\n       ".join(select_parts), from_clause]
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

            dimensions = await self._get_dimensions(metric, context)

            # Build and execute SQL
            sql = self._build_metric_sql(metric, dimensions)
            df: pd.DataFrame = await self.sql_runner.run_sql(
                RunSqlToolArgs(sql=sql), context
            )

            header = _format_metric_with_dimensions(metric, dimensions)

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
