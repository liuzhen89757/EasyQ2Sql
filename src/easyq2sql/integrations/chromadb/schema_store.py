"""
ChromaDB implementation of SchemaStore.

This implementation uses ChromaDB for vector storage of database table schemas,
following the same pattern as ChromaAgentMemory.
"""

import json
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Mapping, Optional

from easyq2sql.capabilities.schema_store import (
    ColumnSchema,
    SchemaSearchResult,
    SchemaStore,
    TableSchema,
)
from easyq2sql.core.search import CrossEncoderReranker
from easyq2sql.core.tool import ToolContext

from .agent_memory import (
    CHROMADB_AVAILABLE,
    NotFoundError,
    _get_or_create_embedding_function,
    chromadb,
    Settings,
)

if not CHROMADB_AVAILABLE:
    raise ImportError(
        "ChromaDB is required for ChromaSchemaStore. Install with: pip install chromadb"
    )


class ChromaSchemaStore(SchemaStore):
    """ChromaDB-based implementation of SchemaStore.

    Stores table schemas as vector embeddings for semantic search.
    Each table schema is stored as a document with its formatted text
    (table name, description, columns) used for embedding, and the
    full structured data serialized as JSON in metadata.

    Uses a separate ChromaDB collection (``"schema_store"``) so schemas
    and agent memories are isolated within the same persist directory.

    Args:
        persist_directory: Directory where ChromaDB stores its data.
        collection_name: ChromaDB collection name (default ``"schema_store"``).
        embedding_function: Optional custom embedding function.
    """

    def __init__(
        self,
        persist_directory: str = "./chroma_memory",
        collection_name: str = "schema_store",
        embedding_function=None,
        cross_encoder_model: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._embedding_function = embedding_function
        self._device = device
        self._cross_encoder = (
            CrossEncoderReranker(cross_encoder_model, device=device)
            if cross_encoder_model
            else None
        )
        # Eagerly warm up the embedding function in the background so the first
        # API call doesn't hang while downloading the SentenceTransformer model.
        self._executor.submit(self._get_embedding_function)

    def _get_client(self):
        """Get or create ChromaDB PersistentClient."""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
        return self._client

    def _get_embedding_function(self):
        """Get or create the embedding function (uses module-level cache)."""
        if self._embedding_function is None:
            self._embedding_function = _get_or_create_embedding_function(
                device=self._device
            )
        return self._embedding_function

    def _get_collection(self):
        """Get or create the ChromaDB collection for schemas."""
        if self._collection is None:
            client = self._get_client()
            try:
                self._collection = client.get_collection(name=self.collection_name)
            except NotFoundError:
                embedding_func = self._get_embedding_function()
                self._collection = client.create_collection(
                    name=self.collection_name,
                    embedding_function=embedding_func,
                    metadata={"description": "Database table schemas for NL-to-SQL"},
                )
        return self._collection

    @staticmethod
    def _format_table_document(table: TableSchema) -> str:
        """Format a TableSchema into an embedding-friendly text document.

        Produces a per-column breakdown format:
            # Table: {name}
            [
            (col:TYPE, Primary Key, description
            Maps to ref_table(col), Examples: [v1, v2, v3]),
            (col:TYPE, description, Examples: [v1, v2, v3]),
            ]
        """
        lines = [f"# Table: {table.table_name}"]
        if table.description:
            lines.append(f"Description: {table.description}")
        lines.append("[")

        for col in table.columns:
            # Build the opening: (name:TYPE, flags, description
            flags: list[str] = []
            if col.is_primary_key:
                flags.append("Primary Key")
            if col.is_foreign_key:
                flags.append("Foreign Key")

            flag_str = ", ".join(flags)
            desc = col.description or ""
            header = f"({col.name}:{col.data_type}"
            if flag_str:
                header += f", {flag_str}"
            if desc:
                header += f", {desc}"
            lines.append(header)

            # Build continuation line: Maps to, Examples
            extras: list[str] = []
            if col.is_foreign_key and col.fk_reference_table:
                ref_col = col.fk_reference_column or "id"
                extras.append(f"Maps to {col.fk_reference_table}({ref_col})")
            if col.examples:
                truncated = [e[:100] + "..." if len(e) > 100 else e for e in col.examples]
                extras.append(f"Examples: [{', '.join(truncated)}]")

            if extras:
                lines.append(", ".join(extras))

            lines[-1] += "),"

        lines.append("]")
        return "\n".join(lines)

    @staticmethod
    def _table_to_metadata(table: TableSchema) -> dict:
        """Serialize a TableSchema into ChromaDB-compatible metadata dict.

        ChromaDB metadata values must be primitive types (str, int, float, bool),
        so complex fields are JSON-serialized.
        """
        return {
            "table_name": table.table_name,
            "schema_name": table.schema_name or "",
            "database_name": table.database_name,
            "description": table.description or "",
            "columns_json": json.dumps(
                [col.model_dump() for col in table.columns]
            ),
            "ddl": table.ddl or "",
            "row_count_estimate": table.row_count_estimate or 0,
            "extracted_at": table.extracted_at.isoformat()
            if table.extracted_at
            else "",
            "is_schema": True,
        }

    @staticmethod
    def _metadata_to_table(
        metadata: Mapping[str, Any], similarity_score: float = 0.0
    ) -> TableSchema:
        """Deserialize ChromaDB metadata back into a TableSchema."""
        columns_data = json.loads(str(metadata.get("columns_json", "[]")))
        columns = [ColumnSchema(**c) for c in columns_data]

        extracted_at_str = str(metadata.get("extracted_at", ""))
        return TableSchema(
            table_name=str(metadata.get("table_name", "")),
            schema_name=str(metadata.get("schema_name", "")) or None,
            database_name=str(metadata.get("database_name", "default")),
            description=str(metadata.get("description", "")) or None,
            columns=columns,
            ddl=str(metadata.get("ddl", "")) or None,
            row_count_estimate=int(metadata.get("row_count_estimate", 0)) or None,
            extracted_at=datetime.fromisoformat(extracted_at_str)
            if extracted_at_str
            else datetime.now(),
        )

    async def save_table_schema(
        self, table: TableSchema, context: ToolContext
    ) -> None:
        """Save or update a single table schema."""

        def _save():
            collection = self._get_collection()
            doc_id = f"schema_{table.database_name}_{table.table_name}"
            document = self._format_table_document(table)
            metadata = self._table_to_metadata(table)
            collection.upsert(ids=[doc_id], documents=[document], metadatas=[metadata])

        await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def get_table_schema(
        self, table_name: str, context: ToolContext
    ) -> Optional[TableSchema]:
        """Retrieve a single table schema by name."""

        def _get():
            collection = self._get_collection()
            results = collection.get(where={"table_name": table_name})
            if results["metadatas"] and len(results["metadatas"]) > 0:
                return self._metadata_to_table(results["metadatas"][0])
            return None

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def search_tables(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.5,
    ) -> List[SchemaSearchResult]:
        """Semantically search tables by natural language query."""

        def _search():
            from easyq2sql.core.search import hybrid_search_chromadb

            collection = self._get_collection()
            hybrid_results = hybrid_search_chromadb(
                collection=collection,
                query=query,
                n_results=limit,
                where={"is_schema": True},
                cross_encoder=self._cross_encoder,
            )

            search_results = []
            for hr in hybrid_results:
                meta = hr.metadata or {}
                table = self._metadata_to_table(meta, hr.fused_score)
                search_results.append(
                    SchemaSearchResult(
                        table=table,
                        similarity_score=hr.fused_score,
                        document_text=hr.document,
                    )
                )
            return search_results

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def update_table_description(
        self, table_name: str, description: str, context: ToolContext
    ) -> bool:
        """Update a table's description and re-index in vector store."""

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
        """Update a column's description and re-index in vector store."""

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
        """List all stored table schemas."""

        def _list():
            collection = self._get_collection()
            results = collection.get(where={"is_schema": True})
            tables = []
            if results["metadatas"]:
                for metadata in results["metadatas"]:
                    tables.append(self._metadata_to_table(metadata))
            return tables

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def delete_table_schema(
        self, table_name: str, context: ToolContext
    ) -> bool:
        """Delete a table schema from storage."""

        def _delete():
            collection = self._get_collection()
            results = collection.get(where={"table_name": table_name})
            if results["ids"] and len(results["ids"]) > 0:
                collection.delete(ids=results["ids"])
                return True
            return False

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def sync_all_schemas(
        self, tables: List[TableSchema], context: ToolContext
    ) -> int:
        """Full sync: replace all stored schemas with the given list."""

        def _sync():
            collection = self._get_collection()

            # Delete all existing schema entries
            existing = collection.get(where={"is_schema": True})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])

            # Insert all new schemas
            if not tables:
                return 0

            ids = []
            documents = []
            metadatas = []
            for table in tables:
                ids.append(f"schema_{table.database_name}_{table.table_name}")
                documents.append(self._format_table_document(table))
                metadatas.append(self._table_to_metadata(table))

            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            return len(tables)

        return await asyncio.get_event_loop().run_in_executor(self._executor, _sync)
