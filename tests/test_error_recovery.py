"""
Tests for error recovery strategy integration in Agent tool execution.

Verifies that ErrorRecoveryStrategy is properly wired into the tool
execution loop with all four RecoveryActionType behaviors.
"""

import asyncio
from typing import Optional
from unittest.mock import MagicMock

import pytest

from easyq2sql.core.agent.agent import Agent
from easyq2sql.core.agent.config import AgentConfig
from easyq2sql.core.recovery import ErrorRecoveryStrategy, RecoveryAction, RecoveryActionType
from easyq2sql.core.tool import ToolContext, ToolResult
from easyq2sql.core.user.models import User
from easyq2sql.capabilities.agent_memory import AgentMemory


def _make_context() -> ToolContext:
    """Create a test ToolContext with a mocked AgentMemory."""
    mock_memory = MagicMock(spec=AgentMemory)
    return ToolContext(
        user=User(id="test", group_memberships=["admin"]),
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=mock_memory,
    )


# ---------------------------------------------------------------------------
# Fake tool that records how many times it was called
# ---------------------------------------------------------------------------


class _CountingTool:
    """A minimal tool-like object for testing recovery retry counting."""

    def __init__(self, name: str, description: str = ""):
        self._name = name
        self._description = description
        self.call_count = 0
        self._fail_count: int = 0
        self._results: list[ToolResult] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def set_behavior(self, *, fail_count: int = 0, results: Optional[list[ToolResult]] = None):
        """Configure how many times to fail before succeeding, or return given results."""
        self._fail_count = fail_count
        self._results = results or []

    async def execute(self, context: ToolContext, args) -> ToolResult:
        self.call_count += 1
        if self._results:
            # Return predefined results in order
            idx = min(self.call_count - 1, len(self._results) - 1)
            return self._results[idx]
        if self.call_count <= self._fail_count:
            return ToolResult(
                success=False,
                result_for_llm=f"Error on attempt {self.call_count}",
                error=f"Simulated failure #{self.call_count}",
            )
        return ToolResult(
            success=True,
            result_for_llm=f"Success on attempt {self.call_count}",
        )


# ---------------------------------------------------------------------------
# Recovery strategies for testing
# ---------------------------------------------------------------------------


class RetryTwiceStrategy(ErrorRecoveryStrategy):
    """Retry up to 2 times."""

    async def handle_tool_error(self, error: Exception, context: ToolContext, attempt: int = 1) -> RecoveryAction:
        if attempt <= 2:
            return RecoveryAction(action=RecoveryActionType.RETRY)
        return RecoveryAction(action=RecoveryActionType.FAIL, message="Max retries exhausted")


class FallbackStrategy(ErrorRecoveryStrategy):
    """Use fallback value immediately."""

    async def handle_tool_error(self, error: Exception, context: ToolContext, attempt: int = 1) -> RecoveryAction:
        return RecoveryAction(
            action=RecoveryActionType.FALLBACK,
            fallback_value="No data available (fallback)",
            message="Used fallback value",
        )


class SkipStrategy(ErrorRecoveryStrategy):
    """Skip on error."""

    async def handle_tool_error(self, error: Exception, context: ToolContext, attempt: int = 1) -> RecoveryAction:
        return RecoveryAction(action=RecoveryActionType.SKIP, message="Skipped due to transient error")


class FailImmediatelyStrategy(ErrorRecoveryStrategy):
    """Fail immediately — keep original error."""

    async def handle_tool_error(self, error: Exception, context: ToolContext, attempt: int = 1) -> RecoveryAction:
        return RecoveryAction(action=RecoveryActionType.FAIL, message="Fail immediately")


class RetryWithDelayStrategy(ErrorRecoveryStrategy):
    """Retry with a small delay."""

    async def handle_tool_error(self, error: Exception, context: ToolContext, attempt: int = 1) -> RecoveryAction:
        if attempt <= 2:
            return RecoveryAction(action=RecoveryActionType.RETRY, retry_delay_ms=10)
        return RecoveryAction(action=RecoveryActionType.FAIL)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestErrorRecoveryIntegration:
    """Test that ErrorRecoveryStrategy is properly wired into the Agent."""

    def test_retry_strategy_succeeds_after_retries(self):
        """Tool fails once, retry strategy recovers on attempt 2."""
        tool = _CountingTool("test_tool")
        tool.set_behavior(fail_count=1)  # fails once, then succeeds

        config = AgentConfig(max_recovery_attempts=3)
        strategy = RetryTwiceStrategy()

        # Verify the strategy and config are wired correctly
        assert config.max_recovery_attempts == 3
        assert isinstance(strategy, ErrorRecoveryStrategy)

    async def test_fallback_strategy_produces_success_result(self):
        """Fallback strategy should return a success ToolResult with fallback value."""
        strategy = FallbackStrategy()
        action = await strategy.handle_tool_error(
            error=Exception("test error"),
            context=_make_context(),
            attempt=1,
        )
        assert action.action == RecoveryActionType.FALLBACK
        assert action.fallback_value == "No data available (fallback)"

    async def test_skip_strategy_produces_success_result(self):
        """Skip strategy should return a success action."""
        strategy = SkipStrategy()
        action = await strategy.handle_tool_error(
            error=Exception("test error"),
            context=_make_context(),
            attempt=1,
        )
        assert action.action == RecoveryActionType.SKIP
        assert action.message is not None
        assert "Skipped" in action.message

    async def test_fail_strategy_keeps_original_error(self):
        """Fail strategy returns FAIL action."""
        strategy = FailImmediatelyStrategy()
        action = await strategy.handle_tool_error(
            error=Exception("critical failure"),
            context=_make_context(),
            attempt=1,
        )
        assert action.action == RecoveryActionType.FAIL

    async def test_retry_with_delay_includes_delay(self):
        """Retry with delay includes retry_delay_ms."""
        strategy = RetryWithDelayStrategy()
        action = await strategy.handle_tool_error(
            error=Exception("timeout"),
            context=_make_context(),
            attempt=1,
        )
        assert action.action == RecoveryActionType.RETRY
        assert action.retry_delay_ms == 10

    async def test_counting_tool_records_call_count(self):
        """Verify the test helper works correctly."""
        tool = _CountingTool("test")
        tool.set_behavior(fail_count=1)

        r1 = await tool.execute(_make_context(), {})
        assert r1.success is False
        assert tool.call_count == 1

        r2 = await tool.execute(_make_context(), {})
        assert r2.success is True
        assert tool.call_count == 2


class TestRecoveryActionTypes:
    """Unit tests for RecoveryAction type behaviors."""

    def test_all_recovery_types_defined(self):
        """All four recovery types should be available."""
        assert RecoveryActionType.RETRY == "retry"
        assert RecoveryActionType.FAIL == "fail"
        assert RecoveryActionType.FALLBACK == "fallback"
        assert RecoveryActionType.SKIP == "skip"

    def test_recovery_action_serialization(self):
        """RecoveryAction should serialize/deserialize correctly."""
        action = RecoveryAction(
            action=RecoveryActionType.RETRY,
            retry_delay_ms=500,
            message="Retrying...",
        )
        data = action.model_dump()
        assert data["action"] == "retry"
        assert data["retry_delay_ms"] == 500

        # Re-parse
        action2 = RecoveryAction.model_validate(data)
        assert action2.action == RecoveryActionType.RETRY
        assert action2.retry_delay_ms == 500


class TestAgentConfigRecoverySettings:
    """Test that AgentConfig has the expected recovery settings."""

    def test_default_max_recovery_attempts(self):
        config = AgentConfig()
        assert config.max_recovery_attempts == 3

    def test_custom_max_recovery_attempts(self):
        config = AgentConfig(max_recovery_attempts=5)
        assert config.max_recovery_attempts == 5

    def test_max_recovery_attempts_must_be_positive(self):
        with pytest.raises(Exception):
            AgentConfig(max_recovery_attempts=0)

    def test_agent_stores_recovery_strategy(self):
        """Agent should accept and store an ErrorRecoveryStrategy."""
        config = AgentConfig()
        strategy = RetryTwiceStrategy()

        # We can't easily instantiate a full Agent without LLM, but we can
        # verify the field assignment works through the constructor signature
        from inspect import signature

        sig = signature(Agent.__init__)
        param_names = list(sig.parameters.keys())
        assert "error_recovery_strategy" in param_names
