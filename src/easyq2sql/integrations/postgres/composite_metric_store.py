"""
PostgreSQL implementation of CompositeMetricStore.

Single-table design. Composite metrics combine two derived metrics (dimension
ids) via a composition operator. Retrieval is handled by the metric graph
(Neo4j), so this table carries no embedding column — it is plain CRUD config.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.composite_metric import (
    CompositeMetric,
    CompositeMetricStore,
)
from easyq2sql.core.tool import ToolContext

from .config import DEFAULT_COMPOSITE_METRIC_TABLE

logger = logging.getLogger(__name__)


class PostgresCompositeMetricStore(CompositeMetricStore):
    """PostgreSQL CompositeMetricStore — single-table design.

    **composite_metric**::

        id                  TEXT PRIMARY KEY
        name                TEXT NOT NULL
        business_definition TEXT DEFAULT ''
        comb_func           TEXT DEFAULT ''
        operand_a           TEXT DEFAULT ''
        operand_b           TEXT DEFAULT ''
        description         TEXT DEFAULT ''
        created_by          TEXT DEFAULT ''
        created_at          TIMESTAMP
        updated_at          TIMESTAMP
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        business_definition TEXT DEFAULT '',
        comb_func TEXT DEFAULT '',
        operand_a TEXT DEFAULT '',
        operand_b TEXT DEFAULT '',
        description TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS {table}_operand_a_idx ON {table} (operand_a);
    CREATE INDEX IF NOT EXISTS {table}_operand_b_idx ON {table} (operand_b);
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5432,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        table_name: str = DEFAULT_COMPOSITE_METRIC_TABLE,
    ):
        if connection_string:
            self._conn_string = connection_string
            self._conn_params = None
        elif host and database and user:
            self._conn_string = None
            self._conn_params = {
                "host": host,
                "port": port,
                "database": database,
                "user": user,
                "password": password,
            }
        else:
            raise ValueError(
                "Either provide connection_string OR (host, database, user) parameters"
            )
        self._table = table_name
        self._executor = ThreadPoolExecutor(max_workers=2)
        # Eagerly create the table (if missing) in the background, so the first
        # import does not pay the latency — or fail — on table creation. A
        # failure only logs and does not affect the lazy create-if-missing in
        # every method below.
        self._executor.submit(self._ensure_table_safely)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _get_conn(self):
        import os

        import psycopg2

        os.environ.setdefault("PGCLIENTENCODING", "UTF8")

        if self._conn_string:
            conn = psycopg2.connect(
                self._conn_string, options="-c client_encoding=UTF8"
            )
        else:
            p = self._conn_params
            conn = psycopg2.connect(
                host=p["host"],
                port=p["port"],
                dbname=p["database"],
                user=p["user"],
                password=p["password"],
                options="-c client_encoding=UTF8",
            )
        return conn

    def _ensure_table(self, conn):
        """Idempotently create the table + indexes.

        Uses a lock timeout with deadlock/lock-wait fallback to avoid races on
        concurrent first-time creation.
        """
        import psycopg2.errors

        ddl = self.DDL.format(table=self._table)
        with conn.cursor() as cur:
            try:
                cur.execute("SET LOCAL lock_timeout = '2s'")
                cur.execute(ddl)
            except (
                psycopg2.errors.DeadlockDetected,
                psycopg2.errors.LockNotAvailable,
            ):
                conn.rollback()
        conn.commit()

    def _ensure_table_blocking(self) -> None:
        """Connect -> create table -> close; re-raises on failure (for one-off
        scripts / startup hooks that need to observe the error)."""
        conn = self._get_conn()
        try:
            self._ensure_table(conn)
        finally:
            conn.close()

    def _ensure_table_safely(self) -> None:
        """Background table creation at startup: failure only logs, never aborts."""
        try:
            self._ensure_table_blocking()
        except Exception:  # noqa: BLE001 — table creation must not abort startup
            logger.exception(
                "Failed to eagerly create composite table %r", self._table
            )

    async def ensure_table(self) -> None:
        """Public idempotent table-creation entry point (startup hooks / scripts)."""
        await asyncio.get_event_loop().run_in_executor(
            self._executor, self._ensure_table_blocking
        )

    # ------------------------------------------------------------------
    # Row conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_composite_metric(row: dict) -> CompositeMetric:
        return CompositeMetric(
            id=row["id"],
            name=row["name"],
            business_definition=row.get("business_definition") or None,
            comb_func=row.get("comb_func", ""),
            operand_a=row.get("operand_a", ""),
            operand_b=row.get("operand_b", ""),
            description=row.get("description") or None,
            created_by=row.get("created_by") or None,
            created_at=row.get("created_at") or datetime.now(),
            updated_at=row.get("updated_at") or datetime.now(),
        )

    # ------------------------------------------------------------------
    # CompositeMetricStore interface
    # ------------------------------------------------------------------

    async def create_composite_metric(
        self, composite_metric: CompositeMetric, context: ToolContext
    ) -> CompositeMetric:
        def _create():
            composite_metric.updated_at = datetime.now()
            if composite_metric.created_at is None:
                composite_metric.created_at = composite_metric.updated_at

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, name, business_definition, comb_func,
                             operand_a, operand_b, description, created_by,
                             created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            business_definition = EXCLUDED.business_definition,
                            comb_func = EXCLUDED.comb_func,
                            operand_a = EXCLUDED.operand_a,
                            operand_b = EXCLUDED.operand_b,
                            description = EXCLUDED.description,
                            updated_at = EXCLUDED.updated_at
                        """,
                        [
                            composite_metric.id,
                            composite_metric.name,
                            composite_metric.business_definition or "",
                            composite_metric.comb_func or "",
                            composite_metric.operand_a,
                            composite_metric.operand_b,
                            composite_metric.description or "",
                            composite_metric.created_by or "",
                            composite_metric.created_at.isoformat() if composite_metric.created_at else datetime.now().isoformat(),
                            composite_metric.updated_at.isoformat() if composite_metric.updated_at else datetime.now().isoformat(),
                        ],
                    )
                conn.commit()
                return composite_metric
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _create)

    async def get_composite_metric(
        self, composite_metric_id: str, context: ToolContext
    ) -> Optional[CompositeMetric]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} WHERE id = %s",
                        [composite_metric_id],
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    cols = [desc[0] for desc in cur.description]
                    return self._row_to_composite_metric(dict(zip(cols, row)))
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def update_composite_metric(
        self, composite_metric: CompositeMetric, context: ToolContext
    ) -> bool:
        def _check():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id FROM {self._table} WHERE id = %s",
                        [composite_metric.id],
                    )
                    return cur.fetchone() is not None
            finally:
                conn.close()

        exists = await asyncio.get_event_loop().run_in_executor(self._executor, _check)
        if not exists:
            return False
        await self.create_composite_metric(composite_metric, context)
        return True

    async def delete_composite_metric(
        self, composite_metric_id: str, context: ToolContext
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = %s",
                        [composite_metric_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def list_composite_metrics(
        self, context: ToolContext
    ) -> List[CompositeMetric]:
        def _list():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} ORDER BY updated_at DESC"
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [
                        self._row_to_composite_metric(dict(zip(cols, r)))
                        for r in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)
