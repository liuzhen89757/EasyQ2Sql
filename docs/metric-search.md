# 指标检索（Metric Retrieval）实现要点

> 本文梳理「指标检索」从 **Postgres(pgvector) 向量检索** 迁移到 **Neo4j 图检索** 之后的实现要点，覆盖：实体映射、图谱构建与同步、图检索算法、`SearchMetricsTool` 的 graph-first 检索流程、以及接入配置。
>
> 配套文档：`docs/middleware.md`（`search_metrics` 的调用节奏收敛）、`docs/hook.md`（观察者）。

---

## 1. 角色定位

指标检索对外只有一个入口 —— `SearchMetricsTool`（工具名 `search_metrics`）。LLM **只能看到这一个指标工具**，底层如何解析维度、复合指标、走图还是走向量，对 LLM 全部透明。

- 输入：`query`（自然语言关键词串，涵盖指标 / 维度 / 复合指标语义）。
- 输出：`ToolResult.result_for_llm` 为格式化的指标/维度/复合指标定义块，`metadata` 里带 `matched_atomic_metrics / matched_derived_metrics / matched_composite_metrics` 与 `retrieval` 来源标记。

检索目标是把用户自然语言中的「指标口径」解析成可执行的指标定义（名称、业务定义、计算逻辑、分析字段、维度、JOIN），交给后续 `execute_metric` / `run_sql` 生成 SQL。

---

## 2. 检索架构演进

| 维度 | 旧（Postgres 向量检索） | 新（Neo4j 图检索） |
|---|---|---|
| 存储 | pgvector `vector(768)` + tsvector 全文 | Neo4j 图（fulltext 索引） |
| 召回 | vector cosine + `ts_rank` → RRF 融合 → Cross-Encoder 重排序 | fulltext seed → 2-hop 扩展 |
| 关系建模 | 无（指标/维度扁平两张表） | `原子→派生→复合` 三层有向图 |
| 复合指标 | 不支持 | `CompositeMetric` 节点 + `USES` 边 |
| 数据一致性 | 单表即真相 | 图是**派生索引**，真相仍是关系型 store |

关键设计：**Neo4j 图不是权威存储，而是关系型配置 store 之上的派生索引**。检索时命中的节点直接携带 `entity_id / entity_name / description / properties`，`SearchMetricsTool` 用 `_format_graph_subgraph_for_llm` 把 `{nodes, edges}` 直接拼成关系链文本，**不回读**关系型 store。这样单点真相不变，图可以随时 `sync` 重建、丢弃、重建。

---

## 3. 实体映射与图谱结构

LLM 抽取（`MetricSchema.json`）产出三类实体，映射到三个 store：

| 图实体类型 | `entity_type` | Neo4j 标签 | 对应 store | 关系 |
|---|---|---|---|---|
| 原子指标 | `原子指标` | `AtomicMetric` | `atomic_metric` → `AtomicMetric` | — |
| 派生指标 | `派生指标` | `DerivedMetric` | `derived_metric` → `DerivedMetric` | `DERIVED_FROM` → 原子指标 |
| 复合指标 | `复合指标` | `CompositeMetric` | `composite_metric` → `CompositeMetric` | `USES` → 派生指标（两个） |

图谱形态：

```
(Atomic) <-[:DERIVED_FROM]- (Derived) <-[:USES]- (Composite)
```

标签与关系类型常量集中在 `integrations/neo4j/config.py`：

| 常量 | 值 |
|---|---|
| `METRIC_NODE_LABEL` | `MetricNode`（所有节点统一挂此标签，供 fulltext 索引） |
| `ATOMIC_LABEL / DERIVED_LABEL / COMPOSITE_LABEL` | `AtomicMetric / DerivedMetric / CompositeMetric` |
| `REL_DERIVED_FROM` | `DERIVED_FROM` |
| `REL_USES` | `USES` |
| `TYPE_ATOMIC / TYPE_DERIVED / TYPE_COMPOSITE` | `原子指标 / 派生指标 / 复合指标`（中文，存为属性） |
| `FULLTEXT_INDEX_NAME` | `metric_node_fulltext` |
| `FULLTEXT_ANALYZER` | `cjk` |

---

## 4. LLM 指标图谱抽取（extract）

抽取是图检索的上游：把关系型库的表结构（`TableSchema`）喂给 LLM，产出「原子指标 / 派生指标 / 复合指标」三类实体及其关系，经草稿区勾选导入后落库，再由第 5 节 `sync` 成 Neo4j 图。

### 4.1 触发与入口

`POST /api/easyq2sql/v1/metric-graph/extract` **在后台线程**跑抽取，接口立即返回 `{"status": "running"}`，不阻塞事件循环（chat 等接口照常响应）：

```
POST /metric-graph/extract
  ├─ schema_store.list_all_tables()            →  List[TableSchema]
  ├─ 若已在 running → 409（防重复启动）
  ├─ _extract_executor.submit(...)              ← 提交到单线程线程池，立即返回
  └─ return {"status": "running", "tables_total": N}

后台 worker 线程（_run_extract_blocking）
  ├─ asyncio.run(MetricGraphExtractor.extract(tables, max_concurrency))
  │     ├─ _load_schema()                      →  MetricSchema.json 词表
  │     └─ for t in tables（Semaphore 限并发）    ← 按表分批抽取
  │           ├─ build_extraction_text([t])     →  单表 "# Table: ..." 文本块
  │           └─ _engine.extract_entities(..., chunk_key=t.table_name)
  ├─ extractor.validate(result, tables)        →  丢弃未匹配指标（打印告警）
  ├─ MetricGraphDraft.from_extraction(result)  →  草稿（内存 + 磁盘 JSON）
  └─ _extract_state → done / error
```

客户端轮询 `GET /metric-graph/extract/status`（`idle | running | done | error`），`done` 后再 `GET /metric-graph/draft` 读草稿。

### 4.2 输入构建（build_extraction_text）

`build_extraction_text` 按表生成文本块。由于抽取是**逐表**进行的，`extract` 每次只传单张表 `build_extraction_text([t])`（表名经 `chunk_key` 传入，LLM 无需再抽取表名）。每列格式化为 `(name:type, Primary Key, desc)`，附带 `Examples` / `Value Range`：

```
# Table: pay_order
Description: 支付订单明细
[
(id:bigint, Primary Key, 订单号 Examples: [1,2,3], Value Range: 1~1000000),
(pay_amount:decimal(18,2), 支付金额(元) Examples: [199.00, ...]),
...
]
```

### 4.3 Schema 约束（MetricSchema.json → prompt 词表）

`load_schema_from_file()` 读 `MetricSchema.json`，`build_schema_prompt()` 生成注入 prompt 的实体/关系词表。三类实体 + 两类关系：

| 实体 | 必需属性 | 关系 |
|---|---|---|
| 原子指标 | 指标名称、来源字段 | — |
| 派生指标 | 指标名称、维度字段来源 | 派生自原子指标 → AtomicMetric |
| 复合指标 | 指标名称、组合计算 | 派生指标来源 → DerivedMetric |

> LLM 抽取时属性**只写字段名**（`来源字段`=`source_field`，`维度字段来源`=`dimension_field`），不带表名。表归属由逐表抽取时传入的 `chunk_key`（表名）落到实体的 `source_id` 上，随后在归一化阶段（4.7）由代码把表名拼回，最终实体属性为 `表.字段`（如 `pay_order.pay_amount`）。

词表构建优先级：`schema_definition`（带描述+属性）> `entity_types / relationship_types`（纯列表）> 开放域。prompt 还内嵌指标定义与抽取规则（不要把维度当原子指标、一个原子指标 + 一个维度只生成一个派生指标）。

### 4.4 LLM 调用（extract_entities，LightRAG 风格）

沿用 LightRAG `extract_entities` 的单 chunk 结构化抽取，LLM 后端换成框架的 `LlmService`（`LlmServiceAdapter` 把 `send_request` 适配成 `async f(user_prompt, *, system_prompt, history_messages) -> str`）。

- **分隔符协议**：字段用 `<|#|>`，整段结束用 `<|COMPLETE|>`。
- **temperature=0.0**（抽取需确定性）。
- **初抽**：system + user prompt 产出 `entity<|#|>name<|#|>type<|#|>desc<|#|>properties` 与 `relation<|#|>src<|#|>tgt<|#|>keywords<|#|>desc<|#|>properties`。
- **gleaning 补漏**：默认 `max_gleaning=1` 轮，用 `_ENTITY_CONTINUE_EXTRACTION_USER_PROMPT` 让 LLM 只补「漏掉/格式错误」的项；合并时同名实体 / 同边保留描述更长者。

### 4.5 结果解析（_parse_extraction_result）

把 LLM 文本按换行 + `<|COMPLETE|>` 切记录，并容忍 LLM 用 `<|#|>` 代替换行、`entity`/`relation` 前缀丢失等格式漂移（`fix_tuple_delimiter_corruption`）。逐条解析：

- `_parse_entity`（5 字段）→ `{entity_name, entity_type, description, properties}`；`properties` 是 JSON 字符串 → `_parse_json_properties` 转 dict。
- `_parse_relation`（6 字段）→ `{src_id, tgt_id, keywords, description, weight}`；`权重`/`weight` 解析成 float。

按 `entity_name` / `(src_id, tgt_id)` 去重聚合，展平成 `{"entities": [...], "relationships": [...]}`。

### 4.6 字段校验（validate_metric_fields）

校验并**丢弃**未匹配的指标（不再仅告警）。此时字段值仍是**裸字段名**（尚未拼表名）：

- 用 `source_id`（逐表抽取时写入的表名）在 `build_table_field_result` 构建的 `{表名: {字段名}}` 集合中定位字段集合；未知来源表 → 丢弃。
- 把「来源字段 / 维度字段来源」逐个对照该表的字段集合；任一未匹配 → 打印 `[validate]` 告警并丢弃该指标。
- 引用被丢弃指标的关系（`src_id`/`tgt_id` 命中丢弃名单）一并移除，避免残留悬空边。

`validate` 返回过滤后的 `result`，`extract` 路由以过滤结果生成草稿。**表名前缀在下一阶段（4.7 归一化）由代码补齐**，不在校验阶段处理。

### 4.7 归一化与草稿（from_extraction）

`MetricGraphDraft.from_extraction(result)` 把抽取结果归一化成 `DraftEntity` / `DraftRelation`：

- `properties` 经 `_coerce_properties` 统一成 dict；`source_id` → `DraftEntity.source_table`。
- `_prefix_field_props()` 用 `prefix_table_field()` 把「来源字段 / 维度字段来源」的裸字段名拼上表名前缀，得到最终 `表.字段`（已带前缀则幂等保留，`from_dict` round-trip 无损）。
- 落库时 `_atomic_to_metric` / `_derived_to_dimension` 再次幂等拼前缀，保证 `Metric.analysis_field` / `Dimension.field_ref` 均为 `表.字段`（与模型定义一致）。

草稿存内存 + 磁盘 JSON（`metric_graph_draft_path`，见第 9 节），勾选导入后由 `import_selected` 按「原子 → 派生 → 复合」依赖序落库。

---

## 5. 图构建与同步

`Neo4jMetricGraphStore`（`integrations/neo4j/metric_graph_store.py`）负责图的写入与检索。

### 5.1 节点/边 payload

- `_atomic_node(metric)`：`entity_id=metric.id`，`properties` JSON 存 `计算逻辑 / 数据表来源 / 分析字段`。
- `_derived_node(dim)`：`entity_id=dim.id`，`properties` 存 `原子指标(dim.atomic_metric_id) / 维度字段 / 数据表来源 / 取值范围`。
- `_composite_node(comp)`：`entity_id=comp.id`，`properties` 存 `组合计算 / 操作数A / 操作数B`。

所有 `properties` 用 `json.dumps(..., ensure_ascii=False)` 序列化，检索时由 `_coerce_properties` 解码回 dict。

### 5.2 `sync_from_stores()` 全量重建

```python
await graph_store.connect()
await graph_store.ensure_indexes()
stats = await graph_store.sync_from_stores(
    atomic_metric_store=..., derived_metric_store=..., composite_metric_store=..., context=...
)
# 返回 {"nodes": n, "edges": m}
```

内部 `_rebuild()` 流程（单事务 `execute_write`）：

1. `MATCH (n:{workspace}) DETACH DELETE n` 清空工作区；
2. 按 `AtomicMetric → DerivedMetric → CompositeMetric` 顺序 upsert 节点（`MERGE` on `entity_id`，`SET n += {...}`）；
3. upsert 边：派生→原子（`dim.atomic_metric_id`）、复合→派生（`operand_a / operand_b`）。

边从关系型 store 的**外键字段**推导，不依赖 LLM 抽取的关系文本——这保证同步结果是确定性的。

### 5.3 工作区隔离与 fulltext 索引

- **workspace 标签**（默认 `base`，可用 `NEO4J_WORKSPACE` 覆盖）：每个节点额外打 `:{workspace}` 标签，`MERGE`/`DETACH DELETE` 均按 workspace 限定，实现多租户/多图隔离。
- **fulltext 索引**：

```cypher
CREATE FULLTEXT INDEX metric_node_fulltext IF NOT EXISTS
FOR (n:`MetricNode`)
ON EACH [n.entity_name, n.description, n.properties]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'cjk' } }
```

`cjk` 分析器负责中文分词，是中文指标名/业务定义召回的关键。

---

## 6. 图检索算法

`Neo4jMetricGraphStore.search(query, top_k)` 三步走，返回 `{"nodes": [...], "edges": [...]}` 的子图：

### 6.1 步骤

1. **清洗**：`query.strip()` 去首尾空白，空查询直接返回空子图。
2. **种子召回**：`_fulltext_seed()` 调 `db.index.fulltext.queryNodes(...)`，按 `score DESC` 取 top_k，且 `WHERE node.workspace = $workspace`；英文词先按 token 空格拼接提升召回。
3. **种子兜底**：fulltext 无结果时 `_contains_seed()` 用 `entity_name CONTAINS $text OR description CONTAINS $text` 兜底。
4. **2-hop 扩展**：`_expand()` 沿 `[:DERIVED_FROM|:USES]*1..2`（无向）扩出邻居，与种子合并去重。
5. **回读**：`_load_nodes()` / `_load_edges()` 加载子图节点与边；节点 `score` 规则：**种子 = 1.0，邻居 = 0.0**。

### 6.2 为什么是「seed → 2-hop 扩展」而不是向量相似度

指标之间存在**组合依赖**：问「客单价」命中复合指标节点后，若不扩展就拿不到它的两个派生指标操作数，也就无法拼出最终 SQL。2-hop 扩展沿 `DERIVED_FROM / USES` 把「复合 → 派生 → 原子」整条链路带出来，保证返回的是一段**可执行的指标上下文**而非孤立的单个匹配。

---

## 7. `SearchMetricsTool` 检索流程

`tools/metric_tools.py::SearchMetricsTool.execute()` 的决策顺序：

```
query（自然语言关键词串，直接来自 `SearchMetricsArgs.query`）
  │
  ├─ [graph-first] metric_graph_store is not None?
  │     └─ _search_via_graph(query, limit, context)
  │           ├─ subgraph = graph_store.search(query, top_k=limit)
  │           ├─ nodes 按 score 降序
  │           └─ 直接用 _format_graph_subgraph_for_llm(nodes, edges) 拼成关系链文本
  │              （不回读 store），命中结果 → 返回（metadata["retrieval"] = "graph"）
  │
  └─ [fallback] 图未配置 / 无结果 / 异常：
        Step 1 直接原子指标检索（atomic_metric_store.search_atomic_metrics）
        Step 2 直接派生指标检索（derived_metric_store.search_derived_metrics）
        Step 3 组装，无结果返回空提示
```

要点：

- **graph-first**：只要 `metric_graph_store` 已注入且图检索有结果，就**完全取代**旧的 pgvector 直查流程（`metadata["retrieval"] == "graph"`）。
- **fail-open**：`_search_via_graph` 抛异常被外层捕获为 `([], [], [], [])`，自然落到 fallback 流程，不会因 Neo4j 不可用而让 `search_metrics` 整体失败。
- **直接拼图**：图节点携带 `entity_name / description / properties`，`_format_graph_subgraph_for_llm` 直接把 `{nodes, edges}` 拼成关系链文本，不回读关系型 store；种子节点的 `score` 由 `_score_tag` 标注为 `[similarity: x.xxxx]`。
- **limit 语义**：`_search_via_graph` 用 `len(result_parts) >= limit` 截断；图检索本身 `top_k=limit` 控种子数，扩展后的节点数可能略多于 limit，最终按排序截断。

### 7.1 三类节点的格式化输出

| 类型 | 格式化函数 | 关键字段 |
|---|---|---|
| 原子指标 | `_format_atomic_metric_with_derived_metrics` | 业务定义 / 计算逻辑 / 数据表 / 分析字段 / 关联派生指标 |
| 派生指标 | `_format_derived_metric_for_llm` | 业务定义 / 数据表 / 分析字段 / 取值范围 / JOIN |
| 复合指标 | `_format_composite_metric_for_llm` | 业务定义 / 组合计算 / 操作数A / 操作数B |

---

## 8. 查询输入

`SearchMetricsTool` 对外只暴露一个 `query` 参数（自然语言关键词串），原样喂给图检索与 fallback 检索。LLM 从用户问题中抽取指标 / 维度 / 复合指标语义写入 `query`（见 `SearchMetricsArgs` 的字段描述），检索端不再做结构化前缀拼装——`query` 直接作为 fulltext / 向量检索的输入。

---

## 9. 接入配置

### 9.1 server config 键

`servers/fastapi/app.py` 与 `metric_graph_routes.py` 读取以下 config 键：

| 键 | 作用 |
|---|---|
| `atomic_metric_store` / `derived_metric_store` | 原子/派生指标的权威 store |
| `composite_metric_store` | 复合指标 store（`integrations/postgres/composite_metric_store.py`） |
| `metric_graph_store` | `Neo4jMetricGraphStore` 实例，注入后启用图检索 |
| `llm_service` | 抽取用的 LLM（`config` 里或 `agent.llm_service`） |
| `metric_graph_max_gleaning` | LightRAG gleaning 轮数（默认 1） |
| `metric_graph_max_concurrency` | 逐表抽取的并发上限（`asyncio.Semaphore`，默认 4） |
| `metric_graph_draft_path` | 抽取草稿的磁盘 JSON 路径（默认 `metric_graph_draft.json`） |

`SearchMetricsTool` 构造时需额外传 `metric_graph_store` 与 `composite_metric_store`，才会启用 graph-first 分支（默认 `None`，向后兼容旧的 pgvector 流程）。

### 9.2 Neo4j 连接（环境变量）

| 变量 | 默认 |
|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | 空（需显式配置） |
| `NEO4J_WORKSPACE` | `base` |

`Neo4jMetricGraphStore.search()` 内做了 **auto-connect**：`_driver is None` 时自动 `await connect()`，因此检索请求无需预先手动 connect（`sync` 路由仍显式 connect + ensure_indexes）。

---

## 10. 限制与后续

- **图是派生索引，会滞后**：`sync` 是手动/按需触发的全量重建；关系型 store 变更后若未 `sync`，图检索会漏掉新配置。后续可在 metric/dimension/composite 写路径上挂 hook 做增量同步。
- **score 粒度粗**：节点 `score` 只有「种子 1.0 / 邻居 0.0」两档，未做 Cross-Encoder 重排序；如需更精细排序，可在 `_search_via_graph` 里对回读后的实体做二次重排。
- **2-hop 是硬编码**：`*1..2` 固定在 `_expand()`；更深的指标依赖链（如复合套复合）会被截断，后续可参数化 hop 数。
- **fallback 仍是旧链路**：graph-first 只替换了「检索来源」，pgvector 直搜仍保留作为兜底；两套检索并存意味着行为存在双路径，需保证格式化输出一致（fallback 统一 `_format_atomic_metric_with_derived_metrics` / `_format_derived_metric_for_llm` / `_format_composite_metric_for_llm`，graph 分支统一 `_format_graph_subgraph_for_llm`）。
- **fulltext 依赖 cjk 分析器**：对纯英文/数字指标名，cjk 切词可能不理想，`_fulltext_seed` 已做 token 空格拼接缓解，但复杂英文缩写仍可能召回不足。
- **按表分批抽取无法跨表组合复合指标**：逐表抽取时每个 `chunk` 只看到一张表，若某个复合指标的两个派生操作数分属不同表，LLM 无法在一次抽取中把它们连起来。后续可在所有表抽取完后，再跑一轮跨表「复合指标补抽」，或由人工在草稿区补关系。
