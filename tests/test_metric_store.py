"""
Tests for MetricStore implementations.

Covers ChromaMetricStore CRUD, search, table-based filtering,
auto-suggestion logic, and Metric data model serialization.
"""

import shutil
import tempfile

import pytest
from easyq2sql.capabilities.metric_store import (
    FUNCTION_CATALOG,
    FunctionCategory,
    FunctionStep,
    JoinClause,
    Metric,
    MetricDimension,
)
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


def create_test_context(user, agent_memory=None):
    """Helper to create a ToolContext for metric tests."""
    return ToolContext(
        user=user,
        conversation_id="metric_test",
        request_id="metric_test_req",
        agent_memory=agent_memory or DemoAgentMemory(max_items=100),
        metadata={},
    )


@pytest.fixture
def sample_metric():
    """Create a sample Metric for testing."""
    return Metric(
        name="Total Sales",
        description="Sum of all order amounts",
        analysis_table="orders",
        analysis_field="orders.amount",
        dimensions=[
            MetricDimension(
                name="Order Date",
                field_ref="orders.order_date",
                joins=[
                    JoinClause(
                        source_table="orders",
                        source_column="customer_id",
                        target_table="customers",
                        target_column="id",
                    ),
                ],
            ),
        ],
        function_steps=[
            FunctionStep(
                category="aggregate",
                function_name="SUM",
                field_ref="orders.amount",
                alias="total_sales",
            ),
        ],
    )


@pytest.fixture
def sample_metrics():
    """Create multiple sample metrics."""
    return [
        Metric(
            name="Total Sales",
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
        Metric(
            name="Customer Count",
            description="Number of unique customers",
            analysis_table="orders",
            analysis_field="orders.customer_id",
            function_steps=[
                FunctionStep(category="aggregate", function_name="COUNT_DISTINCT",
                             field_ref="orders.customer_id"),
            ],
        ),
        Metric(
            name="Product Revenue",
            analysis_table="products",
            analysis_field="products.price",
            dimensions=[
                MetricDimension(name="Product", field_ref="products.name"),
            ],
            function_steps=[
                FunctionStep(category="aggregate", function_name="SUM",
                             field_ref="products.price"),
            ],
        ),
    ]


@pytest.fixture
def chroma_metric_store():
    """Create a ChromaMetricStore backed by temp directories."""
    try:
        from easyq2sql.integrations.chromadb.metric_store import ChromaMetricStore

        temp_dir = tempfile.mkdtemp()
        store = ChromaMetricStore(
            persist_directory=temp_dir,
            collection_name="test_metric_store",
        )
        yield store
        shutil.rmtree(temp_dir, ignore_errors=True)
    except ImportError:
        pytest.skip("ChromaDB not installed")


# ---------------------------------------------------------------------------
# ChromaMetricStore Tests
# ---------------------------------------------------------------------------


class TestChromaMetricStore:
    """Tests for ChromaMetricStore CRUD and search."""

    @pytest.mark.asyncio
    async def test_create_and_get_metric(self, chroma_metric_store, test_user, sample_metric):
        """Test creating a metric and retrieving it by ID."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        created = await store.create_metric(sample_metric, context)
        assert created.id is not None
        assert created.name == "Total Sales"

        retrieved = await store.get_metric(created.id, context)
        assert retrieved is not None
        assert retrieved.name == "Total Sales"
        assert retrieved.analysis_table == "orders"
        assert retrieved.analysis_field == "orders.amount"
        assert len(retrieved.function_steps) == 1
        assert retrieved.function_steps[0].function_name == "SUM"
        assert len(retrieved.dimensions) == 1
        assert retrieved.dimensions[0].name == "Order Date"
        assert len(retrieved.dimensions[0].joins) == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_metric(self, chroma_metric_store, test_user):
        """Test getting a nonexistent metric returns None."""
        context = create_test_context(test_user)
        result = await chroma_metric_store.get_metric("nonexistent_id", context)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_metrics(self, chroma_metric_store, test_user, sample_metrics):
        """Test listing all metrics."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        for metric in sample_metrics:
            await store.create_metric(metric, context)

        all_metrics = await store.list_metrics(context)
        assert len(all_metrics) == 3
        names = {m.name for m in all_metrics}
        assert names == {"Total Sales", "Customer Count", "Product Revenue"}

    @pytest.mark.asyncio
    async def test_update_metric(self, chroma_metric_store, test_user, sample_metric):
        """Test updating an existing metric."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        created = await store.create_metric(sample_metric, context)

        created.name = "Total Sales Updated"
        created.description = "Updated description"
        success = await store.update_metric(created, context)
        assert success is True

        updated = await store.get_metric(created.id, context)
        assert updated.name == "Total Sales Updated"
        assert updated.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_nonexistent_metric(self, chroma_metric_store, test_user):
        """Test updating a nonexistent metric returns False."""
        context = create_test_context(test_user)
        fake_metric = Metric(
            id="fake_id_123",
            name="Fake",
            analysis_table="t",
            analysis_field="t.c",
        )
        success = await chroma_metric_store.update_metric(fake_metric, context)
        assert success is False

    @pytest.mark.asyncio
    async def test_delete_metric(self, chroma_metric_store, test_user, sample_metric):
        """Test deleting a metric."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        created = await store.create_metric(sample_metric, context)
        assert await store.get_metric(created.id, context) is not None

        deleted = await store.delete_metric(created.id, context)
        assert deleted is True
        assert await store.get_metric(created.id, context) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_metric(self, chroma_metric_store, test_user):
        """Test deleting a nonexistent metric returns False."""
        context = create_test_context(test_user)
        deleted = await chroma_metric_store.delete_metric("fake_id", context)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_search_metrics_by_name(self, chroma_metric_store, test_user, sample_metrics):
        """Test semantic search by metric name."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        for metric in sample_metrics:
            await store.create_metric(metric, context)

        results = await store.search_metrics(
            query="sales total amount",
            context=context,
            limit=5,
        )
        assert len(results) >= 1
        assert results[0].metric.name == "Total Sales"

    @pytest.mark.asyncio
    async def test_search_metrics_by_description(self, chroma_metric_store, test_user, sample_metrics):
        """Test that metric descriptions contribute to search."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        for metric in sample_metrics:
            await store.create_metric(metric, context)

        # "Customer Count" has description "Number of unique customers"
        results = await store.search_metrics(
            query="unique customer counting",
            context=context,
            limit=5,
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_get_metrics_by_table(self, chroma_metric_store, test_user, sample_metrics):
        """Test filtering metrics by analysis table."""
        context = create_test_context(test_user)
        store = chroma_metric_store

        for metric in sample_metrics:
            await store.create_metric(metric, context)

        orders_metrics = await store.get_metrics_by_table("orders", context)
        assert len(orders_metrics) == 2
        assert all(m.analysis_table == "orders" for m in orders_metrics)

        products_metrics = await store.get_metrics_by_table("products", context)
        assert len(products_metrics) == 1
        assert products_metrics[0].name == "Product Revenue"

        # Table with no metrics
        empty = await store.get_metrics_by_table("nonexistent", context)
        assert len(empty) == 0

    @pytest.mark.asyncio
    async def test_metric_persistence_across_restarts(self, sample_metric, test_user):
        """Test that metrics survive store re-creation (JSON file persistence)."""
        try:
            from easyq2sql.integrations.chromadb.metric_store import ChromaMetricStore

            temp_dir = tempfile.mkdtemp()
            context = create_test_context(test_user)

            # Create and populate store
            store1 = ChromaMetricStore(
                persist_directory=temp_dir,
                collection_name="test_persist",
            )
            created = await store1.create_metric(sample_metric, context)
            metric_id = created.id

            # Create a new store instance pointing at the same directory
            store2 = ChromaMetricStore(
                persist_directory=temp_dir,
                collection_name="test_persist",
            )
            retrieved = await store2.get_metric(metric_id, context)
            assert retrieved is not None
            assert retrieved.name == "Total Sales"

            shutil.rmtree(temp_dir, ignore_errors=True)
        except ImportError:
            pytest.skip("ChromaDB not installed")


# ---------------------------------------------------------------------------
# Metric Data Model Unit Tests
# ---------------------------------------------------------------------------


class TestMetricModel:
    """Unit tests for Metric data model."""

    def test_metric_auto_generates_id(self):
        """Test that a Metric gets an auto-generated ID."""
        metric = Metric(
            name="Test",
            analysis_table="t",
            analysis_field="t.c",
        )
        assert metric.id is not None
        assert metric.id.startswith("metric_")

    def test_metric_default_values(self):
        """Test Metric default values."""
        metric = Metric(
            name="Test Metric",
            analysis_table="users",
            analysis_field="users.id",
        )
        assert metric.description is None
        assert metric.dimensions == []
        assert metric.dimensions == []
        assert metric.function_steps == []
        assert metric.generated_sql_template is None
        assert metric.created_by is None

    def test_metric_serialization_roundtrip(self):
        """Test that Metric serializes and deserializes correctly."""
        metric = Metric(
            name="Test",
            analysis_table="orders",
            analysis_field="orders.amount",
            dimensions=[
                MetricDimension(
                    name="Date",
                    field_ref="orders.date",
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
                FunctionStep(
                    category="aggregate",
                    function_name="SUM",
                    field_ref="orders.amount",
                    alias="total",
                ),
            ],
        )
        data = metric.model_dump(mode="json")
        restored = Metric(**data)
        assert restored.name == "Test"
        assert restored.analysis_field == "orders.amount"
        assert len(restored.dimensions) == 1
        assert restored.dimensions[0].field_ref == "orders.date"
        assert len(restored.dimensions[0].joins) == 1
        assert restored.dimensions[0].joins[0].join_type == "LEFT JOIN"
        assert len(restored.function_steps) == 1
        assert restored.function_steps[0].function_name == "SUM"

    def test_metric_json_serializable(self):
        """Test that Metric can be serialized to JSON."""
        metric = Metric(
            name="Test",
            analysis_table="t",
            analysis_field="t.c",
            function_steps=[
                FunctionStep(
                    category="aggregate",
                    function_name="COUNT",
                    field_ref="t.c",
                ),
            ],
        )
        json_str = metric.model_dump_json()
        assert "Test" in json_str
        assert "COUNT" in json_str


class TestFunctionStep:
    """Unit tests for FunctionStep model."""

    def test_function_step_defaults(self):
        """Test FunctionStep default values."""
        step = FunctionStep(
            category="aggregate",
            function_name="COUNT",
        )
        assert step.category == "aggregate"
        assert step.function_name == "COUNT"
        assert step.field_ref is None
        assert step.params == {}
        assert step.alias is None

    def test_function_step_with_alias(self):
        """Test FunctionStep with an output alias."""
        step = FunctionStep(
            category="aggregate",
            function_name="SUM",
            field_ref="orders.amount",
            alias="total_revenue",
        )
        assert step.alias == "total_revenue"


class TestFunctionCatalog:
    """Tests for the FUNCTION_CATALOG."""

    def test_all_categories_have_functions(self):
        """Test that every FunctionCategory has at least one function."""
        for category in FunctionCategory:
            assert category.value in FUNCTION_CATALOG
            assert len(FUNCTION_CATALOG[category.value]) > 0

    def test_aggregate_functions(self):
        """Test aggregate function list."""
        agg = FUNCTION_CATALOG[FunctionCategory.AGGREGATE]
        assert "COUNT" in agg
        assert "SUM" in agg
        assert "AVG" in agg
        assert "COUNT_DISTINCT" in agg
        assert "MAX" in agg
        assert "MIN" in agg
        assert "VARIANCE" in agg

    def test_window_functions(self):
        """Test window function list."""
        win = FUNCTION_CATALOG[FunctionCategory.WINDOW]
        assert "RANK" in win
        assert "RANK_DENSE" in win
        assert "ROW_NUMBER" in win
        assert "LEAD" in win
        assert "LAG" in win

    def test_date_functions(self):
        """Test date function list."""
        date_fns = FUNCTION_CATALOG[FunctionCategory.DATE]
        assert "DATE_ADD" in date_fns
        assert "DATE_DIFF" in date_fns
        assert "DATE_TRUNC" in date_fns

    def test_analysis_functions(self):
        """Test analysis function list (from PRD)."""
        analysis = FUNCTION_CATALOG[FunctionCategory.ANALYSIS]
        assert "SAME_PERIOD" in analysis
        assert "PREVIOUS_PERIOD" in analysis
        assert "SUB_TOTAL" in analysis
        assert "SUB_WINDOW" in analysis


class TestJoinClause:
    """Unit tests for JoinClause model."""

    def test_join_clause_defaults(self):
        """Test JoinClause default values."""
        join = JoinClause(
            source_table="orders",
            source_column="customer_id",
            target_table="customers",
            target_column="id",
        )
        assert join.join_type == "LEFT JOIN"
        assert join.source_table == "orders"
        assert join.target_table == "customers"

    def test_join_clause_custom_type(self):
        """Test JoinClause with custom join type."""
        join = JoinClause(
            source_table="a",
            source_column="b_id",
            target_table="b",
            target_column="id",
            join_type="INNER JOIN",
        )
        assert join.join_type == "INNER JOIN"


class TestMetricDimension:
    """Unit tests for MetricDimension model."""

    def test_metric_dimension(self):
        """Test MetricDimension fields."""
        dim = MetricDimension(
            name="Province",
            field_ref="address.province",
        )
        assert dim.name == "Province"
        assert dim.field_ref == "address.province"
