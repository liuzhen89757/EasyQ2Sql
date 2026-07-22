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


@pytest.fixture
def chroma_schema_store():
    """Create a ChromaSchemaStore backed by a temp directory."""
    try:
        from easyq2sql.integrations.chromadb.schema_store import ChromaSchemaStore

        temp_dir = tempfile.mkdtemp()
        store = ChromaSchemaStore(
            persist_directory=temp_dir,
            collection_name="test_schema_store",
        )
        yield store
        shutil.rmtree(temp_dir, ignore_errors=True)
    except ImportError:
        pytest.skip("ChromaDB not installed")


# ---------------------------------------------------------------------------
# ChromaSchemaStore Tests
# ---------------------------------------------------------------------------


class TestChromaSchemaStore:
    """Tests for ChromaSchemaStore CRUD and search operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_table(self, chroma_schema_store, test_user, sample_table):
        """Test saving a table schema and retrieving it by name."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        await store.save_table_schema(sample_table, context)

        retrieved = await store.get_table_schema("orders", context)
        assert retrieved is not None
        assert retrieved.table_name == "orders"
        assert retrieved.description == "Customer orders with line items"
        assert len(retrieved.columns) == 5
        assert retrieved.columns[0].name == "id"
        assert retrieved.columns[0].is_primary_key is True
        assert retrieved.columns[1].is_foreign_key is True

    @pytest.mark.asyncio
    async def test_get_nonexistent_table(self, chroma_schema_store, test_user):
        """Test that getting a nonexistent table returns None."""
        context = create_test_context(test_user)
        result = await chroma_schema_store.get_table_schema("nonexistent", context)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all_tables(self, chroma_schema_store, test_user, sample_tables):
        """Test listing all stored tables."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        all_tables = await store.list_all_tables(context)
        assert len(all_tables) == 3
        table_names = {t.table_name for t in all_tables}
        assert table_names == {"customers", "orders", "products"}

    @pytest.mark.asyncio
    async def test_search_tables_by_description(self, chroma_schema_store, test_user, sample_tables):
        """Test semantic search for tables by natural language query."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        # Search for customer-related tables (use threshold=0.0 since default
        # embedding function may produce low absolute similarity scores)
        results = await store.search_tables(
            query="customer account information",
            context=context,
            limit=5,
            similarity_threshold=0.0,
        )
        assert len(results) >= 1
        # The most relevant result should be the customers table
        assert results[0].table.table_name == "customers"

    @pytest.mark.asyncio
    async def test_search_tables_by_column(self, chroma_schema_store, test_user, sample_tables):
        """Test that column descriptions contribute to search relevance."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        results = await store.search_tables(
            query="product catalog with prices",
            context=context,
            limit=5,
            similarity_threshold=0.0,
        )
        assert len(results) >= 1
        assert results[0].table.table_name == "products"

    @pytest.mark.asyncio
    async def test_search_tables_no_match(self, chroma_schema_store, test_user, sample_tables):
        """Test that unrelated queries return no results at high threshold."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        results = await store.search_tables(
            query="completely unrelated topic about space exploration",
            context=context,
            limit=5,
            similarity_threshold=0.9,
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_update_table_description(self, chroma_schema_store, test_user, sample_table):
        """Test updating a table's description and verifying the change."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        await store.save_table_schema(sample_table, context)

        new_desc = "Updated: all customer order transactions"
        success = await store.update_table_description("orders", new_desc, context)
        assert success is True

        updated = await store.get_table_schema("orders", context)
        assert updated is not None
        assert updated.description == new_desc

    @pytest.mark.asyncio
    async def test_update_table_description_nonexistent(self, chroma_schema_store, test_user):
        """Test updating description of a nonexistent table returns False."""
        context = create_test_context(test_user)
        success = await chroma_schema_store.update_table_description(
            "no_such_table", "new description", context
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_update_column_description(self, chroma_schema_store, test_user, sample_table):
        """Test updating a column's description and verifying the change."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        await store.save_table_schema(sample_table, context)

        new_col_desc = "Updated: order status with new values"
        success = await store.update_column_description(
            "orders", "status", new_col_desc, context
        )
        assert success is True

        updated = await store.get_table_schema("orders", context)
        status_col = next(c for c in updated.columns if c.name == "status")
        assert status_col.description == new_col_desc

    @pytest.mark.asyncio
    async def test_update_column_description_nonexistent(self, chroma_schema_store, test_user, sample_table):
        """Test updating description of a nonexistent column returns False."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        await store.save_table_schema(sample_table, context)

        # Wrong column name
        success = await store.update_column_description(
            "orders", "no_such_column", "desc", context
        )
        assert success is False

        # Wrong table name
        success = await store.update_column_description(
            "no_such_table", "status", "desc", context
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_delete_table_schema(self, chroma_schema_store, test_user, sample_table):
        """Test deleting a table schema."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        await store.save_table_schema(sample_table, context)
        assert await store.get_table_schema("orders", context) is not None

        deleted = await store.delete_table_schema("orders", context)
        assert deleted is True
        assert await store.get_table_schema("orders", context) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_table(self, chroma_schema_store, test_user):
        """Test deleting a nonexistent table returns False."""
        context = create_test_context(test_user)
        deleted = await chroma_schema_store.delete_table_schema("no_table", context)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_sync_all_schemas(self, chroma_schema_store, test_user, sample_tables):
        """Test full sync: replaces all schemas with a new set."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        # First, save some tables
        await store.save_table_schema(sample_tables[0], context)
        await store.save_table_schema(sample_tables[1], context)

        # Now sync with a different set (only products)
        count = await store.sync_all_schemas([sample_tables[2]], context)
        assert count == 1

        all_tables = await store.list_all_tables(context)
        assert len(all_tables) == 1
        assert all_tables[0].table_name == "products"

    @pytest.mark.asyncio
    async def test_sync_empty_list_clears_all(self, chroma_schema_store, test_user, sample_tables):
        """Test that syncing with an empty list removes all schemas."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        count = await store.sync_all_schemas([], context)
        assert count == 0

        all_tables = await store.list_all_tables(context)
        assert len(all_tables) == 0

    @pytest.mark.asyncio
    async def test_search_results_sorted_by_similarity(self, chroma_schema_store, test_user, sample_tables):
        """Test that search results are ranked by similarity score."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        results = await store.search_tables(
            query="customer information and accounts",
            context=context,
            limit=5,
            similarity_threshold=0.0,
        )
        assert len(results) >= 1
        # Scores should be non-increasing (first is highest)
        for i in range(len(results) - 1):
            assert results[i].similarity_score >= results[i + 1].similarity_score

    @pytest.mark.asyncio
    async def test_search_obeys_limit(self, chroma_schema_store, test_user, sample_tables):
        """Test that search respects the limit parameter."""
        context = create_test_context(test_user)
        store = chroma_schema_store

        for table in sample_tables:
            await store.save_table_schema(table, context)

        results = await store.search_tables(
            query="table",
            context=context,
            limit=2,
            similarity_threshold=0.1,
        )
        assert len(results) <= 2


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
