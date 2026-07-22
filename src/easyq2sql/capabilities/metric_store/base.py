"""
Metric storage capability interface.

This module contains the abstract base class for metric storage operations,
following the same pattern as AgentMemory and SchemaStore interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import Metric, MetricSearchResult


class MetricStore(ABC):
    """Abstract base class for metric storage operations.

    Stores user-defined business metrics with semantic search capability.
    Metrics define how to compute measurements from analysis fields with
    dimensions, FK joins, and composable function steps.
    """

    @abstractmethod
    async def create_metric(
        self, metric: "Metric", context: "ToolContext"
    ) -> "Metric":
        """Create a new metric.

        Args:
            metric: The metric definition to create.
            context: Tool execution context for user scoping.

        Returns:
            The created metric with its assigned ID.
        """
        pass

    @abstractmethod
    async def get_metric(
        self, metric_id: str, context: "ToolContext"
    ) -> Optional["Metric"]:
        """Retrieve a single metric by ID.

        Args:
            metric_id: The metric ID to look up.
            context: Tool execution context for user scoping.

        Returns:
            The matching Metric, or None if not found.
        """
        pass

    @abstractmethod
    async def update_metric(
        self, metric: "Metric", context: "ToolContext"
    ) -> bool:
        """Update an existing metric.

        Args:
            metric: The metric definition with updated fields.
            context: Tool execution context for user scoping.

        Returns:
            True if the metric was found and updated, False otherwise.
        """
        pass

    @abstractmethod
    async def delete_metric(
        self, metric_id: str, context: "ToolContext"
    ) -> bool:
        """Delete a metric by ID.

        Args:
            metric_id: The metric ID to delete.
            context: Tool execution context for user scoping.

        Returns:
            True if deleted, False if not found.
        """
        pass

    @abstractmethod
    async def list_metrics(
        self, context: "ToolContext"
    ) -> List["Metric"]:
        """List all stored metrics.

        Args:
            context: Tool execution context for user scoping.

        Returns:
            List of all stored Metric objects.
        """
        pass

    @abstractmethod
    async def search_metrics(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
    ) -> List["MetricSearchResult"]:
        """Semantically search metrics by the user's natural language query.

        Args:
            query: Natural language search query.
            context: Tool execution context for user scoping.
            limit: Maximum number of results to return.

        Returns:
            Ranked list of search results with similarity scores.
        """
        pass

    @abstractmethod
    async def get_metrics_by_table(
        self, table_name: str, context: "ToolContext"
    ) -> List["Metric"]:
        """Get all metrics that reference a given table.

        Args:
            table_name: The table name to filter by.
            context: Tool execution context for user scoping.

        Returns:
            List of metrics that use the specified table.
        """
        pass
