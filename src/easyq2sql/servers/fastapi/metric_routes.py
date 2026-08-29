"""
FastAPI route implementations for Atomic Metric Management.

Registers REST API endpoints for creating, reading, updating, and
deleting atomic metric definitions.

Routes are always registered. When ``atomic_metric_store`` is ``None``
(not configured), endpoints return 503 with a clear message.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.atomic_metric import (
    AtomicMetricStore,
)


class CreateAtomicMetricRequest(BaseModel):
    """Request body for creating a new atomic metric."""

    name: str = Field(description="Atomic metric name (user-defined label)")
    business_definition: Optional[str] = Field(
        default=None, description="Business meaning of this atomic metric"
    )
    calculation_logic: Optional[str] = Field(
        default=None, description="Aggregate function, e.g. COUNT, SUM, AVG"
    )
    data_source: str = Field(description="Source fact table name")
    analysis_field: str = Field(description="table.column being measured")
    description: Optional[str] = Field(default=None, description="Optional notes")


class UpdateAtomicMetricRequest(CreateAtomicMetricRequest):
    """Request body for updating an existing atomic metric."""
    pass


def _get_context(agent):
    """Build a minimal ToolContext for REST API operations."""
    from ...core.tool import ToolContext
    from ...core.user.models import User

    user = User(id="api_admin", group_memberships=["admin"])
    return ToolContext(
        user=user,
        conversation_id="metric_api",
        request_id="metric_api",
        agent_memory=agent.agent_memory,
    )


def _require_store(atomic_metric_store):
    """Raise 503 if atomic_metric_store is not configured."""
    if atomic_metric_store is None:
        raise HTTPException(
            status_code=503,
            detail="AtomicMetricStore is not configured. "
                   "Set 'atomic_metric_store' in server config to enable atomic metric management.",
        )


def register_metric_routes(
    app: FastAPI,
    agent,
    atomic_metric_store: Optional[AtomicMetricStore],
    schema_store=None,
    config: Optional[Dict[str, Any]] = None,
    derived_metric_store=None,
) -> None:
    """Register atomic metric management routes on the FastAPI app."""

    @app.get("/api/easyq2sql/v1/atomic-metrics")
    async def list_atomic_metrics() -> List[Dict[str, Any]]:
        """List all defined atomic metrics."""
        _require_store(atomic_metric_store)
        context = _get_context(agent)
        atomic_metrics = await atomic_metric_store.list_atomic_metrics(context)
        return [m.model_dump(mode="json") for m in atomic_metrics]

    @app.post("/api/easyq2sql/v1/atomic-metrics")
    async def create_atomic_metric(body: CreateAtomicMetricRequest) -> Dict[str, Any]:
        """Create a new atomic metric definition."""
        _require_store(atomic_metric_store)
        from ...capabilities.atomic_metric.models import AtomicMetric

        context = _get_context(agent)

        atomic_metric = AtomicMetric(
            name=body.name,
            business_definition=body.business_definition,
            calculation_logic=body.calculation_logic,
            data_source=body.data_source,
            analysis_field=body.analysis_field,
            description=body.description,
        )

        result = await atomic_metric_store.create_atomic_metric(atomic_metric, context)

        return result.model_dump(mode="json")

    @app.get("/api/easyq2sql/v1/atomic-metrics/{atomic_metric_id}")
    async def get_atomic_metric(atomic_metric_id: str) -> Dict[str, Any]:
        """Get a single atomic metric with full detail."""
        _require_store(atomic_metric_store)
        context = _get_context(agent)
        atomic_metric = await atomic_metric_store.get_atomic_metric(
            atomic_metric_id, context
        )
        if atomic_metric is None:
            raise HTTPException(
                status_code=404, detail=f"AtomicMetric '{atomic_metric_id}' not found"
            )
        return atomic_metric.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/atomic-metrics/{atomic_metric_id}")
    async def update_atomic_metric(
        atomic_metric_id: str, body: UpdateAtomicMetricRequest
    ) -> Dict[str, Any]:
        """Update an existing atomic metric definition."""
        _require_store(atomic_metric_store)
        from ...capabilities.atomic_metric.models import AtomicMetric

        context = _get_context(agent)

        existing = await atomic_metric_store.get_atomic_metric(atomic_metric_id, context)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"AtomicMetric '{atomic_metric_id}' not found"
            )

        atomic_metric = AtomicMetric(
            id=atomic_metric_id,
            name=body.name,
            business_definition=body.business_definition,
            calculation_logic=body.calculation_logic,
            data_source=body.data_source,
            analysis_field=body.analysis_field,
            description=body.description,
            created_by=existing.created_by,
            created_at=existing.created_at,
        )

        success = await atomic_metric_store.update_atomic_metric(atomic_metric, context)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update atomic metric")

        updated = await atomic_metric_store.get_atomic_metric(atomic_metric_id, context)
        return updated.model_dump(mode="json") if updated else {}

    @app.delete("/api/easyq2sql/v1/atomic-metrics/{atomic_metric_id}")
    async def delete_atomic_metric(atomic_metric_id: str) -> Dict[str, str]:
        """Delete an atomic metric definition."""
        _require_store(atomic_metric_store)
        context = _get_context(agent)
        success = await atomic_metric_store.delete_atomic_metric(
            atomic_metric_id, context
        )
        if not success:
            raise HTTPException(
                status_code=404, detail=f"AtomicMetric '{atomic_metric_id}' not found"
            )
        return {"status": "ok", "atomic_metric_id": atomic_metric_id}
