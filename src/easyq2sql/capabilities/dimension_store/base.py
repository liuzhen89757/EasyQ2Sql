"""
Dimension storage capability interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import Dimension, DimensionSearchResult


class DimensionStore(ABC):
    """Abstract base class for dimension storage operations.

    Stores analysis dimensions as independent entities linked to metrics
    via ``metric_id``. Supports hierarchical relationships and vector search.
    """

    @abstractmethod
    async def create_dimension(
        self, dimension: "Dimension", context: "ToolContext"
    ) -> "Dimension":
        """Create a new dimension."""
        pass

    @abstractmethod
    async def get_dimension(
        self, dimension_id: str, context: "ToolContext"
    ) -> Optional["Dimension"]:
        """Retrieve a single dimension by ID."""
        pass

    @abstractmethod
    async def update_dimension(
        self, dimension: "Dimension", context: "ToolContext"
    ) -> bool:
        """Update an existing dimension."""
        pass

    @abstractmethod
    async def delete_dimension(
        self, dimension_id: str, context: "ToolContext"
    ) -> bool:
        """Delete a dimension by ID."""
        pass

    @abstractmethod
    async def list_dimensions(
        self, context: "ToolContext"
    ) -> List["Dimension"]:
        """List all stored dimensions."""
        pass

    @abstractmethod
    async def search_dimensions(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
    ) -> List["DimensionSearchResult"]:
        """Semantically search dimensions by natural language query."""
        pass

    @abstractmethod
    async def get_dimensions_by_metric(
        self, metric_id: str, context: "ToolContext"
    ) -> List["Dimension"]:
        """Get all dimensions linked to a specific metric."""
        pass
