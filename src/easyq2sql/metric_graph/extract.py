"""
Metric graph extraction service.

Bridges the LightRAG-style structured extraction (engine in
``easyq2sql.metric_graph.engine``) to the project's own
``LlmService`` interface, and adds helpers to build the LLM input text and
the Table/Field validation set directly from ``TableSchema`` objects.

The extraction is *not* coupled to the demo CLI: it reuses the same prompt /
parser / gleaning loop, but the LLM backend is the framework's ``LlmService``
(OpenAI / Anthropic / Ollama / ...) instead of the demo's ad-hoc OpenAI client.
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional

from easyq2sql.core.llm.models import LlmMessage, LlmRequest
from easyq2sql.core.user.models import User
import easyq2sql.metric_graph.engine as _engine

#: Default schema file used to constrain extraction (entity types + relations).
#: MetricSchema.json is co-located with this module (moved out of
#: integrations/postgres when the metric_graph package was split off).
_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "MetricSchema.json",
)

#: System user used for LLM audit/permission purposes when none is supplied.
_SYSTEM_USER = User(id="metric_graph_extractor", group_memberships=["admin"])

#: Default per-table extraction concurrency cap (fallback for
#: ``MetricGraphExtractor.extract``).
DEFAULT_MAX_CONCURRENCY: int = 4

#: Default gleaning (gap-filling) rounds for LightRAG-style extraction.
DEFAULT_MAX_GLEANING: int = 0


class LlmServiceAdapter:
    """Wrap the framework ``LlmService`` into the ``llm_func`` callable that
    ``extract_entities`` expects.

    Expected signature::

        async def f(user_prompt, *, system_prompt=None, history_messages=None) -> str
    """

    def __init__(self, llm_service, user: Optional[User] = None):
        self._llm = llm_service
        self._user = user or _SYSTEM_USER

    async def __call__(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None,
        history_messages: Optional[list] = None,
    ) -> str:
        messages: List[LlmMessage] = []
        if history_messages:
            for m in history_messages:
                if not isinstance(m, dict):
                    continue
                messages.append(
                    LlmMessage(role=m.get("role", "user"), content=m.get("content", ""))
                )
        messages.append(LlmMessage(role="user", content=user_prompt))

        request = LlmRequest(
            messages=messages,
            user=self._user,
            system_prompt=system_prompt,
            temperature=0.0,
        )
        resp = await self._llm.send_request(request)
        return resp.content or ""


def _format_column(c) -> str:
    """Format a ``ColumnSchema`` into the ``(name:type, Primary Key, desc ...)``
    hint used by the extraction prompt."""
    header = f"{c.name}:{c.data_type}"
    extras = []
    if c.is_primary_key:
        extras.append("Primary Key")
    if c.description:
        extras.append(c.description)
    if extras:
        header += ", " + ", ".join(extras)

    details = []
    if c.examples:
        details.append(f"Examples: {c.examples}")
    if c.value_range:
        details.append(f"Value Range: {c.value_range}")

    if details:
        return f"({header}\n" + ", ".join(details) + ")"
    return f"({header})"


def build_extraction_text(tables) -> str:
    """Build the ``# Table: ...`` text block fed to the extraction LLM from a
    list of ``TableSchema`` objects."""
    blocks = []
    for t in tables:
        columns = ",\n".join(_format_column(c) for c in t.columns)
        desc = t.description or ""
        blocks.append(
            f"# Table: {t.table_name}\nDescription: {desc}\n[\n{columns}\n]"
        )
    return "\n\n".join(blocks)


def build_table_field_result(tables) -> dict:
    """Build the ``{table: {field: col_meta}}`` validation set consumed by
    ``validate_metric_fields``.

    Each field maps to its column metadata so validation can opportunistically
    pull ``value_range`` and the foreign-key relation (same logic the schema
    ``search_text`` uses to surface ``Value Range`` / ``# Foreign keys``) and
    inject them into the extracted metric entity's ``properties``.
    """
    tables_map = {}
    for t in tables:
        table_name = t.table_name
        fields = {}
        for c in t.columns:
            fk = None
            if c.is_foreign_key and c.fk_reference_table:
                fk = f"{table_name}.{c.name} = {c.fk_reference_table}.{c.fk_reference_column or 'id'}"
            fields[c.name] = {
                "value_range": c.value_range,
                "fk": fk,
            }
        tables_map[table_name] = fields
    return {"tables": tables_map}


class MetricGraphExtractor:
    """Extract the metric graph (原子指标 / 派生指标 / 复合指标) from table
    schemas, using the framework's ``LlmService`` and the MetricSchema.json
    constraints."""

    def __init__(
        self,
        llm_service,
        user: Optional[User] = None,
        schema_path: Optional[str] = None,
        language: str = "Simplified Chinese",
        max_gleaning: int = DEFAULT_MAX_GLEANING,
    ):
        self._llm = llm_service
        self._user = user or _SYSTEM_USER
        self._schema_path = schema_path or _SCHEMA_PATH
        self._language = language
        self._max_gleaning = max_gleaning

    def _load_schema(self):
        if self._schema_path and os.path.exists(self._schema_path):
            loaded = _engine.load_schema_from_file(self._schema_path)
            return (
                loaded["schema_definition"],
                loaded["entity_types"],
                loaded["relationship_types"],
            )
        return None, None, None

    async def extract(self, tables, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> dict:
        """Run structured extraction table-by-table.

        Each table is extracted independently (single chunk), with the table
        name passed as ``chunk_key`` so every entity's ``source_id`` records
        which table it came from. Field properties (来源字段 / 维度字段来源)
        therefore carry only the field name, not ``table.column``.

        Up to ``max_concurrency`` tables are extracted concurrently. Because
        the framework ``LlmService`` is backed by a *synchronous* client whose
        ``send_request`` blocks the event loop, each table's extraction runs in
        a dedicated worker thread (``asyncio.to_thread``) so the blocking LLM
        calls overlap in time. An ``asyncio.Semaphore`` bounds the number of
        concurrent workers; results are collected back in ``tables`` order so
        the merged output stays deterministic.

        Returns ``{"entities": [...], "relationships": [...]}`` where each
        entity carries ``entity_name`` / ``entity_type`` / ``description`` /
        ``properties`` / ``source_id`` (table name).
        """
        schema_definition, entity_types, relationship_types = self._load_schema()
        llm_func = LlmServiceAdapter(self._llm, self._user)

        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        def _extract_one_blocking(t):
            # Run extract_entities_sync (which does its own asyncio.run) in a
            # worker thread. The synchronous LLM call only blocks that thread,
            # not the main event loop -> real parallelism across tables.
            return _engine.extract_entities_sync(
                build_extraction_text([t]),
                schema_definition=schema_definition,
                entity_types=entity_types,
                relationship_types=relationship_types,
                language=self._language,
                max_gleaning=self._max_gleaning,
                llm_func=llm_func,
                chunk_key=t.table_name,
            )

        async def _extract_one(t):
            async with semaphore:
                return await asyncio.to_thread(_extract_one_blocking, t)

        results = await asyncio.gather(*(_extract_one(t) for t in tables))

        all_entities = []
        all_relationships = []
        for result in results:
            all_entities.extend(result["entities"])
            all_relationships.extend(result["relationships"])

        return {"entities": all_entities, "relationships": all_relationships}

    def validate(self, result: dict, tables) -> dict:
        """Validate field references and drop metrics whose field is unmatched.

        Returns a filtered ``result`` — entities with an unknown source table
        or an unmatched 来源字段 / 维度字段来源 are dropped, along with any
        relationship referencing them.
        """
        return _engine.validate_metric_fields(result, build_table_field_result(tables))
