"""
Tests for schema and metric LLM tools.

Covers SearchTableSchemaTool, SearchMetricsTool, GetMetricDetailTool,
ListMetricsTool, and ExecuteMetricTool.
"""

import pytest
from easyq2sql.capabilities.metric_store import (
    FunctionStep,
    JoinClause,
    Metric,
    MetricDimension,
)
from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.core.rich_component import ComponentType
from easyq2sql.core.tool import ToolContext
from easyq2sql.core.user import User
from easyq2sql.integrations.local.agent_memory import DemoAgentMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user():
    """Test user for context."""
    return User(
        id="test_user",
        username="test",
        email="test@example.com",
        group_memberships=["user"],
    )


def create_context(user):
    """Create a ToolContext for tool tests."""
    return ToolContext(
        user=user,
        conversation_id="tool_test",
        request_id="tool_test_req",
        agent_memory=DemoAgentMemory(max_items=10),
        metadata={},
    )


# ---------------------------------------------------------------------------
# In-memory SchemaStore for testing tools without ChromaDB
# ---------------------------------------------------------------------------


class InMemorySchemaStore:
    """Minimal in-memory SchemaStore for tool testing."""

    def __init__(self):
        self._tables: dict[str, TableSchema] = {}

    async def save_table_schema(self, table, context):
        self._tables[table.table_name] = table

    async def get_table_schema(self, table_name, context):
        return self._tables.get(table_name)

    async def search_tables(self, query, context, *, limit=10, similarity_threshold=0.5):
        results = []
        query_lower = query.lower()
        for name, table in self._tables.items():
            score = 0.0
            if name.lower() in query_lower:
                score = 0.8
            elif any(word in query_lower for word in name.lower().split("_")):
                score = 0.6
            elif table.description and any(
                word in query_lower
                for word in table.description.lower().split()
            ):
                score = 0.5
            if score >= similarity_threshold:
                from easyq2sql.capabilities.schema_store import SchemaSearchResult
                doc = f"# Table: {table.table_name}\n[{', '.join(f'{c.name}:{c.data_type}' for c in table.columns)}]"
                results.append(SchemaSearchResult(
                    table=table, similarity_score=score, document_text=doc,
                ))
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:limit]

    async def list_all_tables(self, context):
        return list(self._tables.values())

    async def update_table_description(self, table_name, description, context):
        if table_name in self._tables:
            self._tables[table_name].description = description
            return True
        return False

    async def update_column_description(self, table_name, column_name, description, context):
        if table_name in self._tables:
            for col in self._tables[table_name].columns:
                if col.name == column_name:
                    col.description = description
                    return True
        return False

    async def delete_table_schema(self, table_name, context):
        return self._tables.pop(table_name, None) is not None

    async def sync_all_schemas(self, tables, context):
        self._tables = {t.table_name: t for t in tables}
        return len(self._tables)


# ---------------------------------------------------------------------------
# In-memory MetricStore for testing tools without ChromaDB
# ---------------------------------------------------------------------------


class InMemoryMetricStore:
    """Minimal in-memory MetricStore for tool testing."""

    def __init__(self):
        self._metrics: dict[str, Metric] = {}

    async def create_metric(self, metric, context):
        self._metrics[metric.id] = metric
        return metric

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
        results = []
        query_lower = query.lower()
        for mid, metric in self._metrics.items():
            score = 0.0
            if metric.name.lower() in query_lower:
                score = 0.9
            elif any(w in query_lower for w in metric.name.lower().split()):
                score = 0.7
            elif metric.description and any(
                w in query_lower for w in metric.description.lower().split()
            ):
                score = 0.5
            if score > 0.0:
                doc = f"Metric {metric.name}: {metric.analysis_table}.{metric.analysis_field}"
                results.append(MetricSearchResult(
                    metric=metric, similarity_score=score, document_text=doc,
                ))
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:limit]

    async def get_metrics_by_table(self, table_name, context):
        return [m for m in self._metrics.values() if m.analysis_table == table_name]


# ---------------------------------------------------------------------------
# Fixtures for tools
# ---------------------------------------------------------------------------


@pytest.fixture
def schema_store_with_data():
    """In-memory schema store pre-populated with test tables."""
    store = InMemorySchemaStore()
    store._tables = {
        "orders": TableSchema(
            table_name="orders",
            description="Customer orders",
            columns=[
                ColumnSchema(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnSchema(name="customer_id", data_type="INTEGER",
                             is_foreign_key=True, fk_reference_table="customers",
                             fk_reference_column="id"),
                ColumnSchema(name="amount", data_type="DECIMAL(10,2)",
                             description="Order amount"),
                ColumnSchema(name="order_date", data_type="DATE"),
            ],
        ),
        "customers": TableSchema(
            table_name="customers",
            description="Customer accounts",
            columns=[
                ColumnSchema(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnSchema(name="name", data_type="VARCHAR(100)",
                             description="Full name"),
                ColumnSchema(name="region", data_type="VARCHAR(50)",
                             description="Geographic region"),
            ],
        ),
    }
    return store


@pytest.fixture
def metric_store_with_data():
    """In-memory metric store pre-populated with test metrics."""
    store = InMemoryMetricStore()
    store._metrics = {
        "metric_sales": Metric(
            id="metric_sales",
            name="Total Sales",
            description="Sum of all order amounts",
            analysis_table="orders",
            analysis_field="orders.amount",
            dimensions=[
                MetricDimension(name="Date", field_ref="orders.order_date"),
            ],
            function_steps=[
                FunctionStep(category="aggregate", function_name="SUM",
                             field_ref="orders.amount"),
            ],
        ),
        "metric_customers": Metric(
            id="metric_customers",
            name="Customer Count",
            analysis_table="orders",
            analysis_field="orders.customer_id",
            function_steps=[
                FunctionStep(category="aggregate", function_name="COUNT_DISTINCT",
                             field_ref="orders.customer_id"),
            ],
        ),
    }
    return store


@pytest.fixture
def search_schema_tool(schema_store_with_data):
    """Create a SearchTableSchemaTool with test data."""
    from easyq2sql.tools.schema_tools import SearchTableSchemaTool
    return SearchTableSchemaTool(schema_store=schema_store_with_data)


@pytest.fixture
def search_metrics_tool(metric_store_with_data):
    """Create a SearchMetricsTool with test data."""
    from easyq2sql.tools.metric_tools import SearchMetricsTool
    return SearchMetricsTool(metric_store=metric_store_with_data)


@pytest.fixture
def get_metric_tool(metric_store_with_data):
    """Create a GetMetricDetailTool with test data."""
    from easyq2sql.tools.metric_tools import GetMetricDetailTool
    return GetMetricDetailTool(metric_store=metric_store_with_data)


@pytest.fixture
def list_metrics_tool(metric_store_with_data):
    """Create a ListMetricsTool with test data."""
    from easyq2sql.tools.metric_tools import ListMetricsTool
    return ListMetricsTool(metric_store=metric_store_with_data)


# ---------------------------------------------------------------------------
# SearchTableSchemaTool Tests
# ---------------------------------------------------------------------------


class TestSearchTableSchemaTool:
    """Tests for the search_table_schema LLM tool."""

    @pytest.mark.asyncio
    async def test_search_finds_relevant_tables(self, search_schema_tool, test_user):
        """Test that the tool finds tables relevant to a query."""
        from easyq2sql.tools.schema_tools import SearchTableSchemaArgs

        context = create_context(test_user)
        args = SearchTableSchemaArgs(
            query="customer information and accounts",
            limit=5,
            threshold=0.3,
        )
        result = await search_schema_tool.execute(context, args)

        assert result.success is True
        assert "customers" in result.result_for_llm.lower()
        assert result.metadata["match_count"] >= 1

    @pytest.mark.asyncio
    async def test_search_with_high_threshold_returns_empty(self, search_schema_tool, test_user):
        """Test that a high similarity threshold filters out all results."""
        from easyq2sql.tools.schema_tools import SearchTableSchemaArgs

        context = create_context(test_user)
        args = SearchTableSchemaArgs(
            query="completely unrelated query about spacecraft",
            limit=5,
            threshold=0.99,
        )
        result = await search_schema_tool.execute(context, args)

        assert result.success is True
        assert "no matching tables" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_search_returns_ui_component(self, search_schema_tool, test_user):
        """Test that the tool returns a UI component."""
        from easyq2sql.tools.schema_tools import SearchTableSchemaArgs

        context = create_context(test_user)
        args = SearchTableSchemaArgs(query="orders", limit=5)
        result = await search_schema_tool.execute(context, args)

        assert result.ui_component is not None
        assert result.ui_component.rich_component is not None
        assert result.ui_component.rich_component.type == ComponentType.CARD

    @pytest.mark.asyncio
    async def test_search_includes_column_details(self, search_schema_tool, test_user):
        """Test that results include column names, types, and constraints."""
        from easyq2sql.tools.schema_tools import SearchTableSchemaArgs

        context = create_context(test_user)
        args = SearchTableSchemaArgs(query="orders amount", limit=5)
        result = await search_schema_tool.execute(context, args)

        llm_text = result.result_for_llm.lower()
        assert "orders" in llm_text
        assert "amount" in llm_text
        assert "decimal" in llm_text


# ---------------------------------------------------------------------------
# SearchMetricsTool Tests
# ---------------------------------------------------------------------------


class TestSearchMetricsTool:
    """Tests for the search_metrics LLM tool."""

    @pytest.mark.asyncio
    async def test_search_finds_by_name(self, search_metrics_tool, test_user):
        """Test searching metrics by name."""
        from easyq2sql.tools.metric_tools import SearchMetricsArgs

        context = create_context(test_user)
        args = SearchMetricsArgs(query="total sales", limit=5)
        result = await search_metrics_tool.execute(context, args)

        assert result.success is True
        assert "Total Sales" in result.result_for_llm
        assert result.metadata["match_count"] >= 1

    @pytest.mark.asyncio
    async def test_search_no_results(self, search_metrics_tool, test_user):
        """Test that an unrelated query returns no results."""
        from easyq2sql.tools.metric_tools import SearchMetricsArgs

        context = create_context(test_user)
        args = SearchMetricsArgs(query="spacecraft trajectory calculation", limit=5)
        result = await search_metrics_tool.execute(context, args)

        assert result.success is True
        assert "no matching metrics" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_search_returns_ui_component(self, search_metrics_tool, test_user):
        """Test that search returns a card UI component."""
        from easyq2sql.tools.metric_tools import SearchMetricsArgs

        context = create_context(test_user)
        args = SearchMetricsArgs(query="customer", limit=5)
        result = await search_metrics_tool.execute(context, args)

        assert result.ui_component is not None
        assert result.ui_component.rich_component.type == ComponentType.CARD


# ---------------------------------------------------------------------------
# GetMetricDetailTool Tests
# ---------------------------------------------------------------------------


class TestGetMetricDetailTool:
    """Tests for the get_metric_detail LLM tool."""

    @pytest.mark.asyncio
    async def test_get_existing_metric(self, get_metric_tool, test_user):
        """Test retrieving an existing metric by ID."""
        from easyq2sql.tools.metric_tools import GetMetricDetailArgs

        context = create_context(test_user)
        args = GetMetricDetailArgs(metric_id="metric_sales")
        result = await get_metric_tool.execute(context, args)

        assert result.success is True
        assert "Total Sales" in result.result_for_llm
        assert "orders.amount" in result.result_for_llm
        assert "SUM" in result.result_for_llm
        assert "Date" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_get_nonexistent_metric(self, get_metric_tool, test_user):
        """Test retrieving a nonexistent metric returns failure."""
        from easyq2sql.tools.metric_tools import GetMetricDetailArgs

        context = create_context(test_user)
        args = GetMetricDetailArgs(metric_id="nonexistent_id")
        result = await get_metric_tool.execute(context, args)

        assert result.success is False
        assert "not found" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_detail_includes_function_steps(self, get_metric_tool, test_user):
        """Test that metric detail includes function steps with categories."""
        from easyq2sql.tools.metric_tools import GetMetricDetailArgs

        context = create_context(test_user)
        args = GetMetricDetailArgs(metric_id="metric_sales")
        result = await get_metric_tool.execute(context, args)

        assert "Function Steps" in result.result_for_llm
        assert "aggregate" in result.result_for_llm.lower()


# ---------------------------------------------------------------------------
# ListMetricsTool Tests
# ---------------------------------------------------------------------------


class TestListMetricsTool:
    """Tests for the list_metrics LLM tool."""

    @pytest.mark.asyncio
    async def test_list_all_metrics(self, list_metrics_tool, test_user):
        """Test listing all defined metrics."""
        from easyq2sql.tools.metric_tools import ListMetricsArgs

        context = create_context(test_user)
        args = ListMetricsArgs()
        result = await list_metrics_tool.execute(context, args)

        assert result.success is True
        assert "Total Sales" in result.result_for_llm
        assert "Customer Count" in result.result_for_llm
        assert result.metadata["total_metrics"] == 2

    @pytest.mark.asyncio
    async def test_list_empty_metrics(self, test_user):
        """Test listing metrics when none are defined."""
        from easyq2sql.tools.metric_tools import ListMetricsTool, ListMetricsArgs

        store = InMemoryMetricStore()
        tool = ListMetricsTool(metric_store=store)

        context = create_context(test_user)
        args = ListMetricsArgs()
        result = await tool.execute(context, args)

        assert result.success is True
        assert "no metrics" in result.result_for_llm.lower()


# ---------------------------------------------------------------------------
# ExecuteMetricTool Tests
# ---------------------------------------------------------------------------


class TestExecuteMetricTool:
    """Tests for the execute_metric LLM tool."""

    @pytest.mark.asyncio
    async def test_build_metric_sql_from_function_steps(self, test_user):
        """Test that SQL is correctly built from metric function steps."""
        from easyq2sql.tools.metric_tools import ExecuteMetricTool

        store = InMemoryMetricStore()
        metric = Metric(
            id="test_metric",
            name="Revenue",
            analysis_table="orders",
            analysis_field="orders.amount",
            dimensions=[
                MetricDimension(
                    name="Date", field_ref="orders.date",
                    joins=[
                        JoinClause(
                            source_table="orders",
                            source_column="cust_id",
                            target_table="customers",
                            target_column="id",
                        ),
                    ],
                ),
            ],
            function_steps=[
                FunctionStep(category="aggregate", function_name="SUM",
                             field_ref="orders.amount", alias="total_revenue"),
                FunctionStep(category="aggregate", function_name="COUNT",
                             field_ref="orders.id", alias="order_count"),
            ],
        )
        store._metrics["test_metric"] = metric

        tool = ExecuteMetricTool(metric_store=store, sql_runner=None)
        sql = tool._build_metric_sql(metric)

        assert "SELECT" in sql
        assert "SUM(orders.amount) AS total_revenue" in sql
        assert "COUNT(orders.id) AS order_count" in sql
        assert "FROM orders" in sql
        assert "LEFT JOIN customers" in sql
        assert "orders.cust_id = customers.id" in sql
        assert "GROUP BY orders.date" in sql

    @pytest.mark.asyncio
    async def test_build_sql_no_joins_no_dimensions(self, test_user):
        """Test building SQL for a simple metric with no joins or dimensions."""
        from easyq2sql.tools.metric_tools import ExecuteMetricTool

        store = InMemoryMetricStore()
        metric = Metric(
            id="simple",
            name="Simple Count",
            analysis_table="users",
            analysis_field="users.id",
            function_steps=[
                FunctionStep(category="aggregate", function_name="COUNT",
                             field_ref="users.id"),
            ],
        )
        store._metrics["simple"] = metric

        tool = ExecuteMetricTool(metric_store=store, sql_runner=None)
        sql = tool._build_metric_sql(metric)

        assert "SELECT" in sql
        assert "COUNT(users.id)" in sql
        assert "FROM users" in sql
        assert "LEFT JOIN" not in sql
        assert "GROUP BY" not in sql

    @pytest.mark.asyncio
    async def test_execute_nonexistent_metric(self, test_user):
        """Test executing a nonexistent metric returns failure."""
        from easyq2sql.tools.metric_tools import ExecuteMetricTool, ExecuteMetricArgs

        store = InMemoryMetricStore()
        tool = ExecuteMetricTool(metric_store=store, sql_runner=None)

        context = create_context(test_user)
        args = ExecuteMetricArgs(metric_id="nonexistent")
        result = await tool.execute(context, args)

        assert result.success is False
        assert "not found" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_execute_metric_with_sql_runner(self, test_user):
        """Test executing a metric with a real SQLite runner."""
        from easyq2sql.tools.metric_tools import ExecuteMetricTool, ExecuteMetricArgs
        from easyq2sql.integrations.sqlite import SqliteRunner
        import sqlite3
        import os
        import tempfile

        # Create temp database with test data
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = tmp.name
        tmp.close()

        conn = sqlite3.connect(tmp_path)
        conn.executescript("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                amount DECIMAL(10,2) NOT NULL,
                order_date DATE
            );
            INSERT INTO orders VALUES (1, 100.00, '2024-01-15');
            INSERT INTO orders VALUES (2, 200.00, '2024-01-20');
            INSERT INTO orders VALUES (3, 150.00, '2024-02-01');
        """)
        conn.close()

        try:
            runner = SqliteRunner(database_path=tmp_path)

            store = InMemoryMetricStore()
            metric = Metric(
                id="test_exec",
                name="Total Orders",
                analysis_table="orders",
                analysis_field="orders.amount",
                function_steps=[
                    FunctionStep(category="aggregate", function_name="SUM",
                                 field_ref="orders.amount", alias="total"),
                    FunctionStep(category="aggregate", function_name="COUNT",
                                 field_ref="orders.id", alias="cnt"),
                ],
            )
            store._metrics["test_exec"] = metric

            tool = ExecuteMetricTool(metric_store=store, sql_runner=runner)
            context = create_context(test_user)
            args = ExecuteMetricArgs(metric_id="test_exec")
            result = await tool.execute(context, args)

            assert result.success is True
            assert "Total Orders" in result.result_for_llm
            assert result.metadata["row_count"] == 1
        finally:
            os.unlink(tmp_path)
