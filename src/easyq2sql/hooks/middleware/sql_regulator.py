"""Intervener for the ``run_sql`` tool.

Only injects soft guidance into ``system_prompt``; ``run_sql`` is never
removed from ``request.tools`` (data retrieval is the core goal).
"""

import logging

from ..regulator import (
    RUN_SQL_POLICY,
    ToolState,
    _request_scope,
    evaluate_state,
    get_default_tool_usage_tracker,
)
from easyq2sql.core.middleware import LlmMiddleware

logger = logging.getLogger(__name__)


class SqlRegulatorMiddleware(LlmMiddleware):
    """Constrain ``run_sql``: soft guidance only, never remove the tool."""

    tool_name = "run_sql"
    policy = RUN_SQL_POLICY

    def __init__(self, tracker=None) -> None:
        self._tracker = tracker or get_default_tool_usage_tracker()

    async def before_llm_request(self, request):
        scope = _request_scope.get()
        if scope is None or request.tools is None:
            # First round (no tool calls yet) or nothing to filter: no-op.
            return request

        record = await self._tracker.get_record(scope.request_id, self.tool_name)
        state = evaluate_state(self.policy, record)
        if state is ToolState.OK:
            return request

        logger.info(
            "Tool %s state=%s (request_id=%s): injecting guidance",
            self.tool_name, state.value, scope.request_id,
        )

        text = (
            self.policy.warn_text
            if state is ToolState.WARN
            else (self.policy.block_text or self.policy.warn_text)
        )
        guidance = f"[Tool‑Use Constraints]\n- {self.tool_name}: {text}"
        request.system_prompt = (request.system_prompt or "") + "\n\n" + guidance

        # Hard intervention only for hard_block=True tools; run_sql is soft-only.
        if state is ToolState.BLOCK and self.policy.hard_block:
            request.tools = [
                s for s in request.tools if getattr(s, "name", None) != self.tool_name
            ]
            logger.warning(
                "Tool %s BLOCKED (request_id=%s): removed from request.tools",
                self.tool_name, scope.request_id,
            )

        return request
