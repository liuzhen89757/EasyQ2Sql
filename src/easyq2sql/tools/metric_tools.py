"""
Metric-related LLM tools for semantic metric search and execution.

The LLM only sees metric tools. Derived-metric lookup is resolved internally by
``SearchMetricsTool`` — the LLM is unaware of the underlying derived-metric store.
"""

from typing import Any, Dict, List, Optional, Type

import pandas as pd
from pydantic import BaseModel, Field

from easyq2sql.capabilities.atomic_metric import AtomicMetricStore
from easyq2sql.capabilities.composite_metric import CompositeMetricStore
from easyq2sql.capabilities.derived_metric import DerivedMetricStore
from easyq2sql.capabilities.metric_graph_store import (
    ENTITY_TYPE_ATOMIC,
    ENTITY_TYPE_COMPOSITE,
    ENTITY_TYPE_DERIVED,
    REL_DERIVED_FROM,
    REL_USES,
    MetricGraphEdge,
    MetricGraphNode,
    MetricGraphStore,
)
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


class SearchMetricsArgs(BaseModel):
    """Arguments for searching business metrics by natural language query.

    Metrics come in three kinds — atomic (原子指标: the smallest, un-splittable
    statistical unit with raw calculation logic), derived (派生指标: an atomic
    metric combined with one or more scope-filtering dimensions, e.g. time range,
    terminal type, region, channel), and composite (复合指标: derived metrics
    recombined via 环比/同比/差值/占比 for cross-period comparison).
    """

    query: str = Field(
        description="Keywords for vector search against metric names, business definitions, "
        "calculation logic, dimension names, and analysis fields. Extract the core numeric "
        "measure, its scope-filtering dimensions (时间区间/终端类型/地域/渠道等), and any "
        "cross-period comparison terms (环比/同比/差值/占比) from the user's question — do NOT "
        "pass the raw question verbatim. Think: what metric/dimension would a data steward "
        "have documented?"
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

def _format_atomic_metric_for_llm(atomic_metric, display_name: str | None = None) -> str:
    """Format a single atomic metric for LLM consumption."""
    lines = [f"# Metric: {display_name or atomic_metric.name}"]
    if atomic_metric.business_definition:
        lines.append(f"Business Definition: {atomic_metric.business_definition}")
    if atomic_metric.calculation_logic:
        lines.append(f"Calculation: {atomic_metric.calculation_logic}")
    if atomic_metric.data_source:
        lines.append(f"Data Source: {atomic_metric.data_source}")
    if atomic_metric.analysis_field:
        lines.append(f"Analysis Field: {atomic_metric.analysis_field}")
    return "\n".join(lines)


def _format_derived_metric_for_llm(derived_metric, display_name: str | None = None) -> str:
    """Format a single derived metric for LLM consumption."""
    lines = [f"# Dimension: {display_name or derived_metric.name}"]
    if derived_metric.business_definition:
        lines.append(f"Business Definition: {derived_metric.business_definition}")
    if derived_metric.data_source:
        lines.append(f"Data Source: {derived_metric.data_source}")
    if derived_metric.field_ref:
        lines.append(f"Analysis Field: {derived_metric.field_ref}")
    if derived_metric.value_range:
        lines.append(f"Value Range: {derived_metric.value_range}")
    if derived_metric.joins:
        join_strs = []
        for j in derived_metric.joins:
            src = j.source_column if j.source_column.startswith(j.source_table + ".") else f"{j.source_table}.{j.source_column}"
            tgt = j.target_column if j.target_column.startswith(j.target_table + ".") else f"{j.target_table}.{j.target_column}"
            join_strs.append(f"{src} = {tgt}")
        lines.append(f"Joins: {'; '.join(join_strs)}")
    return "\n".join(lines)


def _format_composite_metric_for_llm(composite_metric) -> str:
    """Format a single composite metric for LLM consumption."""
    lines = [f"# Composite Metric: {composite_metric.name}"]
    if composite_metric.business_definition:
        lines.append(f"Business Definition: {composite_metric.business_definition}")
    if composite_metric.comb_func:
        lines.append(f"Composition: {composite_metric.comb_func}")
    if composite_metric.operand_a:
        lines.append(f"Operand A: {composite_metric.operand_a}")
    if composite_metric.operand_b:
        lines.append(f"Operand B: {composite_metric.operand_b}")
    return "\n".join(lines)


def _format_atomic_metric_with_derived_metrics(
    atomic_metric, derived_metrics: List, display_name: str | None = None
) -> str:
    """Format an atomic metric with all its linked derived metrics."""
    lines = [f"# Metric: {display_name or atomic_metric.name}"]
    if atomic_metric.business_definition:
        lines.append(f"Business Definition: {atomic_metric.business_definition}")
    if atomic_metric.calculation_logic:
        lines.append(f"Calculation Logic: {atomic_metric.calculation_logic}")
    if atomic_metric.data_source:
        lines.append(f"Data Source: {atomic_metric.data_source}")
    if atomic_metric.analysis_field:
        lines.append(f"Analysis Field: {atomic_metric.analysis_field}")
    for derived_metric in derived_metrics:
        lines.append(f"##Dimension: {derived_metric.name}({derived_metric.field_ref})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph-subgraph -> LLM text (built directly from {nodes, edges}, no store look-up)
# ---------------------------------------------------------------------------


def _score_tag(score: float) -> str:
    """Similarity tag for a seed node's header line (empty for expanded nodes)."""
    return f" [similarity: {score:.4f}]" if score and score > 0 else ""


def _attr_line(props: Dict[str, Any], pairs: List[tuple[str, str]]) -> str:
    """Join non-empty ``{label}: {value}`` pairs into one comma-separated line."""
    parts = [f"{label}: {props[k]}" for label, k in pairs
             if props.get(k) not in (None, "", [])]
    return "，".join(parts)


def _format_atomic_inline(props: dict) -> str:
    """Compact atomic-metric attribute string for use inside a chain."""
    return _attr_line(
        props,
        [
            ("字段", "分析字段"),
            ("计算", "计算逻辑"),
            ("取值范围", "取值范围"),
            ("外键", "外键关系"),
        ],
    )


def _format_derived_inline(props: dict) -> str:
    """Compact derived-metric attribute string for use inside a chain."""
    return _attr_line(
        props,
        [
            ("维度", "维度字段"),
            ("取值范围", "取值范围"),
            ("外键", "外键关系"),
        ],
    )


def _format_graph_subgraph_for_llm(
    nodes: List[MetricGraphNode], edges: List[MetricGraphEdge]
) -> str:
    """Render a retrieved metric subgraph as relationship-chain text.

    Built purely from the ``MetricGraphSubgraph`` returned by the graph store —
    no relational-store look-up. Chains are expanded along USES
    (composite→derived) and DERIVED_FROM (derived→atomic):

        # 复合指标: A
          ├ 派生指标: B（维度: …，取值范围: …）
          │   └ 来自 原子指标: C（字段: …，计算: …，外键: …）

    Orphan derived / atomic nodes (not reached via a composite chain) are
    emitted as standalone blocks. Optional attributes appear only when set.
    """
    node_by_id: Dict[str, MetricGraphNode] = {n.entity_id: n for n in nodes}

    # Adjacency along the two relationship types.
    uses: Dict[str, List[str]] = {}      # composite_id -> [derived_id]
    derived_from: Dict[str, str] = {}    # derived_id -> atomic_id
    for e in edges:
        if not e.src_id or not e.tgt_id:
            continue
        if e.rel_type == REL_USES:
            uses.setdefault(e.src_id, []).append(e.tgt_id)
        elif e.rel_type == REL_DERIVED_FROM:
            derived_from.setdefault(e.src_id, e.tgt_id)

    visited: set[str] = set()
    blocks: List[str] = []

    def _node_props(nid: Optional[str]) -> Dict[str, Any]:
        node = node_by_id.get(nid or "")
        return node.properties if node else {}

    def _node_name(nid: Optional[str]) -> str:
        node = node_by_id.get(nid or "")
        return node.entity_name if node else ""

    def _atomic_child_line(atomic_id: str, connector: str) -> str:
        """One ``└ 来自 原子指标: …`` line hanging off a derived node."""
        line = f"{connector}来自 原子指标: {_node_name(atomic_id)}"
        inline = _format_atomic_inline(_node_props(atomic_id))
        if inline:
            line += f"（{inline}）"
        return line

    def _atomic_block(nid: str, indent: str = "") -> List[str]:
        node = node_by_id.get(nid)
        props = _node_props(nid)
        score = node.score if node else 0.0
        lines = [f"{indent}# 原子指标: {_node_name(nid)}{_score_tag(score)}"]
        desc = node.description if node else ""
        if desc:
            lines.append(f"{indent}业务描述: {desc}")
        # Emit each non-empty attribute on its own line for the standalone block.
        for label, key in [("计算逻辑", "计算逻辑"), ("数据来源", "数据表来源"),
                           ("分析字段", "分析字段"), ("取值范围", "取值范围"),
                           ("外键关系", "外键关系")]:
            if props.get(key) not in (None, "", []):
                lines.append(f"{indent}{label}: {props[key]}")
        return lines

    def _derived_chain(nid: str, prefix: str) -> List[str]:
        """Emit one derived node + the atomic it derives from."""
        inline = _format_derived_inline(_node_props(nid))
        head = f"{prefix}派生指标: {_node_name(nid)}"
        if inline:
            head += f"（{inline}）"
        lines = [head]
        atomic_id = derived_from.get(nid)
        if atomic_id and atomic_id in node_by_id:
            lines.append(_atomic_child_line(atomic_id, "  │   └ "))
            visited.add(atomic_id)
        return lines

    # 1) Composite chains first.
    for n in nodes:
        if n.entity_type != ENTITY_TYPE_COMPOSITE:
            continue
        if not n.entity_id or n.entity_id in visited:
            continue
        visited.add(n.entity_id)
        lines = [f"# 复合指标: {n.entity_name}{_score_tag(n.score)}"]
        if n.description:
            lines.append(f"业务描述: {n.description}")
        if n.properties.get("组合计算"):
            lines.append(f"组合计算: {n.properties['组合计算']}")
        for did in uses.get(n.entity_id, []):
            if did not in node_by_id:
                continue
            visited.add(did)
            lines.extend(_derived_chain(did, "  ├ "))
        blocks.append("\n".join(lines))

    # 2) Orphan derived nodes (not under any composite in this subgraph).
    for n in nodes:
        if n.entity_type != ENTITY_TYPE_DERIVED:
            continue
        if n.entity_id in visited:
            continue
        visited.add(n.entity_id)
        lines = [f"# 派生指标: {n.entity_name}{_score_tag(n.score)}"]
        if n.description:
            lines.append(f"业务描述: {n.description}")
        for label, key in [("维度字段", "维度字段"), ("数据来源", "数据表来源"),
                           ("取值范围", "取值范围"), ("外键关系", "外键关系")]:
            if n.properties.get(key) not in (None, "", []):
                lines.append(f"{label}: {n.properties[key]}")
        atomic_id = derived_from.get(n.entity_id)
        if atomic_id and atomic_id in node_by_id:
            lines.append(_atomic_child_line(atomic_id, "  └ "))
            visited.add(atomic_id)
        blocks.append("\n".join(lines))

    # 3) Orphan atomic nodes (not referenced by any derived in this subgraph).
    for n in nodes:
        if n.entity_type != ENTITY_TYPE_ATOMIC:
            continue
        if n.entity_id in visited:
            continue
        visited.add(n.entity_id)
        blocks.append("\n".join(_atomic_block(n.entity_id)))

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class SearchMetricsTool(Tool[SearchMetricsArgs]):
    """Search for business metrics, dimensions, and composite metrics.

    **This is the LLM's only entry point.** Internally:
    1. Graph retrieval (when a metric graph store is configured)
    2. Fallback: direct atomic-metric + derived-metric search
    3. Assemble structured results

    Returns metric definitions with their linked derived metrics and JOIN info.
    """

    def __init__(
        self,
        atomic_metric_store: AtomicMetricStore,
        derived_metric_store: Optional[DerivedMetricStore] = None,
        metric_graph_store: Optional[MetricGraphStore] = None,
        composite_metric_store: Optional[CompositeMetricStore] = None,
    ):
        self.atomic_metric_store = atomic_metric_store
        self.derived_metric_store = derived_metric_store
        self.metric_graph_store = metric_graph_store
        self.composite_metric_store = composite_metric_store

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

    async def _get_derived_metrics(self, atomic_metric_id: str, context: ToolContext) -> List:
        """Fetch derived metrics for an atomic metric, tolerating a missing store."""
        if self.derived_metric_store:
            try:
                return await self.derived_metric_store.get_derived_metrics_by_atomic_metric(
                    atomic_metric_id, context
                )
            except Exception:
                pass
        return []

    async def _search_via_graph(
        self, search_query: str, limit: int, context: ToolContext
    ) -> tuple[List[str], List[str], List[str], List[str]]:
        """Graph-first retrieval: fulltext seed -> 2-hop expand -> chain text.

        The LLM text is built directly from the returned ``MetricGraphSubgraph``
        (see :func:`_format_graph_subgraph_for_llm`) — no relational store
        look-up. Returns
        ``(result_parts, matched_atomic_metrics, matched_derived_metrics, matched_composite_metrics)``.
        """
        result_parts: List[str] = []
        matched_atomic_metrics: List[str] = []
        matched_derived_metrics: List[str] = []
        matched_composite_metrics: List[str] = []

        if self.metric_graph_store is None:
            return (
                result_parts,
                matched_atomic_metrics,
                matched_derived_metrics,
                matched_composite_metrics,
            )

        subgraph = await self.metric_graph_store.search(search_query, top_k=limit)
        if not subgraph.nodes:
            return (
                result_parts,
                matched_atomic_metrics,
                matched_derived_metrics,
                matched_composite_metrics,
            )

        for n in subgraph.nodes:
            if n.entity_type == ENTITY_TYPE_ATOMIC:
                matched_atomic_metrics.append(n.entity_name)
            elif n.entity_type == ENTITY_TYPE_DERIVED:
                matched_derived_metrics.append(n.entity_name)
            elif n.entity_type == ENTITY_TYPE_COMPOSITE:
                matched_composite_metrics.append(n.entity_name)

        text = _format_graph_subgraph_for_llm(subgraph.nodes, subgraph.edges)
        if text:
            result_parts.append(text)

        return (
            result_parts,
            matched_atomic_metrics,
            matched_derived_metrics,
            matched_composite_metrics,
        )

    async def execute(
        self, context: ToolContext, args: SearchMetricsArgs
    ) -> ToolResult:
        """Search metrics with graph-first retrieval + fallback."""
        try:
            result_parts: List[str] = []
            match_count = 0
            matched_atomic_metrics: List[str] = []
            matched_derived_metrics: List[str] = []
            matched_composite_metrics: List[str] = []

            search_query = args.query

            # --- Graph retrieval (primary when a metric graph store is configured) ---
            if self.metric_graph_store is not None:
                try:
                    (
                        g_parts,
                        g_atomic_metrics,
                        g_derived_metrics,
                        g_composite_metrics,
                    ) = await self._search_via_graph(
                        search_query, args.limit, context
                    )
                except Exception:
                    g_parts, g_atomic_metrics, g_derived_metrics, g_composite_metrics = [], [], [], []

                if g_parts:
                    result_text = "\n\n".join(g_parts)
                    return ToolResult(
                        success=True,
                        result_for_llm=result_text,
                        ui_component=UiComponent(
                            rich_component=CardComponent(
                                title=f"📊 Metric Search · {len(g_parts)} results (graph)",
                                content=result_text,
                                icon="🔍",
                                status="info",
                                collapsible=True,
                                collapsed=True,
                                markdown=True,
                            ),
                            simple_component=SimpleTextComponent(text=result_text),
                        ),
                        metadata={
                            "match_count": len(g_parts),
                            "query": search_query,
                            "matched_atomic_metrics": g_atomic_metrics,
                            "matched_derived_metrics": g_derived_metrics,
                            "matched_composite_metrics": g_composite_metrics,
                            "retrieval": "graph",
                        },
                    )

            # --- Step 1: Fallback — direct atomic-metric search ---
            if not result_parts:
                atomic_metric_results = await self.atomic_metric_store.search_atomic_metrics(
                    query=search_query,
                    context=context,
                    limit=args.limit,
                )

                for ar in atomic_metric_results:
                    atomic_metric = ar.atomic_metric
                    # Fetch linked derived metrics
                    derived_metrics = []
                    if self.derived_metric_store:
                        try:
                            derived_metrics = await self.derived_metric_store.get_derived_metrics_by_atomic_metric(
                                atomic_metric.id, context
                            )
                        except Exception:
                            pass

                    formatted = _format_atomic_metric_with_derived_metrics(
                        atomic_metric, derived_metrics
                    )
                    first_line, _, rest = formatted.partition("\n")
                    result_parts.append(f"{first_line} [similarity: {ar.similarity_score:.4f}]\n{rest}" if rest else f"{first_line} [similarity: {ar.similarity_score:.4f}]")
                    match_count += 1
                    matched_atomic_metrics.append(atomic_metric.name)

            # --- Step 2: Also search derived metrics directly as fallback ---
            if self.derived_metric_store and (not result_parts or len(result_parts) < args.limit):
                try:
                    derived_metric_results = await self.derived_metric_store.search_derived_metrics(
                        query=search_query,
                        context=context,
                        limit=max(2, args.limit - len(result_parts)),
                    )
                    for dr in derived_metric_results:
                        derived_metric = dr.derived_metric
                        formatted = _format_derived_metric_for_llm(derived_metric)
                        if formatted not in result_parts:
                            first_line, _, rest = formatted.partition("\n")
                            result_parts.append(f"{first_line} [similarity: {dr.similarity_score:.4f}]\n{rest}" if rest else f"{first_line} [similarity: {dr.similarity_score:.4f}]")
                            match_count += 1
                            matched_derived_metrics.append(derived_metric.name)
                except Exception:
                    pass

            # --- Step 3: Assemble results ---
            if not result_parts:
                no_result_msg = "No matching metrics or dimensions found."
                return ToolResult(
                    success=True,
                    result_for_llm=no_result_msg,
                    ui_component=UiComponent(
                        rich_component=RichTextComponent(content=no_result_msg),
                        simple_component=SimpleTextComponent(text=no_result_msg),
                    ),
                    metadata={
                        "match_count": 0,
                        "query": search_query,
                        "matched_atomic_metrics": [],
                        "matched_derived_metrics": [],
                    },
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
                metadata={
                    "match_count": match_count,
                    "query": search_query,
                    "matched_atomic_metrics": matched_atomic_metrics,
                    "matched_derived_metrics": matched_derived_metrics,
                    "matched_composite_metrics": matched_composite_metrics,
                },
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error searching metrics: {str(e)}",
                error=str(e),
            )


class GetMetricDetailTool(Tool[GetMetricDetailArgs]):
    """Retrieve the full definition of a specific metric including its derived metrics."""

    def __init__(
        self,
        atomic_metric_store: AtomicMetricStore,
        derived_metric_store: Optional[DerivedMetricStore] = None,
    ):
        self.atomic_metric_store = atomic_metric_store
        self.derived_metric_store = derived_metric_store

    @property
    def name(self) -> str:
        return "get_metric_detail"

    @property
    def description(self) -> str:
        return (
            "Get the complete definition of a specific metric by its ID. "
            "Returns the metric name, analysis field, derived metrics, FK JOINs, "
            "and the auto-generated SQL template. "
            "Use this when you need the full SQL logic for a metric."
        )

    def get_args_schema(self) -> Type[GetMetricDetailArgs]:
        return GetMetricDetailArgs

    async def execute(
        self, context: ToolContext, args: GetMetricDetailArgs
    ) -> ToolResult:
        """Retrieve and format a single metric's full definition with derived metrics."""
        try:
            atomic_metric = await self.atomic_metric_store.get_atomic_metric(
                args.metric_id, context
            )
            if atomic_metric is None:
                not_found_msg = f"Metric '{args.metric_id}' not found."
                return ToolResult(
                    success=False,
                    result_for_llm=not_found_msg,
                    error=not_found_msg,
                )

            # Fetch linked derived metrics
            derived_metrics = []
            if self.derived_metric_store:
                try:
                    derived_metrics = await self.derived_metric_store.get_derived_metrics_by_atomic_metric(
                        atomic_metric.id, context
                    )
                except Exception:
                    pass

            result_text = _format_atomic_metric_with_derived_metrics(
                atomic_metric, derived_metrics
            )

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=CardComponent(
                        title=f"Metric: {atomic_metric.name}",
                        content=result_text,
                        markdown=False,
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={"metric_id": atomic_metric.id},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error retrieving metric: {str(e)}",
                error=str(e),
            )


class ListMetricsTool(Tool[ListMetricsArgs]):
    """List all defined business metrics."""

    def __init__(self, atomic_metric_store: AtomicMetricStore):
        self.atomic_metric_store = atomic_metric_store

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
            atomic_metrics = await self.atomic_metric_store.list_atomic_metrics(context)

            if not atomic_metrics:
                no_metrics_msg = "No metrics have been defined yet."
                return ToolResult(
                    success=True,
                    result_for_llm=no_metrics_msg,
                    ui_component=UiComponent(
                        rich_component=RichTextComponent(content=no_metrics_msg),
                        simple_component=SimpleTextComponent(text=no_metrics_msg),
                    ),
                )

            summaries = [_format_atomic_metric_for_llm(m) for m in atomic_metrics]
            result_text = f"Found {len(atomic_metrics)} defined metrics:\n\n" + "\n\n".join(summaries)

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
                metadata={"total_metrics": len(atomic_metrics)},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error listing metrics: {str(e)}",
                error=str(e),
            )


class ExecuteMetricTool(Tool[ExecuteMetricArgs]):
    """Execute a metric against the database.

    Builds the final SQL from the metric's derived metrics and FK JOINs,
    then executes it and returns the results.
    """

    def __init__(
        self,
        atomic_metric_store: AtomicMetricStore,
        sql_runner: SqlRunner,
        derived_metric_store: Optional[DerivedMetricStore] = None,
    ):
        self.atomic_metric_store = atomic_metric_store
        self.sql_runner = sql_runner
        self.derived_metric_store = derived_metric_store

    @property
    def name(self) -> str:
        return "execute_metric"

    @property
    def description(self) -> str:
        return (
            "Execute a pre-defined business metric against the database. "
            "Builds the SQL query from the metric's derived metrics and JOINs, "
            "then runs it and returns the results. "
            "Use this after finding a relevant metric with search_metrics."
        )

    def get_args_schema(self) -> Type[ExecuteMetricArgs]:
        return ExecuteMetricArgs

    async def _get_derived_metrics(self, atomic_metric, context: ToolContext) -> List:
        """Fetch derived metrics for an atomic metric using the given context."""
        if self.derived_metric_store:
            try:
                return await self.derived_metric_store.get_derived_metrics_by_atomic_metric(
                    atomic_metric.id, context
                )
            except Exception:
                pass
        return []

    def _build_atomic_metric_sql(self, atomic_metric, derived_metrics: List) -> str:
        """Build a SQL query from the atomic metric and its derived metrics."""
        # Alias derived from metric name
        alias = atomic_metric.name.replace(" ", "_").lower()

        # SELECT: use calculation_logic if defined, else select field directly
        calc = atomic_metric.calculation_logic.strip() if atomic_metric.calculation_logic else None
        if calc:
            select_parts = [f"{calc}({atomic_metric.analysis_field}) AS {alias}"]
        else:
            select_parts = [f"{atomic_metric.analysis_field} AS {alias}"]

        for derived_metric in derived_metrics:
            if derived_metric.field_ref not in select_parts:
                select_parts.insert(0, derived_metric.field_ref)

        # FROM + JOINs
        from_clause = f"FROM {atomic_metric.data_source}"
        join_clauses = []
        seen_tables = {atomic_metric.data_source}
        for derived_metric in derived_metrics:
            for join in derived_metric.joins:
                if join.target_table not in seen_tables:
                    join_clauses.append(
                        f"{join.join_type} {join.target_table} "
                        f"ON {join.source_table}.{join.source_column} = "
                        f"{join.target_table}.{join.target_column}"
                    )
                    seen_tables.add(join.target_table)

        # GROUP BY: only needed when an aggregate function is present
        group_parts = []
        if calc and derived_metrics:
            group_parts = [derived_metric.field_ref for derived_metric in derived_metrics]

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
            atomic_metric = await self.atomic_metric_store.get_atomic_metric(
                args.metric_id, context
            )
            if atomic_metric is None:
                return ToolResult(
                    success=False,
                    result_for_llm=f"Metric '{args.metric_id}' not found.",
                    error=f"Metric '{args.metric_id}' not found.",
                )

            derived_metrics = await self._get_derived_metrics(atomic_metric, context)

            # Build and execute SQL
            sql = self._build_atomic_metric_sql(atomic_metric, derived_metrics)
            df: pd.DataFrame = await self.sql_runner.run_sql(
                RunSqlToolArgs(sql=sql), context
            )

            header = _format_atomic_metric_with_derived_metrics(
                atomic_metric, derived_metrics
            )

            if df.empty:
                return ToolResult(
                    success=True,
                    result_for_llm=f"{header}\n\nMetric '{atomic_metric.name}' executed. No rows returned.\nSQL: {sql}",
                    ui_component=UiComponent(
                        rich_component=DataFrameComponent(
                            rows=[], columns=[], title=f"Metric: {atomic_metric.name}",
                        ),
                        simple_component=SimpleTextComponent(
                            text=f"Metric '{atomic_metric.name}': No rows returned."
                        ),
                    ),
                )

            rows = df.to_dict("records")
            csv_preview = df.to_csv(index=False)
            if len(csv_preview) > 2000:
                csv_preview = csv_preview[:2000] + "\n...(truncated)"

            result_text = (
                f"{header}\n\n"
                f"Metric '{atomic_metric.name}' results ({len(df)} rows):\n\n"
                f"{csv_preview}\n\n"
                f"Generated SQL:\n{sql}"
            )

            return ToolResult(
                success=True,
                result_for_llm=result_text,
                ui_component=UiComponent(
                    rich_component=DataFrameComponent.from_records(
                        records=rows,
                        title=f"Metric: {atomic_metric.name}",
                        description=f"{len(df)} rows returned",
                    ),
                    simple_component=SimpleTextComponent(text=result_text),
                ),
                metadata={
                    "metric_id": atomic_metric.id,
                    "metric_name": atomic_metric.name,
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
