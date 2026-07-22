"""
PostgreSQL + pgvector implementation of AgentMemory.

Stores tool usage memories and text memories in a single PostgreSQL table
with pgvector for semantic search. Both memory types coexist in the same
table, differentiated by the ``memory_type`` column.
"""

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from easyq2sql.capabilities.agent_memory import (
    AgentMemory,
    TextMemory,
    TextMemorySearchResult,
    ToolMemory,
    ToolMemorySearchResult,
)
from easyq2sql.core.search import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .config import (
    CE_CANDIDATE_MULTIPLIER,
    DEFAULT_AGENT_MEMORY_TABLE,
    DEFAULT_CROSS_ENCODER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
)
from .embedding import EmbeddingHelper


# ---------------------------------------------------------------------------
# PostgresAgentMemory
# ---------------------------------------------------------------------------

class PostgresAgentMemory(AgentMemory):
    """PostgreSQL + pgvector implementation of AgentMemory.

    Tool usage and text memories live in the same table, distinguished by
    the ``memory_type`` column (``'tool_usage'`` or ``'text_memory'``).

    Args:
        connection_string: PostgreSQL connection string. Takes precedence
            over individual parameters.
        host: Database host (used if connection_string is None).
        port: Database port (default 5432).
        database: Database name.
        user: Database user.
        password: Database password.
        table_name: PostgreSQL table name (default ``"agent_memory"``).
        embedding_model: SentenceTransformer model name.
    """

    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        memory_type TEXT NOT NULL DEFAULT 'tool_usage',
        question TEXT DEFAULT '',
        content TEXT DEFAULT '',
        tool_name TEXT DEFAULT '',
        args_json JSONB DEFAULT '{{}}',
        success BOOLEAN DEFAULT TRUE,
        metadata_json JSONB DEFAULT '{{}}',
        "timestamp" TIMESTAMP DEFAULT NOW(),
        embedding vector({vector_dim}),
        search_text TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS {table}_embedding_idx
        ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    CREATE INDEX IF NOT EXISTS {table}_memory_type_idx ON {table} (memory_type);
    CREATE INDEX IF NOT EXISTS {table}_tool_name_idx ON {table} (tool_name);
    CREATE INDEX IF NOT EXISTS {table}_timestamp_idx ON {table} ("timestamp");

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
        table_name: str = DEFAULT_AGENT_MEMORY_TABLE,
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
        """Create the agent_memory table, indexes, and tsvector column.

        The ALTER TABLE … ADD COLUMN IF NOT EXISTS needs a short
        ``lock_timeout`` to prevent deadlocks when multiple connections
        initialise simultaneously.

        Also auto-migrates the ``embedding`` column if the model's vector
        dimension has changed.
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

        lock_id = int(hashlib.md5(self._table.encode()).hexdigest()[:8], 16) % (2**31 - 1)
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

    def _create_memory_id(self) -> str:
        import uuid
        return str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Row → model helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_tool_memory(row: dict) -> ToolMemory:
        args = row.get("args_json")
        if isinstance(args, str):
            args = json.loads(args)
        meta = row.get("metadata_json")
        if isinstance(meta, str):
            meta = json.loads(meta)
        meta = meta or {}
        return ToolMemory(
            memory_id=row["id"],
            question=row.get("question", ""),
            tool_name=row.get("tool_name", ""),
            args=args or {},
            timestamp=str(row.get("timestamp", "")),
            success=row.get("success", True),
            metadata=meta,
            trajectory=meta.get("trajectory"),
            final_sql=meta.get("final_sql"),
        )

    @staticmethod
    def _row_to_text_memory(row: dict) -> TextMemory:
        return TextMemory(
            memory_id=row["id"],
            content=row.get("content", ""),
            timestamp=str(row.get("timestamp", "")),
        )

    # ------------------------------------------------------------------
    # AgentMemory interface
    # ------------------------------------------------------------------

    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        trajectory: Optional[List[Dict[str, Any]]] = None,
        final_sql: Optional[str] = None,
    ) -> None:
        def _save():
            memory_id = self._create_memory_id()
            timestamp = datetime.now().isoformat()
            search_text = question
            embedding = self._embedding_helper.encode(search_text)

            # Merge trajectory and final_sql into metadata_json so they
            # persist without a DDL change.
            merged_meta = dict(metadata or {})
            if trajectory is not None:
                merged_meta["trajectory"] = trajectory
            if final_sql is not None:
                merged_meta["final_sql"] = final_sql

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, memory_type, question, tool_name, args_json,
                             success, metadata_json, "timestamp", embedding, search_text)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            memory_id,
                            "tool_usage",
                            question,
                            tool_name,
                            json.dumps(args, ensure_ascii=False),
                            success,
                            json.dumps(merged_meta, ensure_ascii=False),
                            timestamp,
                            embedding,
                            search_text,
                        ],
                    )
                conn.commit()
            finally:
                conn.close()

        await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def save_text_memory(
        self, content: str, context: ToolContext
    ) -> TextMemory:
        def _save():
            memory_id = self._create_memory_id()
            timestamp = datetime.now().isoformat()
            embedding = self._embedding_helper.encode(content)

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table}
                            (id, memory_type, content, "timestamp", embedding, search_text)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [memory_id, "text_memory", content, timestamp, embedding, content],
                    )
                conn.commit()
                return TextMemory(
                    memory_id=memory_id, content=content, timestamp=timestamp
                )
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(question)

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    # Build extra WHERE clauses for non-embedding filters
                    extra_where = ""
                    tool_param = None
                    if tool_name_filter:
                        extra_where = "AND tool_name = %s"
                        tool_param = tool_name_filter

                    # RRF hybrid search: vector (pgvector) + keyword (tsvector)
                    # FULL OUTER JOIN ensures docs from either ranking participate.
                    # Fetch extra candidates when Cross-Encoder is enabled so the
                    # second stage has enough documents to re-rank.
                    _fetch_limit = limit * CE_CANDIDATE_MULTIPLIER if self._cross_encoder else limit
                    # Convert question to tsquery prefix-matching format (e.g. "风险" → "风险:*")
                    ts_question = ' & '.join([f'{w}:*' for w in question.split()]) if question else question
                    cur.execute(
                        f"""
                        WITH
                        vector_ranked AS (
                            SELECT id,
                                ROW_NUMBER() OVER (
                                    ORDER BY embedding <=> %s::vector
                                ) AS rank
                            FROM {self._table}
                            WHERE memory_type = 'tool_usage'
                              AND success = TRUE
                              AND embedding IS NOT NULL
                              {extra_where}
                        ),
                        text_ranked AS (
                            SELECT id,
                                ROW_NUMBER() OVER (
                                    ORDER BY ts_rank(search_tsv, to_tsquery('simple', %s)) DESC
                                ) AS rank
                            FROM {self._table}
                            WHERE memory_type = 'tool_usage'
                              AND success = TRUE
                              AND search_tsv @@ to_tsquery('simple', %s)
                              {extra_where}
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
                        (
                            [query_embedding, ts_question, ts_question, _fetch_limit]
                            if tool_param is None
                            else [
                                query_embedding,
                                tool_param,
                                ts_question,
                                ts_question,
                                tool_param,
                                _fetch_limit,
                            ]
                        ),
                    )
                    cols = [desc[0] for desc in cur.description]
                    all_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                    # Cross-Encoder re-rank (optional second stage)
                    if self._cross_encoder and len(all_rows) > limit:
                        docs = [
                            row.get("search_text", "") for row in all_rows
                        ]
                        ce_indices = self._cross_encoder.rerank(
                            query=question, documents=docs, top_n=limit
                        )
                        all_rows = [
                            all_rows[i]
                            for i in ce_indices
                            if i < len(all_rows)
                        ][:limit]

                    results = []
                    for i, row_dict in enumerate(all_rows):
                        rrf_score = row_dict.pop("rrf_score", 0.0)
                        if rrf_score >= 0.002:
                            results.append(
                                ToolMemorySearchResult(
                                    memory=self._row_to_tool_memory(row_dict),
                                    similarity_score=round(rrf_score, 6),
                                    rank=i + 1,
                                )
                            )
                    return results
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        def _search():
            query_embedding = self._embedding_helper.encode(query)
            _fetch_limit = limit * CE_CANDIDATE_MULTIPLIER if self._cross_encoder else limit

            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    # RRF hybrid search: vector + keyword
                    # Convert query to tsquery prefix-matching format (e.g. "风险" → "风险:*")
                    ts_query = ' & '.join([f'{w}:*' for w in query.split()]) if query else query
                    cur.execute(
                        f"""
                        WITH
                        vector_ranked AS (
                            SELECT id,
                                ROW_NUMBER() OVER (
                                    ORDER BY embedding <=> %s::vector
                                ) AS rank
                            FROM {self._table}
                            WHERE memory_type = 'text_memory'
                              AND embedding IS NOT NULL
                        ),
                        text_ranked AS (
                            SELECT id,
                                ROW_NUMBER() OVER (
                                    ORDER BY ts_rank(search_tsv, to_tsquery('simple', %s)) DESC
                                ) AS rank
                            FROM {self._table}
                            WHERE memory_type = 'text_memory'
                              AND search_tsv @@ to_tsquery('simple', %s)
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
                        ce_indices = self._cross_encoder.rerank(
                            query=query, documents=docs, top_n=limit
                        )
                        all_rows = [
                            all_rows[i]
                            for i in ce_indices
                            if i < len(all_rows)
                        ][:limit]

                    results = []
                    for i, row_dict in enumerate(all_rows):
                        rrf_score = row_dict.pop("rrf_score", 0.0)
                        if rrf_score >= 0.002:
                            results.append(
                                TextMemorySearchResult(
                                    memory=self._row_to_text_memory(row_dict),
                                    similarity_score=round(rrf_score, 6),
                                    rank=i + 1,
                                )
                            )
                    return results
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT * FROM {self._table}
                        WHERE memory_type = 'tool_usage'
                        ORDER BY "timestamp" DESC
                        LIMIT %s
                        """,
                        [limit],
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [
                        self._row_to_tool_memory(dict(zip(cols, row)))
                        for row in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        def _get():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT * FROM {self._table}
                        WHERE memory_type = 'text_memory'
                        ORDER BY "timestamp" DESC
                        LIMIT %s
                        """,
                        [limit],
                    )
                    cols = [desc[0] for desc in cur.description]
                    return [
                        self._row_to_text_memory(dict(zip(cols, row)))
                        for row in cur.fetchall()
                    ]
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def delete_by_id(
        self, context: ToolContext, memory_id: str
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = %s AND memory_type = 'tool_usage'",
                        [memory_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def delete_text_memory(
        self, context: ToolContext, memory_id: str
    ) -> bool:
        def _delete():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self._table} WHERE id = %s AND memory_type = 'text_memory'",
                        [memory_id],
                    )
                    deleted = cur.rowcount
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        def _clear():
            conn = self._get_conn()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    conditions = []
                    params = []

                    if tool_name:
                        conditions.append("tool_name = %s")
                        params.append(tool_name)

                    if before_date:
                        conditions.append('"timestamp" < %s')
                        params.append(before_date)

                    if conditions:
                        where = "WHERE " + " AND ".join(conditions)
                        cur.execute(
                            f"DELETE FROM {self._table} {where}", params
                        )
                    else:
                        cur.execute(f"DELETE FROM {self._table}")

                    deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()

        return await asyncio.get_event_loop().run_in_executor(self._executor, _clear)
