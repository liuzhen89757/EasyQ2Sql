"""
Metric graph storage capability interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from easyq2sql.core.tool import ToolContext

    from ..atomic_metric import AtomicMetricStore
    from ..composite_metric import CompositeMetricStore
    from ..derived_metric import DerivedMetricStore
    from .models import MetricGraphSubgraph


class MetricGraphStore(ABC):
    """Abstract base class for the metric graph.

    The graph is a *derived index*, not a source of truth: it is rebuilt from
    ``AtomicMetricStore`` / ``DerivedMetricStore`` / ``CompositeMetricStore``
    via :meth:`sync_from_stores`. It exists to answer the retrieval question
    those stores cannot — match a question to a metric, then walk the
    派生/复合 relationships to return the surrounding context in one hop::

        (原子指标) <-[DERIVED_FROM]- (派生指标) <-[USES]- (复合指标)
    """

    async def connect(self) -> None:
        """Open the backend connection.

        Optional lifecycle hook. Backends that need an explicit connection (a
        graph database) override it; in-process backends inherit the no-op, so
        callers may always call it.
        """
        return None

    async def close(self) -> None:
        """Release the backend connection. See :meth:`connect`."""
        return None

    @abstractmethod
    async def ensure_indexes(self) -> None:
        """Create or refresh whatever index :meth:`search` relies on.

        Called before :meth:`sync_from_stores` on a fresh backend. Must be
        idempotent.
        """
        pass

    @abstractmethod
    async def sync_from_stores(
        self,
        *,
        atomic_metric_store: Optional["AtomicMetricStore"] = None,
        derived_metric_store: Optional["DerivedMetricStore"] = None,
        composite_metric_store: Optional["CompositeMetricStore"] = None,
        context: Optional["ToolContext"] = None,
    ) -> Dict[str, int]:
        """Rebuild the graph from the relational stores (full rebuild).

        A store passed as ``None`` contributes no nodes. Returns
        ``{"nodes": n, "edges": m}`` counts for the rebuilt graph.
        """
        pass

    @abstractmethod
    async def search(self, query: str, *, top_k: int = 10) -> "MetricGraphSubgraph":
        """Match ``query`` to seed nodes, expand along the relationships, and
        return the resulting subgraph.

        ``top_k`` bounds the *seed* nodes, not the returned node count — the
        expansion normally pulls in more. Returns an empty subgraph rather than
        raising when nothing matches.
        """
        pass
