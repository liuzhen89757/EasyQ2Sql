"""
Composite metric storage models.

A composite metric combines two derived metrics (i.e. two ``DerivedMetric``
slices) via a composition operator (ratio, difference, period-over-period, ...).
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class CompositeMetric(BaseModel):
    """A composite metric built from two derived metrics.

    ``operand_a`` / ``operand_b`` reference derived metrics. In the current
    system a derived metric is a ``DerivedMetric`` row (an atomic metric sliced
    by a dimension field), so both operands are ``derived_metric`` ids.

    ``comb_func`` is one of the composition operators:

    - ``Ratio``: ``operand_a / operand_b`` (ratio / percentage)
    - ``Diff``: ``operand_a - operand_b`` (difference)
    - ``PoP``: period-over-period growth vs. previous period
    - ``YoY``: year-over-year growth vs. same period last year
    """

    id: str = Field(default_factory=lambda: f"composite_metric_{uuid4().hex[:8]}")
    name: str = Field(description="Composite metric name")
    business_definition: Optional[str] = Field(
        default=None,
        description="Business meaning of this composite metric",
    )
    comb_func: str = Field(
        description="Composition operator: Ratio / Diff / PoP / YoY"
    )
    operand_a: str = Field(description="First derived metric id")
    operand_b: str = Field(description="Second derived metric id")
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class CompositeMetricSearchResult(BaseModel):
    """Represents a search result from composite metric storage."""

    composite_metric: CompositeMetric
    similarity_score: float
    document_text: Optional[str] = None
