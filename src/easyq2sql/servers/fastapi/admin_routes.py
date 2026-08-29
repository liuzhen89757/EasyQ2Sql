"""
FastAPI route registration for admin management pages.

Serves the Schema, Atomic Metric, Derived Metric (Dimension), Composite Metric,
and Metric Graph management UI pages.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ..base.admin_templates import (
    get_composite_admin_html,
    get_dimension_admin_html,
    get_metric_admin_html,
    get_metric_graph_admin_html,
    get_schema_admin_html,
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

    @app.get("/admin/atomic-metrics", response_class=HTMLResponse)
    async def atomic_metrics_admin():
        """Serve the Atomic Metric Management admin page."""
        return get_metric_admin_html(api_base_url=api_base_url)

    @app.get("/admin/derived-metrics", response_class=HTMLResponse)
    async def derived_metrics_admin():
        """Serve the Derived Metric Management admin page."""
        return get_dimension_admin_html(api_base_url=api_base_url)

    @app.get("/admin/composite-metrics", response_class=HTMLResponse)
    async def composite_metrics_admin():
        """Serve the Composite Metric Management admin page."""
        return get_composite_admin_html(api_base_url=api_base_url)

    @app.get("/admin/metric-graph", response_class=HTMLResponse)
    async def metric_graph_admin():
        """Serve the Metric Graph extraction / draft / import admin page."""
        return get_metric_graph_admin_html(api_base_url=api_base_url)
