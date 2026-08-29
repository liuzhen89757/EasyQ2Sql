"""Enhanced tool registry for the ``run_sql`` tool.

A drop-in replacement for :class:`easyq2sql.core.registry.ToolRegistry` that
applies pre-execution safety checks and row-level-security (RLS) rewrites to
SQL before it reaches the ``run_sql`` tool.

Checks run in order (cheap rejections first, rewrite last):

1. SQL injection / dangerous patterns (regex on the raw SQL string).
2. Syntax + single-statement validation (sqlglot parse).
3. Read-only / write-statement governance.
4. Query complexity / resource limits.
5. Forbidden tables / dangerous functions (AST extraction).
6. SQL shape semantics (AST heuristics).
7. Row-level security (RLS) rewrite (AST, SELECT only).

The class overrides only :meth:`ToolRegistry.transform_args`. The base
:meth:`ToolRegistry.execute` already converts a returned
:class:`~easyq2sql.core.tool.ToolRejection` into a failed ``ToolResult`` whose
``result_for_llm`` carries the rejection reason back to the LLM.

.. note::

    Convergence concerns (repeated / frozen SQL skeletons) are intentionally
    NOT handled here — they belong to ``easyq2sql.hooks.regulator``
    (lifecycle hook + LLM middleware soft guidance). The two mechanisms are
    independent and can be stacked.
"""

from __future__ import annotations

import logging
import re
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TypeVar, Union, cast

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.expressions.core import Expression

from easyq2sql.capabilities.sql_runner.models import RunSqlToolArgs
from easyq2sql.core.registry import ToolRegistry
from easyq2sql.core.tool import Tool, ToolContext, ToolRejection
from easyq2sql.core.user import User

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class PatternConfig(BaseModel):
    """A single regex pattern used by the injection check."""

    model_config = ConfigDict(extra="ignore")

    pattern: str
    description: str = ""
    case_sensitive: bool = False
    # When True, this pattern is skipped for metadata-introspection queries
    # (queries that match an entry in ``allowed_metadata_patterns``).
    metadata_related: bool = False


class InjectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    allowed_metadata_patterns: List[PatternConfig] = Field(default_factory=list)
    forbidden_patterns: List[PatternConfig] = Field(default_factory=list)

    @field_validator("allowed_metadata_patterns", "forbidden_patterns", mode="before")
    @classmethod
    def _coerce_patterns(cls, value: Any) -> Any:
        """Accept plain strings or dicts in YAML pattern lists."""
        if value is None:
            return []
        return [{"pattern": item} if isinstance(item, str) else item for item in value]


class GovernanceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    read_only: bool = True


class QueryLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    max_query_length: int = 10000
    max_subqueries: int = 5
    max_cte_depth: int = 3
    max_joins: int = 15
    max_result_rows: int = 10000
    forbidden_tables: List[str] = Field(default_factory=list)
    blocked_functions: List[str] = Field(default_factory=list)


class SemanticsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    check_join: bool = True
    check_aggregation: bool = True
    check_window: bool = True
    check_rollup: bool = True
    check_partition_constant: bool = True
    check_outer_join_null_filter: bool = True
    require_partition_by_for_window_cues: bool = True


class RlsTableConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    table: str
    column: str = ""
    via: Optional[Dict[str, str]] = None
    description: str = ""


class RlsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    group_value_mapping: Dict[str, List[Any]] = Field(default_factory=dict)
    protected_tables: List[RlsTableConfig] = Field(default_factory=list)


class AuditConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    log_sql_transformations: bool = True
    log_rejected_queries: bool = True


class SqlSecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sql_injection: InjectionConfig = Field(default_factory=InjectionConfig)
    query_governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    query_limits: QueryLimitsConfig = Field(default_factory=QueryLimitsConfig)
    sql_semantics: SemanticsConfig = Field(default_factory=SemanticsConfig)
    row_level_security: RlsConfig = Field(default_factory=RlsConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_sql_security_config(
    config_path: str = "sql_security_config.yaml",
) -> SqlSecurityConfig:
    """Load :class:`SqlSecurityConfig` from a YAML file.

    Resolution order: explicit path -> package resource -> same directory as
    this module -> built-in defaults.
    """
    path = Path(config_path)
    data: Optional[dict] = None

    if path.exists():
        data = _read_yaml(path)
    else:
        try:
            resource = resources.files("easyq2sql").joinpath(config_path)
            if resource.is_file():
                data = yaml.safe_load(resource.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover - best-effort fallback
            data = None

        if data is None:
            fallback = Path(__file__).parent / config_path
            if fallback.exists():
                data = _read_yaml(fallback)

    if data is None:
        logger.warning(
            "SQL security config not found at %s, using defaults", config_path
        )
        return SqlSecurityConfig()

    return SqlSecurityConfig.model_validate(data)


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class _MultipleStatementsError(Exception):
    """Raised when a query contains more than one SQL statement."""


class EnhancedToolRegistry(ToolRegistry):
    """ToolRegistry that applies SQL safety checks + RLS before ``run_sql``.

    Args:
        config_path: Path to the ``sql_security_config.yaml`` file.
        audit_logger: Optional audit logger (forwarded to the base registry).
        audit_config: Optional audit config (forwarded to the base registry).
    """

    def __init__(
        self,
        config_path: str = "sql_security_config.yaml",
        audit_logger=None,
        audit_config=None,
    ) -> None:
        super().__init__(audit_logger=audit_logger, audit_config=audit_config)
        self.config = load_sql_security_config(config_path)

    # -- transform_args ----------------------------------------------------

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: User,
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Validate and (optionally) rewrite ``run_sql`` arguments.

        Only ``run_sql`` is guarded, identified by its argument model
        (``RunSqlToolArgs``) so that custom tool names are still covered.
        ``tool`` is unused here (the guard is the argument model); it is kept
        to match the base-class override signature.
        """
        del tool  # not used: the RunSqlToolArgs isinstance check is the guard
        if not isinstance(args, RunSqlToolArgs):
            return args

        sql = args.sql
        dialect = str(context.metadata.get("dialect") or "").strip() or None

        # 1. Injection / dangerous patterns (raw-string regex).
        reason = self._check_injection(sql)
        if reason:
            return self._reject(user, reason)

        # 2. Parse + single-statement / syntax validation.
        try:
            ast = self._parse_single(sql, dialect)
        except ParseError:
            return self._reject(user, "unparseable SQL (syntax error)")
        except _MultipleStatementsError:
            return self._reject(user, "multiple statements (stacked query)")

        # 3. Read-only / write-statement governance.
        reason = self._check_governance(ast)
        if reason:
            return self._reject(user, reason)

        # 4. Complexity / resource limits.
        reason = self._check_complexity(sql, ast)
        if reason:
            return self._reject(user, reason)

        # 5. Forbidden tables / dangerous functions.
        reason = self._check_forbidden(ast)
        if reason:
            return self._reject(user, reason)

        # 6. SQL shape semantics.
        reason = self._check_semantics(ast)
        if reason:
            return self._reject(user, reason)

        # 7. RLS rewrite (SELECT only).
        rewritten = self._apply_rls(ast, user, dialect)
        if rewritten is not None:
            args.sql = rewritten.sql(dialect=dialect)
            if self.config.audit.log_sql_transformations:
                logger.info("RLS applied for user %s", user.id)

        return args

    def _reject(self, user: User, reason: str) -> ToolRejection:
        if self.config.audit.log_rejected_queries:
            logger.warning("SQL rejected for user %s: %s", user.id, reason)
        return ToolRejection(reason=f"SQL rejected: {reason}")

    # -- parsing -----------------------------------------------------------

    def _parse_single(self, sql: str, dialect: Optional[str]) -> Expression:
        statements = list(
            sqlglot.parse(sql, read=dialect) if dialect else sqlglot.parse(sql)
        )
        if not statements:
            raise ParseError("empty SQL")
        if len(statements) > 1:
            raise _MultipleStatementsError(len(statements))
        # ``sqlglot.parse`` is typed ``list[Expr | None]``; the emptiness
        # check above guarantees the first element is a real expression.
        return cast(Expression, statements[0])

    # -- check: injection --------------------------------------------------

    def _check_injection(self, sql: str) -> Optional[str]:
        cfg = self.config.sql_injection
        if not cfg.enabled:
            return None

        is_metadata = any(
            self._pattern_matches(p, sql) for p in cfg.allowed_metadata_patterns
        )

        for forbidden in cfg.forbidden_patterns:
            if forbidden.metadata_related and is_metadata:
                continue
            if self._pattern_matches(forbidden, sql):
                return forbidden.description or "SQL injection pattern detected"
        return None

    @staticmethod
    def _pattern_matches(pattern: PatternConfig, sql: str) -> bool:
        flags = 0 if pattern.case_sensitive else re.IGNORECASE
        return re.search(pattern.pattern, sql, flags) is not None

    # -- check: governance -------------------------------------------------

    def _check_governance(self, ast: Expression) -> Optional[str]:
        cfg = self.config.query_governance
        if not cfg.enabled or not cfg.read_only:
            return None
        if isinstance(ast, exp.Select):
            return None
        return f"read-only mode forbids non-SELECT statements ({_statement_kind(ast)})"

    # -- check: complexity -------------------------------------------------

    def _check_complexity(self, sql: str, ast: Expression) -> Optional[str]:
        cfg = self.config.query_limits
        if not cfg.enabled:
            return None

        if len(sql) > cfg.max_query_length:
            return f"query too long ({len(sql)} > {cfg.max_query_length})"

        subqueries = len(list(ast.find_all(exp.Subquery)))
        if subqueries > cfg.max_subqueries:
            return f"too many subqueries ({subqueries} > {cfg.max_subqueries})"

        ctes = len(list(ast.find_all(exp.CTE)))
        if ctes > cfg.max_cte_depth:
            return f"too many CTEs ({ctes} > {cfg.max_cte_depth})"

        joins = len(list(ast.find_all(exp.Join)))
        if joins > cfg.max_joins:
            return f"too many JOINs ({joins} > {cfg.max_joins})"

        for limit in ast.find_all(exp.Limit):
            value = _literal_int(limit.expression)
            if value is not None and value > cfg.max_result_rows:
                return f"result LIMIT too large ({value} > {cfg.max_result_rows})"

        return None

    # -- check: forbidden tables / functions -------------------------------

    def _check_forbidden(self, ast: Expression) -> Optional[str]:
        cfg = self.config.query_limits
        if not cfg.enabled:
            return None

        forbidden_tables = {t.strip().lower() for t in cfg.forbidden_tables}
        if forbidden_tables:
            for table in ast.find_all(exp.Table):
                name = (table.name or "").lower()
                full = _table_full_name(table).lower()
                if name in forbidden_tables or full in forbidden_tables:
                    return f"forbidden table: {_table_full_name(table)}"

        blocked_functions = {f.strip().lower() for f in cfg.blocked_functions}
        if blocked_functions:
            for func in ast.find_all(exp.Func):
                name = _func_name(func).lower()
                if name in blocked_functions:
                    return f"forbidden function: {_func_name(func)}"

        return None

    # -- check: semantics --------------------------------------------------

    def _check_semantics(self, ast: Expression) -> Optional[str]:
        cfg = self.config.sql_semantics
        if not cfg.enabled:
            return None

        if cfg.check_join:
            reason = self._check_join(ast)
            if reason:
                return reason

        if cfg.check_window and cfg.require_partition_by_for_window_cues:
            reason = self._check_window(ast)
            if reason:
                return reason

        if cfg.check_aggregation:
            reason = self._check_aggregation(ast)
            if reason:
                return reason

        # check_rollup / check_partition_constant / check_outer_join_null_filter
        # are reserved (fail-open) to avoid false rejections on valid queries.
        return None

    def _check_join(self, ast: Expression) -> Optional[str]:
        for join in ast.find_all(exp.Join):
            if join.args.get("on") is None and join.args.get("using") is None:
                kind = join.args.get("kind")
                if kind in ("CROSS", "NATURAL"):
                    continue
                return "JOIN is missing an ON or USING condition"
        return None

    def _check_window(self, ast: Expression) -> Optional[str]:
        for window in ast.find_all(exp.Window):
            if not window.args.get("partition_by"):
                return "window function is missing PARTITION BY"
        return None

    def _check_aggregation(self, ast: Expression) -> Optional[str]:
        for select in ast.find_all(exp.Select):
            group = select.args.get("group")
            expressions = select.args.get("expressions") or []
            if group is None:
                continue
            # Only inspect selects that actually aggregate.
            if not any(list(e.find_all(exp.AggFunc)) for e in expressions):
                continue
            group_cols = {
                column.name.lower()
                for ge in (group.expressions or [])
                for column in ge.find_all(exp.Column)
            }
            if not group_cols:
                # GROUP BY ordinals/expressions — cannot judge safely, fail open.
                continue
            for expr in expressions:
                column = _unwrap_alias(expr)
                if (
                    isinstance(column, exp.Column)
                    and column.name.lower() not in group_cols
                ):
                    return (
                        f"non-aggregated column {column.name} is not in GROUP BY"
                    )
        return None

    # -- RLS ---------------------------------------------------------------

    def _apply_rls(
        self, ast: Expression, user: User, dialect: Optional[str]
    ) -> Optional[Expression]:
        cfg = self.config.row_level_security
        if not cfg.enabled or not cfg.protected_tables:
            return None
        if not isinstance(ast, exp.Select):
            return None

        allowed = self._allowed_values(user)
        if allowed is None:
            return None  # Full access (some group maps to "*").

        by_name = {entry.table.strip().lower(): entry for entry in cfg.protected_tables}
        changed = [False]

        def rewrite(node: Expression) -> Expression:
            if not isinstance(node, exp.Select):
                return node
            conditions: List[str] = []
            for table in _direct_tables(node):
                entry = by_name.get(_table_full_name(table).lower())
                if entry is None:
                    entry = by_name.get((table.name or "").lower())
                if entry is None:
                    continue
                condition = _filter_condition_sql(table, entry, allowed)
                if condition:
                    conditions.append(condition)
            if not conditions:
                return node
            changed[0] = True
            predicate = sqlglot.parse_one(
                " AND ".join(conditions), read=dialect or None
            )
            return node.where(predicate, append=True)

        rewritten = ast.transform(rewrite)
        return rewritten if changed[0] else None

    def _allowed_values(self, user: User) -> Optional[Set[Any]]:
        """Return the user's allowed RLS values.

        Returns ``None`` when the user has full access (a group maps to ``"*"``),
        otherwise a set of allowed values (possibly empty, meaning no access).
        """
        mapping = self.config.row_level_security.group_value_mapping
        values: Set[Any] = set()
        for group in user.group_memberships:
            allowed = mapping.get(group, [])
            if "*" in allowed:
                return None
            values.update(allowed)
        return values


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _statement_kind(ast: Expression) -> str:
    return type(ast).__name__.upper()


def _table_full_name(table: exp.Table) -> str:
    db = table.db or ""
    name = table.name or ""
    return f"{db}.{name}" if db else name


def _func_name(func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous):
        return func.name or ""
    return func.sql_name() or ""


def _direct_tables(select: exp.Select) -> List[exp.Table]:
    """Return the tables referenced directly by this select's FROM/JOIN."""
    tables: List[exp.Table] = []
    from_ = select.args.get("from_")
    if from_ is not None and isinstance(from_.this, exp.Table):
        tables.append(from_.this)
    for join in select.args.get("joins") or []:
        if isinstance(join.this, exp.Table):
            tables.append(join.this)
    return tables


def _unwrap_alias(expr: Expression) -> Expression:
    return expr.this if isinstance(expr, exp.Alias) else expr


def _literal_int(expr: Optional[Expression]) -> Optional[int]:
    if isinstance(expr, exp.Literal):
        try:
            return int(expr.this)
        except (TypeError, ValueError):
            return None
    return None


def _literal_sql(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _filter_condition_sql(
    table: exp.Table, entry: RlsTableConfig, values: Set[Any]
) -> Optional[str]:
    """Build a SQL predicate that filters ``table`` to ``values``.

    Returns ``None`` when the entry is not applicable (e.g. an indirect
    ``via`` mapping with missing fields).
    """
    alias = table.alias_or_name

    if entry.column:
        column = f"{alias}.{entry.column}"
        if values:
            literals = ", ".join(_literal_sql(v) for v in sorted(values, key=str))
            return f"({column} IN ({literals}) OR {column} IS NULL)"
        return "FALSE"

    if entry.via:
        join_table = entry.via.get("join_table")
        join_column = entry.via.get("join_column")
        via_column = entry.via.get("via_column")
        if not (join_table and join_column and via_column):
            return None
        if values:
            literals = ", ".join(_literal_sql(v) for v in sorted(values, key=str))
            inner = f"(h.{via_column} IN ({literals}) OR h.{via_column} IS NULL)"
        else:
            inner = "FALSE"
        return (
            f"EXISTS (SELECT 1 FROM {join_table} AS h "
            f"WHERE h.{join_column} = {alias}.{join_column} AND {inner})"
        )

    return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_enhanced_tool_registry(
    config_path: str = "sql_security_config.yaml",
    audit_logger=None,
) -> EnhancedToolRegistry:
    """Create a configured :class:`EnhancedToolRegistry`."""
    return EnhancedToolRegistry(config_path=config_path, audit_logger=audit_logger)


__all__ = [
    "EnhancedToolRegistry",
    "SqlSecurityConfig",
    "create_enhanced_tool_registry",
    "load_sql_security_config",
]
