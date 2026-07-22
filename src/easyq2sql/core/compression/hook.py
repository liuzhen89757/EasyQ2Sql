"""
Conversation compression hook.

Provides a LifecycleHook that compresses each conversation round into a
structured summary format, reducing context window growth over long
conversations. Compressed rounds are stored in conversation metadata and
injected into the system prompt by the Agent as a "Query History" section,
separate from the Messages list.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from easyq2sql.core.lifecycle import LifecycleHook
from easyq2sql.core.storage import Message

if TYPE_CHECKING:
    from easyq2sql.core.llm import LlmService
    from easyq2sql.core.storage import Conversation, ConversationStore
    from easyq2sql.core.user.models import User

logger = logging.getLogger(__name__)

# Maximum characters to include from a single tool result in the compression prompt.
# Long results (e.g., DataFrames) are truncated to keep the prompt manageable.
MAX_TOOL_RESULT_LENGTH = 2000

# Maximum total characters for the formatted conversation in the compression prompt.
MAX_CONVERSATION_LENGTH = 8000

COMPRESSION_PROMPT_TEMPLATE = """You are a conversation compression assistant. Compress the following conversation round into a single structured history record.

Output format (follow strictly, do not include anything else):
question：{{user question}}；tables：{{table names, comma-separated}}；metrics：{{metric_name(field)[dimension_name(dimension_field)], comma-separated}}；conclusion：{{one-sentence summary of findings}}；sql_file：{{SQL file name or empty}}；data_file：{{data file name or empty}}

Notes:
- metrics format: metric_name(source_field)[dimension_name(dimension_field)], e.g.: risk_level(cust_identity_info.risk_level)[risk_distribution(cust_identity_info.risk_level)]
- Leave field empty if no clear information is available

Conversation:
{conversation_text}

Output the compressed record:"""


def build_query_history_section(entries: list[str]) -> str:
    """Build the Query History section string from raw compressed entries.

    This is used by the Agent when building the LLM request to inject
    conversation history as a separate section in the system prompt.

    Args:
        entries: List of raw compressed strings (without index prefix).

    Returns:
        Formatted section string with header and numbered entries,
        or empty string if entries is empty.
    """
    if not entries:
        return ""

    total = len(entries)
    header = f"── Query History（{total} total）──"
    lines = [header]
    for i, entry in enumerate(entries, 1):
        lines.append(f"[{i}] {entry}")
    return "\n".join(lines)


class ConversationCompressionHook(LifecycleHook):
    """Compresses each conversation round into a structured summary.

    After each round of conversation (user question -> LLM with tool calls ->
    final answer), this hook calls an LLM to generate a structured summary.
    Compressed entries are stored in ``conversation.metadata["compressed_history"]``.
    The Agent reads this metadata in ``_build_llm_request`` and injects it as a
    "Query History" section in the system prompt — separate from Messages.

    Only the current round's user question remains in Messages; all historical
    user questions and tool messages are removed.

    Args:
        llm_service: LLM service used to generate the compression summary.
        conversation_store: Conversation store used to re-persist after
            modifying messages (required because after_message fires after
            the initial save).
        enabled: Whether compression is active. Defaults to True.

    Example:
        >>> hook = ConversationCompressionHook(llm_service, conversation_store)
        >>> agent = Agent(..., lifecycle_hooks=[hook])
    """

    def __init__(
        self,
        llm_service: "LlmService",
        conversation_store: "ConversationStore",
        enabled: bool = True,
    ) -> None:
        self.llm_service = llm_service
        self.conversation_store = conversation_store
        self.enabled = enabled

    # ------------------------------------------------------------------
    # LifecycleHook interface
    # ------------------------------------------------------------------

    async def after_message(self, result: "Conversation") -> None:
        """Compress the latest conversation round and clean up messages.

        Called by the Agent after a full message round completes. Identifies
        the latest round boundary, compresses it via LLM, stores the result
        in conversation metadata, and removes all historical messages —
        keeping only the current user question.

        Args:
            result: The conversation object with all messages (passed
                positionally by the Agent as the Conversation instance).
        """
        if not self.enabled:
            return

        conversation = result
        messages = conversation.messages
        if not messages:
            return

        # Find the start of the latest round (last user message)
        last_user_idx = self._find_last_user_message_index(messages)
        if last_user_idx is None:
            return

        # Check if there are unprocessed assistant/tool messages after the
        # last user message. If not, this round was already compressed.
        if not self._has_unprocessed_round(messages, last_user_idx):
            return

        # Extract round messages and build compression prompt
        round_messages = messages[last_user_idx:]
        prompt = self._build_compression_prompt(round_messages)

        # Call LLM to compress
        try:
            compressed = await self._compress_round(
                prompt, conversation.user
            )
        except Exception as e:
            logger.warning(
                f"Compression LLM call failed for conversation "
                f"{conversation.id}: {e}"
            )
            return

        if not compressed or not compressed.strip():
            logger.warning(
                f"Compression returned empty result for conversation "
                f"{conversation.id}"
            )
            return

        # Store raw entry in metadata (Agent reads this for system prompt)
        compressed_history: list = conversation.metadata.setdefault(
            "compressed_history", []
        )
        compressed_history.append(compressed)

        # Remove any legacy Query History system message (from older hook versions)
        legacy_history_idx = self._find_legacy_history_index(messages)
        if legacy_history_idx is not None:
            del messages[legacy_history_idx]

        # Save round messages to metadata for UI history display before clearing
        saved_messages = []
        for msg in round_messages:
            saved_messages.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "tool_calls": (
                    [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                     for tc in msg.tool_calls]
                    if msg.tool_calls else None
                ),
                "tool_call_id": msg.tool_call_id,
            })
        conversation.metadata.setdefault("message_history", [])
        conversation.metadata["message_history"].extend(saved_messages)

        # Clear messages — LLM context uses compressed_history from metadata.
        # Full history is preserved in metadata.message_history for UI display.
        conversation.messages = []

        # Re-persist since the initial save already happened before this hook
        try:
            await self.conversation_store.update_conversation(conversation)
        except Exception as e:
            logger.error(
                f"Failed to re-save conversation {conversation.id} "
                f"after compression: {e}"
            )

        logger.info(
            f"Compressed round for conversation {conversation.id}: "
            f"{len(round_messages)} messages -> Query History entry "
            f"[{len(compressed_history)}]"
        )

    # ------------------------------------------------------------------
    # Private helpers — message structure
    # ------------------------------------------------------------------

    @staticmethod
    def _find_last_user_message_index(
        messages: list["Message"],
    ) -> Optional[int]:
        """Find the index of the last user message in the list.

        Returns None if no user message exists.
        """
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user":
                return i
        return None

    @staticmethod
    def _has_unprocessed_round(
        messages: list["Message"], last_user_idx: int
    ) -> bool:
        """Check if there are assistant/tool messages after the last user message.

        Returns True if there are unprocessed messages that need compression.
        """
        return any(
            msg.role in ("assistant", "tool")
            for msg in messages[last_user_idx + 1:]
        )

    @staticmethod
    def _find_legacy_history_index(
        messages: list["Message"],
    ) -> Optional[int]:
        """Find and return the index of a legacy Query History system message.

        Older versions of this hook stored the history section as a system
        message. This method finds it so it can be removed during migration.
        """
        marker = "── Query History（"
        for i, msg in enumerate(messages):
            if (
                msg.role == "system"
                and msg.content
                and msg.content.startswith(marker)
            ):
                return i
        return None

    # ------------------------------------------------------------------
    # Private helpers — compression
    # ------------------------------------------------------------------

    @staticmethod
    def _build_compression_prompt(messages: list["Message"]) -> str:
        """Build the compression prompt from a list of round messages.

        Formats each message with its role and content, truncating long
        tool results to keep the prompt manageable.
        """
        parts: list[str] = []

        for msg in messages:
            if msg.role == "user":
                parts.append(f"[User Question]: {msg.content}")
            elif msg.role == "assistant":
                if msg.tool_calls:
                    tool_names = ", ".join(
                        tc.name for tc in msg.tool_calls
                    )
                    parts.append(
                        f"[Assistant (calling tools: {tool_names})]: "
                        f"{msg.content or ''}"
                    )
                else:
                    parts.append(
                        f"[Assistant Final Answer]: {msg.content}"
                    )
            elif msg.role == "tool":
                content = msg.content or ""
                if len(content) > MAX_TOOL_RESULT_LENGTH:
                    content = (
                        content[:MAX_TOOL_RESULT_LENGTH]
                        + f"\n... [truncated, original length: {len(msg.content)} chars]"
                    )
                parts.append(
                    f"[Tool Result (id={msg.tool_call_id})]: {content}"
                )
            else:
                # System messages or other roles — include briefly
                content = msg.content or ""
                if len(content) > 500:
                    content = content[:500] + "... [truncated]"
                parts.append(f"[{msg.role}]: {content}")

        conversation_text = "\n\n".join(parts)

        # Truncate if overall conversation is too long
        if len(conversation_text) > MAX_CONVERSATION_LENGTH:
            conversation_text = (
                conversation_text[:MAX_CONVERSATION_LENGTH]
                + f"\n\n... [truncated, total length: {len(conversation_text)} chars]"
            )

        return COMPRESSION_PROMPT_TEMPLATE.format(
            conversation_text=conversation_text,
        )

    async def _compress_round(
        self, prompt: str, user: "User"
    ) -> Optional[str]:
        """Call the LLM to compress a conversation round.

        Args:
            prompt: The compression prompt with formatted conversation.
            user: The user object for the LLM request context.

        Returns:
            The compressed summary string, or None if the call failed.
        """
        from easyq2sql.core.llm import LlmMessage, LlmRequest

        request = LlmRequest(
            messages=[LlmMessage(role="user", content=prompt)],
            user=user,
            temperature=0.3,
            stream=False,
        )

        response = await self.llm_service.send_request(request)

        if response.content:
            return response.content.strip()

        return None
