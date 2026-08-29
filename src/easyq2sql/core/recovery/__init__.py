"""
Error recovery system for handling failures gracefully.

This module provides interfaces for custom error handling, retry logic,
and fallback strategies. The default implementation encodes the harness
recovery policy documented in ``docs/harness-error-recovery.md``.
"""

from .base import (
    DefaultErrorRecoveryStrategy,
    ErrorRecoveryStrategy,
    RecoveryState,
)
from .models import RecoveryAction, RecoveryActionType

__all__ = [
    "DefaultErrorRecoveryStrategy",
    "ErrorRecoveryStrategy",
    "RecoveryState",
    "RecoveryAction",
    "RecoveryActionType",
]
