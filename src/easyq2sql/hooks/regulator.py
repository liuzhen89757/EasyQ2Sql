"""Shared engine for per-request tool-execution regulation.

This module is framework-neutral: both the observing hooks
(``easyq2sql.hooks.lifecycle.*``) and the intervening middlewares
(``easyq2sql.hooks.middleware.*``) import from here, so a middleware never has
to reach into ``easyq2sql.hooks.lifecycle``.

Contents:

* ``ToolUsageTracker`` / ``ToolUsageRecord`` — per-request, per-tool observed facts
* ``ToolLimitPolicy`` / ``ToolState`` / ``evaluate_state`` — thresholds + derived state
* ``extract_sql_skeleton`` / ``describe_sql_shape`` / ``_try_freeze`` — run_sql convergence
* ``RequestScope`` / ``_request_scope`` — task-local scope bridging hook -> middleware
* ``get_default_tool_usage_tracker`` — process-wide default tracker singleton
* Per-tool policies: ``RUN_SQL_POLICY`` / ``SCHEMA_SEARCH_POLICY`` / ``METRIC_SEARCH_POLICY``
"""

import asyncio
import re
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Dict, NamedTuple, Optional, Set

import sqlparse
from sqlparse import tokens as T


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class ToolState(str, Enum):
    """Derived state of a tool within the current request."""

    OK = "ok"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class ToolLimitPolicy:
    """Per-tool thresholds and intervention copy.

    ``hard_block=False`` marks tools (e.g. ``run_sql``) that must never be
    removed from the LLM request — they only ever receive soft guidance.
    """

    warn_calls: int = 3
    block_calls: int = 5
    max_errors: int = 2
    max_empty: int = 3
    max_repeat: int = 3
    max_no_new: int = 2
    hard_block: bool = True
    freeze_reproduce: int = 2
    freeze_iterations: int = 3
    warn_text: str = "Called too many times; stop repeating."
    block_text: str = "Call limit reached; this tool is now disabled."


# ---------------------------------------------------------------------------
# Per-tool policies
# ---------------------------------------------------------------------------


# run_sql: data retrieval is the core goal — soft guidance only, never remove
# the tool. `block_calls`/`max_empty`/`max_repeat`/`max_no_new` are unused.
RUN_SQL_POLICY = ToolLimitPolicy(
    warn_calls=2,
    block_calls=0,
    max_errors=3,
    max_empty=0,
    max_repeat=0,
    max_no_new=0,
    hard_block=False,
    freeze_reproduce=2,
    freeze_iterations=3,
    warn_text="注意 SQL 正确性，已执行多次，请勿盲目重试。",
    block_text="",
)

# search_table_schema: retrieval tool — soft + hard intervention (BLOCK removes it).
SCHEMA_SEARCH_POLICY = ToolLimitPolicy(
    warn_calls=3,
    block_calls=5,
    max_errors=2,
    max_empty=3,
    max_repeat=3,
    max_no_new=2,
    hard_block=True,
    warn_text="已多次搜索表结构，建议停止重复搜索，基于已有 schema 生成回答，或向用户确认表名。",
    block_text="调用次数已达上限，该工具已停用。请基于已有信息作答，或请用户澄清。",
)

# search_metrics: retrieval tool — soft + hard intervention (BLOCK removes it).
METRIC_SEARCH_POLICY = ToolLimitPolicy(
    warn_calls=3,
    block_calls=5,
    max_errors=2,
    max_empty=3,
    max_repeat=3,
    max_no_new=2,
    hard_block=True,
    warn_text="已多次搜索指标，建议向用户确认 metric/dimension 口径，而非继续搜索。",
    block_text="调用次数已达上限，该工具已停用。请基于已有信息作答，或请用户澄清。",
)


class ToolUsageRecord:
    """Per-request, per-tool observed execution facts."""

    def __init__(self) -> None:
        self.calls: int = 0
        self.successes: int = 0
        self.errors: int = 0
        self.consecutive_errors: int = 0
        self.empties: int = 0
        self.last_query: Optional[str] = None
        self.query_repeat_count: int = 0
        self.seen_tables: Set[str] = set()
        self.no_new_streak: int = 0
        self.skeleton_counts: Dict[str, int] = {}
        self.frozen_skeleton: Optional[str] = None


class ToolUsageTracker:
    """Keyed by ``request_id`` — the limit scope is a single user message."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, ToolUsageRecord]] = {}
        self._lock = asyncio.Lock()

    def _get(self, request_id: str, tool_name: str) -> ToolUsageRecord:
        return self._records.setdefault(request_id, {}).setdefault(
            tool_name, ToolUsageRecord()
        )

    async def record_call(self, request_id: str, tool_name: str) -> None:
        async with self._lock:
            self._get(request_id, tool_name).calls += 1

    async def record_result(
        self, request_id: str, tool_name: str, result
    ) -> None:
        async with self._lock:
            rec = self._get(request_id, tool_name)
            md = result.metadata or {}

            if not result.success:
                rec.errors += 1
                rec.consecutive_errors += 1
            else:
                rec.successes += 1
                rec.consecutive_errors = 0

            # Retrieval facts: query repetition + no-new-tables + empty.
            query = md.get("query")
            if query is not None:
                if query == rec.last_query:
                    rec.query_repeat_count += 1
                else:
                    rec.query_repeat_count = 0
                rec.last_query = query

            tables = (
                list(md.get("tables") or [])
                + list(md.get("matched_metrics") or [])
                + list(md.get("matched_dimensions") or [])
            )
            if tables:
                new_tables = [t for t in tables if t not in rec.seen_tables]
                if not new_tables:
                    rec.no_new_streak += 1
                else:
                    rec.no_new_streak = 0
                rec.seen_tables.update(tables)

            match_count = md.get("match_count")
            row_count = md.get("row_count")
            if match_count == 0 or row_count == 0:
                rec.empties += 1

            # run_sql: SQL skeleton reproduction.
            sql = md.get("sql")
            if sql:
                skeleton = extract_sql_skeleton(sql)
                rec.skeleton_counts[skeleton] = rec.skeleton_counts.get(skeleton, 0) + 1

    async def get_record(
        self, request_id: str, tool_name: str
    ) -> ToolUsageRecord:
        async with self._lock:
            return self._get(request_id, tool_name)

    def drop_request(self, request_id: str) -> None:
        self._records.pop(request_id, None)


def evaluate_state(policy: ToolLimitPolicy, record: ToolUsageRecord) -> ToolState:
    """Derive OK/WARN/BLOCK from policy + observed facts (pure function)."""
    if record.frozen_skeleton is not None:
        # A frozen skeleton means "converged but still re-running" — soft-guide only.
        return ToolState.WARN

    if not policy.hard_block:
        # run_sql: never BLOCK, only soft guidance.
        if (
            record.calls >= policy.warn_calls
            or record.consecutive_errors >= policy.max_errors
        ):
            return ToolState.WARN
        return ToolState.OK

    if (
        record.calls >= policy.block_calls
        or record.consecutive_errors >= policy.max_errors
        or record.empties >= policy.max_empty
        or record.query_repeat_count >= policy.max_repeat
        or record.no_new_streak >= policy.max_no_new
    ):
        return ToolState.BLOCK

    if record.calls >= policy.warn_calls:
        return ToolState.WARN

    return ToolState.OK


# Process-wide default tracker (lazily created). All regulator hooks and
# middlewares default to this instance, so they stay in sync without the
# caller wiring a shared instance by hand.
_default_tracker: Optional[ToolUsageTracker] = None
_default_tracker_lock = threading.Lock()


def get_default_tool_usage_tracker() -> ToolUsageTracker:
    """Return the process-wide default :class:`ToolUsageTracker`.

    Created lazily on first use; callers who want per-Agent isolation can
    still construct and pass their own tracker explicitly.
    """
    global _default_tracker
    with _default_tracker_lock:
        if _default_tracker is None:
            _default_tracker = ToolUsageTracker()
        return _default_tracker


# ---------------------------------------------------------------------------
# Scope bridging (hook -> middleware) via task-local contextvars
# ---------------------------------------------------------------------------


class RequestScope(NamedTuple):
    request_id: str
    conversation_id: str
    user_id: str


# Set by a hook in ``before_tool``; read by a middleware in
# ``before_llm_request``. Both run inside the same ``_send_message`` task,
# so contextvars give correct per-request isolation with no cross-talk.
_request_scope: ContextVar[Optional[RequestScope]] = ContextVar(
    "easyq2sql_regulator_scope", default=None
)


# ---------------------------------------------------------------------------
# SQL skeleton extraction (run_sql convergence)
# ---------------------------------------------------------------------------


def _is_placeholder_token(ttype) -> bool:
    """True for identifiers (names) and literals — replaced by a placeholder."""
    return ttype is not None and (ttype in T.Name or ttype in T.Literal)


def extract_sql_skeleton(sql: str) -> str:
    """Normalize SQL into a structural skeleton.

    Replaces identifiers/literals with a single ``?`` placeholder, upper-cases
    keywords, and preserves punctuation/operators and structural keywords
    (JOIN / GROUP BY / window / rollup).

    Examples::

        "SELECT name FROM users WHERE id = 3"        -> "SELECT ? FROM ? WHERE ? = ?"
        "SELECT dept, SUM(sal) FROM t GROUP BY dept" -> "SELECT ? , ? ( ? ) FROM ? GROUP BY ?"
    """
    statements = sqlparse.parse(sql)
    if not statements:
        return " ".join(sql.split()).upper()

    out: list = []
    prev_placeholder = False
    for tok in statements[0].flatten():
        if tok.is_whitespace:
            if out and out[-1] != " ":
                out.append(" ")
            continue
        if _is_placeholder_token(tok.ttype):
            if not prev_placeholder:
                out.append("?")
                prev_placeholder = True
            continue
        prev_placeholder = False
        if tok.ttype and tok.ttype in T.Keyword:
            out.append(tok.value.upper())
        else:
            out.append(tok.value)
    return " ".join("".join(out).split())


def describe_sql_shape(sql: str) -> Dict[str, bool]:
    """Coarse structural features used for granularity alignment."""
    u = sql.upper()
    return {
        "has_join": bool(re.search(r"\bJOIN\b", u)),
        "has_group_by": bool(re.search(r"\bGROUP\s+BY\b", u)),
        "has_window": bool(re.search(r"\bOVER\s*\(", u)),
        "has_rollup": bool(re.search(r"\b(ROLLUP|CUBE|GROUPING\s+SETS)\b", u)),
        "is_aggregate": bool(re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", u)),
        "has_subquery": u.count("SELECT") > 1,
    }


# Aggregated results are expected to be small (one row per group).
_AGGREGATE_MAX_ROWS = 10000


def _granularity_aligned(shape: Dict[str, bool], row_count) -> bool:
    if row_count is None:
        return True  # no row info -> cannot judge, assume aligned
    if shape["is_aggregate"] and row_count > _AGGREGATE_MAX_ROWS:
        return False
    return True


def _has_no_gaps(sql: str) -> bool:
    """Best-effort structural completeness check (every JOIN has an ON)."""
    u = sql.upper()
    if not re.search(r"\bFROM\b", u):
        return False
    joins = len(re.findall(r"\bJOIN\b", u))
    ons = len(re.findall(r"\bON\b", u))
    return joins <= ons


def _try_freeze(
    rec: ToolUsageRecord, policy: ToolLimitPolicy, sql: str, row_count
) -> None:
    """Freeze a run_sql skeleton once it is stable yet still being re-run."""
    if rec.frozen_skeleton is not None:
        return
    skeleton = extract_sql_skeleton(sql)
    if rec.skeleton_counts.get(skeleton, 0) < policy.freeze_reproduce:
        return
    if rec.calls < policy.freeze_iterations:
        return
    shape = describe_sql_shape(sql)
    if not _granularity_aligned(shape, row_count) or not _has_no_gaps(sql):
        return
    rec.frozen_skeleton = skeleton
