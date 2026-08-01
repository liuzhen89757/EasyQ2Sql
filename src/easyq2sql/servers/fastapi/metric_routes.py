"""
FastAPI route implementations for Metric Management.

Registers REST API endpoints for creating, reading, updating, and
deleting business metric definitions.

Routes are always registered. When ``metric_store`` is ``None``
(not configured), endpoints return 503 with a clear message.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.metric_store import (
    MetricStore,
)


class CreateMetricRequest(BaseModel):
    """Request body for creating a new metric."""

    name: str = Field(description="Metric name (user-defined label)")
    business_definition: Optional[str] = Field(
        default=None, description="Business meaning of this metric"
    )
    calculation_logic: Optional[str] = Field(
        default=None, description="Aggregate function, e.g. COUNT, SUM, AVG"
    )
    data_source: str = Field(description="Source fact table name")
    analysis_field: str = Field(description="table.column being measured")
    description: Optional[str] = Field(default=None, description="Optional notes")


class UpdateMetricRequest(CreateMetricRequest):
    """Request body for updating an existing metric."""
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


def _require_store(metric_store):
    """Raise 503 if metric_store is not configured."""
    if metric_store is None:
        raise HTTPException(
            status_code=503,
            detail="MetricStore is not configured. "
                   "Set 'metric_store' in server config to enable metric management.",
        )


def register_metric_routes(
    app: FastAPI,
    agent,
    metric_store: Optional[MetricStore],
    schema_store=None,
    config: Optional[Dict[str, Any]] = None,
    terminology_store=None,
    dimension_store=None,
) -> None:
    """Register metric management routes on the FastAPI app.

    Creates/updates/deletes metrics and auto-generates terminology entries
    via ``terminology_store.sync_auto_terms()`` when available.
    """

    @app.get("/api/easyq2sql/v1/metrics")
    async def list_metrics() -> List[Dict[str, Any]]:
        """List all defined metrics."""
        _require_store(metric_store)
        context = _get_context(agent)
        metrics = await metric_store.list_metrics(context)
        return [m.model_dump(mode="json") for m in metrics]

    @app.post("/api/easyq2sql/v1/metrics")
    async def create_metric(body: CreateMetricRequest) -> Dict[str, Any]:
        """Create a new metric definition."""
        _require_store(metric_store)
        from ...capabilities.metric_store.models import Metric

        context = _get_context(agent)

        metric = Metric(
            name=body.name,
            business_definition=body.business_definition,
            calculation_logic=body.calculation_logic,
            data_source=body.data_source,
            analysis_field=body.analysis_field,
            description=body.description,
        )

        result = await metric_store.create_metric(metric, context)

        # Auto-generate terminology mapping
        if terminology_store:
            try:
                await terminology_store.sync_auto_terms(
                    context, metrics=[result], dimensions=[]
                )
            except Exception:
                pass

        return result.model_dump(mode="json")

    @app.get("/api/easyq2sql/v1/metrics/{metric_id}")
    async def get_metric(metric_id: str) -> Dict[str, Any]:
        """Get a single metric with full detail."""
        _require_store(metric_store)
        context = _get_context(agent)
        metric = await metric_store.get_metric(metric_id, context)
        if metric is None:
            raise HTTPException(
                status_code=404, detail=f"Metric '{metric_id}' not found"
            )
        return metric.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/metrics/{metric_id}")
    async def update_metric(
        metric_id: str, body: UpdateMetricRequest
    ) -> Dict[str, Any]:
        """Update an existing metric definition."""
        _require_store(metric_store)
        from ...capabilities.metric_store.models import Metric

        context = _get_context(agent)

        existing = await metric_store.get_metric(metric_id, context)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"Metric '{metric_id}' not found"
            )

        metric = Metric(
            id=metric_id,
            name=body.name,
            business_definition=body.business_definition,
            calculation_logic=body.calculation_logic,
            data_source=body.data_source,
            analysis_field=body.analysis_field,
            description=body.description,
            created_by=existing.created_by,
            created_at=existing.created_at,
        )

        success = await metric_store.update_metric(metric, context)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update metric")

        # Auto-generate terminology mapping
        if terminology_store:
            try:
                await terminology_store.sync_auto_terms(
                    context, metrics=[metric], dimensions=[]
                )
            except Exception:
                pass

        updated = await metric_store.get_metric(metric_id, context)
        return updated.model_dump(mode="json") if updated else {}

    @app.delete("/api/easyq2sql/v1/metrics/{metric_id}")
    async def delete_metric(metric_id: str) -> Dict[str, str]:
        """Delete a metric definition."""
        _require_store(metric_store)
        context = _get_context(agent)
        success = await metric_store.delete_metric(metric_id, context)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Metric '{metric_id}' not found"
            )
        return {"status": "ok", "metric_id": metric_id}
