"""
Composite metric storage capability interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import CompositeMetric


class CompositeMetricStore(ABC):
    """Abstract base class for composite metric storage operations.

    Composite metrics combine two derived metrics. Retrieval is handled by the
    metric graph, so this store only provides CRUD + listing; it is not
    responsible for semantic search.
    """

    @abstractmethod
    async def create_composite_metric(
        self, composite_metric: "CompositeMetric", context: "ToolContext"
    ) -> "CompositeMetric":
        """Create a new composite metric."""
        pass

    @abstractmethod
    async def get_composite_metric(
        self, composite_metric_id: str, context: "ToolContext"
    ) -> Optional["CompositeMetric"]:
        """Retrieve a single composite metric by ID."""
        pass

    @abstractmethod
    async def update_composite_metric(
        self, composite_metric: "CompositeMetric", context: "ToolContext"
    ) -> bool:
        """Update an existing composite metric."""
        pass

    @abstractmethod
    async def delete_composite_metric(
        self, composite_metric_id: str, context: "ToolContext"
    ) -> bool:
        """Delete a composite metric by ID."""
        pass

    @abstractmethod
    async def list_composite_metrics(
        self, context: "ToolContext"
    ) -> List["CompositeMetric"]:
        """List all stored composite metrics."""
        pass
