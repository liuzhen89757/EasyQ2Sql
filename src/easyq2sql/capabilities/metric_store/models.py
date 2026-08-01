"""
Metric storage models for business metric definitions.

A metric defines how to compute a business measurement from an analysis field
with a calculation logic (aggregate function). Dimensions are managed independently
via the DimensionStore, and terminology mapping is handled by the TerminologyStore.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class JoinClause(BaseModel):
    """Foreign key join between the analysis table and a dimension table."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "LEFT JOIN"


class Metric(BaseModel):
    """An atomic business metric definition.

    The metric captures the WHAT (business meaning), HOW (calculation logic),
    and WHERE (data source + analysis field). Dimensions are managed as
    independent entities linked via ``metric_id``.
    """

    id: str = Field(default_factory=lambda: f"metric_{uuid4().hex[:8]}")
    name: str = Field(description="Metric name, e.g. 'Order Count'")
    business_definition: Optional[str] = Field(
        default=None,
        description="Business meaning of this metric, e.g. 'Count of valid orders'",
    )
    calculation_logic: Optional[str] = Field(
        default=None,
        description="Aggregate function, e.g. COUNT, SUM, AVG",
    )
    data_source: str = Field(description="Source fact table name")
    analysis_field: str = Field(description="table.column being measured")
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class MetricSearchResult(BaseModel):
    """Represents a search result from metric storage."""

    metric: Metric
    similarity_score: float
    document_text: Optional[str] = None
