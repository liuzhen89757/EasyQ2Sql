"""
Derived metric storage capability interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import DerivedMetric, DerivedMetricSearchResult


class DerivedMetricStore(ABC):
    """Abstract base class for derived metric storage operations.

    Stores derived metrics as independent entities linked to atomic metrics
    via ``atomic_metric_id``. Supports hierarchical relationships and vector search.
    """

    @abstractmethod
    async def create_derived_metric(
        self, derived_metric: "DerivedMetric", context: "ToolContext"
    ) -> "DerivedMetric":
        """Create a new derived metric."""
        pass

    @abstractmethod
    async def get_derived_metric(
        self, derived_metric_id: str, context: "ToolContext"
    ) -> Optional["DerivedMetric"]:
        """Retrieve a single derived metric by ID."""
        pass

    @abstractmethod
    async def update_derived_metric(
        self, derived_metric: "DerivedMetric", context: "ToolContext"
    ) -> bool:
        """Update an existing derived metric."""
        pass

    @abstractmethod
    async def delete_derived_metric(
        self, derived_metric_id: str, context: "ToolContext"
    ) -> bool:
        """Delete a derived metric by ID."""
        pass

    @abstractmethod
    async def delete_derived_metrics(
        self, derived_metric_ids: List[str], context: "ToolContext"
    ) -> int:
        """Delete multiple derived metrics by ID in a single operation.

        Args:
            derived_metric_ids: IDs of the derived metrics to delete.
            context: Tool execution context for user scoping.

        Returns:
            Number of derived metrics deleted.
        """
        pass

    @abstractmethod
    async def list_derived_metrics(
        self, context: "ToolContext"
    ) -> List["DerivedMetric"]:
        """List all stored derived metrics."""
        pass

    @abstractmethod
    async def search_derived_metrics(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
    ) -> List["DerivedMetricSearchResult"]:
        """Semantically search derived metrics by natural language query."""
        pass

    @abstractmethod
    async def get_derived_metrics_by_atomic_metric(
        self, atomic_metric_id: str, context: "ToolContext"
    ) -> List["DerivedMetric"]:
        """Get all derived metrics linked to a specific atomic metric."""
        pass
