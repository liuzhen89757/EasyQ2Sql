"""
Draft-area model and import logic for the LLM-extracted metric graph.

The extraction produces raw entities (原子指标 / 派生指标 / 复合指标) plus the
relationships between them. This module normalises that output into a *draft*
that the admin page can display, and provides the import step that maps a
user-selected subset back into the relational config stores:

    AtomicMetric    -> atomic_metric     (atomic_metric_store)
    DerivedMetric   -> derived_metric    (derived_metric_store, linked via DERIVED_FROM)
    CompositeMetric -> composite_metric  (composite_metric_store, linked via USES)

Import is dependency-ordered: atomic first, then derived (needs its atomic
parent), then composite (needs two derived operands). Items whose dependencies
are neither selected nor already configured are skipped and reported.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

import easyq2sql.metric_graph.engine as _engine
from easyq2sql.capabilities.atomic_metric import AtomicMetricStore
from easyq2sql.capabilities.composite_metric import CompositeMetricStore
from easyq2sql.capabilities.derived_metric import DerivedMetricStore

#: Entity type labels (from MetricSchema.json).
TYPE_ATOMIC = "原子指标"
TYPE_DERIVED = "派生指标"
TYPE_COMPOSITE = "复合指标"

#: Relationship keywords used to resolve derived -> atomic and composite -> derived.
REL_DERIVED_FROM_ATOMIC = "派生自原子指标"
REL_COMPOSITE_OPERAND = "派生指标来源"


class DraftEntity(BaseModel):
    """A single extracted metric entity, normalised for the draft area."""

    entity_name: str
    entity_type: str
    description: str = ""
    source_table: str = ""
    properties: Dict[str, Any] = Field(default_factory=dict)


class DraftRelation(BaseModel):
    """A relationship between two extracted entities (by entity name)."""

    src_id: str
    tgt_id: str
    keywords: str = ""
    description: str = ""


def _prefix_field_props(props: dict, source_table: str) -> dict:
    """Prefix bare field-name properties with their table, producing 'table.column'.

    The table name is supplied by the code (``chunk_key`` -> ``source_id``); the
    LLM only extracts the field name. During normalisation this joins the
    来源字段 / 维度字段来源 values into full 'table.column' references. Already
    prefixed values pass through ``prefix_table_field`` idempotently.
    """
    if not source_table:
        return props
    for key in ("来源字段", "source_field", "source_fields",
                "维度字段来源", "dimension_field", "metric_fields"):
        if key in props and props[key] not in (None, ""):
            props[key] = _engine.prefix_table_field(source_table, props[key])
    return props


class MetricGraphDraft:
    """In-memory holder for one extraction result."""

    def __init__(
        self,
        entities: Optional[List[DraftEntity]] = None,
        relationships: Optional[List[DraftRelation]] = None,
    ):
        self.entities: List[DraftEntity] = entities or []
        self.relationships: List[DraftRelation] = relationships or []

    @classmethod
    def from_extraction(cls, result: dict) -> "MetricGraphDraft":
        entities = []
        for e in result.get("entities", []):
            # The raw LLM output records the source table in ``source_id``;
            # ``to_dict()`` serialises that key as ``source_table``. Accept both
            # so ``from_dict`` round-trips losslessly.
            source_table = (e.get("source_id") or e.get("source_table") or "").strip()
            props = _engine._coerce_properties(e.get("properties"))
            props = _prefix_field_props(props, source_table)
            entities.append(
                DraftEntity(
                    entity_name=e.get("entity_name", ""),
                    entity_type=e.get("entity_type", ""),
                    description=e.get("description", ""),
                    source_table=source_table,
                    properties=props,
                )
            )
        relationships = [
            DraftRelation(
                src_id=r.get("src_id", ""),
                tgt_id=r.get("tgt_id", ""),
                keywords=r.get("keywords", ""),
                description=r.get("description", ""),
            )
            for r in result.get("relationships", [])
        ]
        return cls(entities, relationships)

    def grouped(self) -> Dict[str, List[DraftEntity]]:
        out: Dict[str, List[DraftEntity]] = defaultdict(list)
        for e in self.entities:
            out[e.entity_type].append(e)
        return dict(out)

    def without_entities(self, names: Set[str]) -> "MetricGraphDraft":
        """Return a filtered *copy* excluding ``names`` and any relationship
        touching them.

        Used to hide already-imported entities from the draft view *without*
        mutating the draft — ``metric_graph_draft.json`` stays a complete
        extraction result, so downstream parsing never sees a pruned file.
        """
        if not names:
            return MetricGraphDraft(list(self.entities), list(self.relationships))
        return MetricGraphDraft(
            [e for e in self.entities if e.entity_name not in names],
            [
                r for r in self.relationships
                if r.src_id not in names and r.tgt_id not in names
            ],
        )

    def removed_names_for_tables(self, table_names: Set[str]) -> Set[str]:
        """Return the entity names that would disappear after ``without_tables``.

        These are the entities whose ``source_table`` is in ``table_names`` and
        whose name does *not* also appear in some other (kept) table. Used to
        prune the ``_imported`` list when a table's draft is re-extracted or
        cleared — stale imported names would otherwise keep hiding freshly
        extracted same-name metrics.
        """
        if not table_names:
            return set()
        removed = {e.entity_name for e in self.entities if e.source_table in table_names}
        kept = {e.entity_name for e in self.entities if e.source_table not in table_names}
        return removed - kept

    def without_tables(self, table_names: Set[str]) -> "MetricGraphDraft":
        """Return a filtered *copy* excluding entities from ``table_names``.

        Entities are removed by ``source_table``; relationships are kept only if
        *both* endpoints still exist among the kept entities (matched by name, so
        a same-name entity in another table correctly keeps its relationships).
        """
        if not table_names:
            return MetricGraphDraft(list(self.entities), list(self.relationships))
        kept_entities = [e for e in self.entities if e.source_table not in table_names]
        kept_names = {e.entity_name for e in kept_entities}
        return MetricGraphDraft(
            kept_entities,
            [
                r for r in self.relationships
                if r.src_id in kept_names and r.tgt_id in kept_names
            ],
        )

    def extend(self, other: "MetricGraphDraft") -> None:
        """Append ``other``'s entities and relationships in place (merge draft)."""
        self.entities.extend(other.entities)
        self.relationships.extend(other.relationships)

    def to_dict(self) -> dict:
        return {
            "entities": [e.model_dump() for e in self.entities],
            "relationships": [r.model_dump() for r in self.relationships],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetricGraphDraft":
        """Rebuild a draft from a serialized dict (inverse of ``to_dict``).

        Reuses ``from_extraction`` — its ``_coerce_properties`` is idempotent,
        so ``from_dict(draft.to_dict())`` round-trips losslessly.
        """
        return cls.from_extraction(data)


def _prop(props: dict, *keys: str, default: str = "") -> str:
    """Return the first non-empty property value across candidate keys."""
    val = _engine._first_key(props, *keys)
    return str(val).strip() if val not in (None, "") else default


def _atomic_metric_kwargs(entity: DraftEntity):
    """Map an atomic metric draft to AtomicMetric constructor kwargs."""
    props = entity.properties
    name = _prop(props, "指标名称", "metric_name", default=entity.entity_name)
    field = _engine.prefix_table_field(
        entity.source_table, _prop(props, "来源字段", "source_field", "source_fields")
    )
    return {
        "name": name,
        "business_definition": _prop(props, "业务描述", "description", default=entity.description),
        "calculation_logic": _prop(props, "计算函数", "agg_func"),
        "data_source": entity.source_table,
        "analysis_field": field,
        "value_range": _prop(props, "取值范围", "value_range"),
        "fk_relation": _prop(props, "外键关系", "fk_relation"),
        "description": entity.description,
    }


def _derived_metric_kwargs(entity: DraftEntity, atomic_metric_id: str):
    """Map a derived metric draft to DerivedMetric constructor kwargs."""
    props = entity.properties
    name = _prop(props, "指标名称", "metric_name", default=entity.entity_name)
    field = _engine.prefix_table_field(
        entity.source_table, _prop(props, "维度字段来源", "dimension_field", "metric_fields")
    )
    return {
        "atomic_metric_id": atomic_metric_id,
        "name": name,
        "business_definition": _prop(props, "业务描述", "description", default=entity.description),
        "data_source": entity.source_table,
        "field_ref": field,
        "value_range": _prop(props, "取值范围", "value_range"),
        "fk_relation": _prop(props, "外键关系", "fk_relation"),
        "description": entity.description,
    }


def _composite_metric_kwargs(entity: DraftEntity, operand_a: str, operand_b: str):
    """Map a composite metric draft to CompositeMetric constructor kwargs."""
    props = entity.properties
    name = _prop(props, "指标名称", "metric_name", default=entity.entity_name)
    return {
        "name": name,
        "business_definition": _prop(props, "业务描述", "description", default=entity.description),
        "comb_func": _prop(props, "组合计算", "comb_func", default="比值"),
        "operand_a": operand_a,
        "operand_b": operand_b,
        "description": entity.description,
    }


def _resolve_links(draft: MetricGraphDraft):
    """Resolve derived->atomic and composite->derived references.

    Uses entity types (more robust than exact relationship keywords), falling
    back to the relationship keywords when types are ambiguous.
    """
    type_by_name = {e.entity_name: e.entity_type for e in draft.entities}
    derived_atomic: Dict[str, str] = {}
    composite_operands: Dict[str, List[str]] = defaultdict(list)

    for r in draft.relationships:
        s_type = type_by_name.get(r.src_id)
        t_type = type_by_name.get(r.tgt_id)
        if s_type == TYPE_DERIVED and t_type == TYPE_ATOMIC:
            derived_atomic.setdefault(r.src_id, r.tgt_id)
        elif s_type == TYPE_COMPOSITE and t_type == TYPE_DERIVED:
            composite_operands.setdefault(r.src_id, []).append(r.tgt_id)
        elif r.keywords == REL_DERIVED_FROM_ATOMIC:
            derived_atomic.setdefault(r.src_id, r.tgt_id)
        elif r.keywords == REL_COMPOSITE_OPERAND:
            composite_operands.setdefault(r.src_id, []).append(r.tgt_id)

    return derived_atomic, dict(composite_operands)


async def import_selected(
    draft: MetricGraphDraft,
    selected: List[str],
    *,
    atomic_metric_store: Optional[AtomicMetricStore],
    derived_metric_store: Optional[DerivedMetricStore],
    composite_metric_store: Optional[CompositeMetricStore],
    context,
) -> dict:
    """Import a user-selected subset of the draft into the config stores.

    Args:
        draft: The extraction draft.
        selected: Entity names the user checked for import.
        atomic_metric_store / derived_metric_store / composite_metric_store: target stores.
        context: ToolContext for store operations.

    Returns:
        A report dict::

            {"imported": {原子指标: [...], ...},
             "skipped": [{"entity_name": ..., "reason": ...}],
             "ids": {"<entity_name>": "<store_id>"}}
    """
    from easyq2sql.capabilities.atomic_metric.models import AtomicMetric
    from easyq2sql.capabilities.composite_metric.models import CompositeMetric
    from easyq2sql.capabilities.derived_metric.models import DerivedMetric

    selected_set: Set[str] = set(selected)
    derived_atomic, composite_operands = _resolve_links(draft)

    imported: Dict[str, List[str]] = defaultdict(list)
    skipped: List[dict] = []
    ids: Dict[str, str] = {}

    # Pre-existing records, keyed by name, used as fallback for references to
    # metrics/derived metrics that were configured earlier (not in this draft).
    existing_atomic_metric_ids: Dict[str, str] = {}
    existing_derived_metric_ids: Dict[str, str] = {}
    try:
        if atomic_metric_store is not None:
            existing_atomic_metric_ids = {
                m.name: m.id
                for m in (await atomic_metric_store.list_atomic_metrics(context) or [])
            }
        if derived_metric_store is not None:
            existing_derived_metric_ids = {
                d.name: d.id
                for d in (await derived_metric_store.list_derived_metrics(context) or [])
            }
    except Exception:
        pass

    def _skip(name: str, reason: str) -> None:
        skipped.append({"entity_name": name, "reason": reason})

    # 1) Atomic metrics.
    for entity in draft.entities:
        if entity.entity_type != TYPE_ATOMIC or entity.entity_name not in selected_set:
            continue
        if atomic_metric_store is None:
            _skip(entity.entity_name, "atomic_metric_store not configured")
            continue
        kwargs = _atomic_metric_kwargs(entity)
        if not kwargs["data_source"] or not kwargs["analysis_field"]:
            _skip(entity.entity_name, "missing 来源字段 or source table")
            continue
        atomic_metric = AtomicMetric(**kwargs)
        created = await atomic_metric_store.create_atomic_metric(atomic_metric, context)
        ids[entity.entity_name] = created.id
        imported[TYPE_ATOMIC].append(entity.entity_name)

    # 2) Derived metrics — need their atomic parent.
    for entity in draft.entities:
        if entity.entity_type != TYPE_DERIVED or entity.entity_name not in selected_set:
            continue
        if derived_metric_store is None:
            _skip(entity.entity_name, "derived_metric_store not configured")
            continue
        atomic_name = derived_atomic.get(entity.entity_name)
        atomic_metric_id = ids.get(atomic_name) if atomic_name else None
        if atomic_metric_id is None and atomic_name:
            atomic_metric_id = existing_atomic_metric_ids.get(atomic_name)
        if atomic_metric_id is None:
            _skip(entity.entity_name, "cannot resolve its atomic metric (not selected and not configured)")
            continue
        kwargs = _derived_metric_kwargs(entity, atomic_metric_id)
        if not kwargs["data_source"] or not kwargs["field_ref"]:
            _skip(entity.entity_name, "missing 维度字段来源 or source table")
            continue
        derived_metric = DerivedMetric(**kwargs)
        created = await derived_metric_store.create_derived_metric(derived_metric, context)
        ids[entity.entity_name] = created.id
        imported[TYPE_DERIVED].append(entity.entity_name)

    # 3) Composite metrics — need two derived operands.
    for entity in draft.entities:
        if entity.entity_type != TYPE_COMPOSITE or entity.entity_name not in selected_set:
            continue
        if composite_metric_store is None:
            _skip(entity.entity_name, "composite_metric_store not configured")
            continue
        operand_names = composite_operands.get(entity.entity_name, [])
        resolved = []
        for op_name in operand_names:
            op_id = ids.get(op_name)
            if op_id is None:
                op_id = existing_derived_metric_ids.get(op_name)
            if op_id:
                resolved.append(op_id)
        if len(resolved) < 2:
            _skip(entity.entity_name, "cannot resolve two derived-metric operands (need selected or configured)")
            continue
        kwargs = _composite_metric_kwargs(entity, resolved[0], resolved[1])
        composite_metric = CompositeMetric(**kwargs)
        created = await composite_metric_store.create_composite_metric(
            composite_metric, context
        )
        ids[entity.entity_name] = created.id
        imported[TYPE_COMPOSITE].append(entity.entity_name)

    return {
        "imported": dict(imported),
        "skipped": skipped,
        "ids": ids,
    }
