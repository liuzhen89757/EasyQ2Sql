"""
FastAPI route implementations for Composite Metric Management.

Registers REST API endpoints for creating, reading, updating, and deleting
composite metric definitions (secondary combination metrics built on top of
atomic + derived metric definitions).

Routes are always registered. When ``composite_metric_store`` is ``None``
(not configured), endpoints return 503 with a clear message.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.composite_metric import CompositeMetricStore

#: Composition operators a composite metric may use.
COMB_FUNCS = ("比值", "差值", "环比", "同比")


class CreateCompositeMetricRequest(BaseModel):
    """Request body for creating a new composite metric."""

    name: str = Field(description="Composite metric name, e.g. '客单价'")
    business_definition: Optional[str] = Field(
        default=None, description="Business meaning of this composite metric"
    )
    comb_func: str = Field(description="Composition operator: 比值 / 差值 / 环比 / 同比")
    operand_a: str = Field(description="First derived metric id")
    operand_b: str = Field(description="Second derived metric id")
    description: Optional[str] = Field(default=None, description="Optional notes")


class UpdateCompositeMetricRequest(CreateCompositeMetricRequest):
    """Request body for updating an existing composite metric."""
    pass


def _get_context(agent):
    """Build a minimal ToolContext for REST API operations."""
    from ...core.tool import ToolContext
    from ...core.user.models import User

    user = User(id="api_admin", group_memberships=["admin"])
    return ToolContext(
        user=user,
        conversation_id="composite_api",
        request_id="composite_api",
        agent_memory=agent.agent_memory,
    )


def _require_store(composite_metric_store):
    """Raise 503 if composite_metric_store is not configured."""
    if composite_metric_store is None:
        raise HTTPException(
            status_code=503,
            detail="CompositeMetricStore is not configured. "
                   "Set 'composite_metric_store' in server config to enable composite metrics.",
        )


def _validate_comb_func(comb_func: str) -> None:
    if comb_func not in COMB_FUNCS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid comb_func '{comb_func}'. Expected one of {list(COMB_FUNCS)}.",
        )


def register_composite_routes(
    app: FastAPI,
    agent,
    composite_metric_store: Optional[CompositeMetricStore],
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register composite metric management routes on the FastAPI app."""

    @app.get("/api/easyq2sql/v1/composite-metrics")
    async def list_composite_metrics() -> List[Dict[str, Any]]:
        """List all defined composite metrics."""
        _require_store(composite_metric_store)
        context = _get_context(agent)
        composite_metrics = await composite_metric_store.list_composite_metrics(context)
        return [c.model_dump(mode="json") for c in composite_metrics]

    @app.post("/api/easyq2sql/v1/composite-metrics")
    async def create_composite_metric(
        body: CreateCompositeMetricRequest,
    ) -> Dict[str, Any]:
        """Create a new composite metric definition."""
        _require_store(composite_metric_store)
        _validate_comb_func(body.comb_func)
        from ...capabilities.composite_metric.models import CompositeMetric

        context = _get_context(agent)
        composite_metric = CompositeMetric(
            name=body.name,
            business_definition=body.business_definition,
            comb_func=body.comb_func,
            operand_a=body.operand_a,
            operand_b=body.operand_b,
            description=body.description,
        )
        result = await composite_metric_store.create_composite_metric(
            composite_metric, context
        )
        return result.model_dump(mode="json")

    @app.get("/api/easyq2sql/v1/composite-metrics/{composite_metric_id}")
    async def get_composite_metric(composite_metric_id: str) -> Dict[str, Any]:
        """Get a single composite metric with full detail."""
        _require_store(composite_metric_store)
        context = _get_context(agent)
        composite_metric = await composite_metric_store.get_composite_metric(
            composite_metric_id, context
        )
        if composite_metric is None:
            raise HTTPException(
                status_code=404,
                detail=f"CompositeMetric '{composite_metric_id}' not found",
            )
        return composite_metric.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/composite-metrics/{composite_metric_id}")
    async def update_composite_metric(
        composite_metric_id: str, body: UpdateCompositeMetricRequest
    ) -> Dict[str, Any]:
        """Update an existing composite metric definition."""
        _require_store(composite_metric_store)
        _validate_comb_func(body.comb_func)
        from ...capabilities.composite_metric.models import CompositeMetric

        context = _get_context(agent)
        existing = await composite_metric_store.get_composite_metric(
            composite_metric_id, context
        )
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"CompositeMetric '{composite_metric_id}' not found",
            )

        composite_metric = CompositeMetric(
            id=composite_metric_id,
            name=body.name,
            business_definition=body.business_definition,
            comb_func=body.comb_func,
            operand_a=body.operand_a,
            operand_b=body.operand_b,
            description=body.description,
            created_by=existing.created_by,
            created_at=existing.created_at,
        )
        success = await composite_metric_store.update_composite_metric(
            composite_metric, context
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update composite metric")

        updated = await composite_metric_store.get_composite_metric(
            composite_metric_id, context
        )
        return updated.model_dump(mode="json") if updated else {}

    @app.delete("/api/easyq2sql/v1/composite-metrics/{composite_metric_id}")
    async def delete_composite_metric(composite_metric_id: str) -> Dict[str, str]:
        """Delete a composite metric definition."""
        _require_store(composite_metric_store)
        context = _get_context(agent)
        success = await composite_metric_store.delete_composite_metric(
            composite_metric_id, context
        )
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"CompositeMetric '{composite_metric_id}' not found",
            )
        return {"status": "ok", "composite_metric_id": composite_metric_id}
