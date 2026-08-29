"""Tests for the ``run_sql`` pre-execution security registry.

Covers every checkpoint of :class:`EnhancedToolRegistry.transform_args`:
injection, stacked queries, read-only governance, complexity limits,
forbidden tables/functions, semantic shape checks, and RLS rewriting — plus
the end-to-end flow where a :class:`ToolRejection` becomes a failed
``ToolResult`` via ``ToolRegistry.execute``.
"""

from typing import Type, TypeVar

import pytest
from pydantic import BaseModel, Field

from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs
from easyq2sql.core.tool import Tool, ToolCall, ToolContext, ToolResult, ToolRejection
from easyq2sql.core.user import User
from easyq2sql.integrations.local.agent_memory import DemoAgentMemory
from easyq2sql.enhanced_tool_registry import (
    RlsConfig,
    RlsTableConfig,
    SqlSecurityConfig,
    EnhancedToolRegistry,
)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_memory():
    return DemoAgentMemory(max_items=100)


@pytest.fixture
def user():
    return User(id="u1", username="alice", group_memberships=["china"])


@pytest.fixture
def registry():
    """Registry with the bundled default config (blocked functions etc.)."""
    return EnhancedToolRegistry()


def make_context(user, agent_memory):
    return ToolContext(
        user=user,
        conversation_id="conv",
        request_id="req",
        agent_memory=agent_memory,
    )


async def run_sql(registry, sql, user, agent_memory):
    return await registry.transform_args(
        tool=None,
        args=RunSqlToolArgs(sql=sql),
        user=user,
        context=make_context(user, agent_memory),
    )


class OtherToolArgs(BaseModel):
    query: str = Field(description="a non-SQL argument")


class MockRunSqlTool(Tool[RunSqlToolArgs]):
    """Minimal run_sql-shaped tool for the end-to-end execute() test."""

    @property
    def name(self) -> str:
        return "run_sql"

    @property
    def description(self) -> str:
        return "mock run_sql"

    def get_args_schema(self) -> Type[RunSqlToolArgs]:
        return RunSqlToolArgs

    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        return ToolResult(success=True, result_for_llm="executed")


# ---------------------------------------------------------------------------
# Injection / stacked queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_injection_into_outfile_rejected(registry, user, agent_memory):
    out = await run_sql(registry, "SELECT * FROM orders INTO OUTFILE '/tmp/x'", user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "OUTFILE" in out.reason


@pytest.mark.asyncio
async def test_stacked_query_rejected(registry, user, agent_memory):
    out = await run_sql(registry, "SELECT 1; DROP TABLE users", user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "multiple statements" in out.reason


@pytest.mark.asyncio
async def test_unparseable_sql_rejected(registry, user, agent_memory):
    out = await run_sql(registry, "SELECT FROM WHERE", user, agent_memory)
    assert isinstance(out, ToolRejection)


# ---------------------------------------------------------------------------
# Read-only governance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "CREATE TABLE t (a int)",
    ],
)
async def test_write_statements_rejected(registry, user, agent_memory, sql):
    out = await run_sql(registry, sql, user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "read-only" in out.reason


@pytest.mark.asyncio
async def test_select_and_cte_allowed(registry, user, agent_memory):
    out = await run_sql(registry, "SELECT * FROM t", user, agent_memory)
    assert not isinstance(out, ToolRejection)

    out = await run_sql(
        registry, "WITH x AS (SELECT 1) SELECT * FROM x", user, agent_memory
    )
    assert not isinstance(out, ToolRejection)


# ---------------------------------------------------------------------------
# Complexity / resource limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_too_long_rejected(registry, user, agent_memory):
    sql = "SELECT '" + "x" * 10001 + "'"
    out = await run_sql(registry, sql, user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "too long" in out.reason


@pytest.mark.asyncio
async def test_too_many_subqueries_rejected(registry, user, agent_memory):
    sql = "SELECT " + ", ".join(f"(SELECT {i})" for i in range(6))
    out = await run_sql(registry, sql, user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "subqueries" in out.reason


@pytest.mark.asyncio
async def test_too_many_joins_rejected(registry, user, agent_memory):
    joins = " ".join(f"JOIN t{i} ON 1=1" for i in range(16))
    sql = f"SELECT * FROM t0 {joins}"
    out = await run_sql(registry, sql, user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "JOIN" in out.reason


@pytest.mark.asyncio
async def test_limit_upper_bound(registry, user, agent_memory):
    assert not isinstance(
        await run_sql(registry, "SELECT * FROM t LIMIT 100", user, agent_memory),
        ToolRejection,
    )
    out = await run_sql(registry, "SELECT * FROM t LIMIT 50000", user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "LIMIT" in out.reason


# ---------------------------------------------------------------------------
# Forbidden tables / functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_function_rejected(registry, user, agent_memory):
    out = await run_sql(registry, "SELECT SLEEP(5)", user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "forbidden function" in out.reason


@pytest.mark.asyncio
async def test_forbidden_table_rejected(user, agent_memory):
    cfg = SqlSecurityConfig(
        query_limits={"enabled": True, "forbidden_tables": ["payroll.salaries"]}
    )
    reg = EnhancedToolRegistry()
    reg.config = cfg

    out = await run_sql(reg, "SELECT * FROM payroll.salaries", user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "forbidden table" in out.reason

    # Aliased reference is still caught.
    out = await run_sql(reg, "SELECT * FROM payroll.salaries s", user, agent_memory)
    assert isinstance(out, ToolRejection)


# ---------------------------------------------------------------------------
# Semantic shape checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_requires_on_or_using(registry, user, agent_memory):
    assert not isinstance(
        await run_sql(registry, "SELECT * FROM a JOIN b ON a.id = b.id", user, agent_memory),
        ToolRejection,
    )
    assert not isinstance(
        await run_sql(registry, "SELECT * FROM a CROSS JOIN b", user, agent_memory),
        ToolRejection,
    )
    out = await run_sql(registry, "SELECT * FROM a JOIN b", user, agent_memory)
    assert isinstance(out, ToolRejection)
    assert "ON or USING" in out.reason


@pytest.mark.asyncio
async def test_non_aggregated_column_must_be_in_group_by(registry, user, agent_memory):
    assert not isinstance(
        await run_sql(
            registry, "SELECT dept, COUNT(*) FROM emp GROUP BY dept", user, agent_memory
        ),
        ToolRejection,
    )
    out = await run_sql(
        registry, "SELECT dept, name, COUNT(*) FROM emp GROUP BY dept", user, agent_memory
    )
    assert isinstance(out, ToolRejection)
    assert "GROUP BY" in out.reason


# ---------------------------------------------------------------------------
# Row-level security
# ---------------------------------------------------------------------------


def _rls_registry():
    cfg = SqlSecurityConfig(
        row_level_security=RlsConfig(
            enabled=True,
            group_value_mapping={"china": ["CN"], "admin": ["*"]},
            protected_tables=[RlsTableConfig(table="sales.orders", column="region")],
        )
    )
    reg = EnhancedToolRegistry()
    reg.config = cfg
    return reg


@pytest.mark.asyncio
async def test_rls_injects_filter(agent_memory):
    reg = _rls_registry()
    u = User(id="u1", group_memberships=["china"])
    out = await run_sql(reg, "SELECT * FROM sales.orders WHERE status = 'open'", u, agent_memory)
    assert not isinstance(out, ToolRejection)
    assert "orders.region IN ('CN')" in out.sql
    assert "region IS NULL" in out.sql


@pytest.mark.asyncio
async def test_rls_respects_alias(agent_memory):
    reg = _rls_registry()
    u = User(id="u1", group_memberships=["china"])
    out = await run_sql(
        reg,
        "SELECT o.* FROM sales.orders o JOIN sales.order_items i ON i.order_id = o.order_id",
        u,
        agent_memory,
    )
    assert not isinstance(out, ToolRejection)
    assert "o.region IN ('CN')" in out.sql


@pytest.mark.asyncio
async def test_rls_wildcard_group_has_full_access(agent_memory):
    reg = _rls_registry()
    u = User(id="u2", group_memberships=["admin"])
    out = await run_sql(reg, "SELECT * FROM sales.orders", u, agent_memory)
    assert not isinstance(out, ToolRejection)
    assert "region" not in out.sql  # untouched


@pytest.mark.asyncio
async def test_rls_no_groups_yields_no_access(agent_memory):
    reg = _rls_registry()
    u = User(id="u3", group_memberships=[])
    out = await run_sql(reg, "SELECT * FROM sales.orders", u, agent_memory)
    assert not isinstance(out, ToolRejection)
    assert "FALSE" in out.sql


# ---------------------------------------------------------------------------
# Passthrough + end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_run_sql_args_pass_through(registry, user, agent_memory):
    args = OtherToolArgs(query="not sql")
    out = await registry.transform_args(
        tool=None, args=args, user=user, context=make_context(user, agent_memory)
    )
    assert out is args  # untouched, not a ToolRejection


@pytest.mark.asyncio
async def test_rejection_becomes_failed_result_via_execute(agent_memory, user):
    reg = EnhancedToolRegistry()
    reg.register_local_tool(MockRunSqlTool(), access_groups=[])

    tool_call = ToolCall(
        id="c1",
        name="run_sql",
        arguments={"sql": "SELECT * FROM t INTO OUTFILE '/tmp/x'"},
    )
    result = await reg.execute(tool_call, make_context(user, agent_memory))

    assert result.success is False
    assert "OUTFILE" in result.result_for_llm
    assert result.error == result.result_for_llm
