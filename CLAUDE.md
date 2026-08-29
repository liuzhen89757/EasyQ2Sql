# EasyQ2Sql 给 AI 编码 agent 的指引

## 项目概述
EasyQ2Sql 是一个「元数据驱动」的 Text-to-SQL agent 框架：把自然语言问题转换为 SQL、执行并流式返回答案。核心架构是一句话——**LLM ⇄ 工具循环的 agent 引擎 + 分层能力抽象（capabilities/integrations）+ 7 阶段 SQL 安全治理**。它源自 vanna 的架构模式，在元数据管理、混合检索、多层记忆、SQL 安全与 agent 编排上有显著增强。

## 开发命令
```bash
uv sync                                        # 安装核心依赖（推荐用 uv，见 pyproject.toml）
pytest tests/ -v                               # 跑全部测试
pytest tests/test_sql_security.py::test_x -v   # 跑单个测试
pytest tests/ -m "not integration"             # 跳过需要外部服务的测试
ruff check src/ tests/                         # lint
ruff format --check src/ tests/                # 格式检查（ruff format 自动修复）
mypy src/easyq2sql/tools src/easyq2sql/core src/easyq2sql/capabilities src/easyq2sql/agents src/easyq2sql/utils src/easyq2sql/web_components src/easyq2sql/components --strict   # 类型检查

# 运行
easyq2sql --list-examples                      # 列出可用示例 agent
easyq2sql --example mock_sqlite_example --framework fastapi --port 8000   # 启动 web server（FastAPI 默认）
python -m easyq2sql.examples mock_quickstart   # 交互式运行某个示例
```
`tox` 提供了更细的 env 分组（`py311-unit`、`py311-*-sanity`、`ruff`、`mypy`），可按需使用。

## 架构导览
### 核心数据流
```
自然语言问题
  → 前端 <easyq2sql-chat>  (SSE / WebSocket / Polling，POST /api/easyq2sql/v1/chat_sse)
  → 服务层 servers/  (FastAPI/Flask → ChatHandler → SSE 流式返回，+ admin UI)
  → 核心 agent core/agent/  (UserResolver → WorkflowHandler → LLM ⇄ Tools 循环，
      7 个扩展点：Hook / Middleware / Recovery / Enricher / Enhancer / Filter / Observability
      + hooks/ 调用管控 + enhanced_tool_registry.py SQL 安全)
  → 能力层 capabilities/  (SqlRunner | AgentMemory | SchemaStore | AtomicMetricStore | DerivedMetricStore | CompositeMetricStore | MetricGraphStore)
  → 集成层 integrations/  (LLM / DB / 向量库 / Neo4j 图 / schema 抽取)
  → 生成 SQL → run_sql 工具执行（先过 7 阶段安全管线）→ 流式返回答案
```

### 关键子系统
- `core/` — 核心框架：agent 引擎、tool 抽象、LLM 抽象、user 系统、registry、workflow、7 类扩展点
- `capabilities/` — 能力抽象：SqlRunner / AgentMemory / SchemaStore / AtomicMetricStore / DerivedMetricStore / CompositeMetricStore / MetricGraphStore / FileSystem
- `integrations/` — 第三方集成：LLM（OpenAI/Anthropic/Gemini/Ollama…）、DB（PostgreSQL/MySQL/BigQuery/DuckDB…）、向量库（pgvector/ChromaDB/FAISS/Qdrant…）、Neo4j、`schema/extractors/` DDL 抽取
- `servers/` — Web 服务层：FastAPI/Flask 路由、SSE、admin UI、CLI server
- `tools/` — 内置 LLM 工具：`run_sql`、schema 工具、metric 工具、memory/file/python/可视化工具
- `hooks/` — 工具调用管控：`lifecycle/` observer 钩子 + `middleware/` 干预中间件，共享 `regulator.py` 策略引擎（WARN/BLOCK、SQL 骨架冻结）
- `metric_graph/` — 指标自动抽取：`extract.py`（LLM 抽取）→ `draft.py`（草稿区 + 依赖序导入）→ `metric_graph.py`（LightRAG 式抽取引擎）
- `enhanced_tool_registry.py` — `run_sql` 的 SQL 安全包装（7 阶段预执行管线 + RLS 改写），是核心 `ToolRegistry` 的 drop-in 替代
- `components/` + `web_components/` — UI 组件（Rich：DataFrame/Chart/Card；Simple：Text/Image；前端 web components）

### 入口点
- `src/easyq2sql/servers/cli/server_runner.py` — CLI 入口（`easyq2sql` 命令，`main()` 在 line 104）
- `src/easyq2sql/servers/fastapi/app.py` — `EasyQ2SqlFastAPIServer`（`create_app()` / `run()`）
- `src/easyq2sql/servers/flask/app.py` — `EasyQ2SqlFlaskServer`
- `src/easyq2sql/examples/__main__.py` — 交互式示例运行器（`python -m easyq2sql.examples <name>`）
- `src/easyq2sql/core/agent/agent.py` — `Agent` 核心编排类

## 代码风格
- **Python 版本**：`requires-python >= 3.10`；ruff 与 tox 以 `py311` 为目标版本
- **行宽**：88（Black 默认）；字符串用**双引号**（`quote-style = "double"`）
- **Linter**：`ruff`（`pyproject.toml` 的 `[tool.ruff]` / `[tool.ruff.lint]`）——启用 E/W/F/N/B/C4/SIM，忽略 E501/E402/大部分 N8xx/F401 等（详见 `ignore` 列表）；import 排序（isort，`I`）**关闭**，由 pre-commit 的 isort 负责（`--profile black`）
- **类型检查**：mypy `--strict`（仅对 tox.ini `[testenv:mypy]` 列出的子目录）
- **测试配置**：`pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`），`testpaths = ["tests"]`；用 marker 区分需要外部服务的测试（`integration` / `anthropic` / `openai` / `postgres` / `mysql` …）
- 项目用 **flit** 打包（`[tool.flit.module]`），sdist 排除 `frontends/ tests/ notebooks/ .github/ tox.ini`

## 常用文件位置
- **改 SQL 安全规则** → `src/easyq2sql/sql_security_config.yaml`（每个 section 对应一个 Pydantic 模型，未知 key 忽略）
- **改环境变量模板** → `.env.example`（LLM / 目标 DB / pgvector 元数据库 / Neo4j / 服务器）
- **加/改 FastAPI 路由** → `src/easyq2sql/servers/fastapi/*_routes.py`（注意先注册静态子路径，见 gotchas）
- **改 admin 页面模板** → `src/easyq2sql/servers/base/admin_templates.py`（API helper `<script>` 顺序，见 gotchas）
- **加新工具** → `src/easyq2sql/tools/`（用 `ToolRegistry` 注册）
- **加新能力抽象** → `src/easyq2sql/capabilities/`；**加新集成** → `src/easyq2sql/integrations/<vendor>/`
- **改 agent 编排/扩展点** → `src/easyq2sql/core/agent/agent.py`
- **跑示例** → `src/easyq2sql/examples/`
- **设计/特性文档** → `docs/`（`hook.md` / `middleware.md` / `metric-retrieval.md` / `run-sql-security.md`）
