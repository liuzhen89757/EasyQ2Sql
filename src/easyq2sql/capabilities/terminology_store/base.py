"""
Terminology mapping storage capability interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext
    from .models import TerminologyEntry, TerminologySearchResult


class TerminologyStore(ABC):
    """Abstract base class for terminology mapping storage operations.

    Maps business terms (natural language) to metrics or dimensions.
    Supports both manually configured and auto-generated entries.
    """

    @abstractmethod
    async def create_entry(
        self, entry: "TerminologyEntry", context: "ToolContext"
    ) -> "TerminologyEntry":
        """Create a new terminology mapping."""
        pass

    @abstractmethod
    async def get_entry(
        self, entry_id: str, context: "ToolContext"
    ) -> Optional["TerminologyEntry"]:
        """Retrieve a single terminology entry by ID."""
        pass

    @abstractmethod
    async def update_entry(
        self, entry: "TerminologyEntry", context: "ToolContext"
    ) -> bool:
        """Update an existing terminology entry."""
        pass

    @abstractmethod
    async def delete_entry(
        self, entry_id: str, context: "ToolContext"
    ) -> bool:
        """Delete a terminology entry by ID."""
        pass

    @abstractmethod
    async def list_entries(
        self, context: "ToolContext", *, source: Optional[str] = None
    ) -> List["TerminologyEntry"]:
        """List all terminology entries, optionally filtered by source."""
        pass

    @abstractmethod
    async def search_terminology(
        self,
        query: str,
        context: "ToolContext",
        *,
        limit: int = 10,
    ) -> List["TerminologySearchResult"]:
        """Search terminology mappings by term text, synonyms, and definition."""
        pass

    @abstractmethod
    async def get_terms_by_target(
        self,
        target_type: str,
        target_id: str,
        context: "ToolContext",
    ) -> List["TerminologyEntry"]:
        """Get all terminology entries pointing to a specific target."""
        pass

    @abstractmethod
    async def sync_auto_terms(
        self,
        context: "ToolContext",
        metrics: Optional[List] = None,
        dimensions: Optional[List] = None,
    ) -> int:
        """Generate/update auto terminology entries from metrics and dimensions.

        Args:
            context: Tool execution context.
            metrics: Optional list of Metric objects. If None, fetched internally.
            dimensions: Optional list of Dimension objects. If None, fetched internally.

        Returns:
            Number of auto entries created or updated.
        """
        pass
