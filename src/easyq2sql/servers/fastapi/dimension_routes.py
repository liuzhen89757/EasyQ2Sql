"""
FastAPI route implementations for Dimension Management.

Registers REST API endpoints for creating, reading, updating, and
deleting dimension definitions.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.dimension_store import DimensionStore


class JoinClauseRequest(BaseModel):
    """Join clause within a dimension."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "INNER JOIN"


class CreateDimensionRequest(BaseModel):
    """Request body for creating a new dimension."""

    metric_id: str = Field(description="FK to the parent Metric")
    name: str = Field(description="Dimension name, e.g. 'Time', 'Region'")
    business_definition: Optional[str] = Field(
        default=None, description="Business meaning"
    )
    value_range: Optional[str] = Field(default=None, description="Value range")
    data_source: str = Field(description="Dimension table name")
    field_ref: str = Field(description="table.column reference")
    joins: List[JoinClauseRequest] = Field(
        default_factory=list, description="FK JOIN clauses"
    )
    description: Optional[str] = Field(default=None, description="Optional notes")


class UpdateDimensionRequest(CreateDimensionRequest):
    """Request body for updating an existing dimension."""
    pass


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


def _require_store(dimension_store):
    if dimension_store is None:
        raise HTTPException(
            status_code=503,
            detail="DimensionStore is not configured.",
        )


def register_dimension_routes(
    app: FastAPI,
    agent,
    dimension_store: Optional[DimensionStore],
    config: Optional[Dict[str, Any]] = None,
    terminology_store=None,
) -> None:
    """Register dimension management routes on the FastAPI app."""

    @app.get("/api/easyq2sql/v1/dimensions")
    async def list_dimensions() -> List[Dict[str, Any]]:
        """List all defined dimensions."""
        _require_store(dimension_store)
        context = _get_context(agent)
        dims = await dimension_store.list_dimensions(context)
        return [d.model_dump(mode="json") for d in dims]

    @app.post("/api/easyq2sql/v1/dimensions")
    async def create_dimension(body: CreateDimensionRequest) -> Dict[str, Any]:
        """Create a new dimension definition."""
        _require_store(dimension_store)
        from ...capabilities.dimension_store.models import Dimension
        from ...capabilities.metric_store.models import JoinClause

        context = _get_context(agent)

        dimension = Dimension(
            metric_id=body.metric_id,
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

        result = await dimension_store.create_dimension(dimension, context)

        # Auto-generate terminology mapping
        if terminology_store:
            try:
                await terminology_store.sync_auto_terms(
                    context, metrics=[], dimensions=[result]
                )
            except Exception:
                pass

        return result.model_dump(mode="json")

    @app.get("/api/easyq2sql/v1/dimensions/{dimension_id}")
    async def get_dimension(dimension_id: str) -> Dict[str, Any]:
        """Get a single dimension with full detail."""
        _require_store(dimension_store)
        context = _get_context(agent)
        dim = await dimension_store.get_dimension(dimension_id, context)
        if dim is None:
            raise HTTPException(
                status_code=404, detail=f"Dimension '{dimension_id}' not found"
            )
        return dim.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/dimensions/{dimension_id}")
    async def update_dimension(
        dimension_id: str, body: UpdateDimensionRequest
    ) -> Dict[str, Any]:
        """Update an existing dimension."""
        _require_store(dimension_store)
        from ...capabilities.dimension_store.models import Dimension
        from ...capabilities.metric_store.models import JoinClause

        context = _get_context(agent)

        existing = await dimension_store.get_dimension(dimension_id, context)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"Dimension '{dimension_id}' not found"
            )

        dimension = Dimension(
            id=dimension_id,
            metric_id=body.metric_id,
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

        success = await dimension_store.update_dimension(dimension, context)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update dimension")

        if terminology_store:
            try:
                await terminology_store.sync_auto_terms(
                    context, metrics=[], dimensions=[dimension]
                )
            except Exception:
                pass

        updated = await dimension_store.get_dimension(dimension_id, context)
        return updated.model_dump(mode="json") if updated else {}

    @app.delete("/api/easyq2sql/v1/dimensions/{dimension_id}")
    async def delete_dimension(dimension_id: str) -> Dict[str, str]:
        """Delete a dimension definition."""
        _require_store(dimension_store)
        context = _get_context(agent)
        success = await dimension_store.delete_dimension(dimension_id, context)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Dimension '{dimension_id}' not found"
            )
        return {"status": "ok", "dimension_id": dimension_id}

    @app.get("/api/easyq2sql/v1/metrics/{metric_id}/dimensions")
    async def get_dimensions_by_metric(metric_id: str) -> List[Dict[str, Any]]:
        """Get all dimensions linked to a specific metric."""
        _require_store(dimension_store)
        context = _get_context(agent)
        dims = await dimension_store.get_dimensions_by_metric(metric_id, context)
        return [d.model_dump(mode="json") for d in dims]

    class AutoRangeRequest(BaseModel):
        """Request body for auto-generating dimension value range."""
        data_source: str = Field(description="Dimension table name")
        field_ref: str = Field(description="table.column reference")

    @app.post("/api/easyq2sql/v1/dimensions/auto-range")
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
