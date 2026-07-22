"""
PostgreSQL + pgvector implementation of MetricStore.

Uses a normalized two-table design:
- ``metric_definitions`` — one row per logical metric (shared metadata).
- ``metric_dimensions`` — one row per dimension (1:1:1).

On read, dimension rows are reassembled into the ``Metric.dimensions`` list
so the API / frontend contract is unchanged.
"""

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.metric_store import (
    JoinClause,
    Metric,
    MetricDimension,
    MetricSearchResult,
    MetricStore,
)
from easyq2sql.core.search import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .config import (
    CE_CANDIDATE_MULTIPLIER,
    DEFAULT_CROSS_ENCODER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_METRIC_STORE_TABLE,
)
from .embedding import EmbeddingHelper


# ---------------------------------------------------------------------------
# PostgresMetricStore
# ---------------------------------------------------------------------------


class PostgresMetricStore(MetricStore):
    """PostgreSQL + pgvector MetricStore — normalized two-table design.

    **metric_definitions** — one row per logical metric::

        id              TEXT PRIMARY KEY
        name            TEXT NOT NULL
        description     TEXT
        analysis_table  TEXT
        analysis_field  TEXT
        generated_sql   TEXT
        created_by      TEXT
        created_at      TIMESTAMP
        updated_at      TIMESTAMP

    **metric_dimensions** — one row per dimension (1:1:1)::

        id              TEXT PRIMARY KEY  — ``{metric_id}__{dim_index}``
        metric_id       TEXT NOT NULL REFERENCES metric_definitions
        name            TEXT NOT NULL
        field_ref       TEXT
        joins_json      JSONB
        embedding       vector(384)
        search_text     TEXT

    Reads reassemble dimension rows into ``Metric.dimensions`` so the
    public API / frontend contract is unchanged.
    """

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    DEFINITIONS_DDL = """
    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        analysis_table TEXT DEFAULT '',
        analysis_field TEXT DEFAULT '',
        generated_sql_template TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    """

    DIMENSIONS_DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        metric_id TEXT NOT NULL REFERENCES {definitions_table}(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '',
        field_ref TEXT DEFAULT '',
        joins_json JSONB DEFAULT '[]',
        embedding vector({vector_dim}),
        search_text TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS {table}_metric_id_idx ON {table} (metric_id);

    CREATE INDEX IF NOT EXISTS {table}_embedding_idx
        ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    -- Hybrid search: auto-generated tsvector column + GIN index for full-text search
    ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS search_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED;

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
        table_name: str = DEFAULT_METRIC_STORE_TABLE,
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
        self._definitions_table = f"{table_name}_definitions"
        self._dimensions_table = f"{table_name}_dimensions"
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

    def _ensure_tables(self, conn):
        """Create both tables, indexes, and tsvector column if they don't exist.

        The ALTER TABLE … ADD COLUMN IF NOT EXISTS in the dimensions DDL
        uses a short ``lock_timeout`` to prevent deadlocks during
        concurrent initialisation.

        Also auto-migrates the ``embedding`` column if the model's vector
        dimension has changed.
        """
        import psycopg2.errors

        dim = self._embedding_helper.embedding_dim
        definitions_ddl = self.DEFINITIONS_DDL.format(table=self._definitions_table)
        dimensions_ddl = self.DIMENSIONS_DDL.format(
            table=self._dimensions_table,
            definitions_table=self._definitions_table,
            vector_dim=dim,
        )
        with conn.cursor() as cur:
            cur.execute(definitions_ddl)
            try:
                cur.execute("SET LOCAL lock_timeout = '2s'")
                cur.execute(dimensions_ddl)
            except (
                psycopg2.errors.DeadlockDetected,
                psycopg2.errors.LockNotAvailable,
            ):
                conn.rollback()
        conn.commit()

        # Auto-migrate vector dimension if model changed.
        # pgvector cannot cast between dimensions — clear old vectors
        # first; they'll be regenerated on the next sync / upsert.
        #
        # Uses a PostgreSQL advisory lock to prevent a race condition
        # where two concurrent connections both detect the dimension
        # mismatch and the second one's UPDATE … SET embedding = NULL
        # wipes out embeddings that were just inserted by the first.
        import hashlib
        import re

        lock_id = int(hashlib.md5(self._dimensions_table.encode()).hexdigest()[:8], 16) % (2**31 - 1)
        with conn.cursor() as cur:
            cur.execute(f"SELECT pg_advisory_lock({lock_id})")
            try:
                cur.execute(
                    """
                    SELECT format_type(atttypid, atttypmod)
                    FROM pg_attribute
                    WHERE attrelid = %s::regclass
                      AND attname = 'embedding'
                    """,
                    [self._dimensions_table],
                )
                row = cur.fetchone()
                if row:
                    m = re.search(r'vector\((\d+)\)', row[0])
                    current_dim = int(m.group(1)) if m else None
                    if current_dim is not None and current_dim != dim:
                        cur.execute(
                            f"DROP INDEX IF EXISTS {self._dimensions_table}_embedding_idx"
                        )
                        cur.execute(
                            f"UPDATE {self._dimensions_table} SET embedding = NULL"
                        )
                        cur.execute(
                            f"ALTER TABLE {self._dimensions_table} ALTER COLUMN embedding TYPE vector({dim})"
                        )
                        cur.execute(
                            f"CREATE INDEX IF NOT EXISTS {self._dimensions_table}_embedding_idx "
                            f"ON {self._dimensions_table} USING ivfflat (embedding vector_cosine_ops) "
                            f"WITH (lists = 100)"
                        )
            finally:
                cur.execute(f"SELECT pg_advisory_unlock({lock_id})")
        conn.commit()

    # ------------------------------------------------------------------
    # ID helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_dim_id(metric_id: str, dim_index: int) -> str:
        return f"{metric_id}__{dim_index}"

    # ------------------------------------------------------------------
    # Search text formatting (one per dimension)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_dimension_search_text(
        metric: Metric, dim: MetricDimension, dim_index: int
    ) -> str:
        """Build embedding text for a single metric-dimension pair.

        Format::

            # Metric: name(table.field)
            Description: ...
            ##Dimension: dim_name(dim.field_ref)
            Joins: src.col = tgt.col
        """
        lines = [f"# Metric: {metric.name}({metric.analysis_field})"]
        if metric.description:
            lines.append(f"Description: {metric.description}")
        lines.append(f"##Dimension: {dim.name}({dim.field_ref})")
        if dim.joins:
            join_strs = [
                f"{j.source_table}.{j.source_column} = {j.target_table}.{j.target_column}"
                for j in dim.joins
            ]
            lines.append(f"Joins: {'; '.join(join_strs)}")
        return "\n".join(lines)

    @staticmethod
    def _format_no_dimension_search_text(metric: Metric) -> str:
        """Build embedding text for a metric with no dimensions.

        Format::

            # Metric: name(table.field)
            Description: ...
        """
        lines = [f"# Metric: {metric.name}({metric.analysis_field})"]
        if metric.description:
            lines.append(f"Description: {metric.description}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_metric(definition_row: dict, dimension_rows: list[dict]) -> Metric:
        """Assemble a full Metric from one definition row + its dimension rows."""
        def _json(val, default):
            if isinstance(val, str):
                return json.loads(val) if val else default
            return val if val is not None else default

        # Build dimensions from dimension rows.
        # Skip sentinel rows (dim_index == -1) that represent "no dimensions".
        dimensions: list[MetricDimension] = []
        for dr in sorted(dimension_rows, key=lambda r: r.get("id", "")):
            dim_name = dr.get("name", "")
            dim_field = dr.get("field_ref", "")
            # Sentinel row for metrics without dimensions — skip
            if dr.get("id", "").endswith("__-1") and not dim_name and not dim_field:
                continue
            joins_data = _json(dr.get("joins_json"), [])
            joins = [JoinClause(**j) for j in joins_data]
            dimensions.append(
                MetricDimension(name=dim_name, field_ref=dim_field, joins=joins)
            )

        return Metric(
            id=definition_row["id"],
            name=definition_row["name"],
            description=definition_row.get("description") or None,
            analysis_table=definition_row.get("analysis_table", ""),
            analysis_field=definition_row.get("analysis_field", ""),
            dimensions=dimensions,
            generated_sql_template=definition_row.get("generated_sql_template") or None,
            created_by=definition_row.get("created_by") or None,
            created_at=definition_row.get("created_at") or datetime.now(),
            updated_at=definition_row.get("updated_at") or datetime.now(),
        )

    @staticmethod
    def _metric_from_best_dimension(
        definition: dict, dim_row: dict
    ) -> Metric:
        """Build a Metric with a single best-matching dimension row.

        Unlike :meth:`_row_to_metric`, this does NOT fetch or merge all
        dimensions — it only uses the one dimension row that scored
        highest during hybrid search.
        """
        def _json(val, default):
            if isinstance(val, str):
                return json.loads(val) if val else default
            return val if val is not None else default

        dim_name = dim_row.get("name", "")
        dim_field = dim_row.get("field_ref", "")
        joins_data = _json(dim_row.get("joins_json"), [])
        joins = [JoinClause(**j) for j in joins_data]

        # Sentinel row (dim_index == -1) means no real dimension
        dimensions: list[MetricDimension] = []
        if not dim_row.get("id", "").endswith("__-1") or dim_name or dim_field:
            dimensions.append(
                MetricDimension(name=dim_name, field_ref=dim_field, joins=joins)
            )

        return Metric(
            id=definition["id"],
            name=definition["name"],
            description=definition.get("description") or None,
            analysis_table=definition.get("analysis_table", ""),
            analysis_field=definition.get("analysis_field", ""),
            dimensions=dimensions,
            generated_sql_template=definition.get("generated_sql_template") or None,
            created_by=definition.get("created_by") or None,
            created_at=definition.get("created_at") or datetime.now(),
            updated_at=definition.get("updated_at") or datetime.now(),
        )

    # ------------------------------------------------------------------
    # Low-level read helpers
    # ------------------------------------------------------------------

    def _fetch_definition(self, cur, metric_id: str) -> Optional[dict]:
        cur.execute(
            f"SELECT * FROM {self._definitions_table} WHERE id = %s",
            [metric_id],
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))

    def _fetch_dimensions(self, cur, metric_id: str) -> list[dict]:
        cur.execute(
            f"SELECT * FROM {self._dimensions_table} WHERE metric_id = %s ORDER BY id",
            [metric_id],
        )
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _write_definition(self, cur, metric: Metric) -> None:
        """INSERT … ON CONFLICT UPSERT the metric definition row."""
        cur.execute(
            f"""
            INSERT INTO {self._definitions_table}
                (id, name, description, analysis_table, analysis_field,
                 generated_sql_template,
                 created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                analysis_table = EXCLUDED.analysis_table,
                analysis_field = EXCLUDED.analysis_field,
                generated_sql_template = EXCLUDED.generated_sql_template,
                updated_at = EXCLUDED.updated_at
            """,
            [
                metric.id,
                metric.name,
                metric.description or "",
                metric.analysis_table,
                metric.analysis_field,
                metric.generated_sql_template or "",
                metric.created_by or "",
                metric.created_at.isoformat() if metric.created_at else datetime.now().isoformat(),
                metric.updated_at.isoformat() if metric.updated_at else datetime.now().isoformat(),
            ],
        )

    def _write_dimension_rows(
        self, cur, metric: Metric, delete_first: bool = False
    ) -> None:
        """Write one row per dimension into metric_dimensions.

        If *delete_first*, remove all existing dimension rows for this metric
        before inserting (used by update).
        """
        if delete_first:
            cur.execute(
                f"DELETE FROM {self._dimensions_table} WHERE metric_id = %s",
                [metric.id],
            )

        if metric.dimensions:
            for i, dim in enumerate(metric.dimensions):
                row_id = self._make_dim_id(metric.id, i)
                search_text = self._format_dimension_search_text(metric, dim, i)
                embedding = self._embedding_helper.encode(search_text)

                cur.execute(
                    f"""
                    INSERT INTO {self._dimensions_table}
                        (id, metric_id, name, field_ref, joins_json,
                         embedding, search_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        metric_id = EXCLUDED.metric_id,
                        name = EXCLUDED.name,
                        field_ref = EXCLUDED.field_ref,
                        joins_json = EXCLUDED.joins_json,
                        embedding = EXCLUDED.embedding,
                        search_text = EXCLUDED.search_text
                    """,
                    [
                        row_id,
                        metric.id,
                        dim.name,
                        dim.field_ref,
                        json.dumps(
                            [j.model_dump() for j in dim.joins],
                            ensure_ascii=False,
                        ),
                        embedding,
                        search_text,
                    ],
                )
        else:
            # No dimensions — store a sentinel row so the metric is searchable
            row_id = self._make_dim_id(metric.id, -1)
            search_text = self._format_no_dimension_search_text(metric)
            embedding = self._embedding_helper.encode(search_text)

            cur.execute(
                f"""
                INSERT INTO {self._dimensions_table}
                    (id, metric_id, name, field_ref, joins_json,
                     embedding, search_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    metric_id = EXCLUDED.metric_id,
                    name = EXCLUDED.name,
                    field_ref = EXCLUDED.field_ref,
                    joins_json = EXCLUDED.joins_json,
                    embedding = EXCLUDED.embedding,
                    search_text = EXCLUDED.search_text
                """,
                [
                    row_id,
                    metric.id,
                    "",
                    "",
                    "[]",
                    embedding,
                    search_text,
                ],
            )

    # ------------------------------------------------------------------
    # MetricStore interface
    # ------------------------------------------------------------------

    async def create_metric(
        self, metric: Metric, context: ToolContext
    ) -> Metric:
        def _create():
            metric.updated_at = datetime.now()
            if metric.created_at is None:
                metric.created_at = metric.updated_at

            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    self._write_definition(cur, metric)
                    self._write_dimension_rows(cur, metric, delete_first=False)
                conn.commit()
                return metric
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _create)

    async def get_metric(
        self, metric_id: str, context: ToolContext
    ) -> Optional[Metric]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    definition = self._fetch_definition(cur, metric_id)
                    if definition is None:
                        return None
                    dimensions = self._fetch_dimensions(cur, metric_id)
                    return self._row_to_metric(definition, dimensions)
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def update_metric(
        self, metric: Metric, context: ToolContext
    ) -> bool:
        def _update():
            metric.updated_at = datetime.now()

            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    existing = self._fetch_definition(cur, metric.id)
                    if existing is None:
                        return False
                    self._write_definition(cur, metric)
                    self._write_dimension_rows(cur, metric, delete_first=True)
                conn.commit()
                return True
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _update)

    async def delete_metric(
        self, metric_id: str, context: ToolContext
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    # Delete dimensions first (FK cascade handles this, but
                    # explicit delete avoids surprises on older PG versions)
                    cur.execute(
                        f"DELETE FROM {self._dimensions_table} WHERE metric_id = %s",
                        [metric_id],
                    )
                    cur.execute(
                        f"DELETE FROM {self._definitions_table} WHERE id = %s",
                        [metric_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def list_metrics(
        self, context: ToolContext
    ) -> List[Metric]:
        def _list():
            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    # Fetch all definitions
                    cur.execute(
                        f"SELECT * FROM {self._definitions_table} "
                        f"ORDER BY updated_at DESC"
                    )
                    def_cols = [desc[0] for desc in cur.description]
                    definitions = [dict(zip(def_cols, r)) for r in cur.fetchall()]

                    if not definitions:
                        return []

                    # Fetch all dimensions in one query
                    cur.execute(
                        f"SELECT * FROM {self._dimensions_table} ORDER BY metric_id, id"
                    )
                    dim_cols = [desc[0] for desc in cur.description]
                    all_dims = [dict(zip(dim_cols, r)) for r in cur.fetchall()]

                # Group dimensions by metric_id
                dims_by_metric: dict[str, list[dict]] = {}
                for d in all_dims:
                    mid = d["metric_id"]
                    dims_by_metric.setdefault(mid, []).append(d)

                # Assemble metrics
                metrics = []
                for def_row in definitions:
                    mid = def_row["id"]
                    m = self._row_to_metric(def_row, dims_by_metric.get(mid, []))
                    metrics.append(m)
                return metrics
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def search_metrics(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
    ) -> List[MetricSearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(query)
            _fetch_limit = (limit * CE_CANDIDATE_MULTIPLIER if self._cross_encoder else limit * 3)

            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    # RRF hybrid search on dimensions — returns all matching
                    # dimension rows, NO deduplication by metric_id.
                    # Convert query to tsquery prefix-matching format (e.g. "风险" → "风险:*")
                    ts_query = ' & '.join([f'{w}:*' for w in query.split()]) if query else query
                    cur.execute(
                        f"""
                        WITH
                        vector_ranked AS (
                            SELECT id, metric_id,
                                ROW_NUMBER() OVER (
                                    ORDER BY embedding <=> %s::vector
                                ) AS rank
                            FROM {self._dimensions_table}
                            WHERE embedding IS NOT NULL
                        ),
                        text_ranked AS (
                            SELECT id, metric_id,
                                ROW_NUMBER() OVER (
                                    ORDER BY ts_rank(search_tsv, to_tsquery('simple', %s)) DESC
                                ) AS rank
                            FROM {self._dimensions_table}
                            WHERE search_tsv @@ to_tsquery('simple', %s)
                        ),
                        rrf AS (
                            SELECT
                                COALESCE(v.id, t.id) AS id,
                                COALESCE(v.metric_id, t.metric_id) AS metric_id,
                                COALESCE(1.0 / (60 + v.rank), 0.0)
                                + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score
                            FROM vector_ranked v
                            FULL OUTER JOIN text_ranked t ON v.id = t.id
                        )
                        SELECT d.*, r.rrf_score
                        FROM {self._dimensions_table} d
                        JOIN rrf r ON d.id = r.id
                        ORDER BY r.rrf_score DESC
                        LIMIT %s
                        """,
                        [query_embedding, ts_query, ts_query, _fetch_limit],
                    )
                    dim_cols = [desc[0] for desc in cur.description]
                    dim_rows = [dict(zip(dim_cols, r)) for r in cur.fetchall()]

                if not dim_rows:
                    return []

                # Cross-Encoder re-rank (optional second stage)
                # Re-rank at the dimension-document level.
                if self._cross_encoder and len(dim_rows) > limit:
                    docs = [
                        row.get("search_text", "") for row in dim_rows
                    ]
                    ce_indices = self._cross_encoder.rerank(
                        query=query, documents=docs, top_n=limit * 3
                    )
                    dim_rows = [
                        dim_rows[i]
                        for i in ce_indices
                        if i < len(dim_rows)
                    ]

                # Truncate to limit — NO dedup. Each dimension row is an
                # independent result. Same metric may appear multiple times
                # with different dimensions.
                dim_rows = dim_rows[:limit]

                if not dim_rows:
                    return []

                # Fetch definitions for all metric_ids in the result set
                metric_ids = list({dr["metric_id"] for dr in dim_rows})
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._definitions_table} WHERE id = ANY(%s)",
                        [metric_ids],
                    )
                    def_cols = [desc[0] for desc in cur.description]
                    def_rows = [dict(zip(def_cols, r)) for r in cur.fetchall()]

                def_by_id: dict[str, dict] = {d["id"]: d for d in def_rows}

                # Build one result per dimension row
                results = []
                for dr in dim_rows:
                    mid = dr["metric_id"]
                    definition = def_by_id.get(mid)
                    if definition is None:
                        continue
                    metric = self._metric_from_best_dimension(definition, dr)
                    results.append(
                        MetricSearchResult(
                            metric=metric,
                            similarity_score=round(dr.get("rrf_score", 0.0), 6),
                            document_text=dr.get("search_text"),
                        )
                    )
                return results
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_metrics_by_table(
        self, table_name: str, context: ToolContext
    ) -> List[Metric]:
        def _filter():
            conn = self._get_conn()
            try:
                self._ensure_tables(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._definitions_table} "
                        f"WHERE analysis_table = %s ORDER BY updated_at DESC",
                        [table_name],
                    )
                    def_cols = [desc[0] for desc in cur.description]
                    definitions = [dict(zip(def_cols, r)) for r in cur.fetchall()]

                    if not definitions:
                        return []

                    metric_ids = [d["id"] for d in definitions]
                    cur.execute(
                        f"SELECT * FROM {self._dimensions_table} "
                        f"WHERE metric_id = ANY(%s) ORDER BY metric_id, id",
                        [metric_ids],
                    )
                    dim_cols = [desc[0] for desc in cur.description]
                    all_dims = [dict(zip(dim_cols, r)) for r in cur.fetchall()]

                dims_by_metric: dict[str, list[dict]] = {}
                for d in all_dims:
                    mid = d["metric_id"]
                    dims_by_metric.setdefault(mid, []).append(d)

                metrics = []
                for def_row in definitions:
                    mid = def_row["id"]
                    m = self._row_to_metric(def_row, dims_by_metric.get(mid, []))
                    metrics.append(m)
                return metrics
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _filter)
