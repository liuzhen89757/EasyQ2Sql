"""
Schema storage models for table and column metadata.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ColumnSchema(BaseModel):
    """Represents a single column within a database table."""

    name: str
    data_type: str
    nullable: bool = True
    default_value: Optional[str] = None
    description: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    fk_reference_table: Optional[str] = None
    fk_reference_column: Optional[str] = None
    examples: Optional[List[str]] = None


class TableSchema(BaseModel):
    """Represents a database table with its full structural metadata."""

    table_name: str
    schema_name: Optional[str] = None
    database_name: str = "default"
    description: Optional[str] = None
    columns: List[ColumnSchema] = Field(default_factory=list)
    ddl: Optional[str] = None
    row_count_estimate: Optional[int] = None
    extracted_at: datetime = Field(default_factory=datetime.now)


class SchemaSearchResult(BaseModel):
    """Represents a search result from schema storage."""

    table: TableSchema
    similarity_score: float
    document_text: Optional[str] = None
