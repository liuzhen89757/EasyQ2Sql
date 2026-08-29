"""Observer for the ``run_sql`` tool.

Records execution facts into the shared ``ToolUsageTracker`` and performs
SQL-skeleton freeze detection. Intervention is done separately by
``easyq2sql.hooks.middleware.sql_regulator.SqlRegulatorMiddleware``.
"""

import logging
from contextvars import ContextVar
from typing import Optional

from ..regulator import (
    RUN_SQL_POLICY,
    RequestScope,
    _request_scope,
    _try_freeze,
    get_default_tool_usage_tracker,
)
from easyq2sql.core.lifecycle import LifecycleHook

logger = logging.getLogger(__name__)


class SqlRegulatorHook(LifecycleHook):
    """Observe ``run_sql`` and record its execution facts into the tracker."""

    tool_name = "run_sql"
    policy = RUN_SQL_POLICY

    def __init__(self, tracker=None) -> None:
        self._tracker = tracker or get_default_tool_usage_tracker()
        # Per-instance contextvar: each hook attributes only its own tool, so
        # multiple regulators registered together never clobber each other.
        self._current_tool: ContextVar[Optional[str]] = ContextVar(
            f"easyq2sql_regulator_current_tool_{id(self)}", default=None
        )

    async def before_tool(self, tool, context) -> None:
        if tool.name != self.tool_name:
            return
        _request_scope.set(
            RequestScope(
                request_id=context.request_id,
                conversation_id=context.conversation_id,
                user_id=context.user.id,
            )
        )
        self._current_tool.set(tool.name)
        await self._tracker.record_call(context.request_id, tool.name)
        logger.info("Tool %s invoked (request_id=%s)", tool.name, context.request_id)

    async def after_tool(self, result):
        tool_name = self._current_tool.get()
        self._current_tool.set(None)
        if not tool_name:
            return None
        scope = _request_scope.get()
        if scope is None:
            return None
        await self._tracker.record_result(scope.request_id, tool_name, result)

        md = result.metadata or {}
        if not result.success:
            logger.warning(
                "Tool %s failed (request_id=%s): %s",
                tool_name, scope.request_id, result.error,
            )
        elif md.get("row_count") == 0:
            logger.warning(
                "Tool %s returned empty result (request_id=%s)",
                tool_name, scope.request_id,
            )

        # run_sql only: detect a stable-yet-rerun SQL skeleton.
        sql = md.get("sql")
        if sql:
            record = await self._tracker.get_record(scope.request_id, tool_name)
            _try_freeze(record, self.policy, sql, md.get("row_count"))
            if record.frozen_skeleton is not None:
                logger.warning(
                    "run_sql skeleton frozen (request_id=%s): %s",
                    scope.request_id, record.frozen_skeleton,
                )
        return None  # observe only — never rewrite the result

    async def after_message(self, result) -> None:
        # Request done: free per-request records and clear task-local scope.
        scope = _request_scope.get()
        if scope is not None:
            self._tracker.drop_request(scope.request_id)
            logger.debug(
                "Tool %s regulator cleaned up request %s",
                self.tool_name, scope.request_id,
            )
        _request_scope.set(None)
