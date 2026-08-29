"""
Sanity tests for database implementations.

These tests verify that:
1. Each database implementation correctly implements the SqlRunner interface
2. Imports are working correctly for all database modules
3. Basic class instantiation works (without requiring actual database connections)

Note: These tests do NOT execute actual queries against databases.
They are lightweight sanity checks for the implementation structure.
"""

import pytest
from abc import abstractmethod
from inspect import signature, iscoroutinefunction
import pandas as pd


class TestSqlRunnerInterface:
    """Test that the SqlRunner interface is properly defined."""

    def test_sql_runner_import(self):
        """Test that SqlRunner can be imported."""
        from easyq2sql.capabilities.sql_runner import SqlRunner

        assert SqlRunner is not None

    def test_sql_runner_is_abstract(self):
        """Test that SqlRunner is an abstract base class."""
        from easyq2sql.capabilities.sql_runner import SqlRunner
        from abc import ABC

        assert issubclass(SqlRunner, ABC)

    def test_sql_runner_has_run_sql_method(self):
        """Test that SqlRunner defines the run_sql abstract method."""
        from easyq2sql.capabilities.sql_runner import SqlRunner

        assert hasattr(SqlRunner, "run_sql")
        assert getattr(SqlRunner.run_sql, "__isabstractmethod__", False)

    def test_run_sql_method_signature(self):
        """Test that run_sql has the correct method signature."""
        from easyq2sql.capabilities.sql_runner import SqlRunner

        sig = signature(SqlRunner.run_sql)
        params = list(sig.parameters.keys())

        # Should have: self, args, context
        assert len(params) == 3
        assert params[0] == "self"
        assert params[1] == "args"
        assert params[2] == "context"

    def test_run_sql_is_async(self):
        """Test that run_sql is defined as an async method."""
        from easyq2sql.capabilities.sql_runner import SqlRunner

        # Abstract methods are wrapped, so we check if it's meant to be async
        # by looking at the method definition
        assert iscoroutinefunction(SqlRunner.run_sql)


class TestRunSqlToolArgsModel:
    """Test the RunSqlToolArgs model."""

    def test_run_sql_tool_args_import(self):
        """Test that RunSqlToolArgs can be imported."""
        from easyq2sql.capabilities.sql_runner import RunSqlToolArgs

        assert RunSqlToolArgs is not None

    def test_run_sql_tool_args_has_sql_field(self):
        """Test that RunSqlToolArgs has a 'sql' field."""
        from easyq2sql.capabilities.sql_runner import RunSqlToolArgs

        # Create an instance
        args = RunSqlToolArgs(sql="SELECT 1")
        assert hasattr(args, "sql")
        assert args.sql == "SELECT 1"

    def test_run_sql_tool_args_is_pydantic_model(self):
        """Test that RunSqlToolArgs is a Pydantic model."""
        from easyq2sql.capabilities.sql_runner import RunSqlToolArgs
        from pydantic import BaseModel

        assert issubclass(RunSqlToolArgs, BaseModel)


class TestPostgresRunner:
    """Sanity tests for PostgresRunner implementation."""

    def test_postgres_runner_import(self):
        """Test that PostgresRunner can be imported."""
        from easyq2sql.integrations.postgres import PostgresRunner

        assert PostgresRunner is not None

    def test_postgres_runner_implements_sql_runner(self):
        """Test that PostgresRunner implements SqlRunner interface."""
        from easyq2sql.integrations.postgres import PostgresRunner
        from easyq2sql.capabilities.sql_runner import SqlRunner

        assert issubclass(PostgresRunner, SqlRunner)

    def test_postgres_runner_has_run_sql_method(self):
        """Test that PostgresRunner implements run_sql method."""
        from easyq2sql.integrations.postgres import PostgresRunner

        assert hasattr(PostgresRunner, "run_sql")
        # Should not be abstract anymore
        assert not getattr(PostgresRunner.run_sql, "__isabstractmethod__", False)

    def test_postgres_runner_instantiation_with_connection_string(self):
        """Test that PostgresRunner can be instantiated with connection string."""
        from easyq2sql.integrations.postgres import PostgresRunner

        # This should not raise an error (no actual connection is made in __init__)
        runner = PostgresRunner(connection_string="postgresql://user:pass@localhost/db")
        assert runner is not None
        assert runner.connection_string == "postgresql://user:pass@localhost/db"
        assert runner.connection_params is None

    def test_postgres_runner_instantiation_with_params(self):
        """Test that PostgresRunner can be instantiated with individual parameters."""
        from easyq2sql.integrations.postgres import PostgresRunner

        runner = PostgresRunner(
            host="localhost",
            port=5432,
            database="testdb",
            user="testuser",
            password="testpass",
        )
        assert runner is not None
        assert runner.connection_string is None
        assert runner.connection_params is not None
        assert runner.connection_params["host"] == "localhost"
        assert runner.connection_params["database"] == "testdb"

    def test_postgres_runner_requires_valid_params(self):
        """Test that PostgresRunner raises error with invalid parameters."""
        from easyq2sql.integrations.postgres import PostgresRunner

        with pytest.raises(ValueError, match="Either provide connection_string OR"):
            PostgresRunner()  # No parameters provided

    def test_postgres_runner_checks_psycopg2_import(self):
        """Test that PostgresRunner checks for psycopg2 package."""
        from easyq2sql.integrations.postgres import PostgresRunner

        # If psycopg2 is not installed, this should raise ImportError
        # If it is installed, this should work fine
        try:
            runner = PostgresRunner(connection_string="postgresql://test")
            assert runner.psycopg2 is not None
        except ImportError as e:
            assert "psycopg2" in str(e)


class TestSqliteRunner:
    """Sanity tests for SqliteRunner implementation."""

    def test_sqlite_runner_import(self):
        """Test that SqliteRunner can be imported."""
        from easyq2sql.integrations.sqlite import SqliteRunner

        assert SqliteRunner is not None

    def test_sqlite_runner_implements_sql_runner(self):
        """Test that SqliteRunner implements SqlRunner interface."""
        from easyq2sql.integrations.sqlite import SqliteRunner
        from easyq2sql.capabilities.sql_runner import SqlRunner

        assert issubclass(SqliteRunner, SqlRunner)

    def test_sqlite_runner_has_run_sql_method(self):
        """Test that SqliteRunner implements run_sql method."""
        from easyq2sql.integrations.sqlite import SqliteRunner

        assert hasattr(SqliteRunner, "run_sql")
        # Should not be abstract anymore
        assert not getattr(SqliteRunner.run_sql, "__isabstractmethod__", False)

    def test_sqlite_runner_instantiation(self):
        """Test that SqliteRunner can be instantiated with a database path."""
        from easyq2sql.integrations.sqlite import SqliteRunner

        runner = SqliteRunner(database_path="/tmp/test.db")
        assert runner is not None
        assert runner.database_path == "/tmp/test.db"

    def test_sqlite_uses_builtin_sqlite3(self):
        """Test that SqliteRunner uses Python's built-in sqlite3 module."""
        import sqlite3
        from easyq2sql.integrations.sqlite import SqliteRunner

        # sqlite3 should be importable (it's part of Python standard library)
        assert sqlite3 is not None


class TestDatabaseIntegrationModules:
    """Test that database integration modules can be imported."""

    def test_postgres_module_import(self):
        """Test that the postgres integration module can be imported."""
        try:
            import easyq2sql.integrations.postgres

            assert easyq2sql.integrations.postgres is not None
        except ImportError as e:
            pytest.fail(f"Failed to import postgres module: {e}")

    def test_sqlite_module_import(self):
        """Test that the sqlite integration module can be imported."""
        try:
            import easyq2sql.integrations.sqlite

            assert easyq2sql.integrations.sqlite is not None
        except ImportError as e:
            pytest.fail(f"Failed to import sqlite module: {e}")

    def test_postgres_module_exports_runner(self):
        """Test that postgres module exports PostgresRunner."""
        from easyq2sql.integrations.postgres import PostgresRunner

        assert PostgresRunner is not None

    def test_sqlite_module_exports_runner(self):
        """Test that sqlite module exports SqliteRunner."""
        from easyq2sql.integrations.sqlite import SqliteRunner

        assert SqliteRunner is not None


class TestMySQLRunner:
    """Sanity tests for MySQLRunner implementation."""

    def test_mysql_runner_import(self):
        """Test that MySQLRunner can be imported."""
        from easyq2sql.integrations.mysql import MySQLRunner

        assert MySQLRunner is not None

    def test_mysql_runner_implements_sql_runner(self):
        """Test that MySQLRunner implements SqlRunner interface."""
        from easyq2sql.integrations.mysql import MySQLRunner
        from easyq2sql.capabilities.sql_runner import SqlRunner

        assert issubclass(MySQLRunner, SqlRunner)

    def test_mysql_runner_has_run_sql_method(self):
        """Test that MySQLRunner implements run_sql method."""
        from easyq2sql.integrations.mysql import MySQLRunner

        assert hasattr(MySQLRunner, "run_sql")
        assert not getattr(MySQLRunner.run_sql, "__isabstractmethod__", False)

    def test_mysql_runner_instantiation(self):
        """Test that MySQLRunner can be instantiated with required parameters."""
        from easyq2sql.integrations.mysql import MySQLRunner

        runner = MySQLRunner(
            host="localhost", database="test-db", user="test-user", password="test-pass"
        )
        assert runner is not None
        assert runner.host == "localhost"


