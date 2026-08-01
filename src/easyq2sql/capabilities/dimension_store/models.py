"""
Dimension storage models.

A Dimension is an independent entity that describes how to slice/group
a business metric. Each dimension belongs to exactly one metric (via ``metric_id``).
"""

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from ..metric_store.models import JoinClause


class Dimension(BaseModel):
    """A dimension used for grouping or drill-down in metric analysis.

    Dimensions are independent entities linked to a metric via ``metric_id``.
    """

    id: str = Field(default_factory=lambda: f"dim_{uuid4().hex[:8]}")
    metric_id: str = Field(description="FK to the parent Metric")
    name: str = Field(description="Dimension name, e.g. 'Time', 'Region'")
    business_definition: Optional[str] = Field(
        default=None,
        description="Business meaning of this dimension",
    )
    value_range: Optional[str] = Field(
        default=None,
        description="Value range, e.g. '2020-01-01 ~ today'",
    )
    data_source: str = Field(description="Dimension table name")
    field_ref: str = Field(description="table.column reference")
    joins: List[JoinClause] = Field(
        default_factory=list,
        description="FK joins from the fact table to this dimension table",
    )
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class DimensionSearchResult(BaseModel):
    """Represents a search result from dimension storage."""

    dimension: Dimension
    similarity_score: float
    document_text: Optional[str] = None
