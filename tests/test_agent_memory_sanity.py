"""
Sanity tests for AgentMemory implementations.

These tests verify that:
1. Each AgentMemory implementation correctly implements the AgentMemory interface
2. Imports are working correctly for all vector store modules
3. Basic class instantiation works (without requiring actual service connections)

Note: These tests do NOT execute actual vector operations against services.
They are lightweight sanity checks for the implementation structure.
"""

import pytest
from inspect import signature, iscoroutinefunction
from abc import ABC


class TestAgentMemoryInterface:
    """Test that the AgentMemory interface is properly defined."""

    def test_agent_memory_import(self):
        """Test that AgentMemory can be imported."""
        from easyq2sql.capabilities.agent_memory import AgentMemory

        assert AgentMemory is not None

    def test_agent_memory_is_abstract(self):
        """Test that AgentMemory is an abstract base class."""
        from easyq2sql.capabilities.agent_memory import AgentMemory

        assert issubclass(AgentMemory, ABC)

    def test_agent_memory_has_required_methods(self):
        """Test that AgentMemory defines all required abstract methods."""
        from easyq2sql.capabilities.agent_memory import AgentMemory

        required_methods = [
            "save_tool_usage",
            "save_text_memory",
            "search_similar_usage",
            "search_text_memories",
            "get_recent_memories",
            "get_recent_text_memories",
            "delete_by_id",
            "delete_text_memory",
            "clear_memories",
        ]

        for method_name in required_methods:
            assert hasattr(AgentMemory, method_name)
            method = getattr(AgentMemory, method_name)
            assert getattr(method, "__isabstractmethod__", False), (
                f"{method_name} should be abstract"
            )

    def test_all_methods_are_async(self):
        """Test that all AgentMemory methods are async."""
        from easyq2sql.capabilities.agent_memory import AgentMemory

        methods = [
            "save_tool_usage",
            "save_text_memory",
            "search_similar_usage",
            "search_text_memories",
            "get_recent_memories",
            "get_recent_text_memories",
            "delete_by_id",
            "delete_text_memory",
            "clear_memories",
        ]

        for method_name in methods:
            method = getattr(AgentMemory, method_name)
            assert iscoroutinefunction(method), f"{method_name} should be async"


class TestToolMemoryModel:
    """Test the ToolMemory model."""

    def test_tool_memory_import(self):
        """Test that ToolMemory can be imported."""
        from easyq2sql.capabilities.agent_memory import ToolMemory

        assert ToolMemory is not None

    def test_tool_memory_is_pydantic_model(self):
        """Test that ToolMemory is a Pydantic model."""
        from easyq2sql.capabilities.agent_memory import ToolMemory
        from pydantic import BaseModel

        assert issubclass(ToolMemory, BaseModel)

    def test_tool_memory_has_required_fields(self):
        """Test that ToolMemory has all required fields."""
        from easyq2sql.capabilities.agent_memory import ToolMemory

        required_fields = ["question", "tool_name", "args"]
        optional_fields = ["memory_id", "timestamp", "success", "metadata"]

        model_fields = list(ToolMemory.model_fields.keys())

        for field in required_fields:
            assert field in model_fields, f"Required field '{field}' missing"

        for field in optional_fields:
            assert field in model_fields, f"Optional field '{field}' missing"

    def test_tool_memory_instantiation(self):
        """Test that ToolMemory can be instantiated."""
        from easyq2sql.capabilities.agent_memory import ToolMemory

        memory = ToolMemory(
            memory_id="test-123",
            question="What is the total sales?",
            tool_name="run_sql",
            args={"sql": "SELECT SUM(amount) FROM sales"},
        )

        assert memory.memory_id == "test-123"
        assert memory.question == "What is the total sales?"
        assert memory.tool_name == "run_sql"
        assert memory.args == {"sql": "SELECT SUM(amount) FROM sales"}
        assert memory.success is True  # Default value


class TestToolMemorySearchResultModel:
    """Test the ToolMemorySearchResult model."""

    def test_memory_search_result_import(self):
        """Test that ToolMemorySearchResult can be imported."""
        from easyq2sql.capabilities.agent_memory import ToolMemorySearchResult

        assert ToolMemorySearchResult is not None

    def test_memory_search_result_instantiation(self):
        """Test that ToolMemorySearchResult can be instantiated."""
        from easyq2sql.capabilities.agent_memory import ToolMemorySearchResult, ToolMemory

        memory = ToolMemory(question="test", tool_name="test_tool", args={})

        result = ToolMemorySearchResult(memory=memory, similarity_score=0.95, rank=1)

        assert result.memory == memory
        assert result.similarity_score == 0.95
        assert result.rank == 1


class TestTextMemoryModel:
    """Test the TextMemory model."""

    def test_text_memory_import(self):
        """Test that TextMemory can be imported."""
        from easyq2sql.capabilities.agent_memory import TextMemory

        assert TextMemory is not None

    def test_text_memory_is_pydantic_model(self):
        """Test that TextMemory is a Pydantic model."""
        from easyq2sql.capabilities.agent_memory import TextMemory
        from pydantic import BaseModel

        assert issubclass(TextMemory, BaseModel)

    def test_text_memory_has_required_fields(self):
        """Test that TextMemory has all required fields."""
        from easyq2sql.capabilities.agent_memory import TextMemory

        required_fields = ["content"]
        optional_fields = ["memory_id", "timestamp"]

        model_fields = list(TextMemory.model_fields.keys())

        for field in required_fields:
            assert field in model_fields, f"Required field '{field}' missing"

        for field in optional_fields:
            assert field in model_fields, f"Optional field '{field}' missing"

    def test_text_memory_instantiation(self):
        """Test that TextMemory can be instantiated."""
        from easyq2sql.capabilities.agent_memory import TextMemory

        memory = TextMemory(
            memory_id="text-123", content="Remember to handle edge cases"
        )

        assert memory.memory_id == "text-123"
        assert memory.content == "Remember to handle edge cases"


class TestTextMemorySearchResultModel:
    """Test the TextMemorySearchResult model."""

    def test_text_memory_search_result_import(self):
        """Test that TextMemorySearchResult can be imported."""
        from easyq2sql.capabilities.agent_memory import TextMemorySearchResult

        assert TextMemorySearchResult is not None

    def test_text_memory_search_result_instantiation(self):
        """Test that TextMemorySearchResult can be instantiated."""
        from easyq2sql.capabilities.agent_memory import TextMemorySearchResult, TextMemory

        memory = TextMemory(content="Example memory")

        result = TextMemorySearchResult(memory=memory, similarity_score=0.88, rank=2)

        assert result.memory == memory
        assert result.similarity_score == 0.88
        assert result.rank == 2


class TestDemoAgentMemory:
    """Sanity tests for DemoAgentMemory (in-memory) implementation."""

    def test_demo_import(self):
        """Test that DemoAgentMemory can be imported."""
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

        assert DemoAgentMemory is not None

    def test_demo_implements_agent_memory(self):
        """Test that DemoAgentMemory implements AgentMemory."""
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory
        from easyq2sql.capabilities.agent_memory import AgentMemory

        assert issubclass(DemoAgentMemory, AgentMemory)

    def test_demo_has_all_methods(self):
        """Test that DemoAgentMemory implements all required methods."""
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

        required_methods = [
            "save_tool_usage",
            "save_text_memory",
            "search_similar_usage",
            "search_text_memories",
            "get_recent_memories",
            "get_recent_text_memories",
            "delete_by_id",
            "delete_text_memory",
            "clear_memories",
        ]

        for method_name in required_methods:
            assert hasattr(DemoAgentMemory, method_name)

    def test_demo_instantiation(self):
        """Test that DemoAgentMemory can be instantiated."""
        from easyq2sql.integrations.local.agent_memory import DemoAgentMemory

        memory = DemoAgentMemory(max_items=100)

        assert memory is not None
        assert memory._max_items == 100
