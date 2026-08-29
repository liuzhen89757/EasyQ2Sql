"""
Atomic metric storage capability interface.

This module contains the abstract base class for atomic metric storage operations,
following the same pattern as AgentMemory and SchemaStore interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import AtomicMetric, AtomicMetricSearchResult


class AtomicMetricStore(ABC):
    """Abstract base class for atomic metric storage operations.

    Stores user-defined business atomic metrics with semantic search capability.
    Atomic metrics define how to compute measurements from analysis fields with
    derived metrics, FK joins, and composable function steps.
    """

    @abstractmethod
    async def create_atomic_metric(
        self, atomic_metric: "AtomicMetric", context: "ToolContext"
    ) -> "AtomicMetric":
        """Create a new atomic metric.

        Args:
            atomic_metric: The atomic metric definition to create.
            context: Tool execution context for user scoping.

        Returns:
            The created atomic metric with its assigned ID.
        """
        pass

    @abstractmethod
    async def get_atomic_metric(
        self, atomic_metric_id: str, context: "ToolContext"
    ) -> Optional["AtomicMetric"]:
        """Retrieve a single atomic metric by ID.

        Args:
            atomic_metric_id: The atomic metric ID to look up.
            context: Tool execution context for user scoping.

        Returns:
            The matching AtomicMetric, or None if not found.
        """
        pass

    @abstractmethod
    async def update_atomic_metric(
        self, atomic_metric: "AtomicMetric", context: "ToolContext"
    ) -> bool:
        """Update an existing atomic metric.

        Args:
            atomic_metric: The atomic metric definition with updated fields.
            context: Tool execution context for user scoping.

        Returns:
            True if the atomic metric was found and updated, False otherwise.
        """
        pass

    @abstractmethod
    async def delete_atomic_metric(
        self, atomic_metric_id: str, context: "ToolContext"
    ) -> bool:
        """Delete an atomic metric by ID.

        Args:
            atomic_metric_id: The atomic metric ID to delete.
            context: Tool execution context for user scoping.

        Returns:
            True if deleted, False if not found.
        """
        pass

    @abstractmethod
    async def list_atomic_metrics(
        self, context: "ToolContext"
    ) -> List["AtomicMetric"]:
        """List all stored atomic metrics.

        Args:
            context: Tool execution context for user scoping.

        Returns:
            List of all stored AtomicMetric objects.
        """
        pass

    @abstractmethod
    async def search_atomic_metrics(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
    ) -> List["AtomicMetricSearchResult"]:
        """Semantically search atomic metrics by the user's natural language query.

        Args:
            query: Natural language search query.
            context: Tool execution context for user scoping.
            limit: Maximum number of results to return.

        Returns:
            Ranked list of search results with similarity scores.
        """
        pass

    @abstractmethod
    async def get_atomic_metrics_by_table(
        self, table_name: str, context: "ToolContext"
    ) -> List["AtomicMetric"]:
        """Get all atomic metrics that reference a given table.

        Args:
            table_name: The table name to filter by.
            context: Tool execution context for user scoping.

        Returns:
            List of atomic metrics that use the specified table.
        """
        pass
