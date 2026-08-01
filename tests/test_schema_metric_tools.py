"""
Tests for schema and metric LLM tools.

Covers SearchTableSchemaTool, SearchMetricsTool, GetMetricDetailTool,
and ListMetricsTool with the new Metric model.
"""

import pytest
from easyq2sql.capabilities.metric_store import JoinClause, Metric
from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.core.tool import ToolContext
from easyq2sql.core.user import User
from easyq2sql.integrations.local.agent_memory import DemoAgentMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user():
    return User(
        id="test_user",
        username="test",
        email="test@example.com",
        group_memberships=["user"],
    )


def create_context(user):
    return ToolContext(
        user=user,
        conversation_id="tool_test",
        request_id="tool_test_req",
        agent_memory=DemoAgentMemory(max_items=10),
        metadata={},
    )


# ---------------------------------------------------------------------------
# In-memory MockMetricStore for testing
# ---------------------------------------------------------------------------


class MockMetricStore:
    """In-memory MetricStore for testing tools."""

    def __init__(self):
        self._metrics = {}

    def _add(self, metric):
        self._metrics[metric.id] = metric
        return metric

    async def create_metric(self, metric, context):
        return self._add(metric)

    async def get_metric(self, metric_id, context):
        return self._metrics.get(metric_id)

    async def update_metric(self, metric, context):
        if metric.id in self._metrics:
            self._metrics[metric.id] = metric
            return True
        return False

    async def delete_metric(self, metric_id, context):
        return self._metrics.pop(metric_id, None) is not None

    async def list_metrics(self, context):
        return list(self._metrics.values())

    async def search_metrics(self, query, context, *, limit=10):
        from easyq2sql.capabilities.metric_store import MetricSearchResult
        import re
        results = []
        # Extract meaningful tokens from structured or plain query
        tokens = re.findall(r"[\w一-鿿]+", query.lower())
        for m in self._metrics.values():
            name_lower = m.name.lower()
            biz_lower = (m.business_definition or "").lower()
            if any(t in name_lower or t in biz_lower for t in tokens):
                doc = f"Metric {m.name}: {m.data_source}.{m.analysis_field}"
                results.append(MetricSearchResult(
                    metric=m, similarity_score=0.9,
                    document_text=doc,
                ))
        return results[:limit]

    async def get_metrics_by_table(self, table_name, context):
        return [m for m in self._metrics.values() if m.data_source == table_name]


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_metrics():
    return [
        Metric(
            id="metric_sales",
            name="Total Sales",
            description="Sum of all order amounts",
            business_definition="Sum of all order amounts",
            calculation_logic="SUM",
            data_source="orders",
            analysis_field="orders.amount",
        ),
        Metric(
            id="metric_customers",
            name="Customer Count",
            description="Number of unique customers",
            business_definition="Number of unique customers",
            calculation_logic="COUNT_DISTINCT",
            data_source="orders",
            analysis_field="orders.customer_id",
        ),
    ]


@pytest.fixture
def metric_store(sample_metrics):
    store = MockMetricStore()
    for m in sample_metrics:
        store._add(m)
    return store


# ---------------------------------------------------------------------------
# SearchMetricsTool Tests
# ---------------------------------------------------------------------------


class TestSearchMetricsTool:
    """Tests for SearchMetricsTool (LLM's only metric entry point)."""

    @pytest.mark.asyncio
    async def test_search_finds_relevant_metrics(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import SearchMetricsTool

        tool = SearchMetricsTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()(
            metric="Total Sales",
            dimensions=[],
            limit=5,
        ))
        assert result.success is True
        assert "Total Sales" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_search_finds_with_dimensions(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import SearchMetricsTool

        tool = SearchMetricsTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()(
            metric="Total Sales",
            dimensions=[{"name": "region", "value": "East"}],
            limit=5,
        ))
        assert result.success is True
        assert "Total Sales" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_search_no_results(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import SearchMetricsTool

        tool = SearchMetricsTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()(
            metric="nonexistent_metric",
            dimensions=[],
            limit=5,
        ))
        assert result.success is True
        assert "No matching" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_search_returns_ui_component(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import SearchMetricsTool

        tool = SearchMetricsTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()(
            metric="Total Sales",
            dimensions=[],
            limit=5,
        ))
        assert result.ui_component is not None

    @pytest.mark.asyncio
    async def test_search_generates_tool_schema(self, metric_store):
        from easyq2sql.tools.metric_tools import SearchMetricsTool

        tool = SearchMetricsTool(metric_store=metric_store)
        schema = tool.get_schema()
        assert schema.name == "search_metrics"
        assert "metric" in schema.parameters.get("properties", {})
        assert "dimensions" in schema.parameters.get("properties", {})


# ---------------------------------------------------------------------------
# GetMetricDetailTool Tests
# ---------------------------------------------------------------------------


class TestGetMetricDetailTool:
    """Tests for GetMetricDetailTool."""

    @pytest.mark.asyncio
    async def test_get_existing_metric(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import GetMetricDetailTool

        tool = GetMetricDetailTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()(
            metric_id="metric_sales",
        ))
        assert result.success is True
        assert "Total Sales" in result.result_for_llm
        assert "SUM" in result.result_for_llm
        assert "orders.amount" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_get_nonexistent_metric(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import GetMetricDetailTool

        tool = GetMetricDetailTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()(
            metric_id="nonexistent",
        ))
        assert result.success is False
        assert "not found" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_detail_generates_tool_schema(self, metric_store):
        from easyq2sql.tools.metric_tools import GetMetricDetailTool

        tool = GetMetricDetailTool(metric_store=metric_store)
        schema = tool.get_schema()
        assert schema.name == "get_metric_detail"


# ---------------------------------------------------------------------------
# ListMetricsTool Tests
# ---------------------------------------------------------------------------


class TestListMetricsTool:
    """Tests for ListMetricsTool."""

    @pytest.mark.asyncio
    async def test_list_all_metrics(self, metric_store, test_user):
        from easyq2sql.tools.metric_tools import ListMetricsTool

        tool = ListMetricsTool(metric_store=metric_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()())
        assert result.success is True
        assert "Found 2" in result.result_for_llm
        assert "Total Sales" in result.result_for_llm
        assert "Customer Count" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_list_empty_store(self, test_user):
        from easyq2sql.tools.metric_tools import ListMetricsTool

        empty_store = MockMetricStore()
        tool = ListMetricsTool(metric_store=empty_store)
        context = create_context(test_user)

        result = await tool.execute(context, tool.get_args_schema()())
        assert result.success is True
        assert "No metrics" in result.result_for_llm


# ---------------------------------------------------------------------------
# ExecuteMetricTool Tests
# ---------------------------------------------------------------------------


class TestExecuteMetricTool:
    """Tests for ExecuteMetricTool SQL generation."""

    def test_build_metric_sql(self, sample_metrics):
        from easyq2sql.tools.metric_tools import ExecuteMetricTool

        tool = ExecuteMetricTool(
            metric_store=MockMetricStore(),
            sql_runner=None,  # Not needed for SQL generation test
        )

        metric = sample_metrics[0]
        sql = tool._build_metric_sql(metric, [])
        assert "COUNT" in sql
        assert metric.data_source in sql
        assert metric.analysis_field in sql

    def test_build_metric_sql_no_dimensions(self, sample_metrics):
        from easyq2sql.tools.metric_tools import ExecuteMetricTool

        tool = ExecuteMetricTool(
            metric_store=MockMetricStore(),
            sql_runner=None,
        )

        metric = sample_metrics[1]
        sql = tool._build_metric_sql(metric, [])
        assert "COUNT" in sql
        assert "FROM " + metric.data_source in sql
