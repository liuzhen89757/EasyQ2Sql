"""
Metric graph storage models.

The metric graph is a *derived index* over the three relational metric stores.
Its nodes are metrics and its edges are the relationships between them::

    (原子指标) <-[DERIVED_FROM]- (派生指标) <-[USES]- (复合指标)

A search returns a :class:`MetricGraphSubgraph` — the matched seed nodes plus
the neighbours reached by expanding those relationships — so a caller gets a
metric *and* its surrounding context without a second round trip.
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field

#: ``entity_type`` values carried by graph nodes. Chinese, matching
#: ``MetricSchema.json`` and the vocabulary used across the metric stores.
ENTITY_TYPE_ATOMIC: str = "原子指标"
ENTITY_TYPE_DERIVED: str = "派生指标"
ENTITY_TYPE_COMPOSITE: str = "复合指标"

#: Relationship types between metric nodes.
REL_DERIVED_FROM: str = "DERIVED_FROM"  # 派生指标 -> 原子指标
REL_USES: str = "USES"  # 复合指标 -> 派生指标


class MetricGraphNode(BaseModel):
    """A single metric node in a retrieved subgraph."""

    entity_id: str = Field(
        description="Stable id, equal to the row id in the originating store"
    )
    entity_name: str = Field(description="Metric name")
    entity_type: str = Field(
        description="One of ENTITY_TYPE_ATOMIC / ENTITY_TYPE_DERIVED / "
        "ENTITY_TYPE_COMPOSITE"
    )
    description: str = Field(default="", description="Business definition")
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific attributes keyed by Chinese label "
        "(计算逻辑 / 维度字段 / 组合计算 …). Open-ended by design: each entity "
        "type carries a different key set.",
    )
    score: float = Field(
        default=0.0,
        description="Retrieval score. 0.0 for nodes reached by graph expansion "
        "rather than matched directly by the query.",
    )


class MetricGraphEdge(BaseModel):
    """A directed relationship between two metric nodes."""

    src_id: str = Field(description="entity_id of the source node")
    tgt_id: str = Field(description="entity_id of the target node")
    rel_type: str = Field(description="REL_DERIVED_FROM or REL_USES")


class MetricGraphSubgraph(BaseModel):
    """A metric graph search result: nodes plus the edges among them.

    Only edges whose *both* endpoints are in ``nodes`` are included, so the
    subgraph is self-contained and safe to traverse without further lookups.
    """

    nodes: List[MetricGraphNode] = Field(default_factory=list)
    edges: List[MetricGraphEdge] = Field(default_factory=list)
