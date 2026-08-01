"""
FastAPI route registration for admin management pages.

Serves the Schema Management, Metric Management, Dimension Management,
and Terminology Management UI pages.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ..base.admin_templates import (
    get_dimension_admin_html,
    get_metric_admin_html,
    get_schema_admin_html,
    get_terminology_admin_html,
)


def register_admin_routes(
    app: FastAPI,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register admin page routes on the FastAPI app.

    Args:
        app: FastAPI application instance.
        config: Optional server configuration dict.
    """
    config = config or {}
    api_base_url = config.get("api_base_url", "")

    @app.get("/admin/schema", response_class=HTMLResponse)
    async def schema_admin():
        """Serve the Schema Management admin page."""
        return get_schema_admin_html(api_base_url=api_base_url)

    @app.get("/admin/metrics", response_class=HTMLResponse)
    async def metrics_admin():
        """Serve the Metric Management admin page."""
        return get_metric_admin_html(api_base_url=api_base_url)

    @app.get("/admin/dimensions", response_class=HTMLResponse)
    async def dimensions_admin():
        """Serve the Dimension Management admin page."""
        return get_dimension_admin_html(api_base_url=api_base_url)

    @app.get("/admin/terminology", response_class=HTMLResponse)
    async def terminology_admin():
        """Serve the Terminology Management admin page."""
        return get_terminology_admin_html(api_base_url=api_base_url)
