"""
FastAPI route implementations for Conversation Management.

Registers REST API endpoints for listing, loading, and deleting
conversations from the ConversationStore.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request

from ...core.agent.agent import Agent
from ...core.user.request_context import RequestContext


async def _get_user(agent: Agent, http_request: Request):
    """Resolve user from HTTP request using the agent's UserResolver."""
    request_context = RequestContext(
        cookies=dict(http_request.cookies),
        headers=dict(http_request.headers),
        remote_addr=http_request.client.host if http_request.client else None,
        query_params=dict(http_request.query_params),
    )
    return await agent.user_resolver.resolve_user(request_context)


def _require_store(conversation_store):
    """Raise 503 if conversation_store is not configured."""
    if conversation_store is None:
        raise HTTPException(
            status_code=503,
            detail="ConversationStore is not configured. "
                   "Pass a conversation_store to the Agent to enable conversation history.",
        )


def register_conversation_routes(
    app: FastAPI,
    agent: Agent,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register conversation management routes on the FastAPI app.

    Args:
        app: FastAPI application instance.
        agent: Vanna Agent instance (for UserResolver and ConversationStore access).
        config: Optional server configuration dict.
    """

    @app.get("/api/easyq2sql/v1/conversations")
    async def list_conversations(
        http_request: Request,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List conversations for the current user.

        Returns a list of conversation summaries (id, title, created_at, updated_at,
        message_count). Does NOT include full message content.
        """
        store = agent.conversation_store
        _require_store(store)

        user = await _get_user(agent, http_request)
        conversations = await store.list_conversations(user, limit=limit, offset=offset)

        return [
            {
                "id": conv.id,
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": len(conv.messages) + len(conv.metadata.get("message_history", [])),
            }
            for conv in conversations
            if any(msg.role == "user" and msg.content.strip() for msg in conv.messages)
            or conv.title
        ]

    @app.get("/api/easyq2sql/v1/conversations/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        http_request: Request,
    ) -> Dict[str, Any]:
        """Get full conversation with all messages.

        Returns the complete conversation including message history.
        """
        store = agent.conversation_store
        _require_store(store)

        user = await _get_user(agent, http_request)
        conversation = await store.get_conversation(conversation_id, user)

        if not conversation:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation '{conversation_id}' not found",
            )

        # Merge stored message_history (past rounds) with current messages
        all_messages = list(conversation.metadata.get("message_history", []))
        for msg in conversation.messages:
            all_messages.append({
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

        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "compressed_history": conversation.metadata.get("compressed_history", []),
            "messages": all_messages,
        }

    @app.delete("/api/easyq2sql/v1/conversations/{conversation_id}")
    async def delete_conversation(
        conversation_id: str,
        http_request: Request,
    ) -> Dict[str, Any]:
        """Delete a conversation.

        Returns success status.
        """
        store = agent.conversation_store
        _require_store(store)

        user = await _get_user(agent, http_request)
        success = await store.delete_conversation(conversation_id, user)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation '{conversation_id}' not found",
            )

        return {"status": "deleted", "conversation_id": conversation_id}
