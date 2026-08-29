"""
EasyQ2Sql - A modular framework for building LLM agents.

This package provides a flexible framework for creating conversational AI agents
with tool execution, conversation management, and user scoping.
"""

# Version information
__version__ = "0.1.0"

# Import core framework components
from .core import (
    # Interfaces
    Agent,
    ConversationStore,
    LlmService,
    SystemPromptBuilder,
    Tool,
    UserService,
    T,
    # Models
    Conversation,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
    Message,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSchema,
    User,
    # UI Components
    UiComponent,
    SimpleComponent,
    SimpleComponentType,
    SimpleTextComponent,
    SimpleImageComponent,
    SimpleLinkComponent,
    # Rich Components
    ArtifactComponent,
    BadgeComponent,
    CardComponent,
    DataFrameComponent,
    IconTextComponent,
    LogViewerComponent,
    NotificationComponent,
    ProgressBarComponent,
    ProgressDisplayComponent,
    RichTextComponent,
    StatusCardComponent,
    TaskListComponent,
    # Core implementations
    Agent,
    AgentConfig,
    DefaultSystemPromptBuilder,
    DefaultWorkflowHandler,
    ToolRegistry,
    # Evaluation
    Evaluator,
    TestCase,
    ExpectedOutcome,
    AgentResult,
    EvaluationResult,
    TestCaseResult,
    AgentVariant,
    EvaluationRunner,
    TrajectoryEvaluator,
    OutputEvaluator,
    LLMAsJudgeEvaluator,
    EfficiencyEvaluator,
    EvaluationReport,
    ComparisonReport,
    EvaluationDataset,
    # Exceptions
    AgentError,
    ConversationNotFoundError,
    LlmServiceError,
    PermissionError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError,
)

# Import capabilities
from .capabilities import (
    AtomicMetric,
    AtomicMetricSearchResult,
    AtomicMetricStore,
    ColumnSchema,
    JoinClause,
    SchemaSearchResult,
    SchemaStore,
    TableSchema,
)

# Import basic implementations
from .integrations import MemoryConversationStore, MockLlmService

# Import PostgreSQL-based capability implementations
from .integrations.postgres import (
    PostgresAgentMemory,
    PostgresAtomicMetricStore,
    PostgresRunner,
    PostgresSchemaStore,
)

# Main exports
__all__ = [
    # Version
    "__version__",
    # Core interfaces
    "Agent",
    "Tool",
    "LlmService",
    "ConversationStore",
    "UserService",
    "SystemPromptBuilder",
    "T",
    # Models
    "User",
    "Message",
    "Conversation",
    "ToolCall",
    "ToolResult",
    "ToolContext",
    "ToolSchema",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "LlmStreamChunk",
    # UI Components
    "UiComponent",
    "SimpleComponent",
    "SimpleComponentType",
    "SimpleTextComponent",
    "SimpleImageComponent",
    "SimpleLinkComponent",
    # Rich Components
    "ArtifactComponent",
    "BadgeComponent",
    "CardComponent",
    "DataFrameComponent",
    "IconTextComponent",
    "LogViewerComponent",
    "NotificationComponent",
    "ProgressBarComponent",
    "ProgressDisplayComponent",
    "RichTextComponent",
    "StatusCardComponent",
    "TaskListComponent",
    # Core implementations
    "Agent",
    "AgentConfig",
    "ToolRegistry",
    "DefaultSystemPromptBuilder",
    "DefaultWorkflowHandler",
    # Evaluation
    "Evaluator",
    "TestCase",
    "ExpectedOutcome",
    "AgentResult",
    "EvaluationResult",
    "TestCaseResult",
    "AgentVariant",
    "EvaluationRunner",
    "TrajectoryEvaluator",
    "OutputEvaluator",
    "LLMAsJudgeEvaluator",
    "EfficiencyEvaluator",
    "EvaluationReport",
    "ComparisonReport",
    "EvaluationDataset",
    # Capabilities - Schema
    "SchemaStore",
    "TableSchema",
    "ColumnSchema",
    "SchemaSearchResult",
    # Capabilities - Metric
    "AtomicMetricStore",
    "AtomicMetric",
    "JoinClause",
    "AtomicMetricSearchResult",
    # Basic implementations
    "MemoryConversationStore",
    "MockLlmService",
    # PostgreSQL store implementations
    "PostgresRunner",
    "PostgresSchemaStore",
    "PostgresAtomicMetricStore",
    "PostgresAgentMemory",
    # Server components
    "EasyQ2SqlFlaskServer",
    "EasyQ2SqlFastAPIServer",
    "ChatHandler",
    "ChatRequest",
    "ChatStreamChunk",
    "ExampleAgentLoader",
    # Exceptions
    "AgentError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "PermissionError",
    "ConversationNotFoundError",
    "LlmServiceError",
    "ValidationError",
]
