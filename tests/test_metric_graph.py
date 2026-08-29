"""
Tests for the metric graph feature: composite metrics, LLM-extraction draft,
dependency-ordered import, admin pages, and route registration.

These tests do NOT require Neo4j, PostgreSQL, or an LLM — they exercise the
pure-Python logic (models, draft, import) and the route/page wiring.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easyq2sql.capabilities.composite_metric.models import CompositeMetric
from easyq2sql.metric_graph.draft import (
    DraftEntity,
    DraftRelation,
    MetricGraphDraft,
    import_selected,
)


# ---------------------------------------------------------------------------
# Helpers: fake stores + context
# ---------------------------------------------------------------------------


class FakeAtomicMetricStore:
    def __init__(self):
        self.created = []

    async def create_atomic_metric(self, atomic_metric, context):
        self.created.append(atomic_metric)
        return atomic_metric

    async def list_atomic_metrics(self, context):
        return list(self.created)


class FakeDerivedMetricStore:
    def __init__(self):
        self.created = []

    async def create_derived_metric(self, derived_metric, context):
        self.created.append(derived_metric)
        return derived_metric

    async def list_derived_metrics(self, context):
        return list(self.created)


class FakeCompositeMetricStore:
    def __init__(self):
        self.created = []

    async def create_composite_metric(self, composite_metric, context):
        self.created.append(composite_metric)
        return composite_metric

    async def list_composite_metrics(self, context):
        return list(self.created)


def _context():
    from easyq2sql.core.tool import ToolContext
    from easyq2sql.core.user.models import User
    from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

    return ToolContext(
        user=User(id="test", group_memberships=["admin"]),
        conversation_id="test",
        request_id="test",
        agent_memory=DemoAgentMemory(max_items=10),
    )


def _sample_draft() -> MetricGraphDraft:
    """2 atomic -> 2 derived -> 1 composite, fully linked."""
    entities = [
        DraftEntity(
            entity_name="订单数",
            entity_type="原子指标",
            description="订单总数",
            source_table="ods_order",
            properties={
                "指标名称": "订单数",
                "业务描述": "订单总数",
                "计算函数": "COUNT",
                "来源字段": "ods_order.order_id",
            },
        ),
        DraftEntity(
            entity_name="销售额",
            entity_type="原子指标",
            description="销售总额",
            source_table="ods_order",
            properties={
                "指标名称": "销售额",
                "业务描述": "销售总额",
                "计算函数": "SUM",
                "来源字段": "ods_order.amount",
            },
        ),
        DraftEntity(
            entity_name="订单数_按日",
            entity_type="派生指标",
            description="按日订单数",
            source_table="dim_date",
            properties={
                "指标名称": "订单数_按日",
                "业务描述": "按日订单数",
                "维度字段来源": "dim_date.ds",
            },
        ),
        DraftEntity(
            entity_name="销售额_按日",
            entity_type="派生指标",
            description="按日销售额",
            source_table="dim_date",
            properties={
                "指标名称": "销售额_按日",
                "业务描述": "按日销售额",
                "维度字段来源": "dim_date.ds",
            },
        ),
        DraftEntity(
            entity_name="客单价",
            entity_type="复合指标",
            description="销售额 / 订单数",
            properties={
                "指标名称": "客单价",
                "业务描述": "销售额 / 订单数",
                "组合计算": "比值",
            },
        ),
    ]
    relationships = [
        DraftRelation(src_id="订单数_按日", tgt_id="订单数", keywords="派生自原子指标"),
        DraftRelation(src_id="销售额_按日", tgt_id="销售额", keywords="派生自原子指标"),
        DraftRelation(src_id="客单价", tgt_id="销售额_按日", keywords="派生指标来源"),
        DraftRelation(src_id="客单价", tgt_id="订单数_按日", keywords="派生指标来源"),
    ]
    return MetricGraphDraft(entities, relationships)


# ---------------------------------------------------------------------------
# CompositeMetric model
# ---------------------------------------------------------------------------


class TestCompositeMetricModel:
    def test_auto_generates_id(self):
        comp = CompositeMetric(
            name="客单价", comb_func="比值", operand_a="d1", operand_b="d2"
        )
        assert comp.id.startswith("composite_")

    def test_serialization_roundtrip(self):
        comp = CompositeMetric(
            name="客单价",
            business_definition="销售额 / 订单数",
            comb_func="比值",
            operand_a="d1",
            operand_b="d2",
        )
        data = comp.model_dump(mode="json")
        restored = CompositeMetric(**data)
        assert restored.name == "客单价"
        assert restored.operand_a == "d1"
        assert restored.comb_func == "比值"


# ---------------------------------------------------------------------------
# MetricGraphDraft
# ---------------------------------------------------------------------------


class TestMetricGraphDraft:
    def test_from_extraction_normalizes(self):
        raw = {
            "entities": [
                {
                    "entity_name": "订单数",
                    "entity_type": "原子指标",
                    "description": "订单总数",
                    "properties": '{"计算函数": "COUNT"}',
                },
                {
                    "entity_name": "订单数_按日",
                    "entity_type": "派生指标",
                    "description": "按日订单数",
                    "properties": {},
                },
            ],
            "relationships": [
                {
                    "src_id": "订单数_按日",
                    "tgt_id": "订单数",
                    "keywords": "派生自原子指标",
                    "description": "",
                }
            ],
        }
        draft = MetricGraphDraft.from_extraction(raw)
        assert len(draft.entities) == 2
        # JSON-string properties are coerced back to dict.
        assert draft.entities[0].properties == {"计算函数": "COUNT"}

    def test_from_extraction_prefixes_table_field(self):
        # The LLM only extracts the field name; the normalization stage prefixes it with source_id (table name).
        raw = {
            "entities": [
                {
                    "entity_name": "订单数",
                    "entity_type": "原子指标",
                    "source_id": "ods_order",
                    "properties": {"指标名称": "订单数", "来源字段": "order_id"},
                },
                {
                    "entity_name": "订单数_按日",
                    "entity_type": "派生指标",
                    "source_id": "dim_date",
                    "properties": {"指标名称": "订单数_按日", "维度字段来源": "ds"},
                },
            ],
            "relationships": [],
        }
        draft = MetricGraphDraft.from_extraction(raw)
        atomic, derived = draft.entities
        assert atomic.source_table == "ods_order"
        assert atomic.properties["来源字段"] == "ods_order.order_id"
        assert derived.source_table == "dim_date"
        assert derived.properties["维度字段来源"] == "dim_date.ds"

    def test_grouped_by_type(self):
        draft = _sample_draft()
        grouped = draft.grouped()
        assert set(grouped.keys()) == {"原子指标", "派生指标", "复合指标"}
        assert len(grouped["原子指标"]) == 2
        assert len(grouped["派生指标"]) == 2
        assert len(grouped["复合指标"]) == 1

    def test_without_tables_prunes_dangling_relationships(self):
        draft = _sample_draft()
        filtered = draft.without_tables({"ods_order"})
        names = {e.entity_name for e in filtered.entities}
        # Atomic metrics 订单数/销售额 belong to ods_order and are removed;
        # dim_date derived metrics and the composite metric are kept.
        assert "订单数" not in names
        assert "销售额" not in names
        assert {"订单数_按日", "销售额_按日", "客单价"} <= names
        rel_pairs = {(r.src_id, r.tgt_id) for r in filtered.relationships}
        assert ("订单数_按日", "订单数") not in rel_pairs
        assert ("销售额_按日", "销售额") not in rel_pairs
        assert ("客单价", "销售额_按日") in rel_pairs

    def test_removed_names_for_tables(self):
        draft = _sample_draft()
        assert draft.removed_names_for_tables({"ods_order"}) == {"订单数", "销售额"}
        assert draft.removed_names_for_tables({"dim_date"}) == {"订单数_按日", "销售额_按日"}
        assert draft.removed_names_for_tables({"nonexistent"}) == set()

    def test_without_tables_keeps_same_name_in_other_table(self):
        entities = [
            DraftEntity(entity_name="订单数", entity_type="原子指标", source_table="t1"),
            DraftEntity(entity_name="订单数", entity_type="原子指标", source_table="t2"),
            DraftEntity(entity_name="销售额", entity_type="原子指标", source_table="t1"),
        ]
        relationships = [
            DraftRelation(src_id="订单数", tgt_id="销售额", keywords="x"),
        ]
        draft = MetricGraphDraft(entities, relationships)
        filtered = draft.without_tables({"t1"})
        # "订单数" still exists in t2 under the same name, so only the two t1 entities are removed.
        assert [e.source_table for e in filtered.entities] == ["t2"]
        # The relationship endpoints (订单数 remains, 销售额 removed) are no longer complete → pruned.
        assert filtered.relationships == []

    def test_removed_names_for_tables_handles_collision(self):
        entities = [
            DraftEntity(entity_name="订单数", entity_type="原子指标", source_table="t1"),
            DraftEntity(entity_name="订单数", entity_type="原子指标", source_table="t2"),
        ]
        draft = MetricGraphDraft(entities)
        # "订单数" still exists in t2 under the same name, so it is not considered truly removed.
        assert draft.removed_names_for_tables({"t1"}) == set()

    def test_extend_appends(self):
        a = MetricGraphDraft([DraftEntity(entity_name="A", entity_type="原子指标")])
        b = MetricGraphDraft([DraftEntity(entity_name="B", entity_type="原子指标")])
        a.extend(b)
        assert [e.entity_name for e in a.entities] == ["A", "B"]


# ---------------------------------------------------------------------------
# import_selected
# ---------------------------------------------------------------------------


class TestImportSelected:
    @pytest.mark.asyncio
    async def test_dependency_ordered_import(self):
        metric_store = FakeAtomicMetricStore()
        dim_store = FakeDerivedMetricStore()
        comp_store = FakeCompositeMetricStore()

        report = await import_selected(
            _sample_draft(),
            ["订单数", "销售额", "订单数_按日", "销售额_按日", "客单价"],
            atomic_metric_store=metric_store,
            derived_metric_store=dim_store,
            composite_metric_store=comp_store,
            context=_context(),
        )

        assert report["imported"]["原子指标"] == ["订单数", "销售额"]
        assert report["imported"]["派生指标"] == ["订单数_按日", "销售额_按日"]
        assert report["imported"]["复合指标"] == ["客单价"]
        assert report["skipped"] == []

        ids = report["ids"]
        # Derived dimensions reference their atomic parent metric id.
        dim_by_name = {d.name: d for d in dim_store.created}
        assert dim_by_name["订单数_按日"].atomic_metric_id == ids["订单数"]
        assert dim_by_name["销售额_按日"].atomic_metric_id == ids["销售额"]

        # Composite references the two derived dimension ids (ratio order).
        comp = comp_store.created[0]
        assert comp.operand_a == ids["销售额_按日"]
        assert comp.operand_b == ids["订单数_按日"]
        assert comp.comb_func == "比值"

    @pytest.mark.asyncio
    async def test_composite_skipped_without_operands(self):
        metric_store = FakeAtomicMetricStore()
        dim_store = FakeDerivedMetricStore()
        comp_store = FakeCompositeMetricStore()

        report = await import_selected(
            _sample_draft(),
            ["客单价"],
            atomic_metric_store=metric_store,
            derived_metric_store=dim_store,
            composite_metric_store=comp_store,
            context=_context(),
        )

        assert report["imported"] == {}
        assert len(report["skipped"]) == 1
        assert report["skipped"][0]["entity_name"] == "客单价"

    @pytest.mark.asyncio
    async def test_derived_skipped_without_atomic(self):
        metric_store = FakeAtomicMetricStore()
        dim_store = FakeDerivedMetricStore()
        comp_store = FakeCompositeMetricStore()

        report = await import_selected(
            _sample_draft(),
            ["订单数_按日"],
            atomic_metric_store=metric_store,
            derived_metric_store=dim_store,
            composite_metric_store=comp_store,
            context=_context(),
        )

        assert report["imported"] == {}
        assert len(report["skipped"]) == 1
        assert report["skipped"][0]["entity_name"] == "订单数_按日"


# ---------------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------------


class TestAdminPages:
    def test_composite_page_renders(self):
        from easyq2sql.servers.base.admin_templates import get_composite_admin_html

        html = get_composite_admin_html("/api/easyq2sql/v1")
        assert "CompositeMetric Management" in html
        for marker in ("popOperandOpts", "combTag", "saveComp", "deleteComp"):
            assert marker in html

    def test_metric_graph_page_renders(self):
        from easyq2sql.servers.base.admin_templates import get_metric_graph_admin_html

        html = get_metric_graph_admin_html("/api/easyq2sql/v1")
        assert "Metric Graph" in html
        for marker in ("renderDraft", "importSelected", "syncGraph", "toggleGroup"):
            assert marker in html

    def test_admin_routes_register(self):
        from easyq2sql.servers.fastapi.admin_routes import register_admin_routes

        app = FastAPI()
        register_admin_routes(app, {"api_base_url": "/api/easyq2sql/v1"})
        paths = {r.path for r in app.routes}
        assert "/admin/composite-metrics" in paths
        assert "/admin/metric-graph" in paths

    def test_composite_routes_crud(self):
        from easyq2sql.servers.fastapi.composite_routes import (
            register_composite_routes,
        )
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

        class _Agent:
            agent_memory = DemoAgentMemory(max_items=10)

        app = FastAPI()
        register_composite_routes(app, _Agent(), FakeCompositeMetricStore(), config={})
        client = TestClient(app)

        # Empty list.
        assert client.get("/api/easyq2sql/v1/composite-metrics").json() == []

        # Create.
        resp = client.post(
            "/api/easyq2sql/v1/composite-metrics",
            json={
                "name": "客单价",
                "business_definition": "销售额 / 订单数",
                "comb_func": "比值",
                "operand_a": "d1",
                "operand_b": "d2",
                "description": None,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "客单价"
        assert resp.json()["id"].startswith("composite_")

        # Invalid comb_func rejected.
        resp = client.post(
            "/api/easyq2sql/v1/composite-metrics",
            json={
                "name": "x",
                "comb_func": "相乘",
                "operand_a": "d1",
                "operand_b": "d2",
            },
        )
        assert resp.status_code == 400

    def test_metric_graph_routes_register_and_guard(self, tmp_path):
        from easyq2sql.servers.fastapi.metric_graph_routes import (
            register_metric_graph_routes,
        )
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

        class _Agent:
            agent_memory = DemoAgentMemory(max_items=10)

        app = FastAPI()
        # schema_store / graph_store are None -> extract/sync return 503.
        # Point the draft at an isolated, empty location so the "no draft yet"
        # guard is deterministic regardless of any real draft on disk.
        register_metric_graph_routes(
            app,
            _Agent(),
            config={"metric_graph_draft_path": str(tmp_path / "draft.json")},
        )
        client = TestClient(app)

        paths = {r.path for r in app.routes}
        assert "/api/easyq2sql/v1/metric-graph/extract" in paths
        assert "/api/easyq2sql/v1/metric-graph/draft" in paths
        assert "/api/easyq2sql/v1/metric-graph/draft/import" in paths
        assert "/api/easyq2sql/v1/metric-graph/sync" in paths

        # No draft yet -> 404.
        assert client.get("/api/easyq2sql/v1/metric-graph/draft").status_code == 404
        # No schema_store -> 503.
        assert client.post("/api/easyq2sql/v1/metric-graph/extract").status_code == 503


# ---------------------------------------------------------------------------
# Draft disk persistence (JSON file backing the in-memory draft area)
# ---------------------------------------------------------------------------


class TestDraftDiskPersistence:
    def _agent(self):
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

        class _Agent:
            agent_memory = DemoAgentMemory(max_items=10)

        return _Agent()

    def _register(self, app, path):
        from easyq2sql.servers.fastapi.metric_graph_routes import (
            register_metric_graph_routes,
        )

        register_metric_graph_routes(
            app, self._agent(), config={"metric_graph_draft_path": str(path)}
        )
        return TestClient(app)

    def test_roundtrip_to_dict_from_dict(self):
        draft = _sample_draft()
        assert MetricGraphDraft.from_dict(draft.to_dict()).to_dict() == draft.to_dict()

    def test_draft_survives_restart(self, tmp_path):
        path = tmp_path / "metric_graph_draft.json"
        path.write_text(
            json.dumps(_sample_draft().to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

        app = FastAPI()
        client = self._register(app, path)
        r = client.get("/api/easyq2sql/v1/metric-graph/draft")
        assert r.status_code == 200
        assert r.json()["counts"]["原子指标"] == 2

    def test_clear_removes_file(self, tmp_path):
        path = tmp_path / "metric_graph_draft.json"
        path.write_text(
            json.dumps(_sample_draft().to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

        app = FastAPI()
        client = self._register(app, path)
        assert client.delete("/api/easyq2sql/v1/metric-graph/draft").status_code == 200
        assert not path.exists()
        assert client.get("/api/easyq2sql/v1/metric-graph/draft").status_code == 404

    def test_scoped_clear_removes_only_table(self, tmp_path):
        path = tmp_path / "metric_graph_draft.json"
        path.write_text(
            json.dumps(_sample_draft().to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

        app = FastAPI()
        client = self._register(app, path)

        r = client.post(
            "/api/easyq2sql/v1/metric-graph/draft/clear",
            json={"tables": ["ods_order"]},
        )
        assert r.status_code == 200
        assert r.json()["cleared"] == 2

        remaining = client.get("/api/easyq2sql/v1/metric-graph/draft").json()
        names = {e["entity_name"] for e in remaining["entities"]}
        assert "订单数" not in names
        assert "销售额" not in names
        assert {"订单数_按日", "销售额_按日", "客单价"} <= names

    def test_scoped_clear_last_table_removes_file(self, tmp_path):
        path = tmp_path / "metric_graph_draft.json"
        # Keep only entities from one table.
        draft = MetricGraphDraft(
            entities=[
                DraftEntity(entity_name="订单数", entity_type="原子指标", source_table="t1"),
            ],
            relationships=[],
        )
        path.write_text(json.dumps(draft.to_dict(), ensure_ascii=False), encoding="utf-8")

        app = FastAPI()
        client = self._register(app, path)
        assert (
            client.post("/api/easyq2sql/v1/metric-graph/draft/clear", json={"tables": ["t1"]}).status_code
            == 200
        )
        assert not path.exists()
        assert client.get("/api/easyq2sql/v1/metric-graph/draft").status_code == 404

    def test_corrupt_draft_file_tolerated(self, tmp_path):
        path = tmp_path / "metric_graph_draft.json"
        path.write_text("{not valid json", encoding="utf-8")

        app = FastAPI()
        client = self._register(app, path)
        assert client.get("/api/easyq2sql/v1/metric-graph/draft").status_code == 404

    def test_import_filters_draft_but_keeps_file(self, tmp_path):
        path = tmp_path / "metric_graph_draft.json"
        imported_path = tmp_path / "metric_graph_draft_imported.json"
        path.write_text(
            json.dumps(_sample_draft().to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

        app = FastAPI()
        from easyq2sql.servers.fastapi.metric_graph_routes import (
            register_metric_graph_routes,
        )

        register_metric_graph_routes(
            app,
            self._agent(),
            config={
                "metric_graph_draft_path": str(path),
                "metric_graph_imported_path": str(imported_path),
                "atomic_metric_store": FakeAtomicMetricStore(),
                "derived_metric_store": FakeDerivedMetricStore(),
                "composite_metric_store": FakeCompositeMetricStore(),
            },
        )
        client = TestClient(app)

        resp = client.post(
            "/api/easyq2sql/v1/metric-graph/draft/import",
            json={"selected": ["订单数", "销售额"]},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"]["原子指标"] == ["订单数", "销售额"]

        # The draft JSON file stays intact — the full extraction result; import does not prune it.
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert {e["entity_name"] for e in on_disk["entities"]} == {
            "订单数", "销售额", "订单数_按日", "销售额_按日", "客单价",
        }

        # Imported metrics are hidden from the get_draft view; derived/composite remain visible, and dangling relationships are hidden too.
        after = client.get("/api/easyq2sql/v1/metric-graph/draft").json()
        remaining = {e["entity_name"] for e in after["entities"]}
        assert "订单数" not in remaining
        assert "销售额" not in remaining
        assert {"订单数_按日", "销售额_按日", "客单价"} <= remaining

        rel_pairs = {(r["src_id"], r["tgt_id"]) for r in after["relationships"]}
        assert ("订单数_按日", "订单数") not in rel_pairs
        assert ("销售额_按日", "销售额") not in rel_pairs
        assert ("客单价", "销售额_按日") in rel_pairs

        # The imported-name list is persisted separately.
        assert set(json.loads(imported_path.read_text(encoding="utf-8"))) == {
            "订单数", "销售额"
        }


# ---------------------------------------------------------------------------
# MetricGraphStore capability
# ---------------------------------------------------------------------------


class TestMetricGraphStoreCapability:
    """The MetricGraphStore ABC and the subgraph models it returns."""

    def test_neo4j_store_implements_the_capability(self):
        from easyq2sql.capabilities.metric_graph_store import MetricGraphStore
        from easyq2sql.integrations.neo4j import Neo4jMetricGraphStore

        assert issubclass(Neo4jMetricGraphStore, MetricGraphStore)
        # Instantiable => every abstract method is implemented.
        assert isinstance(Neo4jMetricGraphStore(), MetricGraphStore)

    def test_entity_type_vocabulary_has_one_source(self):
        """The Neo4j config re-exports the capability's constants rather than
        redefining them, so backends and consumers cannot drift apart."""
        from easyq2sql.capabilities.metric_graph_store import (
            ENTITY_TYPE_ATOMIC,
            ENTITY_TYPE_COMPOSITE,
            ENTITY_TYPE_DERIVED,
            REL_DERIVED_FROM,
            REL_USES,
        )
        from easyq2sql.integrations.neo4j import config

        assert config.TYPE_ATOMIC is ENTITY_TYPE_ATOMIC
        assert config.TYPE_DERIVED is ENTITY_TYPE_DERIVED
        assert config.TYPE_COMPOSITE is ENTITY_TYPE_COMPOSITE
        assert config.REL_DERIVED_FROM is REL_DERIVED_FROM
        assert config.REL_USES is REL_USES

    def test_connect_and_close_default_to_no_ops(self):
        """Backends with no connection to manage inherit working lifecycle
        hooks, so callers may always call connect()/close()."""
        import asyncio

        from easyq2sql.capabilities.metric_graph_store import (
            MetricGraphStore,
            MetricGraphSubgraph,
        )

        class InProcessStore(MetricGraphStore):
            async def ensure_indexes(self):
                return None

            async def sync_from_stores(self, **kwargs):
                return {"nodes": 0, "edges": 0}

            async def search(self, query, *, top_k=10):
                return MetricGraphSubgraph()

        store = InProcessStore()
        asyncio.run(store.connect())
        asyncio.run(store.close())
        assert asyncio.run(store.search("x")).nodes == []


class TestGraphSubgraphFormatting:
    """``_format_graph_subgraph_for_llm`` renders the retrieved subgraph as the
    relationship-chain text the LLM sees. Locks the exact output."""

    @staticmethod
    def _subgraph():
        from easyq2sql.capabilities.metric_graph_store import (
            MetricGraphEdge,
            MetricGraphNode,
            MetricGraphSubgraph,
        )

        return MetricGraphSubgraph(
            nodes=[
                MetricGraphNode(
                    entity_id="c1", entity_name="毛利率", entity_type="复合指标",
                    description="毛利与收入之比",
                    properties={"组合计算": "Ratio", "操作数A": "d1", "操作数B": "d2"},
                    score=0.9123,
                ),
                MetricGraphNode(
                    entity_id="d1", entity_name="华东销售额", entity_type="派生指标",
                    description="按区域切片",
                    properties={
                        "原子指标": "a1", "维度字段": "region", "数据表来源": "sales",
                        "取值范围": "华东/华南", "外键关系": "sales.rid=region.id",
                    },
                ),
                MetricGraphNode(
                    entity_id="d3", entity_name="孤立派生", entity_type="派生指标",
                    description="没有复合父节点",
                    properties={"原子指标": "a3", "维度字段": "dept", "数据表来源": "hr"},
                    score=0.5,
                ),
                MetricGraphNode(
                    entity_id="a1", entity_name="销售额", entity_type="原子指标",
                    description="总销售金额",
                    properties={
                        "计算逻辑": "SUM(amount)", "数据表来源": "sales",
                        "分析字段": "amount",
                    },
                ),
                MetricGraphNode(
                    entity_id="a3", entity_name="人数", entity_type="原子指标",
                    description="员工人数",
                    properties={
                        "计算逻辑": "COUNT(1)", "数据表来源": "hr", "分析字段": "emp_id",
                    },
                ),
                MetricGraphNode(
                    entity_id="a4", entity_name="孤立原子", entity_type="原子指标",
                    description="无人引用",
                    properties={
                        "计算逻辑": "AVG(x)", "数据表来源": "t", "分析字段": "x",
                        "取值范围": "0-100", "外键关系": "t.a=u.b",
                    },
                    score=0.77,
                ),
            ],
            edges=[
                MetricGraphEdge(src_id="c1", tgt_id="d1", rel_type="USES"),
                MetricGraphEdge(src_id="d1", tgt_id="a1", rel_type="DERIVED_FROM"),
                MetricGraphEdge(src_id="d3", tgt_id="a3", rel_type="DERIVED_FROM"),
            ],
        )

    def test_renders_chains_orphans_and_scores(self):
        from easyq2sql.tools.metric_tools import _format_graph_subgraph_for_llm

        sub = self._subgraph()
        text = _format_graph_subgraph_for_llm(sub.nodes, sub.edges)

        assert text == (
            "# 复合指标: 毛利率 [similarity: 0.9123]\n"
            "业务描述: 毛利与收入之比\n"
            "组合计算: Ratio\n"
            "  ├ 派生指标: 华东销售额（维度: region，取值范围: 华东/华南，"
            "外键: sales.rid=region.id）\n"
            "  │   └ 来自 原子指标: 销售额（字段: amount，计算: SUM(amount)）\n"
            "\n"
            "# 派生指标: 孤立派生 [similarity: 0.5000]\n"
            "业务描述: 没有复合父节点\n"
            "维度字段: dept\n"
            "数据来源: hr\n"
            "  └ 来自 原子指标: 人数（字段: emp_id，计算: COUNT(1)）\n"
            "\n"
            "# 原子指标: 孤立原子 [similarity: 0.7700]\n"
            "业务描述: 无人引用\n"
            "计算逻辑: AVG(x)\n"
            "数据来源: t\n"
            "分析字段: x\n"
            "取值范围: 0-100\n"
            "外键关系: t.a=u.b"
        )

    def test_atomic_reached_via_a_chain_is_not_repeated_as_an_orphan(self):
        from easyq2sql.tools.metric_tools import _format_graph_subgraph_for_llm

        sub = self._subgraph()
        text = _format_graph_subgraph_for_llm(sub.nodes, sub.edges)
        assert text.count("销售额") == 2  # 华东销售额 + the chained 原子指标
        assert "# 原子指标: 销售额" not in text

    def test_empty_subgraph_renders_empty(self):
        from easyq2sql.tools.metric_tools import _format_graph_subgraph_for_llm

        assert _format_graph_subgraph_for_llm([], []) == ""
