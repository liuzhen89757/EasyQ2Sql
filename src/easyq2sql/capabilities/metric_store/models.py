"""
Metric storage models for business metric definitions.

A metric defines how to compute a business measurement from analysis fields,
with support for dimensions, FK joins, and composable function steps across
seven function categories (aggregate, logical, operator, window, date, general, analysis).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class FunctionCategory(StrEnum):
    """Categories of functions available for metric computation."""

    AGGREGATE = "aggregate"
    LOGICAL = "logical"
    OPERATOR = "operator"
    WINDOW = "window"
    DATE = "date"
    GENERAL = "general"
    ANALYSIS = "analysis"


# Predefined function catalog
FUNCTION_CATALOG: Dict[str, List[str]] = {
    FunctionCategory.AGGREGATE: [
        "COUNT", "SUM", "AVG", "COUNT_DISTINCT", "MAX", "MIN", "VARIANCE",
    ],
    FunctionCategory.LOGICAL: [
        "IF", "IN", "NOT", "ISNULL", "IFILTERED",
    ],
    FunctionCategory.OPERATOR: [
        "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
        "EQUAL", "NOT_EQUAL", "GREATER_THAN", "LESS_THAN",
        "GREATER_EQUAL", "LESS_EQUAL",
        "AND", "OR", "NOT",
    ],
    FunctionCategory.WINDOW: [
        "RANK", "RANK_DENSE", "ROW_NUMBER",
        "ACC_AVG", "ACC_COUNT", "ACC_SUM", "ACC_MAX", "ACC_MIN",
        "LEAD", "LAG", "FIRST", "LAST",
    ],
    FunctionCategory.DATE: [
        "DATE_ADD", "DATE_DIFF", "DATE_TRUNC",
        "TOTAL_DAYS_OF_MONTH", "TOTAL_DAYS_OF_YEAR",
    ],
    FunctionCategory.GENERAL: [
        "CONCAT", "SUBSTRING", "UPPER", "LOWER", "TRIM", "LENGTH", "REPLACE",
        "ABS", "ROUND", "CEIL", "FLOOR", "POWER", "SQRT", "MOD",
        "JSON_EXTRACT", "JSON_EXTRACT_SCALAR",
        "CAST",
    ],
    FunctionCategory.ANALYSIS: [
        "POWER_ADD", "POWER_FIX", "POWER_SUB",
        "SUB_TOTAL", "SUB_WINDOW",
        "SAME_PERIOD", "PREVIOUS_PERIOD",
    ],
}


class FunctionStep(BaseModel):
    """A single function node in the metric computation pipeline.

    Function steps are composed sequentially to build the metric's
    semantic computation. Each step references a function from one of
    the seven supported categories and optionally operates on a field.
    """

    category: str = Field(description="One of FunctionCategory values")
    function_name: str = Field(description="Function name, e.g. COUNT, SUM, IF, DateDiff")
    field_ref: Optional[str] = Field(
        default=None,
        description="table.column reference this function operates on",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extra parameters (window frame, date interval, operator value, etc.)",
    )
    alias: Optional[str] = Field(
        default=None,
        description="Output alias for this computation step",
    )


class JoinClause(BaseModel):
    """Foreign key join between the analysis table and a dimension table."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "LEFT JOIN"


class MetricDimension(BaseModel):
    """A single dimension used for grouping or drill-down in a metric.

    Each dimension includes its own FK joins so that one metric-dimension pair
    maps to one stored row (1:1:1 relationship in the vector database).
    """

    name: str = Field(description="User-friendly dimension label, e.g. 'Provincial Region'")
    field_ref: str = Field(description="table.column reference, e.g. 'dim_table.province'")
    joins: List["JoinClause"] = Field(
        default_factory=list,
        description="FK joins needed to reach this dimension table from the analysis table",
    )


class Metric(BaseModel):
    """A business metric definition that can be executed as a SQL query.

    The metric is composed of:
    - A user-defined name
    - An analysis field (the column being measured)
    - One or more dimensions for grouping
    - FK joins linking the analysis table to dimension tables
    - An ordered list of function steps that define the computation
    """

    id: str = Field(default_factory=lambda: f"metric_{uuid4().hex[:8]}")
    name: str = Field(description="User-defined metric name")
    description: Optional[str] = None
    analysis_table: str = Field(description="Main fact table for this metric")
    analysis_field: str = Field(description="table.column being measured")
    dimensions: List[MetricDimension] = Field(
        default_factory=list,
        description="Grouping dimensions for drill-down (each carries its own FK joins)",
    )
    generated_sql_template: Optional[str] = Field(
        default=None,
        description="Auto-generated SQL template",
    )
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class MetricSearchResult(BaseModel):
    """Represents a search result from metric storage."""

    metric: Metric
    similarity_score: float
    document_text: Optional[str] = None
