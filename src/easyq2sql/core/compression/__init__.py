"""
Conversation compression module.

This module provides a LifecycleHook implementation that compresses
each conversation round into a structured summary, reducing context
window growth in long-running conversations.
"""

from .hook import ConversationCompressionHook, build_query_history_section

__all__ = ["ConversationCompressionHook", "build_query_history_section"]
