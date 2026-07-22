"""
Schema storage capability interface.

This module contains the abstract base class for schema storage operations,
following the same pattern as AgentMemory and SqlRunner interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import SchemaSearchResult, TableSchema


class SchemaStore(ABC):
    """Abstract base class for schema storage operations.

    Stores structured database table/column metadata with vector search
    capability for semantic retrieval during NL-to-SQL generation.
    """

    @abstractmethod
    async def save_table_schema(
        self, table: "TableSchema", context: "ToolContext"
    ) -> None:
        """Save or update a single table schema in storage.

        Args:
            table: The table schema to persist.
            context: Tool execution context for user scoping.
        """
        pass

    @abstractmethod
    async def get_table_schema(
        self, table_name: str, context: "ToolContext"
    ) -> Optional["TableSchema"]:
        """Retrieve a single table schema by name.

        Args:
            table_name: The table name to look up.
            context: Tool execution context for user scoping.

        Returns:
            The matching TableSchema, or None if not found.
        """
        pass

    @abstractmethod
    async def search_tables(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
        similarity_threshold: float = 0.5,
    ) -> List["SchemaSearchResult"]:
        """Semantically search tables by the user's natural language query.

        Args:
            query: Natural language search query.
            context: Tool execution context for user scoping.
            limit: Maximum number of results to return.
            similarity_threshold: Minimum similarity score (0.0 to 1.0).

        Returns:
            Ranked list of search results with similarity scores.
        """
        pass

    @abstractmethod
    async def update_table_description(
        self, table_name: str, description: str, context: "ToolContext"
    ) -> bool:
        """Update a table's description and sync to vector store.

        Args:
            table_name: The table to update.
            description: New description text.
            context: Tool execution context for user scoping.

        Returns:
            True if the table was found and updated, False otherwise.
        """
        pass

    @abstractmethod
    async def update_column_description(
        self,
        table_name: str,
        column_name: str,
        description: str,
        context: "ToolContext",
    ) -> bool:
        """Update a column's description and sync to vector store.

        Args:
            table_name: The table containing the column.
            column_name: The column to update.
            description: New description text.
            context: Tool execution context for user scoping.

        Returns:
            True if the column was found and updated, False otherwise.
        """
        pass

    @abstractmethod
    async def list_all_tables(
        self, context: "ToolContext"
    ) -> List["TableSchema"]:
        """List all stored table schemas.

        Args:
            context: Tool execution context for user scoping.

        Returns:
            List of all stored TableSchema objects.
        """
        pass

    @abstractmethod
    async def delete_table_schema(
        self, table_name: str, context: "ToolContext"
    ) -> bool:
        """Delete a table schema from storage.

        Args:
            table_name: The table to delete.
            context: Tool execution context for user scoping.

        Returns:
            True if deleted, False if not found.
        """
        pass

    @abstractmethod
    async def sync_all_schemas(
        self, tables: List["TableSchema"], context: "ToolContext"
    ) -> int:
        """Full sync: replace all stored schemas with the given list.

        Args:
            tables: Complete list of table schemas to store.
            context: Tool execution context for user scoping.

        Returns:
            Number of tables synced.
        """
        pass
