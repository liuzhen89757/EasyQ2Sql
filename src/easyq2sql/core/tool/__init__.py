"""
Tool domain.

This module provides the core abstractions for tools in the EasyQ2Sql framework.
"""

from .base import T, Tool
from .models import ToolCall, ToolContext, ToolRejection, ToolResult, ToolSchema

__all__ = [
    "Tool",
    "T",
    "ToolCall",
    "ToolContext",
    "ToolRejection",
    "ToolResult",
    "ToolSchema",
]
