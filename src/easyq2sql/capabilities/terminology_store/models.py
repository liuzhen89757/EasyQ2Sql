"""
Terminology mapping storage models.

A TerminologyEntry maps a business term (natural language) to either a
Metric or a Dimension. Terms can be manually configured or auto-generated
when metrics/dimensions are created.
"""

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TerminologyEntry(BaseModel):
    """A mapping from a business term to a metric or dimension.

    - Manual entries: user-configured explicit mappings.
    - Auto entries: generated automatically from metric/dimension names.
    """

    id: str = Field(default_factory=lambda: f"term_{uuid4().hex[:8]}")
    term_text: str = Field(description="The business term, e.g. 'OEE', 'Last Month'")
    target_type: str = Field(
        description="Mapping target type: 'metric' or 'dimension'",
    )
    target_id: str = Field(description="FK to Metric.id or Dimension.id")
    business_definition: Optional[str] = Field(
        default=None,
        description="Business definition — inherited from target for auto entries",
    )
    synonyms: List[str] = Field(
        default_factory=list,
        description="Synonym list for broader matching",
    )
    source: str = Field(
        default="manual",
        description="Source: 'manual' (user-configured) or 'auto' (generated)",
    )
    created_at: datetime = Field(default_factory=datetime.now)


class TerminologySearchResult(BaseModel):
    """Represents a search result from terminology storage."""

    entry: TerminologyEntry
    similarity_score: float
    document_text: Optional[str] = None
