"""
Default system prompt builder implementation with memory workflow support.

This module provides a default implementation of the SystemPromptBuilder interface
that automatically includes memory workflow instructions when memory tools are available.
"""

from typing import TYPE_CHECKING, List, Optional
from datetime import datetime

from .base import SystemPromptBuilder

if TYPE_CHECKING:
    from ..tool.models import ToolSchema
    from ..user.models import User


class DefaultSystemPromptBuilder(SystemPromptBuilder):
    """Default system prompt builder with automatic memory workflow integration.

    Dynamically generates system prompts that include memory workflow
    instructions when memory tools (search_saved_correct_tool_uses and
    save_question_tool_args) are available.
    """

    def __init__(self, base_prompt: Optional[str] = None):
        """Initialize with an optional base prompt.

        Args:
            base_prompt: Optional base system prompt. If not provided, uses a default.
        """
        self.base_prompt = base_prompt

    async def build_system_prompt(
        self, user: "User", tools: List["ToolSchema"]
    ) -> Optional[str]:
        """
        Build a system prompt with memory workflow instructions.

        Args:
            user: The user making the request
            tools: List of tools available to the user

        Returns:
            System prompt string with memory workflow instructions if applicable
        """
        if self.base_prompt is not None:
            return self.base_prompt

        # Check which memory tools are available
        tool_names = [tool.name for tool in tools]
        has_search = "search_saved_correct_tool_uses" in tool_names
        has_save = "save_question_tool_args" in tool_names
        has_text_memory = "save_text_memory" in tool_names
        has_search_metrics = "search_metrics" in tool_names
        has_search_schema = "search_table_schema" in tool_names

        # Get today's date
        today_date = datetime.now().strftime("%Y-%m-%d")

        # Base system prompt
        prompt_parts = [
            f"You are EasyQ2Sql, an AI data analyst assistant created to help users with data analysis tasks. Today's date is {today_date}.",
            "",
            "Response Guidelines:",
            "- Any summary of what you did or observations should be the final step.",
            "- Use the available tools to help the user accomplish their goals.",
            "- When you execute a query, that raw result is shown to the user outside of your response so YOU DO NOT need to include it in your response. Focus on summarizing and interpreting the results.",
        ]

        if tools:
            prompt_parts.append(
                f"\nYou have access to the following tools: {', '.join(tool_names)}"
            )

        # Add memory workflow instructions based on available tools
        if has_search or has_save or has_text_memory:
            prompt_parts.append("\n" + "=" * 60)
            prompt_parts.append("MEMORY SYSTEM:")
            prompt_parts.append("=" * 60)

        if has_search or has_save:
            prompt_parts.append("\n1. TOOL USAGE MEMORY (Structured Workflow):")
            prompt_parts.append("-" * 50)

        if has_search:
            prompt_parts.extend(
                [
                    "",
                    "• FIRST: call search_saved_correct_tool_uses with the user's question to check for existing successful patterns for similar questions. Wait for its result before calling any other tools.",
                ]
            )

        if has_search_metrics:
            prompt_parts.extend(
                [
                    "",
                    f"• If search_saved_correct_tool_uses returns no useful pattern, then call search_metrics to find relevant metrics for the question.",
                ]
            )

        if has_search_schema:
            prompt_parts.extend(
                [
                    "",
                    f"• If search_metrics returns no useful metric, then call search_table_schema to find relevant table schemas as a fallback.",
                ]
            )

        if has_search or has_search_metrics or has_search_schema:
            prompt_parts.extend(
                [
                    "",
                    "• Review the search results (if any) to inform your approach before proceeding with other tool calls.",
                ]
            )

        if has_save:
            prompt_parts.extend(
                [
                    "",
                    "• AFTER successfully executing tools and producing a final answer: only call save_question_tool_args if the result was NOT already found by your earlier search_saved_correct_tool_uses call. If the search already returned a matching pattern, skip the save — it's already stored.",
                ]
            )

        if has_search or has_save:
            prompt_parts.extend(
                [
                    "",
                    "Example workflow:",
                    "  • User asks a question",
                    f'  • First: Call search_saved_correct_tool_uses(question="user\'s question")'
                    if has_search
                    else "",
                    f'  • If no useful pattern: Call search_metrics to find relevant metrics'
                    if has_search_metrics
                    else "",
                    f'  • If search_metrics returns no useful metric: Call search_table_schema as fallback'
                    if has_search_schema
                    else "",
                    "  • Then: Execute the appropriate tool(s) based on search results and the question",
                    f'  • Finally: Only if no matching pattern was found by the earlier search, call save_question_tool_args(question="user\'s question", tool_name="tool_used", args={{the args you used}})'
                    if has_save
                    else "",
                    "",
                    "Do NOT skip the search step."
                    if has_search
                    else "",
                    "",
                    "The only exceptions to searching first are:",
                    '  • When the user is explicitly asking about the tools themselves (like "list the tools")',
                    "  • When the user is testing or asking you to demonstrate the save/search functionality itself",
                    "  • When a relevant SQL from the current conversation history already answers the question",
                ]
            )

        if has_text_memory:
            prompt_parts.extend(
                [
                    "",
                    "2. TEXT MEMORY (Domain Knowledge, Feedback & Context):",
                    "-" * 50,
                    "",
                    "• save_text_memory: Save important context that should persist across conversations",
                    "",
                    "Use text memory to save:",
                    "  • **User feedback and error corrections**: When the user corrects your answer, points out wrong results, or clarifies data meaning — save immediately. ",
                    "  • **Data clarifications**: When the user explains what certain column values actually mean",
                    "  • Database schema details (column meanings, data types, relationships)",
                    "  • Company-specific terminology and definitions",
                    "  • Query patterns or best practices for this database",
                    "  • Domain knowledge about the business or data",
                    "  • User preferences for queries or visualizations",
                    "",
                    "**IMPORTANT**: When the user says something like 'that's wrong', 'this is incorrect', 'actually it should be...', or provides any correction — you MUST call save_text_memory to record the correction so you don't make the same mistake again.",
                    "",
                    "DO NOT save:",
                    "  • Information already captured in tool usage memory",
                    "  • One-time query results or temporary observations",
                    "",
                    "Examples:",
                    '  • save_text_memory(content="The status column uses 1 for active, 0 for inactive")',
                    '  • save_text_memory(content="MRR means Monthly Recurring Revenue in our schema")',
                    "  • save_text_memory(content=\"Always exclude test accounts where email contains 'test'\")",
                    '  • save_text_memory(content="User feedback: the query for 风险等级分布 was wrong because it missed the cust_identity_info join. Correct approach: JOIN risk_alert with cust_identity_info on cust_id to get customer-level risk distribution.\")',
                ]
            )

        if has_search or has_save or has_text_memory:
            # Remove empty strings from the list
            prompt_parts = [part for part in prompt_parts if part != ""]

        return "\n".join(prompt_parts)
