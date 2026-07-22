"""
Schema extraction package.

Provides DDL and table metadata extraction from various database systems.
"""

from .extractors.base import SchemaExtractor

__all__ = [
    "SchemaExtractor",
]
