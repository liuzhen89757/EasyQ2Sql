"""
Unit tests for ConversationCompressionHook.

Validates round boundary detection, compression prompt building,
Query History section formatting, and the full after_message flow.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from easyq2sql.core.compression.hook import (
    MAX_CONVERSATION_LENGTH,
    MAX_TOOL_RESULT_LENGTH,
    ConversationCompressionHook,
    build_query_history_section,
)
from easyq2sql.core.llm import LlmRequest, LlmResponse
from easyq2sql.core.storage import Conversation, Message
from easyq2sql.core.user import User


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user() -> User:
    """Create a test user."""
    return User(id="test-user", group_memberships=["admin", "user"])


@pytest.fixture
def mock_llm_service() -> MagicMock:
    """Create a mock LLM service that returns a canned compression result."""
    mock = MagicMock()

    async def _send_request(request: LlmRequest) -> LlmResponse:
        mock.last_request = request
        return LlmResponse(
            content=(
                "question：test query；tables：table_a、table_b；"
                "metrics：risk_level(table_a.risk_level)"
                "[risk_distribution(table_a.risk_level)]；"
                "conclusion：Found 3 alerts for the user；"
                "sql_file：results_abc123.sql；"
                "data_file：results_abc123.csv"
            )
        )

    mock.send_request = _send_request
    mock.stream_request = MagicMock()
    mock.validate_tools = MagicMock(return_value=[])
    return mock


@pytest.fixture
def mock_conversation_store() -> MagicMock:
    """Create a mock conversation store."""
    store = MagicMock()
    store.update_conversation = MagicMock()
    return store


@pytest.fixture
def compression_hook(
    mock_llm_service: MagicMock, mock_conversation_store: MagicMock
) -> ConversationCompressionHook:
    """Create a ConversationCompressionHook with mock dependencies."""
    return ConversationCompressionHook(
        llm_service=mock_llm_service,
        conversation_store=mock_conversation_store,
        enabled=True,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_conversation(
    user: User, messages: Optional[list[Message]] = None
) -> Conversation:
    """Create a Conversation with the given messages."""
    conv = Conversation(id="conv-test-001", user=user, messages=[])
    if messages:
        for msg in messages:
            conv.add_message(msg)
    return conv


# ---------------------------------------------------------------------------
# Tests: build_query_history_section (standalone function)
# ---------------------------------------------------------------------------


class TestBuildQueryHistorySection:
    def test_returns_empty_for_empty_list(self):
        assert build_query_history_section([]) == ""

    def test_builds_single_entry(self):
        entries = [
            "question：test；tables：t1；conclusion：done；"
            "sql_file：；data_file：",
        ]
        section = build_query_history_section(entries)
        assert "── Query History（1 total）──" in section
        assert "[1] question：test；tables：t1；" in section

    def test_builds_multiple_entries(self):
        entries = [
            "question：q1；tables：a；conclusion：c1；sql_file：；data_file：",
            "question：q2；tables：b；conclusion：c2；sql_file：；data_file：",
        ]
        section = build_query_history_section(entries)
        assert "── Query History（2 total）──" in section
        assert "[1] question：q1；" in section
        assert "[2] question：q2；" in section

    def test_entries_are_numbered_sequentially(self):
        entries = ["entry_a", "entry_b", "entry_c"]
        section = build_query_history_section(entries)
        lines = section.split("\n")
        assert lines[0] == "── Query History（3 total）──"
        assert lines[1] == "[1] entry_a"
        assert lines[2] == "[2] entry_b"
        assert lines[3] == "[3] entry_c"


# ---------------------------------------------------------------------------
# Tests: _find_last_user_message_index
# ---------------------------------------------------------------------------


class TestFindLastUserMessageIndex:
    def test_returns_index_of_last_user_message(self, compression_hook):
        messages = [
            Message(role="user", content="question 1"),
            Message(role="assistant", content="answer 1"),
            Message(role="user", content="question 2"),
            Message(role="assistant", content="answer 2"),
        ]
        idx = compression_hook._find_last_user_message_index(messages)
        assert idx == 2

    def test_returns_none_when_no_user_message(self, compression_hook):
        messages = [
            Message(role="system", content="system msg"),
            Message(role="assistant", content="answer"),
        ]
        idx = compression_hook._find_last_user_message_index(messages)
        assert idx is None

    def test_returns_only_user_message(self, compression_hook):
        messages = [
            Message(role="user", content="only question"),
        ]
        idx = compression_hook._find_last_user_message_index(messages)
        assert idx == 0

    def test_empty_list_returns_none(self, compression_hook):
        idx = compression_hook._find_last_user_message_index([])
        assert idx is None


# ---------------------------------------------------------------------------
# Tests: _has_unprocessed_round
# ---------------------------------------------------------------------------


class TestHasUnprocessedRound:
    def test_true_when_tool_messages_after_user(self, compression_hook):
        messages = [
            Message(role="user", content="question"),
            Message(role="assistant", content="thinking", tool_calls=[]),
            Message(role="tool", content="result", tool_call_id="tc1"),
            Message(role="assistant", content="final answer"),
        ]
        assert compression_hook._has_unprocessed_round(messages, 0) is True

    def test_false_when_only_user_message(self, compression_hook):
        # After compression: only the current user question remains
        messages = [
            Message(role="user", content="current question"),
        ]
        assert compression_hook._has_unprocessed_round(messages, 0) is False

    def test_false_when_user_is_last_message(self, compression_hook):
        messages = [
            Message(role="user", content="just asked, no response yet"),
        ]
        assert compression_hook._has_unprocessed_round(messages, 0) is False

    def test_true_when_assistant_response_after_user(self, compression_hook):
        messages = [
            Message(role="user", content="question"),
            Message(role="assistant", content="direct answer, no tools"),
        ]
        assert compression_hook._has_unprocessed_round(messages, 0) is True


# ---------------------------------------------------------------------------
# Tests: _find_legacy_history_index
# ---------------------------------------------------------------------------


class TestFindLegacyHistoryIndex:
    def test_finds_legacy_history_message(self, compression_hook):
        messages = [
            Message(
                role="system",
                content="── Query History（2 total）──\n[1] ...\n[2] ...",
            ),
            Message(role="user", content="current question"),
        ]
        idx = compression_hook._find_legacy_history_index(messages)
        assert idx == 0

    def test_returns_none_when_no_legacy_history(self, compression_hook):
        messages = [
            Message(role="user", content="question"),
            Message(role="assistant", content="answer"),
        ]
        idx = compression_hook._find_legacy_history_index(messages)
        assert idx is None

    def test_skips_non_system_messages(self, compression_hook):
        messages = [
            Message(
                role="user",
                content="── Query History（1 total）──",  # wrong role
            ),
        ]
        idx = compression_hook._find_legacy_history_index(messages)
        assert idx is None


# ---------------------------------------------------------------------------
# Tests: _build_compression_prompt
# ---------------------------------------------------------------------------


class TestBuildCompressionPrompt:
    def test_formats_user_and_assistant_messages(self, compression_hook):
        messages = [
            Message(role="user", content="What is the risk level?"),
            Message(role="assistant", content="The risk level is high."),
        ]
        prompt = compression_hook._build_compression_prompt(messages)
        assert "[User Question]: What is the risk level?" in prompt
        assert "[Assistant Final Answer]: The risk level is high." in prompt
        assert "[HistoryTask]" not in prompt
        assert "question：{user question}" in prompt

    def test_formats_tool_call_messages(self, compression_hook):
        from easyq2sql.core.tool import ToolCall

        messages = [
            Message(role="user", content="Run query"),
            Message(
                role="assistant",
                content="Running SQL...",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        name="run_sql",
                        arguments={"sql": "SELECT * FROM users"},
                    )
                ],
            ),
            Message(
                role="tool",
                content="Query returned 5 rows",
                tool_call_id="tc1",
            ),
            Message(role="assistant", content="Found 5 users."),
        ]
        prompt = compression_hook._build_compression_prompt(messages)
        assert "calling tools: run_sql" in prompt
        assert "[Tool Result (id=tc1)]" in prompt
        assert "Query returned 5 rows" in prompt
        assert "[Assistant Final Answer]: Found 5 users." in prompt

    def test_truncates_long_tool_results(self, compression_hook):
        long_content = "x" * (MAX_TOOL_RESULT_LENGTH + 500)
        messages = [
            Message(role="user", content="query"),
            Message(
                role="tool",
                content=long_content,
                tool_call_id="tc1",
            ),
        ]
        prompt = compression_hook._build_compression_prompt(messages)
        assert "[truncated" in prompt
        assert str(len(long_content)) in prompt

    def test_truncates_long_overall_conversation(self, compression_hook):
        messages = [
            Message(role="user", content="x" * 3000),
            Message(role="assistant", content="y" * 3000),
            Message(role="user", content="z" * 3000),
        ]
        prompt = compression_hook._build_compression_prompt(messages)
        assert len(prompt) <= MAX_CONVERSATION_LENGTH + 2000


# ---------------------------------------------------------------------------
# Tests: _compress_round
# ---------------------------------------------------------------------------


class TestCompressRound:
    @pytest.mark.asyncio
    async def test_returns_compressed_text(
        self, compression_hook, test_user
    ):
        prompt = "Compress this: user asked about risk"
        result = await compression_hook._compress_round(prompt, test_user)
        assert result is not None
        assert result.startswith("question：")

    @pytest.mark.asyncio
    async def test_sends_correct_llm_request(
        self, compression_hook, mock_llm_service, test_user
    ):
        prompt = "Compress this"
        await compression_hook._compress_round(prompt, test_user)

        last_req = mock_llm_service.last_request
        assert last_req is not None
        assert len(last_req.messages) == 1
        assert last_req.messages[0].role == "user"
        assert last_req.messages[0].content == prompt
        assert last_req.temperature == 0.3
        assert last_req.stream is False
        assert last_req.user == test_user


# ---------------------------------------------------------------------------
# Tests: after_message (full flow)
# ---------------------------------------------------------------------------


class TestAfterMessage:
    @pytest.mark.asyncio
    async def test_compresses_single_round(
        self, compression_hook, mock_conversation_store, test_user
    ):
        """First round: stores in metadata, keeps only current user question."""
        conv = make_conversation(
            test_user,
            messages=[
                Message(role="user", content="What is the risk level?"),
                Message(
                    role="assistant",
                    content="Let me check...",
                    tool_calls=[],
                ),
                Message(
                    role="tool",
                    content="risk_level: high",
                    tool_call_id="tc1",
                ),
                Message(
                    role="assistant", content="The risk level is high."
                ),
            ],
        )

        await compression_hook.after_message(conv)

        # All messages cleared — round is compressed into metadata.
        # The Agent injects Query History into the system prompt.
        assert len(conv.messages) == 0

        # Metadata stores raw entries; system prompt injection by agent.py
        assert "compressed_history" in conv.metadata
        assert len(conv.metadata["compressed_history"]) == 1
        assert conv.metadata["compressed_history"][0].startswith("question：")

        # Conversation store re-persisted
        mock_conversation_store.update_conversation.assert_called_once_with(
            conv
        )

    @pytest.mark.asyncio
    async def test_skips_when_already_compressed(
        self, compression_hook, mock_conversation_store, test_user
    ):
        """Empty or user-only messages (no assistant/tool) → skip."""
        conv = make_conversation(
            test_user,
            messages=[
                Message(
                    role="user", content="What is the risk level?"
                ),
            ],
        )
        await compression_hook.after_message(conv)

        # User-only with no assistant/tool response → not a completed round
        assert len(conv.messages) == 1
        mock_conversation_store.update_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_empty_conversation(
        self, compression_hook, mock_conversation_store, test_user
    ):
        conv = make_conversation(test_user, messages=[])
        await compression_hook.after_message(conv)
        assert len(conv.messages) == 0
        mock_conversation_store.update_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_user_message(
        self, compression_hook, mock_conversation_store, test_user
    ):
        conv = make_conversation(
            test_user,
            messages=[Message(role="system", content="system only")],
        )
        await compression_hook.after_message(conv)
        assert len(conv.messages) == 1
        mock_conversation_store.update_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_only_user_question_no_response(
        self, compression_hook, mock_conversation_store, test_user
    ):
        conv = make_conversation(
            test_user,
            messages=[Message(role="user", content="pending question")],
        )
        await compression_hook.after_message(conv)
        assert len(conv.messages) == 1
        mock_conversation_store.update_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_disabled(
        self, mock_llm_service, mock_conversation_store, test_user
    ):
        hook = ConversationCompressionHook(
            llm_service=mock_llm_service,
            conversation_store=mock_conversation_store,
            enabled=False,
        )
        conv = make_conversation(
            test_user,
            messages=[
                Message(role="user", content="question"),
                Message(role="assistant", content="answer"),
            ],
        )
        await hook.after_message(conv)
        assert len(conv.messages) == 2
        mock_conversation_store.update_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_compresses_multi_round_correctly(
        self, compression_hook, mock_conversation_store, test_user
    ):
        """After each round: 0 messages, metadata accumulates."""
        conv = make_conversation(test_user, messages=[])

        # Round 1
        conv.add_message(Message(role="user", content="question 1"))
        conv.add_message(Message(role="assistant", content="answer 1"))
        await compression_hook.after_message(conv)
        assert len(conv.messages) == 0  # all cleared
        assert len(conv.metadata["compressed_history"]) == 1

        # Round 2
        conv.add_message(Message(role="user", content="question 2"))
        conv.add_message(Message(role="assistant", content="answer 2"))
        await compression_hook.after_message(conv)
        assert len(conv.messages) == 0
        assert len(conv.metadata["compressed_history"]) == 2

        # Round 3
        conv.add_message(Message(role="user", content="question 3"))
        conv.add_message(Message(role="assistant", content="answer 3"))
        await compression_hook.after_message(conv)
        assert len(conv.messages) == 0
        assert len(conv.metadata["compressed_history"]) == 3

        # Verify entries are stored correctly
        for entry in conv.metadata["compressed_history"]:
            assert entry.startswith("question：")

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_crash(
        self, mock_conversation_store, test_user
    ):
        """If the LLM call fails, the hook should log a warning and skip."""
        failing_llm = MagicMock()
        failing_llm.send_request = MagicMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        failing_llm.stream_request = MagicMock()
        failing_llm.validate_tools = MagicMock(return_value=[])

        hook = ConversationCompressionHook(
            llm_service=failing_llm,
            conversation_store=mock_conversation_store,
            enabled=True,
        )
        conv = make_conversation(
            test_user,
            messages=[
                Message(role="user", content="question"),
                Message(role="assistant", content="answer"),
            ],
        )
        await hook.after_message(conv)

        # Messages should remain unchanged
        assert len(conv.messages) == 2
        mock_conversation_store.update_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_metadata_entries_are_sequential(
        self, compression_hook, test_user
    ):
        """Metadata entries accumulate in order across rounds."""
        conv = make_conversation(test_user, messages=[])

        for i in range(1, 4):
            conv.add_message(
                Message(role="user", content=f"question {i}")
            )
            conv.add_message(
                Message(role="assistant", content=f"answer {i}")
            )
            await compression_hook.after_message(conv)

        assert len(conv.metadata["compressed_history"]) == 3
        assert len(conv.messages) == 0  # all cleared

        # Verify build_query_history_section produces correct output
        section = build_query_history_section(
            conv.metadata["compressed_history"]
        )
        assert "── Query History（3 total）──" in section
        assert "[1] question：test query；" in section
        assert "[2] question：test query；" in section
        assert "[3] question：test query；" in section

    @pytest.mark.asyncio
    async def test_removes_legacy_history_system_message(
        self, compression_hook, test_user
    ):
        """Legacy Query History system message is removed during compression."""
        conv = make_conversation(
            test_user,
            messages=[
                Message(
                    role="system",
                    content="── Query History（1 total）──\n[1] old entry",
                ),
                Message(role="user", content="legacy question"),
                Message(role="user", content="new question"),
                Message(role="assistant", content="new answer"),
            ],
        )
        await compression_hook.after_message(conv)

        # Legacy system message and all user questions removed
        assert len(conv.messages) == 0
