"""
MyAgent.py — EasyQ2Sql Agent entry point.

All credentials are read from environment variables.
Copy .env.example to .env and fill in your real values.
"""

import os
import logging

# Auto-load .env file (requires: pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from easyq2sql import Agent
from easyq2sql.enhanced_tool_registry import EnhancedToolRegistry
from easyq2sql.core.user import UserResolver, User, RequestContext
from easyq2sql.core.agent.config import AgentConfig, UiFeatures, AuditConfig
from easyq2sql.tools import RunSqlTool, VisualizeDataTool
from easyq2sql.integrations.local import LocalFileSystem
from easyq2sql.tools.agent_memory import (
    SaveQuestionToolArgsTool,
    SearchSavedCorrectToolUsesTool,
    SaveTextMemoryTool,
)
from easyq2sql.tools.schema_tools import SearchTableSchemaTool
from easyq2sql.tools.metric_tools import SearchMetricsTool
from easyq2sql.servers.fastapi import EasyQ2SqlFastAPIServer
from easyq2sql.integrations.openai import OpenAILlmService
from easyq2sql.integrations.postgres import (
    PostgresAgentMemory,
    PostgresAtomicMetricStore,
    PostgresCompositeMetricStore,
    PostgresDerivedMetricStore,
    PostgresSchemaStore,
)
from easyq2sql.integrations.neo4j import Neo4jMetricGraphStore
from easyq2sql.integrations.local.file_system_conversation_store import FileSystemConversationStore
from easyq2sql.integrations.local.audit import LoggingAuditLogger
from easyq2sql.core.system_prompt import DefaultSystemPromptBuilder
from easyq2sql.core.workflow import DefaultWorkflowHandler
from easyq2sql.core.enhancer import DefaultLlmContextEnhancer
from easyq2sql.core.recovery import DefaultErrorRecoveryStrategy
from easyq2sql.core.enricher import ToolContextEnricher
from easyq2sql.core.filter import ConversationFilter
from easyq2sql.core.observability import ObservabilityProvider
from easyq2sql.core.lifecycle import LifecycleHook
from easyq2sql.core.middleware import LlmMiddleware
from easyq2sql.hooks import (
    SqlRegulatorHook,
    SchemaRegulatorHook,
    MetricRegulatorHook,
    SqlRegulatorMiddleware,
    SchemaRegulatorMiddleware,
    MetricRegulatorMiddleware,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "info")

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = LOG_LEVEL) -> str:
    """Configure app + uvicorn loggers to a common level.

    The agent, hooks and middlewares log via ``logging.getLogger(__name__)``,
    which propagates to the root logger configured here. Uvicorn configures its
    own ``uvicorn.*`` loggers separately, so the same level string is also
    passed to ``server.run(log_level=...)`` to keep both sides aligned.

    Returns the normalized lowercase level string (safe for ``log_level=``).
    """
    level = (level or "info").lower()
    numeric = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(level=numeric, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Align uvicorn's loggers now; uvicorn re-applies them from ``log_level``.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        logging.getLogger(name).setLevel(numeric)

    return level


configure_logging(LOG_LEVEL)
logger = logging.getLogger(__name__)


# ============================================================================
# Services — all credentials from environment variables
# ============================================================================

# --- LLM (对话 / send_message 用) ---
llm = OpenAILlmService(
    model=os.getenv("LLM_MODEL", "deepseek-v4-pro"),
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
)

# --- Metric-extraction LLM (指标提取专用，独立配置 model / api_key / base_url；
# 未设置 METRIC_EXTRACTION_LLM_* 时回退到上面的 LLM_*，保持向后兼容) ---
extraction_llm = OpenAILlmService(
    model=os.getenv("METRIC_EXTRACTION_LLM_MODEL") or os.getenv("LLM_MODEL", "deepseek-v4-pro"),
    api_key=os.getenv("METRIC_EXTRACTION_LLM_API_KEY") or os.getenv("LLM_API_KEY"),
    base_url=os.getenv("METRIC_EXTRACTION_LLM_BASE_URL") or os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
)

# --- Target database ---
DB_TYPE = os.getenv("DB_TYPE", "mysql")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

if DB_TYPE == "mysql":
    from easyq2sql.integrations.mysql import MySQLRunner
    sql_runner = MySQLRunner(
        host=DB_HOST, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD, port=DB_PORT,
    )
elif DB_TYPE == "postgres":
    from easyq2sql.integrations.postgres import PostgresRunner
    sql_runner = PostgresRunner(
        host=DB_HOST, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD, port=DB_PORT,
    )
elif DB_TYPE == "sqlite":
    from easyq2sql.integrations.sqlite import SqliteRunner
    sql_runner = SqliteRunner(database_path=DB_NAME)
else:
    raise ValueError(f"Unsupported DB_TYPE: {DB_TYPE}")

# --- Schema extractor (auto-select by DB_TYPE) ---
if DB_TYPE == "mysql":
    from easyq2sql.integrations.schema.extractors.mysql import MySqlSchemaExtractor
    schema_extractor = MySqlSchemaExtractor()
elif DB_TYPE == "postgres":
    from easyq2sql.integrations.schema.extractors.postgres import PostgresSchemaExtractor
    schema_extractor = PostgresSchemaExtractor()
elif DB_TYPE == "sqlite":
    from easyq2sql.integrations.schema.extractors.sqlite import SqliteSchemaExtractor
    schema_extractor = SqliteSchemaExtractor()
else:
    schema_extractor = None

# --- Metadata store (PostgreSQL + pgvector) ---
PG_HOST = os.getenv("PG_HOST")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DATABASE = os.getenv("PG_DATABASE", "easyq2sql_metadata")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")

agent_memory = PostgresAgentMemory(
    host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
    user=PG_USER, password=PG_PASSWORD,
)
schema_store = PostgresSchemaStore(
    host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
    user=PG_USER, password=PG_PASSWORD,
)
atomic_metric_store = PostgresAtomicMetricStore(
    host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
    user=PG_USER, password=PG_PASSWORD,
)
derived_metric_store = PostgresDerivedMetricStore(
    host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
    user=PG_USER, password=PG_PASSWORD,
)
composite_metric_store = PostgresCompositeMetricStore(
    host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
    user=PG_USER, password=PG_PASSWORD,
)

# --- Metric graph store (Neo4j) — credentials read from NEO4J_* env vars ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_WORKSPACE = os.getenv("NEO4J_WORKSPACE", "base")

metric_graph_store = Neo4jMetricGraphStore(
    uri=NEO4J_URI,
    username=NEO4J_USERNAME,
    password=NEO4J_PASSWORD,
    workspace=NEO4J_WORKSPACE,
)

# --- User resolver ---
class SimpleUserResolver(UserResolver):
    """Extract user identity from cookie."""
    async def resolve_user(self, request_context: RequestContext) -> User:
        user_email = request_context.get_cookie("easyq2sql_email") or "guest@example.com"
        group = "admin" if user_email == "admin@example.com" else "user"
        return User(id=user_email, email=user_email, group_memberships=[group])

user_resolver = SimpleUserResolver()

# --- Conversation store ---
conversation_store = FileSystemConversationStore(
    base_dir=os.getenv("CONVERSATIONS_DIR", "./conversations"),
)

# --- Agent config ---
config = AgentConfig(
    max_tool_iterations=15,
    stream_responses=True,
    auto_save_conversations=True,
    include_thinking_indicators=True,
    temperature=0.7,
    max_tokens=4096,
    ui_features=UiFeatures(),
    audit_config=AuditConfig(
        enabled=True,
        log_tool_access_checks=True,
        log_tool_invocations=True,
        log_tool_results=True,
        log_ai_responses=True,
    ),
)

# ============================================================================
# Extension points — all built-in defaults
# ============================================================================

system_prompt_builder = DefaultSystemPromptBuilder()
workflow_handler = DefaultWorkflowHandler()
llm_context_enhancer = DefaultLlmContextEnhancer(agent_memory)
error_recovery_strategy = DefaultErrorRecoveryStrategy(
    # Switch to this model after repeated 529/overloaded errors. Leave None to
    # disable model switching and only do exponential backoff. Override via env
    # OPENAI_FALLBACK_MODEL if you want the switch behavior.
    fallback_model=os.getenv("OPENAI_FALLBACK_MODEL") or None,
)
observability_provider = ObservabilityProvider()
audit_logger = LoggingAuditLogger()

context_enrichers = [ToolContextEnricher()]
conversation_filters = [ConversationFilter()]

# --- Tool regulators (observer + intervener share the default tracker) ---
lifecycle_hooks: list[LifecycleHook] = [
    SqlRegulatorHook(),
    SchemaRegulatorHook(),
    MetricRegulatorHook(),
]
llm_middlewares: list[LlmMiddleware] = [
    SqlRegulatorMiddleware(),
    SchemaRegulatorMiddleware(),
    MetricRegulatorMiddleware(),
]

# ============================================================================
# Tool registration
# ============================================================================

# Shared FileSystem — all file-producing/consuming tools MUST share the same instance
file_system = LocalFileSystem(working_directory="./easyq2sql_data")

tools = EnhancedToolRegistry()
tools.register_local_tool(RunSqlTool(sql_runner=sql_runner, file_system=file_system), access_groups=["admin", "user"])
tools.register_local_tool(VisualizeDataTool(file_system=file_system), access_groups=["admin", "user"])
tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=["admin"])
tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=["admin", "user"])
tools.register_local_tool(SaveTextMemoryTool(), access_groups=["admin", "user"])
tools.register_local_tool(SearchTableSchemaTool(schema_store=schema_store), access_groups=["admin", "user"])
tools.register_local_tool(
    SearchMetricsTool(
        atomic_metric_store=atomic_metric_store,
        derived_metric_store=derived_metric_store,
        composite_metric_store=composite_metric_store,
        metric_graph_store=metric_graph_store,
    ),
    access_groups=["admin", "user"],
)

# ============================================================================
# Build agent
# ============================================================================

agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=user_resolver,
    agent_memory=agent_memory,
    conversation_store=conversation_store,
    config=config,
    system_prompt_builder=system_prompt_builder,
    workflow_handler=workflow_handler,
    error_recovery_strategy=error_recovery_strategy,
    context_enrichers=context_enrichers,
    llm_context_enhancer=llm_context_enhancer,
    conversation_filters=conversation_filters,
    observability_provider=observability_provider,
    audit_logger=audit_logger,
    lifecycle_hooks=lifecycle_hooks,
    llm_middlewares=llm_middlewares,
)

# ============================================================================
# Launch server
# ============================================================================

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

server = EasyQ2SqlFastAPIServer(agent, config={
    "schema_store": schema_store,
    "atomic_metric_store": atomic_metric_store,
    "derived_metric_store": derived_metric_store,
    "composite_metric_store": composite_metric_store,
    "metric_graph_store": metric_graph_store,
    "schema_extractor": schema_extractor,
    "sql_runner": sql_runner,
    "database_name": DB_NAME,
    "llm_service": extraction_llm,
})

if __name__ == "__main__":
    server.run(host=SERVER_HOST, port=SERVER_PORT, log_level=LOG_LEVEL)
