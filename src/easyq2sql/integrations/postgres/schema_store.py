"""
PostgreSQL + pgvector implementation of SchemaStore.

Stores table schemas directly in PostgreSQL with pgvector for semantic
search. Raw data (columns, DDL) and vector embeddings coexist in the same
row — no separate vector database or JSON file store needed.
"""

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.schema_store import (
    ColumnSchema,
    SchemaSearchResult,
    SchemaStore,
    TableSchema,
    format_table_llm_text,
    format_table_search_text,
)
from easyq2sql.integrations.postgres.embedding import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .config import (
    CE_CANDIDATE_MULTIPLIER,
    DEFAULT_CROSS_ENCODER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_SCHEMA_STORE_TABLE,
)
from .embedding import EmbeddingHelper


# ---------------------------------------------------------------------------
# PostgresSchemaStore
# ---------------------------------------------------------------------------

class PostgresSchemaStore(SchemaStore):
    """PostgreSQL + pgvector implementation of SchemaStore.

    Each table schema is stored as a single row. The ``search_text`` column
    holds human-readable text that gets embedded into the ``embedding``
    column. Semantic search uses pgvector cosine distance (``<=>``).

    Tables are auto-created on first use.

    Args:
        connection_string: PostgreSQL connection string
            (``"postgresql://user:pass@host:port/dbname"``). Takes precedence
            over individual parameters.
        host: Database host (used if connection_string is None).
        port: Database port (default 5432).
        database: Database name.
        user: Database user.
        password: Database password.
        table_name: PostgreSQL table name for schema storage
            (default ``"schema_store"``).
        embedding_model: SentenceTransformer model name
            (default ``"sentence-transformers/all-MiniLM-L6-v2"``).
    """

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        table_name TEXT NOT NULL,
        schema_name TEXT DEFAULT '',
        database_name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        columns_json JSONB DEFAULT '[]',
        ddl TEXT DEFAULT '',
        row_count_estimate INTEGER DEFAULT 0,
        extracted_at TIMESTAMP DEFAULT NOW(),
        embedding vector({vector_dim}),
        search_text TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS {table}_embedding_idx
        ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    CREATE INDEX IF NOT EXISTS {table}_table_name_idx ON {table} (table_name);

    -- Hybrid search: weighted tsvector column + GIN index for full-text search
    -- Weights: table_name(A) > description(B) > column_names(C) > column_comments(D)
    ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS search_tsv tsvector;

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
        table_name: str = DEFAULT_SCHEMA_STORE_TABLE,
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
        # Pre-warm the embedding model in the background
        self._executor.submit(self._embedding_helper._get_model)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _get_conn(self):
        """Create a new psycopg2 connection with pgvector adapter registered."""
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
        """Create the schema_store table, indexes, and tsvector column.

        The ALTER TABLE … ADD COLUMN IF NOT EXISTS needs a short
        ``lock_timeout`` to prevent deadlocks when multiple connections
        initialise simultaneously.  Because the statement is idempotent
        (``IF NOT EXISTS``), lock failures are safe to ignore.

        Also auto-migrates the ``embedding`` column if the model's vector
        dimension has changed (e.g. switching from 384-dim all-MiniLM
        to 768-dim all-mpnet).
        """
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

        # Auto-migrate: if the existing vector column has a different
        # dimension than the current model, clear old embeddings and alter.
        # pgvector cannot cast between dimensions directly, so we must
        # NULL out existing vectors first (they'll be regenerated on the
        # next sync / upsert).
        #
        # Uses a PostgreSQL advisory lock to prevent a race condition
        # where two concurrent connections both detect the dimension
        # mismatch and the second one's UPDATE … SET embedding = NULL
        # wipes out embeddings that were just inserted by the first.
        import hashlib
        import re

        lock_id = int(hashlib.md5(self._table.encode()).hexdigest()[:8], 16) % (2**31 - 1)
        with conn.cursor() as cur:
            cur.execute(f"SELECT pg_advisory_lock({lock_id})")
            try:
                # Re-read dimension under lock — another connection may have
                # already completed the migration while we were waiting.
                # Uses format_type() for reliable dimension extraction
                # (atttypmod arithmetic can vary across pgvector versions).
                cur.execute(
                    """
                    SELECT format_type(atttypid, atttypmod)
                    FROM pg_attribute
                    WHERE attrelid = %s::regclass
                      AND attname = 'embedding'
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
                        cur.execute(
                            f"UPDATE {self._table} SET embedding = NULL"
                        )
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
    # Serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _format_search_text(table: TableSchema) -> str:
        """Build the compact pipe-joined retrieval text (embedding / fts / CE).

        Delegates to the shared :func:`format_table_search_text`. The rich
        LLM-facing breakdown lives in :func:`format_table_llm_text` and is
        rebuilt on demand in :meth:`search_tables`.
        """
        return format_table_search_text(table)

    @staticmethod
    def _row_to_table(row: dict) -> TableSchema:
        """Convert a database row (dict) into a TableSchema."""
        columns_data = row.get("columns_json")
        if isinstance(columns_data, str):
            columns_data = json.loads(columns_data)
        columns = [ColumnSchema(**c) for c in (columns_data or [])]

        extracted_at = row.get("extracted_at")
        if isinstance(extracted_at, str):
            extracted_at = datetime.fromisoformat(extracted_at) if extracted_at else datetime.now()

        return TableSchema(
            table_name=row["table_name"],
            schema_name=row.get("schema_name") or None,
            database_name=row.get("database_name", "default"),
            description=row.get("description") or None,
            columns=columns,
            ddl=row.get("ddl") or None,
            row_count_estimate=row.get("row_count_estimate") or None,
            extracted_at=extracted_at or datetime.now(),
        )

    # ------------------------------------------------------------------
    # Weighted tsvector builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_search_tsv_expr(table: TableSchema):
        """Build weighted tsvector SQL expression and parameters.

        Uses ``to_tsvector('simple', …)`` so that weights (setweight) and
        word-frequency are properly recorded.

        Weights (ts_rank multiples):
          A (1.0) = table_name
          B (0.4) = description
          C (0.2) = column_names
          D (0.1) = column_comments
        """
        tbl_name = table.table_name or ''
        desc = table.description or ''
        col_names = ' '.join([c.name for c in table.columns if c.name])
        col_comments = ' '.join([c.description for c in table.columns if c.description])

        expr = (
            "setweight(to_tsvector('simple', %s), 'A') || "
            "setweight(to_tsvector('simple', %s), 'B') || "
            "setweight(to_tsvector('simple', %s), 'C') || "
            "setweight(to_tsvector('simple', %s), 'D')"
        )
        return expr, [tbl_name, desc, col_names, col_comments]

    # ------------------------------------------------------------------
    # SchemaStore interface
    # ------------------------------------------------------------------

    async def save_table_schema(
        self, table: TableSchema, context: ToolContext
    ) -> None:
        def _save():
            doc_id = f"schema_{table.database_name}_{table.table_name}"
            search_text = self._format_search_text(table)
            embedding = self._embedding_helper.encode(search_text)
            columns_json = json.dumps(
                [c.model_dump() for c in table.columns], ensure_ascii=False
            )
            extracted_at = (
                table.extracted_at.isoformat() if table.extracted_at else datetime.now().isoformat()
            )

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    tsv_expr, tsv_params = self._build_search_tsv_expr(table)
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, table_name, schema_name, database_name, description,
                             columns_json, ddl, row_count_estimate, extracted_at,
                             embedding, search_text, search_tsv, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {tsv_expr}, NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            table_name = EXCLUDED.table_name,
                            schema_name = EXCLUDED.schema_name,
                            database_name = EXCLUDED.database_name,
                            description = EXCLUDED.description,
                            columns_json = EXCLUDED.columns_json,
                            ddl = EXCLUDED.ddl,
                            row_count_estimate = EXCLUDED.row_count_estimate,
                            extracted_at = EXCLUDED.extracted_at,
                            embedding = EXCLUDED.embedding,
                            search_text = EXCLUDED.search_text,
                            search_tsv = EXCLUDED.search_tsv,
                            updated_at = NOW()
                        """,
                        [
                            doc_id,
                            table.table_name,
                            table.schema_name or "",
                            table.database_name,
                            table.description or "",
                            columns_json,
                            table.ddl or "",
                            table.row_count_estimate or 0,
                            extracted_at,
                            embedding,
                            search_text,
                            *tsv_params,
                        ],
                    )
                conn.commit()
            finally:
                conn.close()

        await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def get_table_schema(
        self, table_name: str, context: ToolContext
    ) -> Optional[TableSchema]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} WHERE table_name = %s",
                        [table_name],
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    cols = [desc[0] for desc in cur.description]
                    return self._row_to_table(dict(zip(cols, row)))
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def search_tables(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.5,
    ) -> List[SchemaSearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(query)
            _fetch_limit = limit * CE_CANDIDATE_MULTIPLIER if self._cross_encoder else limit

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    # RRF hybrid search: vector (pgvector) + keyword (tsvector)
                    # Convert query to tsquery prefix-matching format (e.g. "risk" → "risk:*")
                    ts_query = ' | '.join([f'{w}:*' for w in query.split()]) if query else query
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
                                    ORDER BY ts_rank(search_tsv, %s) DESC
                                ) AS rank
                            FROM {self._table}
                            WHERE search_tsv @@ %s
                        ),
                        rrf AS (
                            SELECT
                                COALESCE(v.id, t.id) AS id,
                                COALESCE(1.0 / (60 + v.rank), 0.0)
                                + COALESCE(1.0 / (60 + t.rank), 0.0) AS rrf_score
                            FROM vector_ranked v
                            FULL OUTER JOIN text_ranked t ON v.id = t.id
                        )
                        SELECT t.*, r.rrf_score
                        FROM {self._table} t
                        JOIN rrf r ON t.id = r.id
                        ORDER BY r.rrf_score DESC
                        LIMIT %s
                        """,
                        [query_embedding, ts_query, ts_query, _fetch_limit],
                    )
                    cols = [desc[0] for desc in cur.description]
                    all_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                    # Cross-Encoder re-rank (optional second stage)
                    if self._cross_encoder and len(all_rows) > limit:
                        docs = [
                            row.get("search_text", "") for row in all_rows
                        ]
                        ce_scored = self._cross_encoder.rerank_with_scores(
                            query=query, documents=docs, top_n=limit
                        )
                        for orig_idx, ce_score in ce_scored:
                            if orig_idx < len(all_rows):
                                all_rows[orig_idx]["_ce_score"] = ce_score
                        all_rows = [
                            all_rows[idx]
                            for idx, _ in ce_scored
                            if idx < len(all_rows)
                        ][:limit]

                    results = []
                    for row_dict in all_rows:
                        score = row_dict.pop("_ce_score", row_dict.pop("rrf_score", 0.0))
                        if score >= 0.002:
                            row_dict.pop("search_text", None)
                            table = self._row_to_table(row_dict)
                            results.append(
                                SchemaSearchResult(
                                    table=table,
                                    similarity_score=round(score, 6),
                                    # LLM-facing rich text is rebuilt from the
                                    # reconstructed TableSchema; the stored
                                    # search_text column is the compact
                                    # retrieval form, not the display form.
                                    document_text=format_table_llm_text(table),
                                )
                            )
                    return results
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def update_table_description(
        self, table_name: str, description: str, context: ToolContext
    ) -> bool:
        table = await self.get_table_schema(table_name, context)
        if table is None:
            return False
        table.description = description
        table.extracted_at = datetime.now()
        await self.save_table_schema(table, context)
        return True

    async def update_column_description(
        self,
        table_name: str,
        column_name: str,
        description: str,
        context: ToolContext,
    ) -> bool:
        table = await self.get_table_schema(table_name, context)
        if table is None:
            return False
        found = False
        for col in table.columns:
            if col.name == column_name:
                col.description = description
                found = True
                break
        if not found:
            return False
        table.extracted_at = datetime.now()
        await self.save_table_schema(table, context)
        return True

    async def list_all_tables(
        self, context: ToolContext
    ) -> List[TableSchema]:
        def _list():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {self._table} ORDER BY table_name"
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [self._row_to_table(dict(zip(cols, row))) for row in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def delete_table_schema(
        self, table_name: str, context: ToolContext
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE table_name = %s",
                        [table_name],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def sync_all_schemas(
        self, tables: List[TableSchema], context: ToolContext
    ) -> int:
        def _sync():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    # Delete all existing
                    cur.execute(f"DELETE FROM {self._table}")
                    # Bulk insert
                    for table in tables:
                        doc_id = f"schema_{table.database_name}_{table.table_name}"
                        search_text = self._format_search_text(table)
                        embedding = self._embedding_helper.encode(search_text)
                        columns_json = json.dumps(
                            [c.model_dump() for c in table.columns], ensure_ascii=False
                        )
                        extracted_at = (
                            table.extracted_at.isoformat()
                            if table.extracted_at
                            else datetime.now().isoformat()
                        )
                        tsv_expr, tsv_params = self._build_search_tsv_expr(table)
                        cur.execute(
                            f"""
                            INSERT INTO {self._table}
                                (id, table_name, schema_name, database_name, description,
                                 columns_json, ddl, row_count_estimate, extracted_at,
                                 embedding, search_text, search_tsv, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {tsv_expr}, NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                table_name = EXCLUDED.table_name,
                                schema_name = EXCLUDED.schema_name,
                                database_name = EXCLUDED.database_name,
                                description = EXCLUDED.description,
                                columns_json = EXCLUDED.columns_json,
                                ddl = EXCLUDED.ddl,
                                row_count_estimate = EXCLUDED.row_count_estimate,
                                extracted_at = EXCLUDED.extracted_at,
                                embedding = EXCLUDED.embedding,
                                search_text = EXCLUDED.search_text,
                                search_tsv = EXCLUDED.search_tsv,
                                updated_at = NOW()
                            """,
                            [
                                doc_id,
                                table.table_name,
                                table.schema_name or "",
                                table.database_name,
                                table.description or "",
                                columns_json,
                                table.ddl or "",
                                table.row_count_estimate or 0,
                                extracted_at,
                                embedding,
                                search_text,
                                *tsv_params,
                            ],
                        )
                conn.commit()
                return len(tables)
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _sync)
