<p align="center">
  <h1 align="center">EasyQ2Sql</h1>
  <p align="center"><strong>A Metadata-Driven Agent for Question-to-SQL</strong></p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

EasyQ2Sql is an agentic Text-to-SQL framework that turns natural language questions into executable SQL queries. It combines **metadata management** (schema & metric admin UIs), **hybrid search with reranking**, and a **multi-layer memory system** to give the agent deep context about your database.

> **In short: you manage your database's metadata through admin UIs. The agent retrieves relevant context, generates accurate SQL, and learns from every interaction.**

## 🎯 Core Features

- **🧠 Agentic Architecture** — LLM ⇄ Tool iteration loop with 7 extension points (lifecycle hooks, middleware, error recovery, context enrichers, conversation filters, context enhancers, observability)
- **🗄️ Schema Management** — Admin UI for managing table schemas, column descriptions, and foreign key relationships. Hybrid search (pgvector + tsvector → RRF fusion → Cross-Encoder rerank)
- **📊 Metric Management** — Admin UI for defining business metrics with composable function steps (aggregate, logical, window, date, analysis). Auto-suggest dimensions and generate metric SQL
- **🔍 Hybrid Search & Reranking** — Vector similarity + keyword search fused with Reciprocal Rank Fusion (RRF), then reranked by Cross-Encoder
- **🧩 Multi-Layer Memory** — Conversation memory (short-term) + Tool usage memory (long-term) + Text memory (knowledge base). Agent recalls relevant past interactions to improve future answers

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────┐
│              Frontend <easyq2sql-chat>                │
│           (SSE / WebSocket / Polling)                 │
└──────────────────────┬───────────────────────────────┘
                       │ POST /api/easyq2sql/v1/chat_sse
┌──────────────────────▼───────────────────────────────┐
│               Server Layer (servers/)                  │
│   FastAPI / Flask → ChatHandler → SSE Streaming       │
│   + Admin UI (/admin/schema, /admin/metrics)          │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│               Core Agent (core/agent/)                 │
│   UserResolver → WorkflowHandler → LLM ⇄ Tools Loop  │
│   7 Extension Points: Hook / Middleware / Recovery     │
│                      Enricher / Enhancer / Filter      │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│           Capability Layer (capabilities/)             │
│   SqlRunner | AgentMemory | SchemaStore | MetricStore │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│           Integration Layer (integrations/)            │
│   LLM: OpenAI / Anthropic / Gemini / Ollama ...       │
│   DB: PostgreSQL / MySQL / BigQuery / DuckDB ...      │
│   Vector: pgvector / ChromaDB / FAISS / Qdrant ...    │
└──────────────────────────────────────────────────────┘
```

## 📦 Installation

### Prerequisites

- Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

### Setup

```bash
# Clone the repository
git clone https://github.com/lili/easyq2sql.git
cd easyq2sql

# Install core dependencies
uv sync

# Set up your configuration
cp .env.example .env
# Edit .env with your LLM API key and database credentials
```

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

EasyQ2Sql is built upon architectural patterns from the [vanna](https://github.com/vanna-ai/vanna) Text-to-SQL framework, with significant enhancements in metadata management, hybrid search, multi-layer memory, and agent orchestration.
