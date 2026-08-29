"""
Derived metric storage models.

A derived metric is an independent entity that describes how to slice/group
a business atomic metric. Each derived metric belongs to exactly one atomic
metric (via ``atomic_metric_id``).
"""

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from ..atomic_metric.models import JoinClause


class DerivedMetric(BaseModel):
    """A derived metric used for grouping or drill-down in metric analysis.

    Derived metrics are independent entities linked to an atomic metric via
    ``atomic_metric_id``.
    """

    id: str = Field(default_factory=lambda: f"derived_metric_{uuid4().hex[:8]}")
    atomic_metric_id: str = Field(description="FK to the parent AtomicMetric")
    name: str = Field(description="Derived metric name, e.g. 'Time', 'Region'")
    business_definition: Optional[str] = Field(
        default=None,
        description="Business meaning of this derived metric",
    )
    value_range: Optional[str] = Field(
        default=None,
        description="Value range, e.g. '2020-01-01 ~ today'",
    )
    fk_relation: Optional[str] = Field(
        default=None,
        description="Foreign-key relation of the derived metric field's column, "
        "e.g. 'dim.region_id = regions.id'",
    )
    data_source: str = Field(description="Derived metric table name")
    field_ref: str = Field(description="table.column reference")
    joins: List[JoinClause] = Field(
        default_factory=list,
        description="FK joins from the fact table to this derived metric table",
    )
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class DerivedMetricSearchResult(BaseModel):
    """Represents a search result from derived metric storage."""

    derived_metric: DerivedMetric
    similarity_score: float
    document_text: Optional[str] = None
