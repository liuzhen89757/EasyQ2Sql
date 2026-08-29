"""
Tests for LLM error recovery integration.

Verifies that ``Agent.handle_llm_error`` correctly drives an
``ErrorRecoveryStrategy`` and applies each ``RecoveryActionType``, and that
``DefaultErrorRecoveryStrategy`` implements the harness recovery policy from
``docs/harness-error-recovery.md`` (output truncation, context-too-long,
transient 429/529 backoff, fallback-model switch).
"""

import asyncio
from typing import Optional
from unittest.mock import MagicMock

import pytest

from easyq2sql.core.agent.agent import Agent
from easyq2sql.core.agent.config import AgentConfig
from easyq2sql.core.llm.models import LlmMessage, LlmRequest, LlmResponse
from easyq2sql.core.recovery import (
    DefaultErrorRecoveryStrategy,
    ErrorRecoveryStrategy,
    RecoveryAction,
    RecoveryActionType,
)
from easyq2sql.core.user.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(max_tokens: Optional[int] = 4096) -> LlmRequest:
    return LlmRequest(
        messages=[LlmMessage(role="user", content="hi")],
        user=User(id="u", group_memberships=[]),
        max_tokens=max_tokens,
    )


def _bare_agent(strategy) -> Agent:
    """Build a minimal Agent without running __init__."""
    agent = Agent.__new__(Agent)
    agent.error_recovery_strategy = strategy
    agent.observability_provider = None
    agent.config = MagicMock(stream_responses=False, max_recovery_attempts=3)
    agent.llm_service = MagicMock()
    agent.llm_middlewares = []  # _send_llm_request iterates these
    return agent


# ---------------------------------------------------------------------------
# DefaultErrorRecoveryStrategy — classification
# ---------------------------------------------------------------------------


class TestDefaultStrategyClassification:
    """Recovery policy encoded in DefaultErrorRecoveryStrategy."""

    def test_rate_limit_429_retries_with_backoff(self):
        s = DefaultErrorRecoveryStrategy(base_delay_ms=10, jitter_fraction=0.0)
        act = asyncio.run(
            s.handle_llm_error(Exception("RateLimitError 429 too many requests"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.RETRY
        assert act.retry_delay_ms == 10  # base * 2^0, no jitter

    def test_rate_limit_429_fails_after_max_retries(self):
        s = DefaultErrorRecoveryStrategy(max_retries=3)
        act = asyncio.run(
            s.handle_llm_error(Exception("429 too many requests"), _make_request(), 3)
        )
        assert act.action == RecoveryActionType.FAIL

    def test_truncation_escalates_max_tokens_once(self):
        s = DefaultErrorRecoveryStrategy()
        req = _make_request(max_tokens=4096)
        act = asyncio.run(
            s.handle_llm_error(Exception("stop_reason max_tokens output token"), req, 1)
        )
        assert act.action == RecoveryActionType.RETRY
        assert req.max_tokens == s.escalated_max_tokens

    def test_truncation_fails_on_second_occurrence(self):
        s = DefaultErrorRecoveryStrategy()
        req = _make_request(max_tokens=4096)
        asyncio.run(s.handle_llm_error(Exception("max_tokens"), req, 1))
        act = asyncio.run(s.handle_llm_error(Exception("max_tokens"), req, 2))
        assert act.action == RecoveryActionType.FAIL

    def test_context_too_long_compacts_once(self):
        s = DefaultErrorRecoveryStrategy(compact_keep_recent=2, compact_keep_first=1)
        req = _make_request()
        req.messages = [LlmMessage(role="user", content=f"m{i}") for i in range(10)]
        act = asyncio.run(
            s.handle_llm_error(Exception("context_length_exceeded context too long"), req, 1)
        )
        assert act.action == RecoveryActionType.RETRY
        # head(1) + summary(1) + tail(2) = 4
        assert len(req.messages) == 4

    def test_context_too_long_fails_after_compaction(self):
        s = DefaultErrorRecoveryStrategy()
        req = _make_request()
        asyncio.run(s.handle_llm_error(Exception("context too long"), req, 1))
        act = asyncio.run(s.handle_llm_error(Exception("context too long"), req, 2))
        assert act.action == RecoveryActionType.FAIL

    def test_overloaded_529_switches_to_fallback_model(self):
        s = DefaultErrorRecoveryStrategy(
            max_consecutive_529=2,
            fallback_model="gpt-4o-mini",
            base_delay_ms=10,
            jitter_fraction=0.0,
        )
        asyncio.run(s.handle_llm_error(Exception("529 overloaded"), _make_request(), 1))
        act = asyncio.run(s.handle_llm_error(Exception("529 overloaded"), _make_request(), 2))
        assert act.action == RecoveryActionType.RETRY
        assert act.switch_model == "gpt-4o-mini"

    def test_non_transient_error_fails_immediately(self):
        s = DefaultErrorRecoveryStrategy()
        act = asyncio.run(
            s.handle_llm_error(ValueError("invalid api key"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.FAIL

    def test_retries_exhausted_for_overloaded_without_fallback(self):
        s = DefaultErrorRecoveryStrategy(max_retries=2, fallback_model=None)
        act = asyncio.run(s.handle_llm_error(Exception("529 overloaded"), _make_request(), 2))
        assert act.action == RecoveryActionType.FAIL


# ---------------------------------------------------------------------------
# Other API exception categories
# ---------------------------------------------------------------------------


class TestOtherApiExceptions:
    """Network/timeout, 5xx server, and auth/client errors."""

    def test_timeout_is_transient_and_retries(self):
        s = DefaultErrorRecoveryStrategy(base_delay_ms=10, jitter_fraction=0.0)
        act = asyncio.run(
            s.handle_llm_error(Exception("APITimeoutError Request timed out"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.RETRY
        assert act.retry_delay_ms == 10

    def test_connect_timeout_is_transient(self):
        s = DefaultErrorRecoveryStrategy(base_delay_ms=10, jitter_fraction=0.0)
        act = asyncio.run(
            s.handle_llm_error(Exception("httpx.ConnectTimeout handshake timed out"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.RETRY

    def test_timeout_does_not_trigger_model_switch(self):
        # Timeouts are transient but NOT overload signals — they must not
        # burn the consecutive_529 counter or switch the fallback model.
        s = DefaultErrorRecoveryStrategy(
            max_consecutive_529=1,
            fallback_model="fallback",
            base_delay_ms=10,
            jitter_fraction=0.0,
        )
        act = asyncio.run(
            s.handle_llm_error(Exception("APITimeoutError Request timed out"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.RETRY
        assert act.switch_model is None

    def test_500_server_error_is_transient(self):
        s = DefaultErrorRecoveryStrategy(base_delay_ms=10, jitter_fraction=0.0)
        act = asyncio.run(
            s.handle_llm_error(Exception("InternalServerError 500"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.RETRY

    def test_503_service_unavailable_is_transient(self):
        s = DefaultErrorRecoveryStrategy(base_delay_ms=10, jitter_fraction=0.0)
        act = asyncio.run(
            s.handle_llm_error(Exception("503 service unavailable"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.RETRY

    def test_auth_error_fails_immediately(self):
        s = DefaultErrorRecoveryStrategy()
        act = asyncio.run(
            s.handle_llm_error(Exception("AuthenticationError 401 incorrect api key"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.FAIL

    def test_403_forbidden_fails_immediately(self):
        s = DefaultErrorRecoveryStrategy()
        act = asyncio.run(
            s.handle_llm_error(Exception("PermissionDeniedError 403 forbidden"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.FAIL

    def test_400_bad_request_fails_immediately(self):
        s = DefaultErrorRecoveryStrategy()
        act = asyncio.run(
            s.handle_llm_error(Exception("BadRequestError 400 max_tokens must be < 4096"), _make_request(), 1)
        )
        # Must FAIL — a 400 is not the same as an output-truncation stop_reason.
        assert act.action == RecoveryActionType.FAIL

    def test_404_not_found_fails_immediately(self):
        s = DefaultErrorRecoveryStrategy()
        act = asyncio.run(
            s.handle_llm_error(Exception("NotFoundError 404 model not found"), _make_request(), 1)
        )
        assert act.action == RecoveryActionType.FAIL


# ---------------------------------------------------------------------------
# Agent.handle_llm_error — orchestration
# ---------------------------------------------------------------------------


class _StubStrategy(ErrorRecoveryStrategy):
    """Returns a scripted sequence of actions."""

    def __init__(self, actions):
        self._actions = list(actions)
        self.calls = []

    async def handle_llm_error(self, error, request, attempt=1):
        self.calls.append((str(error), attempt))
        if attempt - 1 < len(self._actions):
            return self._actions[attempt - 1]
        return RecoveryAction(action=RecoveryActionType.FAIL, message="exhausted")


class _OkLlm:
    """A fake LLM service whose send_request always succeeds."""

    model = "primary"

    async def send_request(self, request):
        return LlmResponse(content="ok", finish_reason="stop")


class TestAgentHandleLlmError:
    def test_no_strategy_reraises(self):
        agent = _bare_agent(strategy=None)
        with pytest.raises(RuntimeError):
            asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("boom")))

    def test_fail_action_reraises_original(self):
        agent = _bare_agent(
            _StubStrategy([RecoveryAction(action=RecoveryActionType.FAIL)])
        )
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("boom")))

    def test_fallback_action_returns_synthetic_response(self):
        agent = _bare_agent(
            _StubStrategy(
                [
                    RecoveryAction(
                        action=RecoveryActionType.FALLBACK, fallback_value="safe answer"
                    )
                ]
            )
        )
        resp = asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("down")))
        assert resp.content == "safe answer"
        assert resp.metadata["recovery_action"] == "fallback"

    def test_skip_action_returns_empty_response(self):
        agent = _bare_agent(
            _StubStrategy(
                [RecoveryAction(action=RecoveryActionType.SKIP, message="skipped")]
            )
        )
        resp = asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("down")))
        assert "skipped" in (resp.content or "")
        assert resp.metadata["recovery_action"] == "skip"

    def test_retry_action_resends_and_succeeds(self):
        agent = _bare_agent(
            _StubStrategy([RecoveryAction(action=RecoveryActionType.RETRY)])
        )
        agent.llm_service = _OkLlm()  # type: ignore[assignment]
        resp = asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("transient")))
        assert resp.content == "ok"

    def test_retry_with_switch_model_updates_llm_service(self):
        agent = _bare_agent(
            _StubStrategy(
                [
                    RecoveryAction(
                        action=RecoveryActionType.RETRY, switch_model="fallback-model"
                    )
                ]
            )
        )
        llm = _OkLlm()
        agent.llm_service = llm  # type: ignore[assignment]
        asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("529")))
        assert llm.model == "fallback-model"

    def test_recovery_exhausted_reraises_last_error(self):
        # Always RETRY, but the LLM keeps failing -> after max_recovery_attempts
        # the last error must be re-raised.
        agent = _bare_agent(
            _StubStrategy(
                [
                    RecoveryAction(action=RecoveryActionType.RETRY),
                    RecoveryAction(action=RecoveryActionType.RETRY),
                    RecoveryAction(action=RecoveryActionType.RETRY),
                ]
            )
        )

        class _FailLlm:
            model = "primary"

            async def send_request(self, request):
                raise RuntimeError("still down")

        agent.llm_service = _FailLlm()  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="still down"):
            asyncio.run(agent.handle_llm_error(_make_request(), RuntimeError("first failure")))


# ---------------------------------------------------------------------------
# RecoveryState ledger
# ---------------------------------------------------------------------------


class TestRecoveryState:
    def test_default_state_is_clean(self):
        st = DefaultErrorRecoveryStrategy()
        # Fresh strategy should have a clean ledger.
        assert st._state.has_escalated is False
        assert st._state.recovery_count == 0
        assert st._state.consecutive_529 == 0
        assert st._state.has_attempted_reactive_compact is False
