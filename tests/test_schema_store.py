"""
Tests for SchemaStore implementations and SchemaExtractor.

Covers ChromaSchemaStore CRUD, vector search, description updates,
sync operations, and SQLite schema extraction.
"""

import asyncio
import shutil
import tempfile
from datetime import datetime

import pytest
from easyq2sql.capabilities.schema_store import ColumnSchema, TableSchema
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
    """Helper to create a ToolContext for schema tests."""
    return ToolContext(
        user=user,
        conversation_id="schema_test",
        request_id="schema_test_req",
        agent_memory=agent_memory or DemoAgentMemory(max_items=100),
        metadata={},
    )


@pytest.fixture
def sample_table():
    """Create a sample TableSchema for testing."""
    return TableSchema(
        table_name="orders",
        database_name="test_db",
        description="Customer orders with line items",
        columns=[
            ColumnSchema(
                name="id",
                data_type="INTEGER",
                nullable=False,
                description="Primary key",
                is_primary_key=True,
            ),
            ColumnSchema(
                name="customer_id",
                data_type="INTEGER",
                nullable=False,
                description="FK to customers table",
                is_foreign_key=True,
                fk_reference_table="customers",
                fk_reference_column="id",
            ),
            ColumnSchema(
                name="amount",
                data_type="DECIMAL(10,2)",
                nullable=False,
                description="Order total amount",
            ),
            ColumnSchema(
                name="order_date",
                data_type="DATE",
                nullable=True,
                description="Date the order was placed",
            ),
            ColumnSchema(
                name="status",
                data_type="VARCHAR(20)",
                nullable=True,
                description="Order status: pending, shipped, delivered",
            ),
        ],
    )


@pytest.fixture
def sample_tables():
    """Create multiple sample TableSchema objects."""
    return [
        TableSchema(
            table_name="customers",
            database_name="test_db",
            description="Customer account information",
            columns=[
                ColumnSchema(
                    name="id", data_type="INTEGER", nullable=False,
                    description="Primary key", is_primary_key=True,
                ),
                ColumnSchema(
                    name="name", data_type="VARCHAR(100)", nullable=False,
                    description="Customer full name",
                ),
                ColumnSchema(
                    name="email", data_type="VARCHAR(255)", nullable=True,
                    description="Customer email address",
                ),
            ],
        ),
        TableSchema(
            table_name="orders",
            database_name="test_db",
            description="Customer orders",
            columns=[
                ColumnSchema(
                    name="id", data_type="INTEGER", nullable=False,
                    description="Primary key", is_primary_key=True,
                ),
                ColumnSchema(
                    name="customer_id", data_type="INTEGER", nullable=False,
                    description="FK to customers",
                    is_foreign_key=True,
                    fk_reference_table="customers",
                    fk_reference_column="id",
                ),
                ColumnSchema(
                    name="total", data_type="DECIMAL(12,2)", nullable=False,
                    description="Order total",
                ),
            ],
        ),
        TableSchema(
            table_name="products",
            database_name="test_db",
            description="Product catalog",
            columns=[
                ColumnSchema(
                    name="id", data_type="INTEGER", nullable=False,
                    description="Primary key", is_primary_key=True,
                ),
                ColumnSchema(
                    name="name", data_type="VARCHAR(200)", nullable=False,
                    description="Product name",
                ),
                ColumnSchema(
                    name="price", data_type="DECIMAL(10,2)", nullable=False,
                    description="Unit price",
                ),
            ],
        ),
    ]



# ---------------------------------------------------------------------------
# ColumnSchema Unit Tests
# ---------------------------------------------------------------------------


class TestColumnSchema:
    """Unit tests for ColumnSchema model."""

    def test_column_schema_defaults(self):
        """Test that ColumnSchema has sensible defaults."""
        col = ColumnSchema(name="test_col", data_type="VARCHAR")
        assert col.name == "test_col"
        assert col.data_type == "VARCHAR"
        assert col.nullable is True
        assert col.description is None
        assert col.is_primary_key is False
        assert col.is_foreign_key is False
        assert col.fk_reference_table is None
        assert col.fk_reference_column is None

    def test_column_schema_with_fk(self):
        """Test ColumnSchema with foreign key info."""
        col = ColumnSchema(
            name="user_id",
            data_type="INTEGER",
            nullable=False,
            is_foreign_key=True,
            fk_reference_table="users",
            fk_reference_column="id",
        )
        assert col.is_foreign_key is True
        assert col.fk_reference_table == "users"
        assert col.fk_reference_column == "id"

    def test_column_schema_serialization(self):
        """Test that ColumnSchema serializes correctly."""
        col = ColumnSchema(name="id", data_type="INTEGER", is_primary_key=True)
        data = col.model_dump(mode="json")
        assert data["name"] == "id"
        assert data["data_type"] == "INTEGER"
        assert data["is_primary_key"] is True


# ---------------------------------------------------------------------------
# TableSchema Unit Tests
# ---------------------------------------------------------------------------


class TestTableSchema:
    """Unit tests for TableSchema model."""

    def test_table_schema_defaults(self):
        """Test TableSchema default values."""
        table = TableSchema(table_name="test")
        assert table.table_name == "test"
        assert table.database_name == "default"
        assert table.schema_name is None
        assert table.description is None
        assert table.columns == []
        assert table.ddl is None
        assert isinstance(table.extracted_at, datetime)

    def test_table_schema_with_columns(self):
        """Test TableSchema with columns."""
        table = TableSchema(
            table_name="users",
            columns=[
                ColumnSchema(name="id", data_type="INTEGER"),
                ColumnSchema(name="name", data_type="VARCHAR(100)"),
            ],
        )
        assert len(table.columns) == 2
        assert table.columns[0].name == "id"

    def test_table_schema_serialization(self):
        """Test round-trip serialization."""
        table = TableSchema(
            table_name="products",
            database_name="store",
            description="Product catalog",
            columns=[
                ColumnSchema(name="id", data_type="INTEGER", is_primary_key=True),
                ColumnSchema(name="name", data_type="VARCHAR"),
            ],
        )
        data = table.model_dump(mode="json")
        restored = TableSchema(**data)
        assert restored.table_name == "products"
        assert restored.database_name == "store"
        assert restored.description == "Product catalog"
        assert len(restored.columns) == 2
        assert restored.columns[0].is_primary_key is True


# ---------------------------------------------------------------------------
# SQLite SchemaExtractor Integration Test
# ---------------------------------------------------------------------------


class TestSqliteSchemaExtractor:
    """Integration tests for SQLite schema extraction."""

    @pytest.fixture
    def sqlite_runner(self):
        """Create an in-memory SQLite database with test tables."""
        from easyq2sql.integrations.sqlite import SqliteRunner

        import sqlite3

        # Create in-memory DB and populate with test schema
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(255),
                created_at DATE DEFAULT CURRENT_DATE
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                order_date DATE,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                price DECIMAL(10,2) NOT NULL DEFAULT 0.00
            );
        """)
        conn.close()

        # Use file-based SQLite since in-memory DBs are connection-specific
        import tempfile
        import os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = tmp.name
        tmp.close()

        file_conn = sqlite3.connect(tmp_path)
        file_conn.executescript("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(255),
                created_at DATE DEFAULT CURRENT_DATE
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                order_date DATE,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                price DECIMAL(10,2) NOT NULL DEFAULT 0.00
            );
        """)
        file_conn.close()

        runner = SqliteRunner(database_path=tmp_path)
        yield runner
        os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_extract_schemas_from_sqlite(self, sqlite_runner, test_user):
        """Test that the extractor retrieves correct table and column metadata."""
        from easyq2sql.integrations.schema.extractors.sqlite import SqliteSchemaExtractor

        context = create_test_context(test_user)
        extractor = SqliteSchemaExtractor()

        tables = await extractor.extract_schemas(sqlite_runner, context, "test_db")

        assert len(tables) == 3
        table_names = {t.table_name for t in tables}
        assert table_names == {"customers", "orders", "products"}

        # Verify customers table
        customers = next(t for t in tables if t.table_name == "customers")
        assert len(customers.columns) == 4
        col_names = {c.name for c in customers.columns}
        assert col_names == {"id", "name", "email", "created_at"}
        id_col = next(c for c in customers.columns if c.name == "id")
        assert id_col.is_primary_key is True
        assert id_col.data_type.upper() in ("INTEGER", "INT")

        # Verify orders table with FK
        orders = next(t for t in tables if t.table_name == "orders")
        customer_id_col = next(c for c in orders.columns if c.name == "customer_id")
        assert customer_id_col.is_foreign_key is True
        assert customer_id_col.fk_reference_table == "customers"
        assert customer_id_col.fk_reference_column == "id"

    @pytest.mark.asyncio
    async def test_extracted_tables_have_database_name(self, sqlite_runner, test_user):
        """Test that all extracted tables get the specified database name."""
        from easyq2sql.integrations.schema.extractors.sqlite import SqliteSchemaExtractor

        context = create_test_context(test_user)
        extractor = SqliteSchemaExtractor()

        tables = await extractor.extract_schemas(sqlite_runner, context, "my_database")
        for table in tables:
            assert table.database_name == "my_database"

    @pytest.mark.asyncio
    async def test_extract_value_ranges(self, sqlite_runner, test_user):
        """Test that numeric/temporal columns get min~max and text columns get distinct values."""
        from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs
        from easyq2sql.integrations.schema.extractors.sqlite import SqliteSchemaExtractor

        context = create_test_context(test_user)

        await sqlite_runner.run_sql(
            RunSqlToolArgs(sql=(
                "INSERT INTO customers (name, email) VALUES "
                "('Alice','a@x.com'),('Bob','b@x.com'),('Carol','c@x.com')"
            )),
            context,
        )
        await sqlite_runner.run_sql(
            RunSqlToolArgs(sql=(
                "INSERT INTO orders (customer_id, amount, order_date) VALUES "
                "(1,10.5,'2024-01-01'),(2,25.0,'2024-02-01'),(3,40.0,'2024-03-01')"
            )),
            context,
        )

        extractor = SqliteSchemaExtractor()
        tables = await extractor.extract_schemas(sqlite_runner, context, "test_db")

        customers = next(t for t in tables if t.table_name == "customers")
        name_col = next(c for c in customers.columns if c.name == "name")
        assert name_col.value_range == "[Alice, Bob, Carol]"

        orders = next(t for t in tables if t.table_name == "orders")
        amount_col = next(c for c in orders.columns if c.name == "amount")
        # SQLite NUMERIC affinity stores whole-number decimals as integers (40.0 -> 40).
        assert amount_col.value_range == "10.5 ~ 40"

        date_col = next(c for c in orders.columns if c.name == "order_date")
        assert date_col.value_range == "2024-01-01 ~ 2024-03-01"

    @pytest.mark.asyncio
    async def test_value_range_skips_high_cardinality(self, sqlite_runner, test_user):
        """Test that text columns with >10 distinct values leave value_range empty."""
        from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs
        from easyq2sql.integrations.schema.extractors.sqlite import SqliteSchemaExtractor

        context = create_test_context(test_user)
        values = ", ".join(f"('name_{i}', {i})" for i in range(11))
        await sqlite_runner.run_sql(
            RunSqlToolArgs(sql=f"INSERT INTO products (name, price) VALUES {values}"),
            context,
        )

        extractor = SqliteSchemaExtractor()
        tables = await extractor.extract_schemas(sqlite_runner, context, "test_db")
        products = next(t for t in tables if t.table_name == "products")
        name_col = next(c for c in products.columns if c.name == "name")
        assert name_col.value_range is None


# ---------------------------------------------------------------------------
# Data type classification unit tests
# ---------------------------------------------------------------------------


class TestDataTypeClassification:
    """Unit tests for schema value-range type classification."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("integer", "numeric"),
            ("INT", "numeric"),
            ("decimal(10,2)", "numeric"),
            ("int(11) unsigned", "numeric"),
            ("double precision", "numeric"),
            ("varchar(20)", "text"),
            ("character varying", "text"),
            ("text", "text"),
            ("uuid", "text"),
            ("enum('a','b')", "text"),
            ("boolean", "boolean"),
            ("timestamp without time zone", "temporal"),
            ("date", "temporal"),
            ("jsonb", "other"),
            ("bytea", "other"),
        ],
    )
    def test_classify_data_type(self, raw, expected):
        from easyq2sql.integrations.schema.extractors.base import SchemaExtractor

        assert SchemaExtractor._classify_data_type(raw) == expected
