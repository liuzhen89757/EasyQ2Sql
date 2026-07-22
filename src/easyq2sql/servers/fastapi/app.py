"""
FastAPI server factory for EasyQ2Sql.
"""

import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ...core import Agent
from ..base import ChatHandler
from .routes import register_chat_routes

logger = logging.getLogger(__name__)


class EasyQ2SqlFastAPIServer:
    """FastAPI server factory for EasyQ2Sql."""

    def __init__(self, agent: Agent, config: Optional[Dict[str, Any]] = None):
        """Initialize FastAPI server.

        Args:
            agent: The agent to serve (must have user_resolver configured)
            config: Optional server configuration
        """
        self.agent = agent
        self.config = config or {}
        self.chat_handler = ChatHandler(agent)

    def create_app(self) -> FastAPI:
        """Create configured FastAPI app.

        Returns:
            Configured FastAPI application
        """
        # Create FastAPI app
        app_config = self.config.get("fastapi", {})
        app = FastAPI(
            title="EasyQ2Sql API",
            description="API server for EasyQ2Sql framework",
            version="0.1.0",
            **app_config,
        )

        # Configure CORS if enabled
        cors_config = self.config.get("cors", {})
        if cors_config.get("enabled", True):
            cors_params = {k: v for k, v in cors_config.items() if k != "enabled"}

            # Set sensible defaults
            cors_params.setdefault("allow_origins", ["*"])
            cors_params.setdefault("allow_credentials", True)
            cors_params.setdefault("allow_methods", ["*"])
            cors_params.setdefault("allow_headers", ["*"])

            app.add_middleware(CORSMiddleware, **cors_params)

        # Serve static files (web component JS)
        static_folder = self.config.get("static_folder", "static")
        try:
            if os.path.exists(static_folder):
                app.mount(
                    "/static", StaticFiles(directory=static_folder), name="static"
                )
        except Exception:
            pass  # Static files not available

        # Register routes
        register_chat_routes(app, self.chat_handler, self.config)

        # Register admin UI routes (always available)
        from .admin_routes import register_admin_routes

        register_admin_routes(app, self.config)

        # Register schema management routes (always register; routes return
        # 503 when schema_store is not configured)
        schema_store = self.config.get("schema_store")
        from .schema_routes import register_schema_routes

        register_schema_routes(app, self.agent, schema_store, self.config)

        # Register metric management routes (always register; routes return
        # 503 when metric_store is not configured)
        metric_store = self.config.get("metric_store")
        from .metric_routes import register_metric_routes

        register_metric_routes(
            app, self.agent, metric_store,
            schema_store=schema_store,
            config=self.config,
        )

        # Register conversation management routes (always register; routes return
        # 503 when conversation_store is not configured)
        from .conversation_routes import register_conversation_routes

        register_conversation_routes(app, self.agent, self.config)

        # Add startup event for automatic schema extraction
        auto_extract = self.config.get("auto_extract_schema", False) or (
            hasattr(self.agent, 'config')
            and self.agent.config.auto_extract_schema
        )

        if auto_extract and schema_store is not None:
            from contextlib import asynccontextmanager

            extractor = self.config.get("schema_extractor")
            sql_runner = self.config.get("sql_runner")
            db_name = self.config.get("database_name", "default")

            @asynccontextmanager
            async def schema_lifespan(app_ref: FastAPI):
                """Lifespan handler that extracts schemas on startup."""
                if extractor is not None and sql_runner is not None:
                    try:
                        from ...core.tool import ToolContext
                        from ...core.user.models import User

                        context = ToolContext(
                            user=User(id="startup", group_memberships=["admin"]),
                            conversation_id="startup",
                            request_id="startup_schema_extraction",
                            agent_memory=self.agent.agent_memory,
                        )
                        tables = await extractor.extract_schemas(
                            sql_runner, context, db_name
                        )
                        count = await schema_store.sync_all_schemas(tables, context)
                        logger.info(
                            f"Schema extraction complete: {count} tables synced "
                            f"from database '{db_name}'"
                        )
                    except Exception as e:
                        logger.error(f"Schema extraction on startup failed: {e}")
                else:
                    logger.warning(
                        "auto_extract_schema is enabled but schema_extractor "
                        "or sql_runner is not configured. Skipping extraction."
                    )
                yield

            # Replace the app's router lifespan with ours
            app.router.lifespan_context = schema_lifespan

        # Add health check
        @app.get("/health")
        async def health_check() -> Dict[str, str]:
            return {"status": "healthy", "service": "easyq2sql"}

        return app

    def run(self, **kwargs: Any) -> None:
        """Run the FastAPI server.

        This method automatically detects if running in an async environment
        (Jupyter, Colab, IPython, etc.) and:
        - Uses appropriate async handling for existing event loops
        - Sets up port forwarding if in Google Colab
        - Displays the correct URL for accessing the app

        Args:
            **kwargs: Arguments passed to uvicorn configuration
        """
        import sys
        import asyncio
        import uvicorn

        # Check if we're in an environment with a running event loop FIRST
        in_async_env = False
        try:
            asyncio.get_running_loop()
            in_async_env = True
        except RuntimeError:
            in_async_env = False

        # If in async environment, apply nest_asyncio BEFORE creating the app
        if in_async_env:
            try:
                import nest_asyncio

                nest_asyncio.apply()
            except ImportError:
                print("Warning: nest_asyncio not installed. Installing...")
                import subprocess

                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "nest_asyncio"]
                )
                import nest_asyncio

                nest_asyncio.apply()

        # Now create the app after nest_asyncio is applied
        app = self.create_app()

        # Set defaults
        run_kwargs = {"host": "0.0.0.0", "port": 8000, "log_level": "info", **kwargs}

        # Get the port and other config from run_kwargs
        port = run_kwargs.get("port", 8000)
        host = run_kwargs.get("host", "0.0.0.0")
        log_level = run_kwargs.get("log_level", "info")

        # Check if we're specifically in Google Colab for port forwarding
        in_colab = "google.colab" in sys.modules

        if in_colab:
            try:
                from google.colab import output

                output.serve_kernel_port_as_window(port)
                from google.colab.output import eval_js

                print("Your app is running at:")
                print(eval_js(f"google.colab.kernel.proxyPort({port})"))
            except Exception as e:
                print(f"Warning: Could not set up Colab port forwarding: {e}")
                print(f"Your app is running at: http://localhost:{port}")
        else:
            print("Your app is running at:")
            print(f"http://localhost:{port}")

        if in_async_env:
            # In Jupyter/Colab, create config with loop="asyncio" and use asyncio.run()
            # This matches the working pattern from Colab
            config = uvicorn.Config(
                app, host=host, port=port, log_level=log_level, loop="asyncio"
            )
            server = uvicorn.Server(config)
            asyncio.run(server.serve())
        else:
            # Normal execution outside of Jupyter/Colab
            uvicorn.run(app, **run_kwargs)
