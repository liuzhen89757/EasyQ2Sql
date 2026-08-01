"""
ChromaDB + JSON dual-mode implementation of MetricStore.

Uses ChromaDB for semantic vector search and JSON files on disk for
authoritative CRUD (avoids ChromaDB metadata size limits for complex
Metric objects with nested function steps).
"""

import json
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from easyq2sql.capabilities.metric_store import (
    JoinClause,
    Metric,
    MetricSearchResult,
    MetricStore,
)

# Local MetricDimension for backward-compatible ChromaDB storage.
# The new architecture uses capabilites.dimension_store.Dimension instead,
# but ChromaDB's metric store keeps dimensions inline for simplicity.
from pydantic import BaseModel, Field


class MetricDimension(BaseModel):
    """Local dimension model for ChromaDB metric storage (backward compat)."""
    name: str = Field(description="Dimension label")
    field_ref: str = Field(description="table.column reference")
    joins: list[JoinClause] = Field(default_factory=list)
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
        "ChromaDB is required for ChromaMetricStore. Install with: pip install chromadb"
    )


class ChromaMetricStore(MetricStore):
    """Dual-mode MetricStore: ChromaDB for search, JSON files for CRUD.

    ChromaDB collections store document embeddings for semantic search.
    JSON files under ``metrics_dir`` serve as the authoritative source
    for create/read/update/delete operations, avoiding ChromaDB's
    metadata size constraints for complex Metric objects.

    The ChromaDB index is updated on every write to keep search results
    in sync with the authoritative JSON store.

    Args:
        persist_directory: Directory where ChromaDB stores its data.
        metrics_dir: Directory for JSON metric files. Defaults to
                     ``<persist_directory>/metrics/``.
        collection_name: ChromaDB collection name (default ``"metric_store"``).
        embedding_function: Optional custom embedding function.
    """

    def __init__(
        self,
        persist_directory: str = "./chroma_memory",
        metrics_dir: Optional[str] = None,
        collection_name: str = "metric_store",
        embedding_function=None,
        cross_encoder_model: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.persist_directory = persist_directory
        self.metrics_dir = metrics_dir or os.path.join(persist_directory, "metrics")
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

        # Ensure metrics directory exists
        os.makedirs(self.metrics_dir, exist_ok=True)

        # Eagerly warm up the embedding function in the background so the first
        # API call doesn't hang while downloading the SentenceTransformer model.
        self._executor.submit(self._get_embedding_function)

    # ------------------------------------------------------------------
    # ChromaDB helpers (same pattern as ChromaAgentMemory)
    # ------------------------------------------------------------------

    def _get_client(self):
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
        if self._collection is None:
            client = self._get_client()
            try:
                self._collection = client.get_collection(name=self.collection_name)
            except NotFoundError:
                embedding_func = self._get_embedding_function()
                self._collection = client.create_collection(
                    name=self.collection_name,
                    embedding_function=embedding_func,
                    metadata={"description": "Business metric definitions"},
                )
        return self._collection

    # ------------------------------------------------------------------
    # JSON file helpers (authoritative CRUD)
    # ------------------------------------------------------------------

    def _metric_file_path(self, metric_id: str) -> str:
        return os.path.join(self.metrics_dir, f"{metric_id}.json")

    def _read_metric_from_file(self, metric_id: str) -> Optional[Metric]:
        path = self._metric_file_path(metric_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Metric(**data)

    def _write_metric_to_file(self, metric: Metric) -> None:
        path = self._metric_file_path(metric.id)
        data = metric.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _delete_metric_file(self, metric_id: str) -> bool:
        path = self._metric_file_path(metric_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    # ------------------------------------------------------------------
    # ChromaDB document helpers (one document per dimension — 1:1:1)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_dimension_document(metric: Metric, dim: MetricDimension, dim_index: int) -> str:
        """Format one metric-dimension pair into embedding text.

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
    def _format_no_dimension_document(metric: Metric) -> str:
        """Format a metric with no dimensions into embedding text.

        Format::

            # Metric: name(table.field)
            Description: ...
        """
        lines = [f"# Metric: {metric.name}({metric.analysis_field})"]
        if metric.description:
            lines.append(f"Description: {metric.description}")
        return "\n".join(lines)

    @staticmethod
    def _dimension_to_chroma_metadata(metric: Metric, dim: MetricDimension) -> dict:
        """Extract searchable metadata for one metric-dimension pair."""
        join_parts = [
            f"{j.join_type} {j.target_table} ON {j.source_table}.{j.source_column}={j.target_table}.{j.target_column}"
            for j in dim.joins
        ]
        return {
            "metric_id": metric.id,
            "metric_name": metric.name,
            "metric_description": metric.description or "",
            "metric_field": metric.analysis_field,
            "dimension_name": dim.name,
            "dimension_field": dim.field_ref,
            "join_relations": ", ".join(join_parts) if join_parts else "",
            "is_metric": True,
        }

    @staticmethod
    def _chroma_id(metric_id: str, dim_index: int) -> str:
        return f"{metric_id}__{dim_index}"

    def _sync_metric_to_chroma(self, metric: Metric) -> None:
        """Upsert one document per dimension into ChromaDB (1:1:1)."""
        collection = self._get_collection()
        # Delete all old dimension docs for this metric first
        self._delete_metric_from_chroma(metric.id)

        if metric.dimensions:
            ids, docs, metas = [], [], []
            for i, dim in enumerate(metric.dimensions):
                ids.append(self._chroma_id(metric.id, i))
                docs.append(self._format_dimension_document(metric, dim, i))
                metas.append(self._dimension_to_chroma_metadata(metric, dim))
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
        else:
            collection.upsert(
                ids=[self._chroma_id(metric.id, -1)],
                documents=[self._format_no_dimension_document(metric)],
                metadatas=[{
                    "metric_id": metric.id,
                    "metric_name": metric.name,
                    "metric_description": metric.description or "",
                    "metric_field": metric.analysis_field,
                    "dimension_name": "",
                    "dimension_field": "",
                    "join_relations": "",
                    "is_metric": True,
                }],
            )

    def _delete_metric_from_chroma(self, metric_id: str) -> None:
        """Remove all dimension documents for a metric from ChromaDB."""
        collection = self._get_collection()
        try:
            existing = collection.get(where={"metric_id": metric_id})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # MetricStore interface
    # ------------------------------------------------------------------

    async def create_metric(
        self, metric: Metric, context: ToolContext
    ) -> Metric:
        """Create a new metric. Persists to JSON file and indexes in ChromaDB."""

        def _create():
            metric.updated_at = datetime.now()
            self._write_metric_to_file(metric)
            self._sync_metric_to_chroma(metric)
            return metric

        return await asyncio.get_event_loop().run_in_executor(self._executor, _create)

    async def get_metric(
        self, metric_id: str, context: ToolContext
    ) -> Optional[Metric]:
        """Retrieve a single metric by ID from the JSON store."""

        def _get():
            return self._read_metric_from_file(metric_id)

        return await asyncio.get_event_loop().run_in_executor(self._executor, _get)

    async def update_metric(
        self, metric: Metric, context: ToolContext
    ) -> bool:
        """Update an existing metric. Returns True if found and updated.

        Deletes the old ChromaDB record before re-indexing so that stale
        metadata fields from a previous schema version are fully removed.
        """

        def _update():
            existing = self._read_metric_from_file(metric.id)
            if existing is None:
                return False
            metric.updated_at = datetime.now()
            self._write_metric_to_file(metric)
            # Delete old ChromaDB record first, then re-sync.
            # upsert alone merges metadata — it won't remove stale keys.
            self._delete_metric_from_chroma(metric.id)
            self._sync_metric_to_chroma(metric)
            return True

        return await asyncio.get_event_loop().run_in_executor(self._executor, _update)

    async def delete_metric(
        self, metric_id: str, context: ToolContext
    ) -> bool:
        """Delete a metric by ID from both JSON and ChromaDB."""

        def _delete():
            self._delete_metric_from_chroma(metric_id)
            return self._delete_metric_file(metric_id)

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def list_metrics(
        self, context: ToolContext
    ) -> List[Metric]:
        """List all stored metrics from the JSON store."""

        def _list():
            metrics = []
            if not os.path.exists(self.metrics_dir):
                return metrics
            for filename in os.listdir(self.metrics_dir):
                if filename.endswith(".json"):
                    metric_id = filename[:-5]  # strip .json
                    metric = self._read_metric_from_file(metric_id)
                    if metric:
                        metrics.append(metric)
            metrics.sort(key=lambda m: m.updated_at, reverse=True)
            return metrics

        return await asyncio.get_event_loop().run_in_executor(self._executor, _list)

    async def search_metrics(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
    ) -> List[MetricSearchResult]:
        """Semantically search metrics using ChromaDB vector similarity.

        Returns one result per unique metric (deduplicated across dimensions).
        """

        def _search():
            from easyq2sql.core.search import hybrid_search_chromadb

            collection = self._get_collection()
            hybrid_results = hybrid_search_chromadb(
                collection=collection,
                query=query,
                n_results=limit * 3,
                where={"is_metric": True},
                cross_encoder=self._cross_encoder,
            )

            seen: set[str] = set()
            search_results = []
            for hr in hybrid_results:
                meta = hr.metadata or {}
                metric_id = meta.get("metric_id", "")
                if metric_id in seen:
                    continue
                seen.add(metric_id)
                metric = self._read_metric_from_file(metric_id)
                if metric:
                    search_results.append(
                        MetricSearchResult(
                            metric=metric,
                            similarity_score=hr.fused_score,
                            document_text=hr.document,
                        )
                    )
                if len(search_results) >= limit:
                    break
            return search_results

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_metrics_by_table(
        self, table_name: str, context: ToolContext
    ) -> List[Metric]:
        """Get all metrics that reference a given table."""

        def _filter():
            metrics = []
            if not os.path.exists(self.metrics_dir):
                return metrics
            for filename in os.listdir(self.metrics_dir):
                if filename.endswith(".json"):
                    metric_id = filename[:-5]
                    metric = self._read_metric_from_file(metric_id)
                    if metric and metric.analysis_table == table_name:
                        metrics.append(metric)
            return metrics

        return await asyncio.get_event_loop().run_in_executor(self._executor, _filter)
