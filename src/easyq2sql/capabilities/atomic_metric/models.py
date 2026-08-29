"""
Atomic metric storage models for business metric definitions.

An atomic metric defines how to compute a business measurement from an analysis
field with a calculation logic (aggregate function). Derived metrics are managed
independently via the DerivedMetricStore.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class JoinClause(BaseModel):
    """Foreign key join between the analysis table and a derived metric table."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "LEFT JOIN"


class AtomicMetric(BaseModel):
    """An atomic business metric definition.

    The atomic metric captures the WHAT (business meaning), HOW (calculation
    logic), and WHERE (data source + analysis field). Derived metrics are
    managed as independent entities linked via ``atomic_metric_id``.
    """

    id: str = Field(default_factory=lambda: f"atomic_metric_{uuid4().hex[:8]}")
    name: str = Field(description="Atomic metric name, e.g. 'Order Count'")
    business_definition: Optional[str] = Field(
        default=None,
        description="Business meaning of this atomic metric, e.g. 'Count of valid orders'",
    )
    calculation_logic: Optional[str] = Field(
        default=None,
        description="Aggregate function, e.g. COUNT, SUM, AVG",
    )
    data_source: str = Field(description="Source fact table name")
    analysis_field: str = Field(description="table.column being measured")
    value_range: Optional[str] = Field(
        default=None,
        description="Value range of the analysis field's column, e.g. '0 ~ 999999.99'",
    )
    fk_relation: Optional[str] = Field(
        default=None,
        description="Foreign-key relation of the analysis field's column, "
        "e.g. 'orders.user_id = users.id'",
    )
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AtomicMetricSearchResult(BaseModel):
    """Represents a search result from atomic metric storage."""

    atomic_metric: AtomicMetric
    similarity_score: float
    document_text: Optional[str] = None
