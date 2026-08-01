"""
PostgreSQL + pgvector implementation of TerminologyStore.

Maps business terms (natural language) to metrics or dimensions.
Supports both manually configured entries and auto-generated entries
.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.terminology_store import (
    TerminologyEntry,
    TerminologySearchResult,
    TerminologyStore,
)
from easyq2sql.core.search import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .config import (
    CE_CANDIDATE_MULTIPLIER,
    DEFAULT_CROSS_ENCODER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_TERMINOLOGY_TABLE
)
from .embedding import EmbeddingHelper


class PostgresTerminologyStore(TerminologyStore):
    """PostgreSQL + pgvector TerminologyStore.

    **terminology_mappings**::

        id                  TEXT PRIMARY KEY
        term_text           TEXT NOT NULL
        target_type         TEXT NOT NULL  — 'metric' | 'dimension'
        target_id           TEXT NOT NULL
        business_definition TEXT DEFAULT ''
        synonyms_json       JSONB DEFAULT '[]'
        source              TEXT DEFAULT 'manual'
        created_at          TIMESTAMP
        embedding           vector(N)
        search_text         TEXT
        search_tsv          tsvector GENERATED ALWAYS
    """

    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        term_text TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        business_definition TEXT DEFAULT '',
        synonyms_json JSONB DEFAULT '[]',
        source TEXT DEFAULT 'manual',
        created_at TIMESTAMP DEFAULT NOW(),
        embedding vector({vector_dim}),
        search_text TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS {table}_target_idx ON {table} (target_type, target_id);

    CREATE INDEX IF NOT EXISTS {table}_embedding_idx
        ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

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
        table_name: str = DEFAULT_TERMINOLOGY_TABLE,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        cross_encoder_model: Optional[str] = DEFAULT_CROSS_ENCODER_MODEL,
        device: Optional[str] = None,
        metric_store=None,
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
        self._metric_store = metric_store
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
    def _format_search_text(entry: TerminologyEntry) -> str:
        """Build embedding text for a terminology entry.

        Format::

            # {term_text}[/{synonym1}/{synonym2}...]
            business_definition:{business_definition}

        Example::

            # 基金收益率/基金经理收益
            business_definition:衡量基金经理收益的指标
        """
        header = f"# {entry.term_text}"
        if entry.synonyms:
            header += "/" + "/".join(entry.synonyms)
        parts = [header]
        if entry.business_definition:
            parts.append(f"{entry.business_definition}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Row conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: dict) -> TerminologyEntry:
        import json

        synonyms = row.get("synonyms_json")
        if isinstance(synonyms, str):
            synonyms = json.loads(synonyms) if synonyms else []
        elif synonyms is None:
            synonyms = []

        return TerminologyEntry(
            id=row["id"],
            term_text=row["term_text"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            business_definition=row.get("business_definition") or None,
            synonyms=synonyms,
            source=row.get("source", "manual"),
            created_at=row.get("created_at") or datetime.now(),
        )

    # ------------------------------------------------------------------
    # TerminologyStore interface
    # ------------------------------------------------------------------

    async def create_entry(
        self, entry: TerminologyEntry, context: ToolContext
    ) -> TerminologyEntry:
        def _create():
            import json

            search_text = self._format_search_text(entry)
            embedding = self._embedding_helper.encode(search_text)

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, term_text, target_type, target_id,
                             business_definition, synonyms_json, source,
                             created_at, embedding, search_text)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            term_text = EXCLUDED.term_text,
                            target_type = EXCLUDED.target_type,
                            target_id = EXCLUDED.target_id,
                            business_definition = EXCLUDED.business_definition,
                            synonyms_json = EXCLUDED.synonyms_json,
                            source = EXCLUDED.source,
                            embedding = EXCLUDED.embedding,
                            search_text = EXCLUDED.search_text
                        """,
                        [
                            entry.id,
                            entry.term_text,
                            entry.target_type,
                            entry.target_id,
                            entry.business_definition or "",
                            json.dumps(entry.synonyms, ensure_ascii=False),
                            entry.source,
                            entry.created_at.isoformat() if entry.created_at else datetime.now().isoformat(),
                            embedding,
                            search_text,
                        ],
                    )
                conn.commit()
                return entry
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _create)

    async def get_entry(
        self, entry_id: str, context: ToolContext
    ) -> Optional[TerminologyEntry]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} WHERE id = %s",
                        [entry_id],
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    cols = [desc[0] for desc in cur.description]
                    return self._row_to_entry(dict(zip(cols, row)))
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def update_entry(
        self, entry: TerminologyEntry, context: ToolContext
    ) -> bool:
        def _check():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id FROM {self._table} WHERE id = %s",
                        [entry.id],
                    )
                    return cur.fetchone() is not None
            finally:
                conn.close()

        exists = await asyncio.get_event_loop().run_in_executor(self._executor, _check)
        if not exists:
            return False
        # Mark as manual when user explicitly updates
        entry.source = "manual"
        await self.create_entry(entry, context)
        return True

    async def delete_entry(
        self, entry_id: str, context: ToolContext
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = %s",
                        [entry_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def list_entries(
        self, context: ToolContext, *, source: Optional[str] = None
    ) -> List[TerminologyEntry]:
        def _list():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    if source:
                        cur.execute(
                            f"SELECT * FROM {self._table} "
                            f"WHERE source = %s ORDER BY created_at DESC",
                            [source],
                        )
                    else:
                        cur.execute(
                            f"SELECT * FROM {self._table} ORDER BY created_at DESC"
                        )
                    cols = [desc[0] for desc in cur.description]
                    return [self._row_to_entry(dict(zip(cols, r))) for r in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def search_terminology(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
    ) -> List[TerminologySearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(query)
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    # Extract word/CJK tokens from query for keyword search.
                    # Strip structured format prefixes ("# metric:", "# dimensions:")
                    # so only the actual search values contribute to keyword matching.
                    import re

                    cleaned = re.sub(r"#\s*\w+:\s*", "", query)
                    tokens = re.findall(r"[\w一-鿿]+", cleaned)
                    ts_query = (
                        " | ".join([f"{t}:*" for t in tokens])
                        if tokens
                        else query
                    )
                    params = [query_embedding, ts_query, ts_query, limit * CE_CANDIDATE_MULTIPLIER]

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
                        SELECT e.*, r.rrf_score
                        FROM {self._table} e
                        JOIN rrf r ON e.id = r.id
                        ORDER BY r.rrf_score DESC
                        LIMIT %s
                        """,
                        params,
                    )
                    cols = [desc[0] for desc in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                if not rows:
                    return []

                if self._cross_encoder and len(rows) > limit:
                    docs = [row.get("search_text", "") for row in rows]
                    ce_scored = self._cross_encoder.rerank_with_scores(
                        query=query, documents=docs, top_n=limit * CE_CANDIDATE_MULTIPLIER
                    )
                    # Attach CE scores and reorder by CE rank
                    for orig_idx, ce_score in ce_scored:
                        if orig_idx < len(rows):
                            rows[orig_idx]["_ce_score"] = ce_score
                    rows = [rows[idx] for idx, _ in ce_scored if idx < len(rows)]

                rows = rows[:limit]

                results = []
                for r in rows:
                    entry = self._row_to_entry(r)
                    results.append(
                        TerminologySearchResult(
                            entry=entry,
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

    async def get_terms_by_target(
        self,
        target_type: str,
        target_id: str,
        context: ToolContext,
    ) -> List[TerminologyEntry]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} "
                        f"WHERE target_type = %s AND target_id = %s "
                        f"ORDER BY created_at DESC",
                        [target_type, target_id],
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [self._row_to_entry(dict(zip(cols, r))) for r in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def sync_auto_terms(
        self,
        context: ToolContext,
        metrics: Optional[List] = None,
        dimensions: Optional[List] = None,
    ) -> int:
        """Generate auto terminology entries from metric and dimension names.

        - For metrics: term_text = metric name, target_type = 'metric'
        - For dimensions: term_text = "{dim_name}({metric_name})", target_type = 'dimension'
        """
        count = 0

        # Fetch metrics if not provided
        if metrics is None and self._metric_store:
            metrics = await self._metric_store.list_metrics(context)
        metrics = metrics or []

        # Fetch dimensions if not provided
        if dimensions is None and self._dimension_store:
            dimensions = await self._dimension_store.list_dimensions(context)
        dimensions = dimensions or []

        # Build metric name lookup
        metric_names: dict[str, str] = {m.id: m.name for m in metrics}

        # Generate auto entries for metrics
        for m in metrics:
            entry = TerminologyEntry(
                id=f"term_auto_metric_{m.id}",
                term_text=m.name,
                target_type="metric",
                target_id=m.id,
                business_definition=m.business_definition,
                synonyms=[],
                source="auto",
            )
            await self.create_entry(entry, context)
            count += 1

        # Generate auto entries for dimensions
        for d in dimensions:
            metric_name = metric_names.get(d.metric_id, d.metric_id)
            # Combine business_definition and value_range
            biz_parts = []
            if d.business_definition:
                biz_parts.append(d.business_definition)
            if d.value_range:
                biz_parts.append(d.value_range)
            biz_def = " | ".join(biz_parts) if biz_parts else None
            entry = TerminologyEntry(
                id=f"term_auto_dim_{d.id}",
                term_text=f"{d.name}({metric_name})",
                target_type="dimension",
                target_id=d.id,
                business_definition=biz_def,
                synonyms=[],
                source="auto",
            )
            await self.create_entry(entry, context)
            count += 1

        return count
