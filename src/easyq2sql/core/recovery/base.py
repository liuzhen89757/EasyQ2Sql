"""
Base error recovery strategy interface and default implementation.

Recovery strategies allow you to customize how the agent handles errors
during tool execution and LLM communication.

The default implementation (:class:`DefaultErrorRecoveryStrategy`) encodes the
harness error-recovery policy documented in ``docs/harness-error-recovery.md``:

- **Output truncated** (``max_tokens`` / ``stop_reason=max_tokens``) —
  escalate the ``max_tokens`` cap and retry.
- **Context too long** — compress the conversation once and retry.
- **Transient faults** (429 rate limit / 529 overloaded) — exponential
  backoff with jitter; switch to a fallback model after repeated 529s.

A :class:`RecoveryState` ledger is threaded across retries so every escalation
happens at most once and the retry count is bounded.
"""

import logging
from abc import ABC
from random import uniform
from typing import TYPE_CHECKING, Optional

from .models import RecoveryAction, RecoveryActionType

if TYPE_CHECKING:
    from ..tool.models import ToolContext
    from ..llm import LlmRequest

# Imported at runtime because _reactive_compact constructs LlmMessage instances.
from ..llm.models import LlmMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunable policy constants (mirror docs/harness-error-recovery.md)
# ---------------------------------------------------------------------------

# Cap the agent orchestrator escalates to when an LLM output is truncated.
DEFAULT_ESCALATED_MAX_TOKENS = 65536

# Retry budget for transient (429/529) LLM errors.
DEFAULT_MAX_RETRIES = 3

# Max consecutive 529 (overloaded) errors before switching to a fallback model.
DEFAULT_MAX_CONSECUTIVE_529 = 3

# Exponential-backoff base delay in milliseconds; doubles per attempt.
DEFAULT_BASE_DELAY_MS = 1000

# Upper bound (ms) for the exponential term before jitter is added.
DEFAULT_MAX_DELAY_MS = 32000

# Fraction of the computed delay used as random jitter (anti-thundering-herd).
DEFAULT_JITTER_FRACTION = 0.25

# Markers used to classify an error as a transient 429 rate-limit failure.
_RATE_LIMIT_MARKERS = ("ratelimit", "rate_limit", "rate limit", "429", "too many requests")

# Markers used to classify an error as a 529 / overloaded failure.
_OVERLOADED_MARKERS = ("overloaded", "529", "overload", "capacity")

# Markers used to classify an error as an output-truncation failure.
_TRUNCATION_MARKERS = (
    "max_tokens",
    "max tokens",
    "maxtokens",
    "truncat",
    "stop_reason",
    "finish_reason",
    "output token",
    "completion length",
    "length",
)

# Markers used to classify an error as a context-too-long failure.
_CONTEXT_TOO_LONG_MARKERS = (
    "context length",
    "context too long",
    "context window",
    "prompt is too long",
    "maximum context",
    "context_length_exceeded",
    "too long",
)

# Markers for auth/permission errors — NEVER transient. Fail fast so we don't
# burn the retry budget on a bad API key or a forbidden model.
_AUTH_ERROR_MARKERS = (
    "authenticationerror",
    "authentication",
    "permissiondeniederror",
    "permission denied",
    "unauthorized",
    "401",
    "403",
    "forbidden",
    "invalid api key",
    "incorrect api key",
    "not authenticated",
)

# Markers for client/request errors — NEVER transient. Checked early so a 400
# mentioning "max_tokens" (e.g. "max_tokens must be < 4096") is not misrouted to
# the truncation-escalation path (which would only make it worse).
_CLIENT_ERROR_MARKERS = (
    "badrequesterror",
    "bad request",
    "notfounderror",
    "not found",
    "not_found",
    "unprocessableentityerror",
    "unprocessable entity",
    "validationerror",
    "validation error",
    "400",
    "404",
    "422",
)

# Markers for connection/network errors — genuinely transient. Retried with
# exponential backoff (like 429), but they do NOT count toward the 529
# model-switch threshold (they are not overload signals).
_NETWORK_MARKERS = (
    "apiconnectionerror",
    "apitimeouterror",
    "apirequesttimeout",
    "timeouterror",
    "timeout",
    "connectionerror",
    "connectionreseterror",
    "connectionabortederror",
    "connectionrefused",
    "connecterror",
    "readtimeout",
    "writetimeout",
    "pooltimeout",
    "networkerror",
    "temporarily unavailable",
    "connection reset",
    "name resolution",
    "getaddrinfo",
    "socket",
    "eof occurred",
    "remotedisconnected",
    "remotedisconnecterror",
    "peer closed",
)

# Markers for 5xx server errors — transient (the upstream is unhealthy). Retried
# with backoff; does not trigger a model switch (only 529/overload does).
# NOTE: the standalone "500" marker is intentionally broad; in an LLM-API error
# context it almost always denotes the HTTP status.
_SERVER_ERROR_MARKERS = (
    "internalservererror",
    "badgateway",
    "serviceunavailable",
    "gatewaytimeout",
    "server error",
    "internal error",
    "502",
    "503",
    "504",
    "500",
)


def _matches_any(text: str, markers: tuple) -> bool:
    """Return True if ``text`` contains any of ``markers`` (case-insensitive)."""
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


class RecoveryState:
    """Track recovery attempts across the retry loop.

    This is the "ledger" from ``docs/harness-error-recovery.md``: every
    escalation or compression must record that it has happened, otherwise the
    loop either repeats work indefinitely or never escalates at all.

    Attributes:
        has_escalated: ``max_tokens`` has already been escalated once — never
            escalate again in the same turn.
        recovery_count: Number of continuation retries performed so far.
        consecutive_529: Consecutive 529/overloaded errors seen; switching to a
            fallback model resets this to 0.
        has_attempted_reactive_compact: Conversation has already been compressed
            once — never compress again in the same turn.
        current_model: The model currently in use (the orchestrator may rewrite
            this when a fallback model is selected).
    """

    def __init__(self, current_model: Optional[str] = None) -> None:
        self.has_escalated: bool = False
        self.recovery_count: int = 0
        self.consecutive_529: int = 0
        self.has_attempted_reactive_compact: bool = False
        self.current_model: Optional[str] = current_model


class ErrorRecoveryStrategy(ABC):
    """Strategy for handling errors and implementing retry logic.

    Subclass this to create custom error recovery strategies that can:
    - Retry failed operations with backoff
    - Fallback to alternative approaches
    - Log errors to external systems
    - Gracefully degrade functionality

    Example:
        class ExponentialBackoffStrategy(ErrorRecoveryStrategy):
            async def handle_tool_error(
                self, error: Exception, context: ToolContext, attempt: int
            ) -> RecoveryAction:
                if attempt < 3:
                    delay = (2 ** attempt) * 1000  # Exponential backoff
                    return RecoveryAction(
                        action=RecoveryActionType.RETRY,
                        retry_delay_ms=delay,
                        message=f"Retrying after {delay}ms"
                    )
                return RecoveryAction(
                    action=RecoveryActionType.FAIL,
                    message="Max retries exceeded"
                )

        agent = AgentRunner(
            llm_service=...,
            error_recovery_strategy=ExponentialBackoffStrategy()
        )
    """

    async def handle_tool_error(
        self, error: Exception, context: "ToolContext", attempt: int = 1
    ) -> RecoveryAction:
        """Handle errors during tool execution.

        Args:
            error: The exception that occurred
            context: Tool execution context
            attempt: Current attempt number (1-indexed)

        Returns:
            RecoveryAction indicating how to proceed
        """
        # Default: fail immediately
        return RecoveryAction(
            action=RecoveryActionType.FAIL, message=f"Tool error: {str(error)}"
        )

    async def handle_llm_error(
        self, error: Exception, request: "LlmRequest", attempt: int = 1
    ) -> RecoveryAction:
        """Handle errors during LLM communication.

        Args:
            error: The exception that occurred
            request: The LLM request that failed
            attempt: Current attempt number (1-indexed)

        Returns:
            RecoveryAction indicating how to proceed
        """
        # Default: fail immediately
        return RecoveryAction(
            action=RecoveryActionType.FAIL, message=f"LLM error: {str(error)}"
        )


class DefaultErrorRecoveryStrategy(ErrorRecoveryStrategy):
    """Default LLM error-recovery policy.

    Implements the three-pronged recovery from
    ``docs/harness-error-recovery.md``:

    - **Output truncation** (``max_tokens`` hit) — signal the orchestrator to
      escalate ``max_tokens`` (once) and retry.
    - **Context too long** — ask the orchestrator to compress the conversation
      (once) and retry; if it has already been compressed, fail.
    - **Transient faults** (429 / 529) — exponential backoff with jitter; after
      ``max_consecutive_529`` consecutive 529s, switch to a fallback model.
    - Anything else is non-transient and fails immediately.

    A :class:`RecoveryState` ledger is created per ``handle_llm_error`` call and
    is not shared across calls; the orchestrator is expected to bound the outer
    retry count via ``config.max_recovery_attempts``.
    """

    def __init__(
        self,
        *,
        escalated_max_tokens: int = DEFAULT_ESCALATED_MAX_TOKENS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_consecutive_529: int = DEFAULT_MAX_CONSECUTIVE_529,
        base_delay_ms: int = DEFAULT_BASE_DELAY_MS,
        max_delay_ms: int = DEFAULT_MAX_DELAY_MS,
        jitter_fraction: float = DEFAULT_JITTER_FRACTION,
        fallback_model: Optional[str] = None,
        compact_keep_recent: int = 6,
        compact_keep_first: int = 1,
    ) -> None:
        self.escalated_max_tokens = escalated_max_tokens
        self.max_retries = max_retries
        self.max_consecutive_529 = max_consecutive_529
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.jitter_fraction = jitter_fraction
        self.fallback_model = fallback_model
        # How many trailing / leading messages reactive compaction preserves.
        self.compact_keep_recent = compact_keep_recent
        self.compact_keep_first = compact_keep_first
        # Per-strategy ledger; reset whenever a fresh recovery sequence begins.
        self._state = RecoveryState()

    # -- public API ---------------------------------------------------------

    async def handle_tool_error(
        self, error: Exception, context: "ToolContext", attempt: int = 1
    ) -> RecoveryAction:
        """Tool errors are non-transient by default — fail immediately.

        Override in a subclass to add tool-specific retry/fallback behavior.
        """
        return RecoveryAction(
            action=RecoveryActionType.FAIL, message=f"Tool error: {str(error)}"
        )

    async def handle_llm_error(
        self, error: Exception, request: "LlmRequest", attempt: int = 1
    ) -> RecoveryAction:
        """Classify the LLM error and return the matching recovery action."""
        self._state.recovery_count = attempt - 1  # attempt is 1-indexed
        category = self._classify_error(error)
        logger.warning(
            "LLM error encountered: type=%s category=%s attempt=%d/%d | %s",
            type(error).__name__,
            category,
            attempt,
            self.max_retries,
            str(error),
        )

        # --- Hard client errors (auth / 400 / 404): never transient --------
        # Checked before truncation/context classification so that e.g. a 400
        # that happens to mention "max_tokens" is not misrouted into the
        # escalation path (which would only make it worse).
        if self._is_auth_error(error) or self._is_client_error(error):
            logger.warning(
                "LLM recovery FAILED (non-retryable %s): attempt=%d/%d | %s",
                category,
                attempt,
                self.max_retries,
                str(error),
            )
            return RecoveryAction(
                action=RecoveryActionType.FAIL,
                message=f"Non-retryable LLM error: {str(error)}",
            )

        # --- Context too long: compress once, then fail ---------------------
        if self._is_context_too_long_error(error):
            if not self._state.has_attempted_reactive_compact:
                self._state.has_attempted_reactive_compact = True
                self._reactive_compact(request)
                logger.info(
                    "LLM recovery: %s — compacting context before retry "
                    "(attempt=%d/%d)",
                    category,
                    attempt,
                    self.max_retries,
                )
                return RecoveryAction(
                    action=RecoveryActionType.RETRY,
                    retry_delay_ms=0,
                    message="Context too long — conversation compacted before retry",
                )
            logger.warning(
                "LLM recovery FAILED (%s still too long after compaction): "
                "attempt=%d/%d | %s",
                category,
                attempt,
                self.max_retries,
                str(error),
            )
            return RecoveryAction(
                action=RecoveryActionType.FAIL,
                message="Context still too large after compaction — cannot continue",
            )

        # --- Output truncated: escalate max_tokens once, then fail ---------
        if self._is_truncation_error(error):
            if not self._state.has_escalated:
                self._state.has_escalated = True
                # Ask the orchestrator to raise the cap on the request.
                request.max_tokens = self.escalated_max_tokens
                logger.info(
                    "LLM recovery: %s — escalating max_tokens to %d before retry "
                    "(attempt=%d/%d)",
                    category,
                    self.escalated_max_tokens,
                    attempt,
                    self.max_retries,
                )
                return RecoveryAction(
                    action=RecoveryActionType.RETRY,
                    retry_delay_ms=0,
                    message=(
                        f"Output truncated — escalating max_tokens to "
                        f"{self.escalated_max_tokens}"
                    ),
                )
            logger.warning(
                "LLM recovery FAILED (%s still truncated after escalation): "
                "attempt=%d/%d | %s",
                category,
                attempt,
                self.max_retries,
                str(error),
            )
            return RecoveryAction(
                action=RecoveryActionType.FAIL,
                message="Output still truncated after max_tokens escalation",
            )

        # --- Transient faults: 429 rate limit / 529 overloaded / network /
        # generic 5xx — all retried with exponential backoff. Only 529 can
        # trigger a fallback-model switch.
        if (
            self._is_rate_limit_error(error)
            or self._is_overloaded_error(error)
            or self._is_network_error(error)
            or self._is_server_error(error)
        ):
            return self._handle_transient(error, attempt, category)

        # --- Non-transient: fail immediately -----------------------------
        logger.warning(
            "LLM recovery FAILED (non-retryable %s): attempt=%d/%d | %s",
            category,
            attempt,
            self.max_retries,
            str(error),
        )
        return RecoveryAction(
            action=RecoveryActionType.FAIL, message=f"LLM error: {str(error)}"
        )

    # -- classification helpers --------------------------------------------

    @staticmethod
    def _error_text(error: Exception) -> str:
        return f"{type(error).__name__} {error}"

    @classmethod
    def _classify_error(cls, error: Exception) -> str:
        """Return a short, human-readable category label for ``error``.

        Mirrors the classification order in :meth:`handle_llm_error` so the log
        category matches the recovery branch actually taken. Order matters: a
        400 mentioning "max_tokens" must be reported as a client error, not as
        truncation.
        """
        if cls._is_auth_error(error):
            return "auth_error"
        if cls._is_client_error(error):
            return "client_error"
        if cls._is_context_too_long_error(error):
            return "context_too_long"
        if cls._is_truncation_error(error):
            return "output_truncated"
        if cls._is_overloaded_error(error):
            return "overloaded_529"
        if cls._is_rate_limit_error(error):
            return "rate_limit_429"
        if cls._is_network_error(error):
            return "network_error"
        if cls._is_server_error(error):
            return "server_error_5xx"
        return "unknown"

    @classmethod
    def _is_truncation_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _TRUNCATION_MARKERS)

    @classmethod
    def _is_context_too_long_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _CONTEXT_TOO_LONG_MARKERS)

    @classmethod
    def _is_rate_limit_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _RATE_LIMIT_MARKERS)

    @classmethod
    def _is_overloaded_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _OVERLOADED_MARKERS)

    @classmethod
    def _is_auth_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _AUTH_ERROR_MARKERS)

    @classmethod
    def _is_client_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _CLIENT_ERROR_MARKERS)

    @classmethod
    def _is_network_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _NETWORK_MARKERS)

    @classmethod
    def _is_server_error(cls, error: Exception) -> bool:
        return _matches_any(cls._error_text(error), _SERVER_ERROR_MARKERS)

    # -- transient-fault handling ------------------------------------------

    def _handle_transient(
        self, error: Exception, attempt: int, category: str = "transient"
    ) -> RecoveryAction:
        """Exponential backoff for 429/529; switch model after repeated 529s."""
        is_overloaded = self._is_overloaded_error(error)

        if is_overloaded:
            self._state.consecutive_529 += 1
        else:
            # A 429 resets the overloaded streak.
            self._state.consecutive_529 = 0

        # Switch to the fallback model once we've hit the 529 threshold.
        if (
            is_overloaded
            and self._state.consecutive_529 >= self.max_consecutive_529
            and self.fallback_model
            and self._state.current_model != self.fallback_model
        ):
            self._state.current_model = self.fallback_model
            self._state.consecutive_529 = 0
            delay_ms = self._retry_delay(attempt)
            logger.warning(
                "LLM recovery: %s — %d consecutive 529s, switching to fallback "
                "model '%s' and retrying after %dms (attempt=%d/%d)",
                category,
                self.max_consecutive_529,
                self.fallback_model,
                delay_ms,
                attempt,
                self.max_retries,
            )
            return RecoveryAction(
                action=RecoveryActionType.RETRY,
                retry_delay_ms=delay_ms,
                switch_model=self.fallback_model,
                message=(
                    f"Repeated 529 errors — switching to fallback model "
                    f"'{self.fallback_model}'"
                ),
            )

        # Exhausted the retry budget — give up.
        if attempt >= self.max_retries:
            logger.warning(
                "LLM recovery FAILED (%s — max retries %d exceeded): "
                "attempt=%d/%d | %s",
                category,
                self.max_retries,
                attempt,
                self.max_retries,
                str(error),
            )
            return RecoveryAction(
                action=RecoveryActionType.FAIL,
                message=(
                    f"Max retries ({self.max_retries}) exceeded for "
                    f"transient LLM error: {error}"
                ),
            )

        delay_ms = self._retry_delay(attempt)
        logger.info(
            "LLM recovery: %s — retrying after %dms backoff (attempt=%d/%d)",
            category,
            delay_ms,
            attempt,
            self.max_retries,
        )
        return RecoveryAction(
            action=RecoveryActionType.RETRY,
            retry_delay_ms=delay_ms,
            message=f"Transient LLM error — retrying after backoff (attempt {attempt})",
        )

    def _retry_delay(self, attempt: int, retry_after_ms: Optional[int] = None) -> int:
        """Compute an exponential backoff delay in milliseconds.

        ``base = min(BASE * 2^attempt, MAX)`` plus a random jitter of up to
        ``jitter_fraction * base``. If a server-supplied ``retry_after`` is
        provided, it is honored instead.
        """
        if retry_after_ms is not None:
            return max(0, int(retry_after_ms))
        base = min(self.base_delay_ms * (2 ** (attempt - 1)), self.max_delay_ms)
        jitter = uniform(0, base * self.jitter_fraction)  # noqa: S311 - non-crypto jitter
        return int(base + jitter)

    # -- reactive compaction ------------------------------------------------

    def _reactive_compact(self, request: "LlmRequest") -> None:
        """In-place "emergency" compaction of ``request.messages``.

        Keeps the first ``compact_keep_first`` messages (system/tool setup) and
        the most recent ``compact_keep_recent`` messages verbatim, and replaces
        everything in between with a single summary placeholder. This mirrors
        the ``reactive_compact()`` step in ``docs/harness-error-recovery.md``:
        cheap, deterministic, and guaranteed to shrink the context.

        No-op when the message list is already short enough to fit in the keep
        windows.
        """
        messages = request.messages
        keep_first = max(0, self.compact_keep_first)
        keep_recent = max(0, self.compact_keep_recent)

        if len(messages) <= keep_first + keep_recent:
            return  # Nothing to compact

        head = messages[:keep_first]
        middle = messages[keep_first : len(messages) - keep_recent]
        tail = messages[len(messages) - keep_recent :]

        # Summarize the dropped middle as a single synthetic user note. We don't
        # call an LLM here (that would be a retry inside a retry); a structural
        # placeholder is enough to free context while preserving turn order.
        dropped_roles = [m.role for m in middle]
        summary = LlmMessage(
            role="user",
            content=(
                f"[Context compacted — {len(middle)} earlier "
                f"message(s) ({', '.join(sorted(set(dropped_roles)))}) "
                f"elided to fit the context window.]"
            ),
        )

        request.messages = head + [summary] + tail
