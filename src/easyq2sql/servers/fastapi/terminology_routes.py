"""
FastAPI route implementations for Terminology Mapping Management.

Registers REST API endpoints for creating, reading, updating, and
deleting terminology mappings. Also provides a /sync endpoint for
auto-generating entries from metrics and dimensions.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.terminology_store import TerminologyStore


class CreateTerminologyRequest(BaseModel):
    """Request body for creating a new terminology mapping."""

    term_text: str = Field(description="Business term, e.g. 'OEE', 'Last Month'")
    target_type: str = Field(description="Mapping target: 'metric' or 'dimension'")
    target_id: str = Field(description="FK to Metric.id or Dimension.id")
    business_definition: Optional[str] = Field(
        default=None, description="Business definition"
    )
    synonyms: List[str] = Field(
        default_factory=list, description="Synonym list for broader matching"
    )


class UpdateTerminologyRequest(CreateTerminologyRequest):
    """Request body for updating an existing terminology mapping."""
    pass


def _get_context(agent):
    from ...core.tool import ToolContext
    from ...core.user.models import User

    user = User(id="api_admin", group_memberships=["admin"])
    return ToolContext(
        user=user,
        conversation_id="terminology_api",
        request_id="terminology_api",
        agent_memory=agent.agent_memory,
    )


def _require_store(terminology_store):
    if terminology_store is None:
        raise HTTPException(
            status_code=503,
            detail="TerminologyStore is not configured.",
        )


def register_terminology_routes(
    app: FastAPI,
    agent,
    terminology_store: Optional[TerminologyStore],
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register terminology mapping routes on the FastAPI app."""

    @app.get("/api/easyq2sql/v1/terminology")
    async def list_terminology(source: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all terminology entries, optionally filtered by source."""
        _require_store(terminology_store)
        context = _get_context(agent)
        entries = await terminology_store.list_entries(context, source=source)
        return [e.model_dump(mode="json") for e in entries]

    @app.post("/api/easyq2sql/v1/terminology")
    async def create_terminology(body: CreateTerminologyRequest) -> Dict[str, Any]:
        """Create a new terminology mapping."""
        _require_store(terminology_store)
        from ...capabilities.terminology_store.models import TerminologyEntry

        context = _get_context(agent)

        entry = TerminologyEntry(
            term_text=body.term_text,
            target_type=body.target_type,
            target_id=body.target_id,
            business_definition=body.business_definition,
            synonyms=body.synonyms,
            source="manual",
        )

        result = await terminology_store.create_entry(entry, context)
        return result.model_dump(mode="json")

    @app.get("/api/easyq2sql/v1/terminology/{entry_id}")
    async def get_terminology(entry_id: str) -> Dict[str, Any]:
        """Get a single terminology entry."""
        _require_store(terminology_store)
        context = _get_context(agent)
        entry = await terminology_store.get_entry(entry_id, context)
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"Terminology entry '{entry_id}' not found"
            )
        return entry.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/terminology/{entry_id}")
    async def update_terminology(
        entry_id: str, body: UpdateTerminologyRequest
    ) -> Dict[str, Any]:
        """Update an existing terminology entry (marks as manual)."""
        _require_store(terminology_store)
        from ...capabilities.terminology_store.models import TerminologyEntry

        context = _get_context(agent)

        existing = await terminology_store.get_entry(entry_id, context)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"Terminology entry '{entry_id}' not found"
            )

        entry = TerminologyEntry(
            id=entry_id,
            term_text=body.term_text,
            target_type=body.target_type,
            target_id=body.target_id,
            business_definition=body.business_definition,
            synonyms=body.synonyms,
            source="manual",
            created_at=existing.created_at,
        )

        success = await terminology_store.update_entry(entry, context)
        if not success:
            raise HTTPException(
                status_code=500, detail="Failed to update terminology entry"
            )

        updated = await terminology_store.get_entry(entry_id, context)
        return updated.model_dump(mode="json") if updated else {}

    @app.delete("/api/easyq2sql/v1/terminology/{entry_id}")
    async def delete_terminology(entry_id: str) -> Dict[str, str]:
        """Delete a terminology entry."""
        _require_store(terminology_store)
        context = _get_context(agent)
        success = await terminology_store.delete_entry(entry_id, context)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Terminology entry '{entry_id}' not found"
            )
        return {"status": "ok", "entry_id": entry_id}

    @app.post("/api/easyq2sql/v1/terminology/sync")
    async def sync_terminology() -> Dict[str, Any]:
        """Regenerate auto terminology entries from metrics and dimensions."""
        _require_store(terminology_store)
        context = _get_context(agent)
        count = await terminology_store.sync_auto_terms(context)
        return {"status": "ok", "auto_entries_synced": count}
