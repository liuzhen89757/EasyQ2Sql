"""
Tests for SchemaMetricContextEnhancer.

Covers system prompt enhancement with schema and metric context,
fail-open behavior on errors, and empty/invalid input handling.
"""

import pytest
from easyq2sql.capabilities.atomic_metric import AtomicMetric
from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
from easyq2sql.core.user import User


# ---------------------------------------------------------------------------
# Minimal in-memory stores for enhancer testing
# ---------------------------------------------------------------------------


class MockSchemaStore:
    """SchemaStore that returns predefined results for testing."""

    def __init__(self, tables=None, should_fail=False):
        self.tables = tables or []
        self.should_fail = should_fail
        self.search_calls = []

    async def search_tables(self, query, context, *, limit=10, similarity_threshold=0.5):
        self.search_calls.append(query)
        if self.should_fail:
            raise RuntimeError("Simulated schema search failure")
        from easyq2sql.capabilities.schema_store import SchemaSearchResult
        return [
            SchemaSearchResult(
                table=t, similarity_score=0.85 - i * 0.1,
                document_text=f"# Table: {t.table_name}\n[{', '.join(f'{c.name}:{c.data_type}' for c in t.columns)}]",
            )
            for i, t in enumerate(self.tables[:limit])
        ]

    async def get_table_schema(self, table_name, context):
        for t in self.tables:
            if t.table_name == table_name:
                return t
        return None

    async def list_all_tables(self, context):
        return self.tables

    async def save_table_schema(self, table, context):
        pass

    async def update_table_description(self, table_name, description, context):
        return True

    async def update_column_description(self, table_name, column_name, description, context):
        return True

    async def delete_table_schema(self, table_name, context):
        return True

    async def sync_all_schemas(self, tables, context):
        return len(tables)


class MockAtomicMetricStore:
    """AtomicMetricStore that returns predefined results for testing."""

    def __init__(self, metrics=None, should_fail=False):
        self.metrics = metrics or []
        self.should_fail = should_fail
        self.search_calls = []

    async def search_atomic_metrics(self, query, context, *, limit=10):
        self.search_calls.append(query)
        if self.should_fail:
            raise RuntimeError("Simulated metric search failure")
        from easyq2sql.capabilities.atomic_metric import AtomicMetricSearchResult
        return [
            AtomicMetricSearchResult(atomic_metric=m, similarity_score=0.9 - i * 0.1)
            for i, m in enumerate(self.metrics[:limit])
        ]

    async def get_atomic_metric(self, metric_id, context):
        for m in self.metrics:
            if m.id == metric_id:
                return m
        return None

    async def create_atomic_metric(self, atomic_metric, context):
        return atomic_metric

    async def update_atomic_metric(self, atomic_metric, context):
        return True

    async def delete_atomic_metric(self, metric_id, context):
        return True

    async def list_atomic_metrics(self, context):
        return self.metrics

    async def get_atomic_metrics_by_table(self, table_name, context):
        return [m for m in self.metrics if m.data_source == table_name]


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


@pytest.fixture
def sample_tables():
    return [
        TableSchema(
            table_name="orders",
            description="Customer orders with amounts and dates",
            columns=[
                ColumnSchema(name="id", data_type="INTEGER", is_primary_key=True,
                             description="Primary key"),
                ColumnSchema(name="customer_id", data_type="INTEGER",
                             is_foreign_key=True,
                             fk_reference_table="customers",
                             fk_reference_column="id",
                             description="FK to customers"),
                ColumnSchema(name="amount", data_type="DECIMAL(10,2)",
                             description="Order total amount"),
                ColumnSchema(name="order_date", data_type="DATE",
                             description="Date of order"),
            ],
        ),
        TableSchema(
            table_name="customers",
            description="Customer account records",
            columns=[
                ColumnSchema(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnSchema(name="name", data_type="VARCHAR(100)"),
                ColumnSchema(name="region", data_type="VARCHAR(50)"),
            ],
        ),
    ]


@pytest.fixture
def sample_metrics():
    return [
        AtomicMetric(
            id="metric_sales",
            name="Total Sales",
            description="Sum of all order amounts",
            business_definition="Sum of all order amounts",
            calculation_logic="SUM",
            data_source="orders",
            analysis_field="orders.amount",
        ),
        AtomicMetric(
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
def enhancer(sample_tables, sample_metrics):
    """Create a SchemaMetricContextEnhancer with mock stores."""
    from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

    schema_store = MockSchemaStore(tables=sample_tables)
    metric_store = MockAtomicMetricStore(metrics=sample_metrics)
    return SchemaMetricContextEnhancer(
        schema_store=schema_store,
        atomic_metric_store=metric_store,
        max_schema_tables=3,
        max_metrics=3,
    )


# ---------------------------------------------------------------------------
# SchemaMetricContextEnhancer Tests
# ---------------------------------------------------------------------------


class TestSchemaMetricContextEnhancer:
    """Tests for the SchemaMetricContextEnhancer."""

    @pytest.mark.asyncio
    async def test_injects_schema_context(self, enhancer, test_user):
        """Test that relevant table schemas are injected into the system prompt."""
        base_prompt = "You are a helpful SQL assistant."
        user_message = "Show me the total sales by customer"

        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, user_message, test_user
        )

        assert base_prompt in enhanced
        assert "Available Database Schema" in enhanced
        assert "orders" in enhanced.lower()
        assert "customers" in enhanced.lower()
        assert "amount" in enhanced.lower()
        assert "DECIMAL" in enhanced

    @pytest.mark.asyncio
    async def test_injects_metric_context(self, enhancer, test_user):
        """Test that relevant metrics are injected into the system prompt."""
        base_prompt = "You are a helpful SQL assistant."
        user_message = "What is the total sales amount?"

        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, user_message, test_user
        )

        assert base_prompt in enhanced
        assert "Available Business Metrics" in enhanced
        assert "Total Sales" in enhanced
        assert "SUM" in enhanced

    @pytest.mark.asyncio
    async def test_includes_schema_pk_and_fk_info(self, enhancer, test_user):
        """Test that primary key and foreign key info is included."""
        base_prompt = "You are a SQL assistant."
        user_message = "Show orders with customer info"

        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, user_message, test_user
        )

        assert "PK" in enhanced
        assert "FK" in enhanced
        assert "customers" in enhanced.lower()

    @pytest.mark.asyncio
    async def test_includes_metric_calculation_logic(self, enhancer, test_user):
        """Test that metric calculation logic is included in the context."""
        base_prompt = "You are a SQL assistant."
        user_message = "total sales metric"

        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, user_message, test_user
        )

        assert "Total Sales" in enhanced
        assert "SUM" in enhanced
        assert "orders.amount" in enhanced

    @pytest.mark.asyncio
    async def test_includes_metric_usage_hints(self, enhancer, test_user):
        """Test that the enhancer tells the LLM how to use each metric."""
        base_prompt = "You are a SQL assistant."
        user_message = "customer count metric"

        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, user_message, test_user
        )

        assert "execute_metric" in enhanced.lower()
        assert "search_metrics" in enhanced.lower()

    @pytest.mark.asyncio
    async def test_empty_user_message_returns_original(self, enhancer, test_user):
        """Test that an empty user message returns the original prompt unchanged."""
        base_prompt = "You are a SQL assistant."

        enhanced = await enhancer.enhance_system_prompt(base_prompt, "", test_user)
        assert enhanced == base_prompt

        enhanced = await enhancer.enhance_system_prompt(base_prompt, "   ", test_user)
        assert enhanced == base_prompt

    @pytest.mark.asyncio
    async def test_fail_open_on_schema_error(self, test_user):
        """Test that schema search errors don't break the enhancer."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(should_fail=True)
        metric_store = MockAtomicMetricStore(metrics=[])
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store,
            atomic_metric_store=metric_store,
        )

        base_prompt = "You are a SQL assistant."
        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, "Show sales", test_user
        )

        # Should return original prompt unchanged on error
        assert enhanced == base_prompt

    @pytest.mark.asyncio
    async def test_fail_open_on_metric_error(self, test_user, sample_tables):
        """Test that metric search errors don't prevent schema injection."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(tables=sample_tables)
        metric_store = MockAtomicMetricStore(should_fail=True)
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store,
            atomic_metric_store=metric_store,
        )

        base_prompt = "You are a SQL assistant."
        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, "Show sales", test_user
        )

        # Schema context should still be present even though metrics failed
        assert base_prompt in enhanced
        assert "Available Database Schema" in enhanced
        assert "Available Business Metrics" not in enhanced

    @pytest.mark.asyncio
    async def test_no_stores_returns_original(self, test_user):
        """Test that enhancer with empty stores returns original prompt."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(tables=[])
        metric_store = MockAtomicMetricStore(metrics=[])
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store,
            atomic_metric_store=metric_store,
        )

        base_prompt = "You are a SQL assistant."
        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, "Show sales", test_user
        )

        # When no tables or metrics match, the prompt should be returned
        # with only the base (the enhancer only adds sections when results exist)
        assert base_prompt in enhanced

    @pytest.mark.asyncio
    async def test_enhance_user_messages_passthrough(self, enhancer, test_user):
        """Test that enhance_user_messages returns messages unchanged."""
        messages = ["msg1", "msg2"]
        result = await enhancer.enhance_user_messages(messages, test_user)
        assert result == messages

    @pytest.mark.asyncio
    async def test_search_uses_user_message_as_query(self, enhancer, test_user):
        """Test that the user's message is passed as the search query."""
        user_message = "Show me the quarterly sales breakdown by region"

        # Access the mock stores through the enhancer
        await enhancer.enhance_system_prompt(
            "Base prompt", user_message, test_user
        )

        # Verify both stores received the user message as search query
        assert len(enhancer.schema_store.search_calls) > 0
        assert enhancer.schema_store.search_calls[0] == user_message
        assert len(enhancer.atomic_metric_store.search_calls) > 0
        assert enhancer.atomic_metric_store.search_calls[0] == user_message

    @pytest.mark.asyncio
    async def test_combined_schema_and_metric_injection(self, enhancer, test_user):
        """Test that BOTH schema and metric sections appear when relevant."""
        base_prompt = "You are a SQL assistant."
        user_message = "Show total sales from orders"

        enhanced = await enhancer.enhance_system_prompt(
            base_prompt, user_message, test_user
        )

        assert "Available Database Schema" in enhanced
        assert "Available Business Metrics" in enhanced
        # Schema section should come before metrics
        schema_idx = enhanced.index("Available Database Schema")
        metric_idx = enhanced.index("Available Business Metrics")
        assert schema_idx < metric_idx


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------


class TestEnhancerEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self, test_user, sample_tables):
        """Test that special characters in user messages don't cause issues."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(tables=sample_tables)
        metric_store = MockAtomicMetricStore(metrics=[])
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store, atomic_metric_store=metric_store
        )

        # Messages with SQL-like syntax, quotes, etc.
        for msg in [
            "SELECT * FROM orders",
            "What's the average order value?",
            "Sales for Q4'2024",
            "Price > $100 and < $500",
        ]:
            enhanced = await enhancer.enhance_system_prompt(
                "Base", msg, test_user
            )
            assert isinstance(enhanced, str)
            assert "Base" in enhanced

    @pytest.mark.asyncio
    async def test_very_long_user_message(self, test_user, sample_tables):
        """Test with a very long user message."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(tables=sample_tables)
        metric_store = MockAtomicMetricStore(metrics=[])
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store, atomic_metric_store=metric_store
        )

        long_message = "sales " * 500  # very long message
        enhanced = await enhancer.enhance_system_prompt(
            "Base prompt", long_message, test_user
        )
        assert isinstance(enhanced, str)

    @pytest.mark.asyncio
    async def test_table_with_no_columns(self, test_user):
        """Test that tables with empty columns list don't cause crashes."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(tables=[
            TableSchema(table_name="empty_table", description="A table with no columns")
        ])
        metric_store = MockAtomicMetricStore(metrics=[])
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store, atomic_metric_store=metric_store
        )

        enhanced = await enhancer.enhance_system_prompt(
            "Base", "empty table", test_user
        )
        assert "empty_table" in enhanced.lower()

    @pytest.mark.asyncio
    async def test_table_with_null_description(self, test_user):
        """Test that tables with None descriptions render correctly."""
        from easyq2sql.core.enhancer.schema_metric_enhancer import SchemaMetricContextEnhancer

        schema_store = MockSchemaStore(tables=[
            TableSchema(
                table_name="no_desc_table",
                columns=[ColumnSchema(name="id", data_type="INTEGER")],
            )
        ])
        metric_store = MockAtomicMetricStore(metrics=[])
        enhancer = SchemaMetricContextEnhancer(
            schema_store=schema_store, atomic_metric_store=metric_store
        )

        enhanced = await enhancer.enhance_system_prompt(
            "Base", "no description table", test_user
        )
        assert "no_desc_table" in enhanced.lower()
