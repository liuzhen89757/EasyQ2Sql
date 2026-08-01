"""
Tests for MetricStore models and PostgresMetricStore.

Covers the new Metric, Dimension, and TerminologyEntry models,
plus PostgresMetricStore CRUD (when database is available).
ChromaDB tests are skipped pending ChromaMetricStore refactor.
"""

import pytest
from easyq2sql.capabilities.metric_store import (
    JoinClause,
    Metric,
    MetricSearchResult,
)


# ---------------------------------------------------------------------------
# Metric Model Unit Tests
# ---------------------------------------------------------------------------


class TestMetricModel:
    """Unit tests for the new Metric data model."""

    def test_metric_auto_generates_id(self):
        """Metric gets an auto-generated ID."""
        metric = Metric(
            name="Test",
            data_source="t",
            analysis_field="t.c",
        )
        assert metric.id is not None
        assert metric.id.startswith("metric_")

    def test_metric_default_values(self):
        """Metric default values."""
        metric = Metric(
            name="Test Metric",
            data_source="users",
            analysis_field="users.id",
        )
        assert metric.description is None
        assert metric.business_definition is None
        assert metric.calculation_logic is None
        assert metric.created_by is None

    def test_metric_all_fields(self):
        """Metric with all fields populated."""
        metric = Metric(
            name="Total Sales",
            business_definition="Sum of all order amounts",
            calculation_logic="SUM",
            data_source="orders",
            analysis_field="orders.amount",
            description="Revenue metric",
            created_by="admin",
        )
        assert metric.name == "Total Sales"
        assert metric.business_definition == "Sum of all order amounts"
        assert metric.calculation_logic == "SUM"
        assert metric.data_source == "orders"
        assert metric.analysis_field == "orders.amount"

    def test_metric_serialization_roundtrip(self):
        """Metric serializes and deserializes correctly."""
        metric = Metric(
            name="Test",
            business_definition="Count of payments",
            calculation_logic="COUNT",
            data_source="payments",
            analysis_field="payments.id",
        )
        data = metric.model_dump(mode="json")
        restored = Metric(**data)
        assert restored.name == "Test"
        assert restored.data_source == "payments"
        assert restored.analysis_field == "payments.id"
        assert restored.calculation_logic == "COUNT"

    def test_metric_json_serializable(self):
        """Metric can be serialized to JSON."""
        metric = Metric(
            name="Test",
            data_source="t",
            analysis_field="t.c",
        )
        json_str = metric.model_dump_json()
        assert "Test" in json_str


# ---------------------------------------------------------------------------
# JoinClause Unit Tests
# ---------------------------------------------------------------------------


class TestJoinClause:
    """Unit tests for JoinClause model."""

    def test_join_clause_defaults(self):
        """JoinClause default values."""
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
        """JoinClause with custom join type."""
        join = JoinClause(
            source_table="a",
            source_column="b_id",
            target_table="b",
            target_column="id",
            join_type="INNER JOIN",
        )
        assert join.join_type == "INNER JOIN"


# ---------------------------------------------------------------------------
# Dimension Model Tests
# ---------------------------------------------------------------------------


class TestDimensionModel:
    """Unit tests for Dimension model."""

    def test_dimension_auto_generates_id(self):
        from easyq2sql.capabilities.dimension_store.models import Dimension
        dim = Dimension(
            metric_id="m1",
            name="Time",
            data_source="dim_date",
            field_ref="dim_date.date",
        )
        assert dim.id is not None
        assert dim.id.startswith("dim_")

    def test_dimension_with_joins(self):
        from easyq2sql.capabilities.dimension_store.models import Dimension
        dim = Dimension(
            metric_id="m1",
            name="Region",
            data_source="dim_region",
            field_ref="dim_region.name",
            joins=[
                JoinClause(
                    source_table="orders",
                    source_column="region_id",
                    target_table="dim_region",
                    target_column="id",
                ),
            ],
        )
        assert len(dim.joins) == 1
        assert dim.joins[0].target_table == "dim_region"

    def test_dimension_hierarchy(self):
        from easyq2sql.capabilities.dimension_store.models import Dimension
        dim = Dimension(
            metric_id="m1",
            name="Month",
            data_source="dim_date",
            field_ref="dim_date.month",
            hierarchy="Year/Month",
            level=1,
            parent_id="dim_parent",
        )
        assert dim.level == 1
        assert dim.parent_id == "dim_parent"
        assert dim.hierarchy == "Year/Month"


# ---------------------------------------------------------------------------
# TerminologyEntry Model Tests
# ---------------------------------------------------------------------------


class TestTerminologyModel:
    """Unit tests for TerminologyEntry model."""

    def test_entry_auto_generates_id(self):
        from easyq2sql.capabilities.terminology_store.models import TerminologyEntry
        entry = TerminologyEntry(
            term_text="OEE",
            target_type="metric",
            target_id="m1",
        )
        assert entry.id is not None
        assert entry.id.startswith("term_")

    def test_entry_with_synonyms(self):
        from easyq2sql.capabilities.terminology_store.models import TerminologyEntry
        entry = TerminologyEntry(
            term_text="Revenue",
            target_type="metric",
            target_id="m2",
            synonyms=["Income", "Sales"],
            business_definition="Total revenue from all channels",
            source="manual",
        )
        assert "Income" in entry.synonyms
        assert entry.source == "manual"

    def test_entry_default_source(self):
        from easyq2sql.capabilities.terminology_store.models import TerminologyEntry
        entry = TerminologyEntry(
            term_text="Orders",
            target_type="metric",
            target_id="m1",
        )
        assert entry.source == "manual"


# ---------------------------------------------------------------------------
# PostgresMetricStore Tests (requires database)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires PostgreSQL database connection")
class TestPostgresMetricStore:
    """Integration tests for PostgresMetricStore."""

    @pytest.mark.asyncio
    async def test_create_and_get_metric(self):
        """Create a metric and retrieve it by ID."""
        from easyq2sql.integrations.postgres.metric_store import PostgresMetricStore
        from easyq2sql.core.tool import ToolContext
        from easyq2sql.core.user.models import User

        store = PostgresMetricStore(
            host="localhost",
            database="test_db",
            user="postgres",
            password="postgres",
            table_name="test_metrics",
        )
        user = User(id="test", group_memberships=["admin"])
        context = ToolContext(
            user=user,
            conversation_id="test",
            request_id="test",
            agent_memory=None,
        )

        metric = Metric(
            name="Test Metric",
            business_definition="A test metric",
            calculation_logic="COUNT",
            data_source="test_table",
            analysis_field="test_table.id",
        )

        created = await store.create_metric(metric, context)
        assert created.id is not None
        assert created.name == "Test Metric"

        retrieved = await store.get_metric(created.id, context)
        assert retrieved is not None
        assert retrieved.name == "Test Metric"
