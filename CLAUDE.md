# Vanna 2.0 项目架构

> NL → SQL → Answer 的 AI Agent 框架。用户自然语言提问，系统生成 SQL、执行查询、流式返回结果。

- **版本**: 2.0.2（相对 0.x 完整重写）
- **核心依赖**: Pydantic / FastAPI / Plotly / pgvector
- **前端**: 原生 Web Component `<vanna-chat>`，框架无关
- **默认 Embedding**: `BAAI/bge-base-zh-v1.5` (768 维，中文优化)
- **默认 Cross-Encoder**: `BAAI/bge-reranker-base` (重排序)

---

## 一、整体架构分层

```
┌──────────────────────────────────────────────────────────────┐
│                      前端 Web Component                       │
│              <vanna-chat>  (SSE / WebSocket)                 │
└──────────────────────────┬───────────────────────────────────┘
                           │ POST /api/vanna/v2/chat_sse
┌──────────────────────────▼───────────────────────────────────┐
│                    服务层 (servers/)                          │
│   FastAPI / Flask → ChatHandler → SSE 流式输出                │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                   核心 Agent (core/agent/)                     │
│   7 大扩展点: LifecycleHook / LlmMiddleware / ErrorRecovery   │
│              ContextEnricher / LlmContextEnhancer             │
│              ConversationFilter / ObservabilityProvider       │
│   工作流: UserResolver → WorkflowHandler → LLM → Tools       │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                     能力层 (capabilities/)                     │
│   SqlRunner | AgentMemory | FileSystem | SchemaStore | MetricStore │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                   集成层 (integrations/)                       │
│   LLM: OpenAI/Anthropic/Ollama/Gemini/Azure...              │
│   DB: PostgreSQL/MySQL/Snowflake/BigQuery/DuckDB/SQLite...  │
│   向量: Postgres(pgvector) / ChromaDB / FAISS / ...         │
│   图表: Plotly                                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

### 2.1 根目录 `src/vanna/`

| 路径 | 用途 |
|------|------|
| `core/` | **核心框架** — Agent 引擎、工具系统、LLM 抽象、用户系统 |
| `servers/` | **Web 服务层** — FastAPI/Flask 路由、SSE、Admin UI |
| `integrations/` | **第三方集成** — LLM、数据库驱动、向量存储、图表、Schema 提取器 |
| `tools/` | **内置工具** — run_sql、visualize_data、记忆工具、schema/metric 工具 |
| `capabilities/` | **能力抽象** — SqlRunner、AgentMemory、FileSystem、SchemaStore、MetricStore |
| `components/` | **UI 组件** — Rich（DataFrame/Chart/Card）和 Simple（Text/Image）双轨 |
| `legacy/` | Vanna 0.x 兼容层 |

### 2.2 `core/` — 核心框架

```
core/
├── agent/              # Agent 主类 — send_message() / _send_message()
│   ├── agent.py        #   框架核心编排器
│   └── config.py       #   AgentConfig, UiFeatures, AuditConfig
├── tool/               # 工具抽象
│   ├── base.py         #   Tool<T> 基类
│   └── models.py       #   ToolCall, ToolContext, ToolResult, ToolSchema
├── llm/                # LLM 抽象
│   ├── base.py         #   LlmService 接口
│   └── models.py       #   LlmRequest, LlmResponse, LlmStreamChunk
├── user/               # 用户系统
│   ├── models.py       #   User (id, group_memberships)
│   ├── resolver.py     #   UserResolver — 从 Cookie/JWT 提取身份
│   └── request_context.py
├── registry.py         # ToolRegistry — 工具注册、权限验证、执行调度
├── storage/            # ConversationStore — 对话持久化
├── system_prompt/      # SystemPromptBuilder — 含记忆工作流指令
├── lifecycle/          # LifecycleHook — 消息/工具生命周期钩子
├── middleware/         # LlmMiddleware — LLM 请求/响应中间件链
├── workflow/           # WorkflowHandler — LLM 前拦截命令
├── recovery/           # ErrorRecoveryStrategy — 错误重试/降级
├── enricher/           # ToolContextEnricher — 上下文增强
├── enhancer/           # LlmContextEnhancer — 从 AgentMemory 注入记忆
├── filter/             # ConversationFilter — 上下文窗口管理
├── observability/      # ObservabilityProvider — 分布式追踪
├── audit/              # AuditLogger — 审计日志（含参数脱敏）
├── search/             # 混合搜索 — RRF 融合 + Cross-Encoder 重排序
│   ├── __init__.py     #   hybrid_search_chromadb(), tokenize(), keyword_score()
│   └── cross_encoder.py#   CrossEncoderReranker (模块级缓存 + GPU 支持)
└── evaluation/         # 评估框架
```

### 2.3 `servers/` — Web 服务层

| 文件 | 用途 |
|------|------|
| `base/chat_handler.py` | **ChatHandler** — 框架无关的聊天处理核心 |
| `base/templates.py` | 主页 HTML 模板 |
| `base/admin_templates.py` | **Admin UI 模板** — Schema/Metric 管理页面 (纯 HTML+Tailwind+JS) |
| `fastapi/app.py` | FastAPI 应用工厂（含所有路由注册） |
| `fastapi/routes.py` | Chat 路由 — SSE / WebSocket / Polling |
| `fastapi/admin_routes.py` | Admin 页面路由 — `/admin/schema`, `/admin/metrics` |
| `fastapi/schema_routes.py` | **Schema REST API** — CRUD + sync (`/api/vanna/v2/schema/*`) |
| `fastapi/metric_routes.py` | **Metric REST API** — CRUD + functions/suggest (`/api/vanna/v2/metrics/*`) |

> **⚠️ `admin_templates.py` 脚本顺序约束**: `_admin_page_wrapper()` 中 API 辅助脚本（`apiGet`, `showToast`）**必须位于** `{body_html}` 之前，否则页面脚本执行时 `apiGet` 未定义 → `ReferenceError`。

> **⚠️ `metric_routes.py` 路由顺序约束**: `/functions` 和 `/suggest/function` 必须注册在 `/{metric_id}` 之前，否则 FastAPI 会将 `"functions"` 当作 metric_id 匹配 → 404。

### 2.4 `integrations/` — 第三方集成

**LLM**：`openai/`, `anthropic/`, `google/`, `ollama/`, `azureopenai/`, `mock/`
**数据库**：`postgres/`, `mysql/`, `snowflake/`, `bigquery/`, `sqlite/`, `duckdb/`, `clickhouse/`, `mssql/`, `oracle/`, `presto/`, `hive/`
**向量存储**：`postgres/` (pgvector), `chromadb/`, `faiss/`, `pinecone/`, `qdrant/`, `weaviate/`, `milvus/`, `marqo/`, `opensearch/`, `azuresearch/`
**Schema 提取**：`integrations/schema/extractors/` — 从数据库提取 DDL（MySQL, SQLite 等）
**图表**：`plotly/chart_generator.py`

**Postgres 集成** (`integrations/postgres/`) — **主存储后端**：

| 文件 | 类 | 说明 |
|------|------|------|
| `sql_runner.py` | `PostgresRunner` | SQL 执行器 |
| `schema_store.py` | `PostgresSchemaStore` | Schema 存储 — pgvector 向量搜索 + tsvector 全文搜索 |
| `metric_store.py` | `PostgresMetricStore` | Metric 存储 — 双表设计 (definitions + dimensions) |
| `agent_memory.py` | `PostgresAgentMemory` | Agent 记忆 — tool_usage + text_memory 合一表 |
| `embedding.py` | `EmbeddingHelper` | **共享** SentenceTransformer 封装 (模块级缓存 + GPU) |
| `config.py` | — | 默认模型名、表名、CE 候选倍数 |

**ChromaDB 集成** (`integrations/chromadb/`) — **备选存储后端**：

| 文件 | 类 | 说明 |
|------|------|------|
| `schema_store.py` | `ChromaSchemaStore` | ChromaDB 向量存储 Schema |
| `metric_store.py` | `ChromaMetricStore` | ChromaDB + JSON 双模 Metric |
| `agent_memory.py` | `ChromaAgentMemory` | ChromaDB 向量存储记忆 + 模块级 EF 缓存 |

### 2.5 `tools/` — 内置工具

| 文件 | 工具 | 说明 |
|------|------|------|
| `run_sql.py` | `RunSqlTool` | SQL 执行 → DataFrame 组件 |
| `visualize_data.py` | `VisualizeDataTool` | CSV → Plotly 图表 |
| `agent_memory.py` | 3 个记忆工具 | save_question_tool_args, search_saved_correct_tool_uses, save_text_memory |
| `schema_tools.py` | 3 个 Schema 工具 | search_table_schema, get_table_schema, list_tables |
| `metric_tools.py` | 4 个 Metric 工具 | search_metrics, get_metric_detail, list_metrics, execute_metric |
| `file_system.py` | 文件工具 | 文件读写 |
| `python.py` | Python 工具 | 安全执行 Python 代码 |

### 2.6 `capabilities/` — 能力抽象

| 目录 | 核心方法 |
|------|---------|
| `sql_runner/` | `run_sql(args, context) → DataFrame` |
| `agent_memory/` | `save_tool_usage()`, `search_similar_usage()`, `save_text_memory()` |
| `schema_store/` | `list_all_tables()`, `get_table_schema()`, `search_tables()`, `sync_all_schemas()` |
| `metric_store/` | `create_metric()`, `list_metrics()`, `search_metrics()`, `get_metrics_by_table()` |
| `file_system/` | `read_file()`, `write_file()`, `delete_file()` |

---

## 三、Embedding 模型管理

### 3.1 模型缓存架构

所有模型实例通过模块级 dict 缓存，**相同 `(model_name, device)` 只加载一次**：

```
┌────────────────────────────────────────────────────────────┐
│                     磁盘缓存 (永久)                          │
│  HuggingFace: D:\.cache\huggingface\hub\  (HF_HOME)        │
│  ChromaDB ONNX: ~/.cache/chroma/onnx_models/               │
└────────────────────────┬───────────────────────────────────┘
                         │ 首次下载后永久缓存
┌────────────────────────▼───────────────────────────────────┐
│                    内存缓存 (进程生命周期)                     │
│                                                             │
│  Postgres embedding: _EMBEDDING_CACHE[model__device]        │
│  ChromaDB embedding: _EF_CACHE[key]                         │
│  Cross-Encoder:      _CE_CACHE[model__device]               │
│                                                             │
│  所有 Store 共享同一实例，不会重复加载                          │
└────────────────────────────────────────────────────────────┘
```

### 3.2 三个缓存层

| 缓存 | 位置 | Key | 线程安全 |
|------|------|-----|---------|
| `_EMBEDDING_CACHE` | `postgres/embedding.py` | `"model_name__device"` | `threading.Lock` |
| `_EF_CACHE` | `chromadb/agent_memory.py` | `"__default_onnx__"` 或 `"model__device"` | `threading.Lock` |
| `_CE_CACHE` | `core/search/cross_encoder.py` | `"model_name__device"` | `threading.Lock` |

### 3.3 GPU 支持

所有 Store 构造函数接受 `device` 参数：

```python
# 自动检测 CUDA > MPS > CPU
store = PostgresSchemaStore(host=..., database=..., user=...)

# 显式指定 GPU
store = PostgresSchemaStore(host=..., database=..., user=..., device="cuda")

# ChromaDB GPU 模式 — 自动切换到 SentenceTransformerEmbeddingFunction
memory = ChromaAgentMemory(device="cuda")
```

device 检测逻辑 (`_get_device()`): CUDA available → `"cuda"`, MPS available → `"mps"`, else → `"cpu"`

### 3.4 后台预热

所有 Store 在 `__init__` 中通过 `ThreadPoolExecutor.submit()` 后台加载模型，避免首次 API 调用时下载/加载导致超时：

| Store | 预热目标 | 预热代码位置 |
|-------|---------|------------|
| `PostgresSchemaStore` | `EmbeddingHelper._get_model()` | `schema_store.py` L135 |
| `PostgresMetricStore` | `EmbeddingHelper._get_model()` | `metric_store.py` L153 |
| `PostgresAgentMemory` | `EmbeddingHelper._get_model()` | `agent_memory.py` L125 |
| `ChromaSchemaStore` | `_get_embedding_function()` | `schema_store.py` L76 |
| `ChromaMetricStore` | `_get_embedding_function()` | `metric_store.py` L87 |
| `ChromaAgentMemory` | `_get_embedding_function()` | `agent_memory.py` L200 |
| `CrossEncoderReranker` | `_get_model()` | `cross_encoder.py` L114 |

### 3.5 默认模型

| 模型类型 | 默认值 | 维度 | 说明 |
|---------|-------|------|------|
| Embedding (bi-encoder) | `BAAI/bge-base-zh-v1.5` | 768 | 中文优化，通过 `postgres/config.py` 配置 |
| Cross-Encoder | `BAAI/bge-reranker-base` | — | 重排序，通过 `postgres/config.py` 配置 |

---

## 四、Schema 与 Metric 管理系统

### 4.1 Postgres (pgvector) — 主存储

```
Admin UI (/admin/schema, /admin/metrics)
  纯 HTML + Tailwind + Vanilla JS，无框架依赖
        │ REST API (fetch)
        ▼
schema_routes.py           metric_routes.py
  /api/vanna/v2/schema/*    /api/vanna/v2/metrics/*
        │                         │
        ▼                         ▼
PostgresSchemaStore         PostgresMetricStore
  PostgreSQL + pgvector       双表设计 (definitions + dimensions)
  └─ schema_store 表           └─ metric_store_definitions 表
  └─ vector(768) 列            └─ metric_store_dimensions 表 (vector(768))
  └─ tsvector 全文索引          └─ tsvector 全文索引
```

**搜索流程**: pgvector cosine 距离 (vector) + ts_rank (keyword) → RRF 融合 → Cross-Encoder 重排序

### 4.2 ChromaDB — 备选存储

```
ChromaSchemaStore          ChromaMetricStore
  ChromaDB 向量存储          JSON 文件 + ChromaDB 双模
  ./chroma_memory/           ./chroma_memory/
  └─ chroma.sqlite3           ├─ metrics/*.json (权威数据)
                              └─ chroma.sqlite3 (搜索索引)
```

### 4.3 pgvector 维度自动迁移

`_ensure_table()` 每次被调用时会检测 embedding 列的实际维度。如果与当前模型不匹配，**自动迁移**：

```
检测到维度变化 (384 → 768)
    │
    ├─ pg_advisory_lock()     ← 防止并发竞态
    ├─ format_type() 读取当前列类型
    ├─ DROP INDEX             ← 移除旧向量索引
    ├─ UPDATE SET embedding = NULL  ← 清空旧维度向量
    ├─ ALTER COLUMN TYPE vector(768) ← 改列类型
    ├─ CREATE INDEX           ← 重建 ivfflat 索引
    └─ pg_advisory_unlock()
```

> **注意**: 迁移清空旧向量后需重新 sync 数据来生成新维度的 embedding。维度检测使用 `format_type(atttypid, atttypmod)` 而非 `atttypmod - 4`，兼容不同 pgvector 版本。

---

## 五、完整请求处理流程

```
用户输入 → 前端 <vanna-chat> → POST /api/vanna/v2/chat_sse
    │
    ▼
FastAPI routes → ChatHandler.handle_stream() → Agent.send_message()
    │
    ▼
POST /api/vanna/v2/chat_sse
│
├─[外] send_message()      ← 异常捕获外罩 (L142-229)
│
└─[内] _send_message()     ← 编排主引擎 (L231-1154)
  │
  ├─ 阶段一: 用户解析 (L249-350)
  │   user = user_resolver.resolve_user(request)
  │   if starter_request → get_starter_ui() → return
  │   if empty message  → return
  │
  ├─ 阶段二: before_message 钩子链 (L363-392)
  │   for hook: message = hook.before_message(user, message)
  │
  ├─ 阶段三: Workflow 命令拦截 (L394-508)
  │   conversation = store.get_conversation(...)
  │   workflow_result = workflow_handler.try_handle(...)
  │   if should_skip_llm → yield components → save → return
  │
  ├─ 阶段四: 上下文装配 (L510-641)
  │   conversation.add_message(user_msg)
  │   context = ToolContext(user, conversation_id, request_id, agent_memory, ...)
  │   for enricher: context = enricher.enrich_context(context)
  │   tool_schemas = tool_registry.get_schemas(user)  ← 权限过滤
  │   system_prompt = builder.build(user, tool_schemas)
  │   system_prompt = enhancer.enhance(system_prompt, message, user)
  │   request = _build_llm_request(conversation, ...)
  │     ├─ filtered = conversation_filters.chain(messages)
  │     ├─ llm_messages = convert(filtered)
  │     └─ request = LlmRequest(messages, tools, system_prompt)
  │
  ├─ 阶段五+六: LLM ⇄ Tool 循环 (L643-1012)
  │   tool_iterations = 0
  │   while tool_iterations < max:
  │     ├─ response = middleware_before → llm.send/stream → middleware_after
  │     │
  │     ├─ if is_tool_call():
  │     │   tool_iterations++
  │     │   conversation.add_message(assistant + tool_calls)
  │     │   for each tool_call:
  │     │     ├─ before_tool 钩子
  │     │     ├─ registry.execute():
  │     │     │   ① 查找 ② 权限 ③ 参数校验 ④ transform ⑤ 审计 ⑥ 执行
  │     │     ├─ after_tool 钩子
  │     │     ├─ yield UI 结果
  │     │     └─ tool_results.append(...)
  │     │   conversation.add_messages(tool_results)
  │     │   request = _build_llm_request(conversation, ...)  ← 回环
  │     │
  │     └─ else:  # 纯文本
  │         conversation.add_message(assistant)
  │         yield final response → break
  │
  ├─ 阶段七: 限流警告 (L1044-1085)
  │   if hit limit → yield warning
  │
  └─ 阶段八: 收尾 (L1087-1154)
      conversation_store.save(conversation)
      for hook: hook.after_message(conversation)
      observability.end_span()
    │
    ▼
LLM 回复循环 (最多 max_tool_iterations):
  ★ tool_calls → before_tool → ToolRegistry.execute() → after_tool → 回传 LLM
  ★ 纯文本   → 跳出循环
    │
    ▼
SSE 流式输出: UiComponent → ChatStreamChunk → JSON → 前端渲染
  组件序列: StatusBar → TaskTracker → StatusCard → DataFrame → Chart → Text → ChatInput
```

## Agent观测Span
agent.send_message                          ← 根 Span (L355)
│
├── agent.user_resolution                   ← 用户身份解析 (L252)
│   metric: agent.user_resolution.duration
│
├── agent.workflow_handler.starter_ui       ← 启动页 UI (L278)
│   metric: agent.workflow_handler.starter_ui.duration
│
├── agent.hook.before_message               ← 每条消息的 before 钩子 (L368)
│   metric: agent.hook.duration
│
├── agent.conversation.load                 ← 对话加载 (L412)
│   metric: agent.conversation.load.duration
│
├── agent.workflow_handler.try_handle       ← Workflow 命令拦截 (L443)
│
├── agent.context.enrichment                ← ContextEnricher 链 (L547)
│   metric: agent.enrichment.duration
│
├── agent.tool_schemas.fetch                ← 获取可用工具 Schema (L567)
│   metric: agent.tool_schemas.duration
│
├── agent.system_prompt.build               ← 构建 System Prompt (L594)
│   metric: agent.system_prompt.duration
│
├── agent.llm_context.enhance_system_prompt ← 增强 System Prompt (L607)
│   metric: agent.llm_context.enhance_system_prompt.duration
│
├── agent.conversation.filter               ← 对话过滤器链 (L1173)
│   metric: agent.filter.duration
│
├── agent.llm_context.enhance_user_messages ← 增强用户消息 (L1208)
│   metric: agent.llm_context.enhance_user_messages.duration
│
├── agent.middleware.before_llm             ← LLM 请求前中间件 (L1247/L1321)
│   metric: agent.middleware.duration
│
├── llm.request / llm.stream                ← LLM 调用本身 (L1270/L1351)
│   metric: llm.request.duration / llm.stream.duration
│
├── agent.hook.before_tool                  ← 工具执行前钩子 (L791)
│   metric: agent.hook.duration
│
├── agent.tool.execute                      ← 工具执行 (L819)
│   metric: agent.tool.duration
│
├── agent.hook.after_tool                   ← 工具执行后钩子 (L851)
│   metric: agent.hook.duration
│
├── agent.middleware.after_llm              ← LLM 响应后中间件 (L1293/L1383)
│   metric: agent.middleware.duration
│
├── agent.conversation.save                 ← 对话保存 (L1091)
│   metric: agent.conversation.save.duration
│
├── agent.hook.after_message                ← 消息处理完毕钩子 (L1114)
│   metric: agent.hook.duration
│
└── agent.send_message.error                ← 异常捕获 (L177)
    metric: agent.error.count
