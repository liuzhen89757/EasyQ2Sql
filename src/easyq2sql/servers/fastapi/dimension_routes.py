"""
FastAPI route implementations for Derived Metric Management.

Registers REST API endpoints for creating, reading, updating, and
deleting derived metric definitions.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.derived_metric import DerivedMetricStore


class JoinClauseRequest(BaseModel):
    """Join clause within a derived metric."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "INNER JOIN"


class CreateDerivedMetricRequest(BaseModel):
    """Request body for creating a new derived metric."""

    atomic_metric_id: str = Field(description="FK to the parent AtomicMetric")
    name: str = Field(description="Derived metric name, e.g. 'Time', 'Region'")
    business_definition: Optional[str] = Field(
        default=None, description="Business meaning"
    )
    value_range: Optional[str] = Field(default=None, description="Value range")
    data_source: str = Field(description="Derived metric table name")
    field_ref: str = Field(description="table.column reference")
    joins: List[JoinClauseRequest] = Field(
        default_factory=list, description="FK JOIN clauses"
    )
    description: Optional[str] = Field(default=None, description="Optional notes")


class UpdateDerivedMetricRequest(CreateDerivedMetricRequest):
    """Request body for updating an existing derived metric."""
    pass


class BatchDeleteDerivedMetricsRequest(BaseModel):
    """Request body for batch-deleting derived metrics."""

    ids: List[str] = Field(description="Derived metric IDs to delete")


def _get_context(agent):
    from ...core.tool import ToolContext
    from ...core.user.models import User

    user = User(id="api_admin", group_memberships=["admin"])
    return ToolContext(
        user=user,
        conversation_id="dimension_api",
        request_id="dimension_api",
        agent_memory=agent.agent_memory,
    )


def _require_store(derived_metric_store):
    if derived_metric_store is None:
        raise HTTPException(
            status_code=503,
            detail="DerivedMetricStore is not configured.",
        )


def register_dimension_routes(
    app: FastAPI,
    agent,
    derived_metric_store: Optional[DerivedMetricStore],
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register derived metric management routes on the FastAPI app."""

    @app.get("/api/easyq2sql/v1/derived-metrics")
    async def list_derived_metrics() -> List[Dict[str, Any]]:
        """List all defined derived metrics."""
        _require_store(derived_metric_store)
        context = _get_context(agent)
        derived_metrics = await derived_metric_store.list_derived_metrics(context)
        return [d.model_dump(mode="json") for d in derived_metrics]

    @app.post("/api/easyq2sql/v1/derived-metrics")
    async def create_derived_metric(body: CreateDerivedMetricRequest) -> Dict[str, Any]:
        """Create a new derived metric definition."""
        _require_store(derived_metric_store)
        from ...capabilities.atomic_metric.models import JoinClause
        from ...capabilities.derived_metric.models import DerivedMetric

        context = _get_context(agent)

        derived_metric = DerivedMetric(
            atomic_metric_id=body.atomic_metric_id,
            name=body.name,
            business_definition=body.business_definition,
            value_range=body.value_range,
            data_source=body.data_source,
            field_ref=body.field_ref,
            joins=[
                JoinClause(
                    source_table=j.source_table,
                    source_column=j.source_column,
                    target_table=j.target_table,
                    target_column=j.target_column,
                    join_type=j.join_type,
                )
                for j in body.joins
            ],
            description=body.description,
        )

        result = await derived_metric_store.create_derived_metric(derived_metric, context)

        return result.model_dump(mode="json")

    @app.get("/api/easyq2sql/v1/derived-metrics/{derived_metric_id}")
    async def get_derived_metric(derived_metric_id: str) -> Dict[str, Any]:
        """Get a single derived metric with full detail."""
        _require_store(derived_metric_store)
        context = _get_context(agent)
        derived_metric = await derived_metric_store.get_derived_metric(
            derived_metric_id, context
        )
        if derived_metric is None:
            raise HTTPException(
                status_code=404,
                detail=f"DerivedMetric '{derived_metric_id}' not found",
            )
        return derived_metric.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/derived-metrics/{derived_metric_id}")
    async def update_derived_metric(
        derived_metric_id: str, body: UpdateDerivedMetricRequest
    ) -> Dict[str, Any]:
        """Update an existing derived metric."""
        _require_store(derived_metric_store)
        from ...capabilities.atomic_metric.models import JoinClause
        from ...capabilities.derived_metric.models import DerivedMetric

        context = _get_context(agent)

        existing = await derived_metric_store.get_derived_metric(
            derived_metric_id, context
        )
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"DerivedMetric '{derived_metric_id}' not found",
            )

        derived_metric = DerivedMetric(
            id=derived_metric_id,
            atomic_metric_id=body.atomic_metric_id,
            name=body.name,
            business_definition=body.business_definition,
            value_range=body.value_range,
            data_source=body.data_source,
            field_ref=body.field_ref,
            joins=[
                JoinClause(
                    source_table=j.source_table,
                    source_column=j.source_column,
                    target_table=j.target_table,
                    target_column=j.target_column,
                    join_type=j.join_type,
                )
                for j in body.joins
            ],
            description=body.description,
            created_at=existing.created_at,
        )

        success = await derived_metric_store.update_derived_metric(derived_metric, context)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update derived metric")

        updated = await derived_metric_store.get_derived_metric(
            derived_metric_id, context
        )
        return updated.model_dump(mode="json") if updated else {}

    @app.delete("/api/easyq2sql/v1/derived-metrics/{derived_metric_id}")
    async def delete_derived_metric(derived_metric_id: str) -> Dict[str, str]:
        """Delete a derived metric definition."""
        _require_store(derived_metric_store)
        context = _get_context(agent)
        success = await derived_metric_store.delete_derived_metric(
            derived_metric_id, context
        )
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"DerivedMetric '{derived_metric_id}' not found",
            )
        return {"status": "ok", "derived_metric_id": derived_metric_id}

    @app.post("/api/easyq2sql/v1/derived-metrics/batch-delete")
    async def batch_delete_derived_metrics(
        body: BatchDeleteDerivedMetricsRequest,
    ) -> Dict[str, Any]:
        """Delete multiple derived metrics in a single operation."""
        _require_store(derived_metric_store)
        context = _get_context(agent)
        deleted = await derived_metric_store.delete_derived_metrics(body.ids, context)
        return {"status": "ok", "deleted": deleted}

    @app.get("/api/easyq2sql/v1/atomic-metrics/{atomic_metric_id}/derived-metrics")
    async def get_derived_metrics_by_atomic_metric(
        atomic_metric_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all derived metrics linked to a specific atomic metric."""
        _require_store(derived_metric_store)
        context = _get_context(agent)
        derived_metrics = await derived_metric_store.get_derived_metrics_by_atomic_metric(
            atomic_metric_id, context
        )
        return [d.model_dump(mode="json") for d in derived_metrics]

    class AutoRangeRequest(BaseModel):
        """Request body for auto-generating derived metric value range."""
        data_source: str = Field(description="Derived metric table name")
        field_ref: str = Field(description="table.column reference")

    @app.post("/api/easyq2sql/v1/derived-metrics/auto-range")
    async def auto_range(body: AutoRangeRequest) -> Dict[str, Any]:
        """Run SELECT DISTINCT to auto-generate value range.

        Returns distinct values if count ≤ 20, otherwise ``too_many`` flag.
        """
        sql_runner = config.get("sql_runner") if config else None
        if sql_runner is None:
            raise HTTPException(
                status_code=400,
                detail="No SqlRunner configured. Set 'sql_runner' in server config.",
            )

        # Extract table and column from field_ref (e.g. "dim_date.year")
        parts = body.field_ref.split(".", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid field_ref '{body.field_ref}'. Expected 'table.column'.",
            )
        table, column = parts

        # Validate identifiers: only allow alphanumeric, underscores, and dots
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
            raise HTTPException(status_code=400, detail=f"Invalid table name: {table}")
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", column):
            raise HTTPException(status_code=400, detail=f"Invalid column name: {column}")

        sql = (
            f"SELECT DISTINCT `{column}` AS val "
            f"FROM `{table}` "
            f"ORDER BY `{column}` "
            f"LIMIT 21"
        )

        from ...capabilities.sql_runner.models import RunSqlToolArgs

        context = _get_context(agent)
        try:
            df = await sql_runner.run_sql(RunSqlToolArgs(sql=sql), context)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"SQL execution failed: {e}"
            )

        values = [str(v) for v in df.iloc[:, 0].dropna().tolist()]

        if len(values) > 20:
            return {"too_many": True, "count": len(values), "values": []}

        return {"too_many": False, "count": len(values), "values": values}
