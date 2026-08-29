"""
Schema and metric context enhancer for LLM system prompts.

Injects relevant table schemas and business metric definitions into the
system prompt based on the user's natural language question, enabling
the LLM to generate more accurate SQL with full data model awareness.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from easyq2sql.core.enhancer.base import LlmContextEnhancer

if TYPE_CHECKING:
    from easyq2sql.capabilities.atomic_metric import AtomicMetricStore
    from easyq2sql.capabilities.schema_store import SchemaStore
    from easyq2sql.core.user.models import User

logger = logging.getLogger(__name__)


class SchemaMetricContextEnhancer(LlmContextEnhancer):
    """Enhances the system prompt with relevant schema and metric context.

    On each conversation turn, this enhancer:
    1. Searches the SchemaStore for tables relevant to the user's question
    2. Searches the AtomicMetricStore for atomic metrics relevant to the user's question
    3. Formats the results and appends them to the system prompt

    This gives the LLM direct visibility into the data model without
    requiring it to make additional tool calls for schema discovery.

    The enhancer follows a fail-open design: if schema or metric search
    fails for any reason, the original prompt is returned unchanged.

    Args:
        schema_store: SchemaStore implementation for table metadata search.
        atomic_metric_store: AtomicMetricStore implementation for metric search.
        max_schema_tables: Maximum number of matching tables to inject (default 5).
        max_metrics: Maximum number of matching metrics to inject (default 5).

    Example:
        >>> enhancer = SchemaMetricContextEnhancer(schema_store, atomic_metric_store)
        >>> agent = Agent(..., llm_context_enhancer=enhancer)
    """

    def __init__(
        self,
        schema_store: "SchemaStore",
        atomic_metric_store: "AtomicMetricStore",
        max_schema_tables: int = 5,
        max_metrics: int = 5,
    ):
        self.schema_store = schema_store
        self.atomic_metric_store = atomic_metric_store
        self.max_schema_tables = max_schema_tables
        self.max_metrics = max_metrics

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: "User"
    ) -> str:
        """Enhance the system prompt with relevant schema and metric context.

        Args:
            system_prompt: The current system prompt text.
            user_message: The user's latest message (used as search query).
            user: The current user.

        Returns:
            Enhanced system prompt with schema/metric context appended,
            or the original prompt if enhancement fails.
        """
        if not user_message or not user_message.strip():
            return system_prompt

        try:
            from easyq2sql.core.tool import ToolContext
            from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

            context = ToolContext(
                user=user,
                conversation_id="temp",
                request_id=str(uuid.uuid4()),
                agent_memory=DemoAgentMemory(max_items=10),
            )

            sections: list[str] = []

            # 1. Search and inject relevant table schemas
            try:
                schema_results = await self.schema_store.search_tables(
                    query=user_message,
                    context=context,
                    limit=self.max_schema_tables,
                    similarity_threshold=0.3,
                )
                if schema_results:
                    lines = [
                        "\n\n## Available Database Schema",
                        "",
                        "The following database tables are relevant to the user's question:",
                        "",
                    ]
                    for r in schema_results:
                        t = r.table
                        lines.append(f"### Table: {t.table_name}")
                        if t.description:
                            lines.append(f"Description: {t.description}")
                        lines.append("Columns:")
                        for col in t.columns:
                            extras = []
                            if col.is_primary_key:
                                extras.append("PK")
                            if col.is_foreign_key:
                                extras.append(
                                    f"FK -> {col.fk_reference_table}.{col.fk_reference_column}"
                                )
                            extra_str = f" [{', '.join(extras)}]" if extras else ""
                            desc_str = f" -- {col.description}" if col.description else ""
                            lines.append(
                                f"  - {col.name} ({col.data_type})"
                                f"{'' if col.nullable else ' NOT NULL'}"
                                f"{extra_str}{desc_str}"
                            )
                        lines.append("")
                    sections.append("\n".join(lines))
            except Exception as e:
                logger.warning(f"Failed to search schemas for context injection: {e}")

            # 2. Search and inject relevant metrics
            try:
                metric_results = await self.atomic_metric_store.search_atomic_metrics(
                    query=user_message,
                    context=context,
                    limit=self.max_metrics,
                )
                if metric_results:
                    lines = [
                        "\n\n## Available Business Metrics",
                        "",
                        "The following pre-defined metrics may be relevant:",
                        "",
                    ]
                    for r in metric_results:
                        m = r.atomic_metric
                        lines.append(f"### Metric: {m.name} (id: {m.id})")
                        if m.business_definition:
                            lines.append(f"Business Definition: {m.business_definition}")
                        elif m.description:
                            lines.append(f"Description: {m.description}")
                        lines.append(f"Source: {m.data_source}")
                        lines.append(f"Analysis Field: {m.analysis_field}")
                        if m.calculation_logic:
                            lines.append(f"Calculation: {m.calculation_logic}")
                        lines.append("")

                        # Add usage hint
                        lines.append(
                            "**Usage**: Use `search_metrics` to get full details "
                            f"with dimensions for metric '{m.name}' (id={m.id}), "
                            "or `execute_metric` to run it."
                        )
                        lines.append("")
                    sections.append("\n".join(lines))
            except Exception as e:
                logger.warning(f"Failed to search metrics for context injection: {e}")

            if sections:
                return system_prompt + "\n".join(sections)

            return system_prompt

        except Exception as e:
            logger.warning(
                f"Failed to enhance system prompt with schema/metric context: {e}"
            )
            return system_prompt

    async def enhance_user_messages(self, messages, user):
        """No per-message enhancement needed; schema/metric context is
        injected once at the start of each conversation turn via
        enhance_system_prompt."""
        return messages
