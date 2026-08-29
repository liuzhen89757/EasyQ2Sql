"""
PostgreSQL + pgvector implementation of AtomicMetricStore.

Single-table design. Each atomic metric is stored as one row with its own
embedding for vector search. Derived metrics are managed independently by
``PostgresDerivedMetricStore``.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.atomic_metric import (
    AtomicMetric,
    AtomicMetricSearchResult,
    AtomicMetricStore,
)
from easyq2sql.integrations.postgres.embedding import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .config import (
    CE_CANDIDATE_MULTIPLIER,
    DEFAULT_ATOMIC_METRIC_TABLE,
    DEFAULT_CROSS_ENCODER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
)
from .embedding import EmbeddingHelper


class PostgresAtomicMetricStore(AtomicMetricStore):
    """PostgreSQL + pgvector AtomicMetricStore — single-table design.

    **atomic_metric**::

        id                  TEXT PRIMARY KEY
        name                TEXT NOT NULL
        business_definition TEXT DEFAULT ''
        calculation_logic   TEXT DEFAULT ''
        data_source         TEXT DEFAULT ''
        analysis_field      TEXT DEFAULT ''
        description         TEXT DEFAULT ''
        created_by          TEXT DEFAULT ''
        created_at          TIMESTAMP
        updated_at          TIMESTAMP
        embedding           vector(N)
        search_text         TEXT
        search_tsv          tsvector GENERATED ALWAYS

    Search uses hybrid retrieval (vector + keyword with RRF fusion)
    followed by optional Cross-Encoder re-rank.
    """

    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        business_definition TEXT DEFAULT '',
        calculation_logic TEXT DEFAULT '',
        data_source TEXT DEFAULT '',
        analysis_field TEXT DEFAULT '',
        description TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        embedding vector({vector_dim}),
        search_text TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS {table}_embedding_idx
        ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS search_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED;

    ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS value_range TEXT DEFAULT '';
    ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS fk_relation TEXT DEFAULT '';

    CREATE INDEX IF NOT EXISTS {table}_tsv_idx ON {table} USING GIN (search_tsv);
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5432,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        table_name: str = DEFAULT_ATOMIC_METRIC_TABLE,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        cross_encoder_model: Optional[str] = DEFAULT_CROSS_ENCODER_MODEL,
        device: Optional[str] = None,
        dimension_store=None,
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
        self._embedding_helper = EmbeddingHelper(embedding_model, device=device)
        self._cross_encoder = (
            CrossEncoderReranker(cross_encoder_model, device=device)
            if cross_encoder_model
            else None
        )
        self._dimension_store = dimension_store
        self._executor.submit(self._embedding_helper._get_model)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _get_conn(self):
        import os

        import psycopg2
        from pgvector.psycopg2 import register_vector

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
        register_vector(conn)
        return conn

    def _ensure_table(self, conn):
        """Create table and auto-migrate embedding dimension if model changed."""
        import hashlib
        import re

        import psycopg2.errors

        dim = self._embedding_helper.embedding_dim
        ddl = self.DDL.format(table=self._table, vector_dim=dim)
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

        lock_id = int(
            hashlib.md5(self._table.encode()).hexdigest()[:8], 16
        ) % (2**31 - 1)
        with conn.cursor() as cur:
            cur.execute(f"SELECT pg_advisory_lock({lock_id})")
            try:
                cur.execute(
                    """
                    SELECT format_type(atttypid, atttypmod)
                    FROM pg_attribute
                    WHERE attrelid = %s::regclass AND attname = 'embedding'
                    """,
                    [self._table],
                )
                row = cur.fetchone()
                if row:
                    m = re.search(r'vector\((\d+)\)', row[0])
                    current_dim = int(m.group(1)) if m else None
                    if current_dim is not None and current_dim != dim:
                        cur.execute(
                            f"DROP INDEX IF EXISTS {self._table}_embedding_idx"
                        )
                        cur.execute(f"UPDATE {self._table} SET embedding = NULL")
                        cur.execute(
                            f"ALTER TABLE {self._table} ALTER COLUMN embedding TYPE vector({dim})"
                        )
                        cur.execute(
                            f"CREATE INDEX IF NOT EXISTS {self._table}_embedding_idx "
                            f"ON {self._table} USING ivfflat (embedding vector_cosine_ops) "
                            f"WITH (lists = 100)"
                        )
            finally:
                cur.execute(f"SELECT pg_advisory_unlock({lock_id})")
        conn.commit()

    # ------------------------------------------------------------------
    # Search text formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_search_text(atomic_metric: AtomicMetric) -> str:
        """Build embedding text for an atomic metric.

        Format::

            # Metric: name(data_source.analysis_field)
            Business Definition: business_definition
            Calculation: calculation_logic
        """
        lines = [
            f"# Metric: {atomic_metric.name}"
            f"({atomic_metric.data_source}.{atomic_metric.analysis_field})"
        ]
        if atomic_metric.business_definition:
            lines.append(f"Business Definition: {atomic_metric.business_definition}")
        if atomic_metric.calculation_logic:
            lines.append(f"Calculation: {atomic_metric.calculation_logic}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Row conversion
    # ------------------------------------------------------------------

    def _row_to_atomic_metric(self, row: dict) -> AtomicMetric:
        return AtomicMetric(
            id=row["id"],
            name=row["name"],
            business_definition=row.get("business_definition") or None,
            calculation_logic=row.get("calculation_logic") or None,
            data_source=row.get("data_source", ""),
            analysis_field=row.get("analysis_field", ""),
            value_range=row.get("value_range") or None,
            fk_relation=row.get("fk_relation") or None,
            description=row.get("description") or None,
            created_by=row.get("created_by") or None,
            created_at=row.get("created_at") or datetime.now(),
            updated_at=row.get("updated_at") or datetime.now(),
        )

    # ------------------------------------------------------------------
    # AtomicMetricStore interface
    # ------------------------------------------------------------------

    async def create_atomic_metric(
        self, atomic_metric: AtomicMetric, context: ToolContext
    ) -> AtomicMetric:
        def _create():
            atomic_metric.updated_at = datetime.now()
            if atomic_metric.created_at is None:
                atomic_metric.created_at = atomic_metric.updated_at
            search_text = self._format_search_text(atomic_metric)
            embedding = self._embedding_helper.encode(search_text)

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, name, business_definition,
                             calculation_logic, data_source, analysis_field,
                             value_range, fk_relation,
                             description, created_by, created_at, updated_at,
                             embedding, search_text)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            business_definition = EXCLUDED.business_definition,
                            calculation_logic = EXCLUDED.calculation_logic,
                            data_source = EXCLUDED.data_source,
                            analysis_field = EXCLUDED.analysis_field,
                            value_range = EXCLUDED.value_range,
                            fk_relation = EXCLUDED.fk_relation,
                            description = EXCLUDED.description,
                            updated_at = EXCLUDED.updated_at,
                            embedding = EXCLUDED.embedding,
                            search_text = EXCLUDED.search_text
                        """,
                        [
                            atomic_metric.id,
                            atomic_metric.name,
                            atomic_metric.business_definition or "",
                            atomic_metric.calculation_logic or "",
                            atomic_metric.data_source,
                            atomic_metric.analysis_field,
                            atomic_metric.value_range or "",
                            atomic_metric.fk_relation or "",
                            atomic_metric.description or "",
                            atomic_metric.created_by or "",
                            atomic_metric.created_at.isoformat() if atomic_metric.created_at else datetime.now().isoformat(),
                            atomic_metric.updated_at.isoformat() if atomic_metric.updated_at else datetime.now().isoformat(),
                            embedding,
                            search_text,
                        ],
                    )
                conn.commit()
                return atomic_metric
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _create)

    async def get_atomic_metric(
        self, atomic_metric_id: str, context: ToolContext
    ) -> Optional[AtomicMetric]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} WHERE id = %s",
                        [atomic_metric_id],
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    cols = [desc[0] for desc in cur.description]
                    return self._row_to_atomic_metric(dict(zip(cols, row)))
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def update_atomic_metric(
        self, atomic_metric: AtomicMetric, context: ToolContext
    ) -> bool:
        def _update():
            atomic_metric.updated_at = datetime.now()
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id FROM {self._table} WHERE id = %s",
                        [atomic_metric.id],
                    )
                    if cur.fetchone() is None:
                        return False
                # Re-use create logic (upsert)
                return True
            finally:
                conn.close()

        # Use create_atomic_metric's upsert logic
        await self.create_atomic_metric(atomic_metric, context)
        return True

    async def delete_atomic_metric(
        self, atomic_metric_id: str, context: ToolContext
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = %s",
                        [atomic_metric_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def list_atomic_metrics(
        self, context: ToolContext
    ) -> List[AtomicMetric]:
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
                        self._row_to_atomic_metric(dict(zip(cols, r)))
                        for r in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def search_atomic_metrics(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
    ) -> List[AtomicMetricSearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(query)

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    # Extract word/CJK tokens from query for keyword search.
                    import re

                    tokens = re.findall(r"[\w一-鿿]+", query)
                    ts_query = (
                        " & ".join([f"{t}:*" for t in tokens])
                        if tokens
                        else query
                    )
                    cur.execute(
                        f"""
                        WITH
                        vector_ranked AS (
                            SELECT id,
                                ROW_NUMBER() OVER (
                                    ORDER BY embedding <=> %s::vector
                                ) AS rank
                            FROM {self._table}
                            WHERE embedding IS NOT NULL
                        ),
                        text_ranked AS (
                            SELECT id,
                                ROW_NUMBER() OVER (
                                    ORDER BY ts_rank(search_tsv, to_tsquery('simple', %s)) DESC
                                ) AS rank
                            FROM {self._table}
                            WHERE search_tsv @@ to_tsquery('simple', %s)
                        ),
                        rrf AS (
                            SELECT
                                COALESCE(v.id, t.id) AS id,
                                COALESCE(1.0 / (60 + v.rank), 0.0)
                                + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score
                            FROM vector_ranked v
                            FULL OUTER JOIN text_ranked t ON v.id = t.id
                        )
                        SELECT m.*, r.rrf_score
                        FROM {self._table} m
                        JOIN rrf r ON m.id = r.id
                        ORDER BY r.rrf_score DESC
                        LIMIT %s
                        """,
                        [query_embedding, ts_query, ts_query, limit * CE_CANDIDATE_MULTIPLIER],
                    )
                    cols = [desc[0] for desc in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                if not rows:
                    return []

                # Optional Cross-Encoder re-rank
                if self._cross_encoder and len(rows) > limit:
                    docs = [row.get("search_text", "") for row in rows]
                    ce_scored = self._cross_encoder.rerank_with_scores(
                        query=query, documents=docs, top_n=limit * CE_CANDIDATE_MULTIPLIER
                    )
                    for orig_idx, ce_score in ce_scored:
                        if orig_idx < len(rows):
                            rows[orig_idx]["_ce_score"] = ce_score
                    rows = [rows[idx] for idx, _ in ce_scored if idx < len(rows)]

                rows = rows[:limit]

                results = []
                for r in rows:
                    atomic_metric = self._row_to_atomic_metric(r)
                    results.append(
                        AtomicMetricSearchResult(
                            atomic_metric=atomic_metric,
                            similarity_score=round(
                                r.get("_ce_score", r.get("rrf_score", 0.0)), 6
                            ),
                            document_text=r.get("search_text"),
                        )
                    )
                return results
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_atomic_metrics_by_table(
        self, table_name: str, context: ToolContext
    ) -> List[AtomicMetric]:
        def _filter():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} "
                        f"WHERE data_source = %s ORDER BY updated_at DESC",
                        [table_name],
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [
                        self._row_to_atomic_metric(dict(zip(cols, r)))
                        for r in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _filter)
