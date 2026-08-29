"""
PostgreSQL + pgvector implementation of DerivedMetricStore.

Single-table design. Each derived metric is stored as one row with its own
embedding for vector search.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.atomic_metric import JoinClause
from easyq2sql.capabilities.derived_metric import (
    DerivedMetric,
    DerivedMetricSearchResult,
    DerivedMetricStore,
)
from easyq2sql.integrations.postgres.embedding import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .config import (
    CE_CANDIDATE_MULTIPLIER,
    DEFAULT_CROSS_ENCODER_MODEL,
    DEFAULT_DERIVED_METRIC_TABLE,
    DEFAULT_EMBEDDING_MODEL,
)
from .embedding import EmbeddingHelper


class PostgresDerivedMetricStore(DerivedMetricStore):
    """PostgreSQL + pgvector DerivedMetricStore.

    **derived_metric**::

        id                  TEXT PRIMARY KEY
        metric_id           TEXT NOT NULL
        name                TEXT NOT NULL
        business_definition TEXT DEFAULT ''
        value_range         TEXT DEFAULT ''
        data_source         TEXT DEFAULT ''
        field_ref           TEXT DEFAULT ''
        joins_json          JSONB DEFAULT '[]'
        description         TEXT DEFAULT ''
        created_at          TIMESTAMP
        updated_at          TIMESTAMP
        embedding           vector(N)
        search_text         TEXT
        search_tsv          tsvector GENERATED ALWAYS
    """

    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        metric_id TEXT NOT NULL,
        name TEXT NOT NULL,
        business_definition TEXT DEFAULT '',
        value_range TEXT DEFAULT '',
        data_source TEXT DEFAULT '',
        field_ref TEXT DEFAULT '',
        joins_json JSONB DEFAULT '[]',
        description TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        embedding vector({vector_dim}),
        search_text TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS {table}_metric_id_idx ON {table} (metric_id);

    CREATE INDEX IF NOT EXISTS {table}_embedding_idx
        ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS search_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED;

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
        table_name: str = DEFAULT_DERIVED_METRIC_TABLE,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        cross_encoder_model: Optional[str] = DEFAULT_CROSS_ENCODER_MODEL,
        device: Optional[str] = None,
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
    def _format_search_text(
        derived_metric: DerivedMetric, metric_name: str = ""
    ) -> str:
        """Build embedding text for a derived metric.

        Format::

            # Dimension: name(field_ref)
            Business Definition: bizDef
            Metric: metric_name(atomic_metric_id)
            Value Range: value_range
        """
        lines = [f"# Dimension: {derived_metric.name}({derived_metric.field_ref})"]
        if derived_metric.business_definition:
            lines.append(f"Business Definition: {derived_metric.business_definition}")
        if metric_name:
            lines.append(f"Metric: {metric_name}({derived_metric.atomic_metric_id})")
        else:
            lines.append(f"Metric ID: {derived_metric.atomic_metric_id}")
        if derived_metric.value_range:
            lines.append(f"Value Range: {derived_metric.value_range}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Row conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_derived_metric(row: dict) -> DerivedMetric:
        joins_data = row.get("joins_json")
        if isinstance(joins_data, str):
            joins_data = json.loads(joins_data) if joins_data else []
        elif joins_data is None:
            joins_data = []
        joins = [JoinClause(**j) for j in joins_data]

        return DerivedMetric(
            id=row["id"],
            atomic_metric_id=row["metric_id"],
            name=row["name"],
            business_definition=row.get("business_definition") or None,
            value_range=row.get("value_range") or None,
            fk_relation=row.get("fk_relation") or None,
            data_source=row.get("data_source", ""),
            field_ref=row.get("field_ref", ""),
            joins=joins,
            description=row.get("description") or None,
            created_at=row.get("created_at") or datetime.now(),
            updated_at=row.get("updated_at") or datetime.now(),
        )

    # ------------------------------------------------------------------
    # DerivedMetricStore interface
    # ------------------------------------------------------------------

    async def create_derived_metric(
        self, derived_metric: DerivedMetric, context: ToolContext
    ) -> DerivedMetric:
        def _create():
            derived_metric.updated_at = datetime.now()
            if derived_metric.created_at is None:
                derived_metric.created_at = derived_metric.updated_at
            search_text = self._format_search_text(derived_metric)
            embedding = self._embedding_helper.encode(search_text)

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, metric_id, name, business_definition,
                             value_range, fk_relation, data_source, field_ref,
                             joins_json, description,
                             created_at, updated_at, embedding, search_text)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            metric_id = EXCLUDED.metric_id,
                            name = EXCLUDED.name,
                            business_definition = EXCLUDED.business_definition,
                            value_range = EXCLUDED.value_range,
                            fk_relation = EXCLUDED.fk_relation,
                            data_source = EXCLUDED.data_source,
                            field_ref = EXCLUDED.field_ref,
                            joins_json = EXCLUDED.joins_json,
                            description = EXCLUDED.description,
                            updated_at = EXCLUDED.updated_at,
                            embedding = EXCLUDED.embedding,
                            search_text = EXCLUDED.search_text
                        """,
                        [
                            derived_metric.id,
                            derived_metric.atomic_metric_id,
                            derived_metric.name,
                            derived_metric.business_definition or "",
                            derived_metric.value_range or "",
                            derived_metric.fk_relation or "",
                            derived_metric.data_source,
                            derived_metric.field_ref,
                            json.dumps(
                                [j.model_dump() for j in derived_metric.joins],
                                ensure_ascii=False,
                            ),
                            derived_metric.description or "",
                            derived_metric.created_at.isoformat() if derived_metric.created_at else datetime.now().isoformat(),
                            derived_metric.updated_at.isoformat() if derived_metric.updated_at else datetime.now().isoformat(),
                            embedding,
                            search_text,
                        ],
                    )
                conn.commit()
                return derived_metric
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _create)

    async def get_derived_metric(
        self, derived_metric_id: str, context: ToolContext
    ) -> Optional[DerivedMetric]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} WHERE id = %s",
                        [derived_metric_id],
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    cols = [desc[0] for desc in cur.description]
                    return self._row_to_derived_metric(dict(zip(cols, row)))
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def update_derived_metric(
        self, derived_metric: DerivedMetric, context: ToolContext
    ) -> bool:
        def _check():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id FROM {self._table} WHERE id = %s",
                        [derived_metric.id],
                    )
                    return cur.fetchone() is not None
            finally:
                conn.close()

        exists = await asyncio.get_event_loop().run_in_executor(self._executor, _check)
        if not exists:
            return False
        await self.create_derived_metric(derived_metric, context)
        return True

    async def delete_derived_metric(
        self, derived_metric_id: str, context: ToolContext
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = %s",
                        [derived_metric_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def delete_derived_metrics(
        self, derived_metric_ids: List[str], context: ToolContext
    ) -> int:
        def _delete():
            if not derived_metric_ids:
                return 0
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = ANY(%s)",
                        [derived_metric_ids],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def list_derived_metrics(
        self, context: ToolContext
    ) -> List[DerivedMetric]:
        def _list():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} ORDER BY metric_id, id"
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [
                        self._row_to_derived_metric(dict(zip(cols, r)))
                        for r in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def search_derived_metrics(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
    ) -> List[DerivedMetricSearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(query)
            fetch_limit = (
                limit * CE_CANDIDATE_MULTIPLIER
                if self._cross_encoder
                else limit * 3
            )

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
                        SELECT d.*, r.rrf_score
                        FROM {self._table} d
                        JOIN rrf r ON d.id = r.id
                        ORDER BY r.rrf_score DESC
                        LIMIT %s
                        """,
                        [query_embedding, ts_query, ts_query, fetch_limit],
                    )
                    cols = [desc[0] for desc in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                if not rows:
                    return []

                if self._cross_encoder and len(rows) > limit:
                    docs = [row.get("search_text", "") for row in rows]
                    ce_scored = self._cross_encoder.rerank_with_scores(
                        query=query, documents=docs, top_n=limit * 3
                    )
                    for orig_idx, ce_score in ce_scored:
                        if orig_idx < len(rows):
                            rows[orig_idx]["_ce_score"] = ce_score
                    rows = [rows[idx] for idx, _ in ce_scored if idx < len(rows)]

                rows = rows[:limit]

                results = []
                for r in rows:
                    derived_metric = self._row_to_derived_metric(r)
                    results.append(
                        DerivedMetricSearchResult(
                            derived_metric=derived_metric,
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

    async def get_derived_metrics_by_atomic_metric(
        self, atomic_metric_id: str, context: ToolContext
    ) -> List[DerivedMetric]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} "
                        f"WHERE metric_id = %s ORDER BY id",
                        [atomic_metric_id],
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [
                        self._row_to_derived_metric(dict(zip(cols, r)))
                        for r in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)
