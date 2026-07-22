"""
FastAPI route implementations for Schema Management.

Registers REST API endpoints for browsing and editing database
table/column metadata stored in the SchemaStore.

Routes are always registered. When ``schema_store`` is ``None``
(not configured), endpoints return 503 with a clear message.
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from ...capabilities.schema_store import SchemaStore
from ...core.agent.agent import Agent


class UpdateTableDescriptionRequest(BaseModel):
    """Request body for updating a table's description."""

    description: str = Field(description="New description for the table")


class UpdateColumnDescriptionRequest(BaseModel):
    """Request body for updating a column's description."""

    description: str = Field(description="New description for the column")


async def _get_context(agent: Agent):
    """Build a minimal ToolContext for REST API operations."""
    from ...core.tool import ToolContext
    from ...core.user.models import User

    user = User(id="api_admin", group_memberships=["admin"])
    return ToolContext(
        user=user,
        conversation_id="schema_api",
        request_id="schema_api",
        agent_memory=agent.agent_memory,
    )


def _require_store(schema_store):
    """Raise 503 if schema_store is not configured."""
    if schema_store is None:
        raise HTTPException(
            status_code=503,
            detail="SchemaStore is not configured. "
                   "Set 'schema_store' in server config to enable schema management.",
        )


def register_schema_routes(
    app: FastAPI,
    agent: Agent,
    schema_store: Optional[SchemaStore],
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register schema management routes on the FastAPI app.

    Routes are always registered so the admin UI can discover them.
    If ``schema_store`` is ``None``, endpoints return 503.

    Args:
        app: FastAPI application instance.
        agent: Vanna Agent instance (for ToolContext construction).
        schema_store: SchemaStore implementation, or None if not configured.
        config: Optional server configuration dict.
    """

    @app.get("/api/easyq2sql/v1/schema/tables")
    async def list_tables() -> List[Dict[str, Any]]:
        """List all tables with their columns and metadata."""
        _require_store(schema_store)
        context = await _get_context(agent)
        tables = await schema_store.list_all_tables(context)
        return [t.model_dump(mode="json") for t in tables]

    @app.get("/api/easyq2sql/v1/schema/tables/{table_name}")
    async def get_table(table_name: str) -> Dict[str, Any]:
        """Get a single table with full detail."""
        _require_store(schema_store)
        context = await _get_context(agent)
        table = await schema_store.get_table_schema(table_name, context)
        if table is None:
            raise HTTPException(
                status_code=404, detail=f"Table '{table_name}' not found"
            )
        return table.model_dump(mode="json")

    @app.put("/api/easyq2sql/v1/schema/tables/{table_name}/description")
    async def update_table_description(
        table_name: str, body: UpdateTableDescriptionRequest
    ) -> Dict[str, str]:
        """Update a table's description. Syncs the change to the vector store."""
        _require_store(schema_store)
        context = await _get_context(agent)
        success = await schema_store.update_table_description(
            table_name, body.description, context
        )
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Table '{table_name}' not found"
            )
        return {
            "status": "ok",
            "table_name": table_name,
            "description": body.description,
        }

    @app.put(
        "/api/easyq2sql/v1/schema/tables/{table_name}/columns/{column_name}/description"
    )
    async def update_column_description(
        table_name: str,
        column_name: str,
        body: UpdateColumnDescriptionRequest,
    ) -> Dict[str, str]:
        """Update a column's description. Syncs the change to the vector store."""
        _require_store(schema_store)
        context = await _get_context(agent)
        success = await schema_store.update_column_description(
            table_name, column_name, body.description, context
        )
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Column '{column_name}' in table '{table_name}' not found",
            )
        return {
            "status": "ok",
            "table_name": table_name,
            "column_name": column_name,
            "description": body.description,
        }

    @app.post("/api/easyq2sql/v1/schema/sync")
    async def sync_schemas(
        database_name: str = Query(default="default"),
    ) -> Dict[str, Any]:
        """Manually trigger DDL re-extraction and vector store sync.

        Requires ``schema_extractor``, ``sql_runner``, and ``schema_store``
        to be set in the server config dict.
        """
        _require_store(schema_store)
        context = await _get_context(agent)
        extractor = config.get("schema_extractor") if config else None
        sql_runner = config.get("sql_runner") if config else None

        if extractor is None:
            raise HTTPException(
                status_code=400,
                detail="No SchemaExtractor configured. Set 'schema_extractor' in server config.",
            )
        if sql_runner is None:
            raise HTTPException(
                status_code=400,
                detail="No SqlRunner configured. Set 'sql_runner' in server config.",
            )

        try:
            tables = await extractor.extract_schemas(
                sql_runner, context, database_name
            )
            count = await schema_store.sync_all_schemas(tables, context)
            return {
                "status": "ok",
                "tables_synced": count,
                "database_name": database_name,
            }
        except Exception as e:
            import traceback

            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Schema sync failed: {str(e)}",
            ) from e
