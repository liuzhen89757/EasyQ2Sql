"""
Tests for AtomicMetricStore models and PostgresAtomicMetricStore.

Covers the new AtomicMetric and DerivedMetric models,
plus PostgresAtomicMetricStore CRUD (when database is available).
ChromaDB tests are skipped pending ChromaAtomicMetricStore refactor.
"""

import pytest
from easyq2sql.capabilities.atomic_metric import (
    JoinClause,
    AtomicMetric,
)


# ---------------------------------------------------------------------------
# AtomicMetric Model Unit Tests
# ---------------------------------------------------------------------------


class TestAtomicMetricModel:
    """Unit tests for the new AtomicMetric data model."""

    def test_metric_auto_generates_id(self):
        """AtomicMetric gets an auto-generated ID."""
        atomic_metric = AtomicMetric(
            name="Test",
            data_source="t",
            analysis_field="t.c",
        )
        assert atomic_metric.id is not None
        assert atomic_metric.id.startswith("atomic_metric_")

    def test_metric_default_values(self):
        """AtomicMetric default values."""
        atomic_metric = AtomicMetric(
            name="Test Metric",
            data_source="users",
            analysis_field="users.id",
        )
        assert atomic_metric.description is None
        assert atomic_metric.business_definition is None
        assert atomic_metric.calculation_logic is None
        assert atomic_metric.created_by is None

    def test_metric_all_fields(self):
        """AtomicMetric with all fields populated."""
        atomic_metric = AtomicMetric(
            name="Total Sales",
            business_definition="Sum of all order amounts",
            calculation_logic="SUM",
            data_source="orders",
            analysis_field="orders.amount",
            description="Revenue metric",
            created_by="admin",
        )
        assert atomic_metric.name == "Total Sales"
        assert atomic_metric.business_definition == "Sum of all order amounts"
        assert atomic_metric.calculation_logic == "SUM"
        assert atomic_metric.data_source == "orders"
        assert atomic_metric.analysis_field == "orders.amount"

    def test_metric_serialization_roundtrip(self):
        """AtomicMetric serializes and deserializes correctly."""
        atomic_metric = AtomicMetric(
            name="Test",
            business_definition="Count of payments",
            calculation_logic="COUNT",
            data_source="payments",
            analysis_field="payments.id",
        )
        data = atomic_metric.model_dump(mode="json")
        restored = AtomicMetric(**data)
        assert restored.name == "Test"
        assert restored.data_source == "payments"
        assert restored.analysis_field == "payments.id"
        assert restored.calculation_logic == "COUNT"

    def test_metric_json_serializable(self):
        """AtomicMetric can be serialized to JSON."""
        atomic_metric = AtomicMetric(
            name="Test",
            data_source="t",
            analysis_field="t.c",
        )
        json_str = atomic_metric.model_dump_json()
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
# DerivedMetric Model Tests
# ---------------------------------------------------------------------------


class TestDerivedMetricModel:
    """Unit tests for DerivedMetric model."""

    def test_derived_metric_auto_generates_id(self):
        from easyq2sql.capabilities.derived_metric.models import DerivedMetric
        derived_metric = DerivedMetric(
            atomic_metric_id="m1",
            name="Time",
            data_source="dim_date",
            field_ref="dim_date.date",
        )
        assert derived_metric.id is not None
        assert derived_metric.id.startswith("derived_metric_")

    def test_derived_metric_with_joins(self):
        from easyq2sql.capabilities.derived_metric.models import DerivedMetric
        derived_metric = DerivedMetric(
            atomic_metric_id="m1",
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
        assert len(derived_metric.joins) == 1
        assert derived_metric.joins[0].target_table == "dim_region"


# ---------------------------------------------------------------------------
# PostgresAtomicMetricStore Tests (requires database)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires PostgreSQL database connection")
class TestPostgresAtomicMetricStore:
    """Integration tests for PostgresAtomicMetricStore."""

    @pytest.mark.asyncio
    async def test_create_and_get_metric(self):
        """Create an atomic metric and retrieve it by ID."""
        from easyq2sql.integrations.postgres.atomic_metric_store import PostgresAtomicMetricStore
        from easyq2sql.core.tool import ToolContext
        from easyq2sql.core.user.models import User

        store = PostgresAtomicMetricStore(
            host="localhost",
            database="test_db",
            user="postgres",
            password="postgres",
            table_name="test_atomic_metrics",
        )
        user = User(id="test", group_memberships=["admin"])
        context = ToolContext(
            user=user,
            conversation_id="test",
            request_id="test",
            agent_memory=None,
        )

        atomic_metric = AtomicMetric(
            name="Test Metric",
            business_definition="A test metric",
            calculation_logic="COUNT",
            data_source="test_table",
            analysis_field="test_table.id",
        )

        created = await store.create_atomic_metric(atomic_metric, context)
        assert created.id is not None
        assert created.name == "Test Metric"

        retrieved = await store.get_atomic_metric(created.id, context)
        assert retrieved is not None
        assert retrieved.name == "Test Metric"
