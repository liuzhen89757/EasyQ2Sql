"""
Neo4j-backed metric graph storage + graph retrieval.

The metric graph is a *derived index* over the relational config stores:

    atomic_metric_store      -> 原子指标 (AtomicMetric) nodes
    derived_metric_store     -> 派生指标 (DerivedMetric) nodes + DERIVED_FROM edges
    composite_metric_store   -> 复合指标 (CompositeMetric) nodes + USES edges

Graph shape::

    (Atomic) <-[:DERIVED_FROM]- (Derived) <-[:USES]- (Composite)

Retrieval is graph traversal: fulltext match to seed nodes, then expand
neighbours along DERIVED_FROM / USES edges (2 hops) and return the subgraph.

``neo4j`` is imported lazily so this module can be imported even when the
driver is not installed (as long as no graph operation is performed).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from easyq2sql.capabilities.metric_graph_store import (
    MetricGraphEdge,
    MetricGraphNode,
    MetricGraphStore,
    MetricGraphSubgraph,
)

from .config import (
    ATOMIC_LABEL,
    COMPOSITE_LABEL,
    DERIVED_LABEL,
    FULLTEXT_ANALYZER,
    FULLTEXT_INDEX_NAME,
    METRIC_NODE_LABEL,
    REL_DERIVED_FROM,
    REL_USES,
    TYPE_ATOMIC,
    TYPE_COMPOSITE,
    TYPE_DERIVED,
)

if TYPE_CHECKING:
    from easyq2sql.capabilities.atomic_metric import AtomicMetricStore
    from easyq2sql.capabilities.composite_metric import CompositeMetricStore
    from easyq2sql.capabilities.derived_metric import DerivedMetricStore
    from easyq2sql.core.tool import ToolContext


def _coerce_properties(props) -> dict:
    """Normalise extracted properties into a dict (may be dict or JSON string)."""
    if isinstance(props, dict):
        return props
    if isinstance(props, str) and props.strip():
        try:
            parsed = json.loads(props)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


#: Property keys that hold opaque store ids (relational links) rather than
#: searchable text. They are excluded from the node ``search_text`` — the
#: relationships they encode are already captured by graph edges.
_ID_LINK_PROP_KEYS = frozenset({"原子指标", "操作数A", "操作数B"})


def _build_node_search_text(entity_name: str, description: str, props: dict) -> str:
    """Build the fulltext-index source for a metric node.

    ``entity_name | description | <all non-empty property values>`` excluding
    the opaque id-link properties (see ``_ID_LINK_PROP_KEYS``).
    """
    parts = [entity_name or ""]
    if description:
        parts.append(description)
    for key, value in (props or {}).items():
        if key in _ID_LINK_PROP_KEYS:
            continue
        if value in (None, "", []):
            continue
        parts.append(str(value))
    return " | ".join(p for p in parts if p)


class Neo4jMetricGraphStore(MetricGraphStore):
    """Store + retrieve the metric graph in Neo4j."""

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        workspace: Optional[str] = None,
    ):
        self.uri = uri
        self.username = username
        self.password = password
        self.workspace = (workspace or "base").strip() or "base"
        self._driver = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _require_driver(self):
        if self._driver is None:
            raise RuntimeError("Neo4j is not connected; call connect() first")
        return self._driver

    async def connect(self) -> None:
        from neo4j import AsyncGraphDatabase

        if not self.uri or not self.username or not self.password:
            raise ValueError(
                "Missing Neo4j connection config; set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD"
            )
        if self._driver is not None:
            return
        self._driver = AsyncGraphDatabase.driver(
            self.uri, auth=(self.username, self.password)
        )
        # Verify connectivity.
        async with self._driver.session() as session:
            await session.run("RETURN 1")

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def __aenter__(self) -> "Neo4jMetricGraphStore":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def ensure_indexes(self) -> None:
        """Create the fulltext index used for seed-node matching.

        Indexes the node ``search_text`` property (``entity_name | description
        | <property values>``) rather than the individual ``entity_name`` /
        ``description`` / ``properties`` fields. The index is dropped first so
        that a previously-created index over the old field set is replaced.
        """
        self._require_driver()
        async with self._driver.session() as session:
            await session.run(f"DROP INDEX {FULLTEXT_INDEX_NAME} IF EXISTS")
            await session.run(
                f"""
                CREATE FULLTEXT INDEX {FULLTEXT_INDEX_NAME} IF NOT EXISTS
                FOR (n:`{METRIC_NODE_LABEL}`)
                ON EACH [n.search_text]
                OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: '{FULLTEXT_ANALYZER}' }} }}
                """
            )

    # ------------------------------------------------------------------
    # Node / edge payload builders
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_node(metric) -> dict:
        props = {
            "计算逻辑": metric.calculation_logic or "",
            "数据表来源": metric.data_source or "",
            "分析字段": metric.analysis_field or "",
        }
        if getattr(metric, "value_range", None):
            props["取值范围"] = metric.value_range
        if getattr(metric, "fk_relation", None):
            props["外键关系"] = metric.fk_relation
        return {
            "entity_id": metric.id,
            "entity_name": metric.name,
            "entity_type": TYPE_ATOMIC,
            "description": metric.business_definition or "",
            "properties": json.dumps(props, ensure_ascii=False),
            "search_text": _build_node_search_text(
                metric.name, metric.business_definition or "", props
            ),
        }

    @staticmethod
    def _derived_node(dim) -> dict:
        props = {
            "原子指标": dim.atomic_metric_id,
            "维度字段": dim.field_ref or "",
            "数据表来源": dim.data_source or "",
            "取值范围": dim.value_range or "",
        }
        if getattr(dim, "fk_relation", None):
            props["外键关系"] = dim.fk_relation
        return {
            "entity_id": dim.id,
            "entity_name": dim.name,
            "entity_type": TYPE_DERIVED,
            "description": dim.business_definition or "",
            "properties": json.dumps(props, ensure_ascii=False),
            "search_text": _build_node_search_text(
                dim.name, dim.business_definition or "", props
            ),
        }

    @staticmethod
    def _composite_node(comp) -> dict:
        props = {
            "组合计算": comp.comb_func or "",
            "操作数A": comp.operand_a or "",
            "操作数B": comp.operand_b or "",
        }
        return {
            "entity_id": comp.id,
            "entity_name": comp.name,
            "entity_type": TYPE_COMPOSITE,
            "description": comp.business_definition or "",
            "properties": json.dumps(props, ensure_ascii=False),
            "search_text": _build_node_search_text(
                comp.name, comp.business_definition or "", props
            ),
        }

    # ------------------------------------------------------------------
    # Sync from relational stores
    # ------------------------------------------------------------------

    async def sync_from_stores(
        self,
        *,
        atomic_metric_store: Optional["AtomicMetricStore"] = None,
        derived_metric_store: Optional["DerivedMetricStore"] = None,
        composite_metric_store: Optional["CompositeMetricStore"] = None,
        context: Optional["ToolContext"] = None,
    ) -> Dict[str, int]:
        """Rebuild the graph from the relational stores (full rebuild).

        Returns ``{"nodes": n, "edges": m}`` counts.
        """
        self._require_driver()

        context = context or _default_context()

        metrics: List[Any] = []
        if atomic_metric_store is not None:
            metrics = await atomic_metric_store.list_atomic_metrics(context) or []
        dims: List[Any] = []
        if derived_metric_store is not None:
            dims = await derived_metric_store.list_derived_metrics(context) or []
        composites: List[Any] = []
        if composite_metric_store is not None:
            composites = await composite_metric_store.list_composite_metrics(context) or []

        node_ids: List[str] = []
        edges: List[tuple] = []  # (src_id, tgt_id, rel_type)

        for m in metrics:
            node_ids.append(m.id)
        for d in dims:
            node_ids.append(d.id)
            if d.atomic_metric_id:
                edges.append((d.id, d.atomic_metric_id, REL_DERIVED_FROM))
        for c in composites:
            node_ids.append(c.id)
            for operand in (c.operand_a, c.operand_b):
                if operand:
                    edges.append((c.id, operand, REL_USES))

        await self._rebuild(metrics, dims, composites)
        return {"nodes": len(node_ids), "edges": len(edges)}

    async def _rebuild(self, metrics, dims, composites) -> None:
        """Clear the workspace and upsert all nodes + edges."""
        driver = self._require_driver()

        async def _do(tx):
            # 1) Clear workspace.
            await tx.run(f"MATCH (n:`{self.workspace}`) DETACH DELETE n")
            # 2) Upsert nodes.
            for m in metrics:
                result = await tx.run(
                    self._upsert_node_cypher(ATOMIC_LABEL),
                    workspace=self.workspace,
                    **self._atomic_node(m),
                )
                await result.consume()
            for d in dims:
                result = await tx.run(
                    self._upsert_node_cypher(DERIVED_LABEL),
                    workspace=self.workspace,
                    **self._derived_node(d),
                )
                await result.consume()
            for c in composites:
                result = await tx.run(
                    self._upsert_node_cypher(COMPOSITE_LABEL),
                    workspace=self.workspace,
                    **self._composite_node(c),
                )
                await result.consume()
            # 3) Upsert edges.
            for d in dims:
                if d.atomic_metric_id:
                    await tx.run(
                        self._upsert_edge_cypher(REL_DERIVED_FROM),
                        src_id=d.id,
                        tgt_id=d.atomic_metric_id,
                    )
            for c in composites:
                for operand in (c.operand_a, c.operand_b):
                    if operand:
                        await tx.run(
                            self._upsert_edge_cypher(REL_USES),
                            src_id=c.id,
                            tgt_id=operand,
                        )

        async with driver.session() as session:
            await session.execute_write(_do)

    def _upsert_node_cypher(self, type_label: str) -> str:
        return f"""
        MERGE (n:`{self.workspace}`:`{METRIC_NODE_LABEL}`:`{type_label}`
               {{entity_id: $entity_id}})
        SET n += {{
            entity_name: $entity_name,
            entity_type: $entity_type,
            description: $description,
            properties: $properties,
            search_text: $search_text,
            workspace: $workspace
        }}
        """

    def _upsert_edge_cypher(self, rel_type: str) -> str:
        return f"""
        MATCH (src:`{self.workspace}` {{entity_id: $src_id}})
        MATCH (tgt:`{self.workspace}` {{entity_id: $tgt_id}})
        MERGE (src)-[r:`{rel_type}`]->(tgt)
        """

    # ------------------------------------------------------------------
    # Graph retrieval
    # ------------------------------------------------------------------

    async def search(self, query: str, *, top_k: int = 10) -> MetricGraphSubgraph:
        """Search the metric graph and return a local subgraph.

        Steps:
          1. fulltext match ``entity_name`` / ``description`` / ``properties``
             to obtain seed nodes;
          2. expand 2 hops along DERIVED_FROM / USES edges;
          3. return the de-duplicated node + edge set.

        Node properties are decoded back to dicts and each seed node carries a
        ``score`` of 1.0 (expanded neighbours score 0.0).
        """
        if self._driver is None:
            await self.connect()
        self._require_driver()
        cleaned = query.strip()
        if not cleaned:
            return MetricGraphSubgraph()

        seeds = await self._fulltext_seed(cleaned, top_k)
        if not seeds:
            seeds = await self._contains_seed(cleaned, top_k)
        if not seeds:
            return MetricGraphSubgraph()

        node_ids = await self._expand(seeds)
        nodes = await self._load_nodes(node_ids, seeds)
        edges = await self._load_edges(node_ids)
        return MetricGraphSubgraph(nodes=nodes, edges=edges)

    async def _fulltext_seed(self, text: str, top_k: int) -> List[str]:
        driver = self._require_driver()
        query = f"""
        CALL db.index.fulltext.queryNodes('{FULLTEXT_INDEX_NAME}', $text)
        YIELD node, score
        WHERE node.workspace = $workspace
        RETURN node.entity_id AS entity_id
        ORDER BY score DESC
        LIMIT $top_k
        """
        # cjk analyzer splits on CJK; pad English terms for better recall.
        tokens = re.findall(r"[\w一-鿿]+", text)
        search_text = " ".join(tokens) if tokens else text
        async with driver.session() as session:
            result = await session.run(
                query, text=search_text, workspace=self.workspace, top_k=top_k
            )
            records = [r async for r in result]
            return [r["entity_id"] for r in records]

    async def _contains_seed(self, text: str, top_k: int) -> List[str]:
        """Fallback when fulltext yields nothing: CONTAINS on name/description."""
        driver = self._require_driver()
        query = f"""
        MATCH (n:`{self.workspace}`:`{METRIC_NODE_LABEL}`)
        WHERE n.entity_name CONTAINS $text OR n.description CONTAINS $text
        RETURN n.entity_id AS entity_id
        LIMIT $top_k
        """
        async with driver.session() as session:
            result = await session.run(query, text=text, top_k=top_k)
            records = [r async for r in result]
            return [r["entity_id"] for r in records]

    async def _expand(self, seed_ids: List[str]) -> List[str]:
        """2-hop expansion from seeds, returning all node ids in the subgraph."""
        driver = self._require_driver()
        query = f"""
        MATCH (seed:`{self.workspace}`) WHERE seed.entity_id IN $seed_ids
        CALL {{
            WITH seed
            MATCH (seed)-[:`{REL_DERIVED_FROM}`|`{REL_USES}`*1..2]-(m:`{self.workspace}`)
            RETURN m.entity_id AS entity_id
        }}
        RETURN DISTINCT entity_id
        """
        async with driver.session() as session:
            result = await session.run(query, seed_ids=seed_ids)
            records = [r async for r in result]
            ids = [r["entity_id"] for r in records]
            # Ensure seeds themselves are included.
            merged = list(dict.fromkeys([*seed_ids, *ids]))
            return merged

    async def _load_nodes(
        self, node_ids: List[str], scored_seeds: List[str]
    ) -> List[MetricGraphNode]:
        driver = self._require_driver()
        query = f"""
        MATCH (n:`{self.workspace}`:`{METRIC_NODE_LABEL}`)
        WHERE n.entity_id IN $ids
        RETURN n.entity_id AS entity_id, n.entity_name AS entity_name,
               n.entity_type AS entity_type, n.description AS description,
               n.properties AS properties
        """
        async with driver.session() as session:
            result = await session.run(query, ids=node_ids)
            records = [r async for r in result]
        nodes = []
        for r in records:
            props = _coerce_properties(r["properties"])
            nodes.append(
                MetricGraphNode(
                    entity_id=r["entity_id"],
                    entity_name=r["entity_name"],
                    entity_type=r["entity_type"],
                    description=r["description"] or "",
                    properties=props,
                    score=1.0 if r["entity_id"] in scored_seeds else 0.0,
                )
            )
        return nodes

    async def _load_edges(self, node_ids: List[str]) -> List[MetricGraphEdge]:
        driver = self._require_driver()
        query = f"""
        MATCH (src:`{self.workspace}`:`{METRIC_NODE_LABEL}`)
              -[r:`{REL_DERIVED_FROM}`|`{REL_USES}`]->
              (tgt:`{self.workspace}`:`{METRIC_NODE_LABEL}`)
        WHERE src.entity_id IN $ids AND tgt.entity_id IN $ids
        RETURN src.entity_id AS src_id, tgt.entity_id AS tgt_id, type(r) AS rel_type
        """
        async with driver.session() as session:
            result = await session.run(query, ids=node_ids)
            records = [r async for r in result]
        return [
            MetricGraphEdge(
                src_id=r["src_id"], tgt_id=r["tgt_id"], rel_type=r["rel_type"]
            )
            for r in records
        ]


def _default_context():
    """Build a minimal ToolContext for store list operations."""
    from easyq2sql.core.tool import ToolContext
    from easyq2sql.core.user.models import User
    from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

    return ToolContext(
        user=User(id="graph_sync", group_memberships=["admin"]),
        conversation_id="graph_sync",
        request_id="graph_sync",
        agent_memory=DemoAgentMemory(max_items=100),
    )
