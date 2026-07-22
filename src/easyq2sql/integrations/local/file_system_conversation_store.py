"""
File system conversation store implementation.

This module provides a file-based implementation of the ConversationStore
interface that persists conversations to disk as a single JSON file per conversation.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from easyq2sql.core.storage import ConversationStore, Conversation, Message
from easyq2sql.core.user import User


class FileSystemConversationStore(ConversationStore):
    """File system-based conversation store.

    Stores each conversation as a single JSON file:
    conversations/{conversation_id}.json
    """

    def __init__(self, base_dir: str = "conversations") -> None:
        """Initialize the file system conversation store.

        Args:
            base_dir: Base directory for storing conversations
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, conversation_id: str) -> Path:
        """Get the file path for a conversation."""
        return self.base_dir / f"{conversation_id}.json"

    def _save_conversation(self, conversation: Conversation) -> None:
        """Save entire conversation to a single JSON file."""
        file_path = self._get_file_path(conversation.id)

        data = {
            "id": conversation.id,
            "user": conversation.user.model_dump(mode="json"),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "messages": [msg.model_dump(mode="json") for msg in conversation.messages],
            "metadata": conversation.metadata,
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_conversation(self, conversation_id: str) -> Optional[dict]:
        """Load conversation data from JSON file."""
        file_path = self._get_file_path(conversation_id)

        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Failed to load conversation {conversation_id}: {e}")
            return None

    async def create_conversation(
        self, conversation_id: str, user: User, initial_message: str
    ) -> Conversation:
        """Create a new conversation with the specified ID."""
        conversation = Conversation(
            id=conversation_id,
            user=user,
            messages=[Message(role="user", content=initial_message)],
        )
        self._save_conversation(conversation)
        return conversation

    async def get_conversation(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        """Get conversation by ID, scoped to user."""
        data = self._load_conversation(conversation_id)
        if data is None:
            return None

        # Verify ownership
        if data["user"]["id"] != user.id:
            return None

        messages = [Message.model_validate(msg) for msg in data["messages"]]

        return Conversation(
            id=data["id"],
            user=User.model_validate(data["user"]),
            messages=messages,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )

    async def update_conversation(self, conversation: Conversation) -> None:
        """Update conversation with new messages (rewrites single file)."""
        conversation.updated_at = datetime.now()
        self._save_conversation(conversation)

    async def delete_conversation(self, conversation_id: str, user: User) -> bool:
        """Delete conversation."""
        file_path = self._get_file_path(conversation_id)

        if not file_path.exists():
            return False

        # Verify ownership before deleting
        conversation = await self.get_conversation(conversation_id, user)
        if not conversation:
            return False

        try:
            file_path.unlink()
            return True
        except OSError as e:
            print(f"Failed to delete conversation {conversation_id}: {e}")
            return False

    async def list_conversations(
        self, user: User, limit: int = 50, offset: int = 0
    ) -> List[Conversation]:
        """List conversations for user."""
        if not self.base_dir.exists():
            return []

        conversations = []

        for file_path in sorted(
            self.base_dir.glob("*.json"), reverse=True
        ):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                continue

            # Skip conversations not owned by this user
            if data.get("user", {}).get("id") != user.id:
                continue

            messages = [Message.model_validate(msg) for msg in data.get("messages", [])]

            conversation = Conversation(
                id=data["id"],
                user=User.model_validate(data["user"]),
                messages=messages,
                created_at=datetime.fromisoformat(data["created_at"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
                metadata=data.get("metadata", {}),
            )
            conversations.append(conversation)

        # Apply pagination
        return conversations[offset : offset + limit]
