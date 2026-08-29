"""
FastAPI route implementations for the metric-graph extraction workflow.

Provides the manual-trigger -> draft-area -> checkbox-import workflow:

    POST /metric-graph/extract        kick off LLM extraction in the background
    GET  /metric-graph/extract/status poll the background extraction state
    GET  /metric-graph/draft          read the current draft
    POST /metric-graph/draft/import   import user-selected entities into stores
    DELETE /metric-graph/draft        clear the whole draft
    POST /metric-graph/draft/clear    clear the draft (full or per-table)
    POST /metric-graph/sync           rebuild the Neo4j graph from stores

The draft lives in memory for the lifetime of the server process; it is the
"draft area" the admin page renders, from which the user checks items to import.
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ...capabilities.metric_graph_store import MetricGraphStore
from ...metric_graph import DEFAULT_DRAFT_PATH, DEFAULT_IMPORTED_PATH
from ...metric_graph.draft import MetricGraphDraft, import_selected
from ...metric_graph.extract import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_GLEANING,
    MetricGraphExtractor,
)


class ImportDraftRequest(BaseModel):
    """Request body: entity names (entity_name) the user checked for import."""

    selected: List[str] = Field(
        description="Entity names to import, in any order; dependencies are "
                    "resolved automatically."
    )


class ExtractRequest(BaseModel):
    """Request body for triggering LLM extraction.

    ``tables`` limits extraction to the named (already-synced) schema tables;
    omit it — or pass an empty list — to run full extraction over all tables.
    """

    tables: Optional[List[str]] = Field(
        default=None,
        description="Table names to limit extraction to; omit or empty = extract all",
    )


class ClearDraftRequest(BaseModel):
    """Request body for scoped clearing of the draft.

    ``tables`` limits clearing to the named tables' extracted entities; omit it
    — or pass an empty list — to clear the entire draft.
    """

    tables: Optional[List[str]] = Field(
        default=None,
        description="Table names to limit clearing to; omit or empty = clear all",
    )


def _get_context(agent):
    """Build a minimal ToolContext for REST API operations."""
    from ...core.tool import ToolContext
    from ...core.user.models import User

    user = User(id="api_admin", group_memberships=["admin"])
    return ToolContext(
        user=user,
        conversation_id="metric_graph_api",
        request_id="metric_graph_api",
        agent_memory=agent.agent_memory,
    )


def register_metric_graph_routes(
    app: FastAPI,
    agent,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register metric-graph extraction / draft / import / sync routes."""

    config = config or {}
    schema_store = config.get("schema_store")
    atomic_metric_store = config.get("atomic_metric_store")
    derived_metric_store = config.get("derived_metric_store")
    composite_metric_store = config.get("composite_metric_store")
    graph_store: Optional[MetricGraphStore] = config.get("metric_graph_store")
    max_gleaning = config.get("metric_graph_max_gleaning", DEFAULT_MAX_GLEANING)
    max_concurrency = config.get("metric_graph_max_concurrency", DEFAULT_MAX_CONCURRENCY)

    # Draft area, backed by a JSON file so it survives process restarts.
    # The in-memory dict stays the source of truth during a process's lifetime;
    # the file is written on extract and removed on clear. Both files default
    # to the metric_graph package directory (next to MetricSchema.json), so the
    # draft does not depend on the process's current working directory.
    draft_path = config.get("metric_graph_draft_path") or DEFAULT_DRAFT_PATH

    def _imported_path_for(path: str) -> str:
        # The already-imported list is persisted separately, so the draft JSON body stays untouched.
        if path.endswith(".json"):
            return path[:-5] + "_imported.json"
        return path + "_imported.json"

    imported_path = (
        config.get("metric_graph_imported_path")
        or (DEFAULT_IMPORTED_PATH if draft_path == DEFAULT_DRAFT_PATH else _imported_path_for(draft_path))
    )

    def _save_draft(draft: MetricGraphDraft) -> None:
        try:
            with open(draft_path, "w", encoding="utf-8") as f:
                json.dump(draft.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError:
            # Persistence is best-effort: the in-memory draft still works.
            pass

    def _load_draft() -> Optional[MetricGraphDraft]:
        if not os.path.exists(draft_path):
            return None
        try:
            with open(draft_path, "r", encoding="utf-8") as f:
                return MetricGraphDraft.from_dict(json.load(f))
        except (OSError, ValueError, TypeError):
            return None

    def _load_imported() -> Set[str]:
        if not os.path.exists(imported_path):
            return set()
        try:
            with open(imported_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return {str(x) for x in data}
        except (OSError, ValueError, TypeError):
            pass
        return set()

    def _save_imported(names: Set[str]) -> None:
        try:
            with open(imported_path, "w", encoding="utf-8") as f:
                json.dump(sorted(names), f, ensure_ascii=False, indent=2)
        except OSError:
            # Persistence is best-effort; the in-memory set still works.
            pass

    _draft: Dict[str, Optional[MetricGraphDraft]] = {"draft": _load_draft()}
    _imported: Dict[str, Set[str]] = {"names": _load_imported()}

    def _require_draft() -> MetricGraphDraft:
        if _draft["draft"] is None:
            raise HTTPException(
                status_code=404,
                detail="No draft available. Run POST /metric-graph/extract first.",
            )
        return _draft["draft"]

    def _require_schema_store():
        if schema_store is None:
            raise HTTPException(
                status_code=503,
                detail="SchemaStore is not configured. Set 'schema_store' in config.",
            )

    def _require_graph_store() -> MetricGraphStore:
        if graph_store is None:
            raise HTTPException(
                status_code=503,
                detail="Neo4j metric graph store is not configured. "
                       "Set 'metric_graph_store' in config.",
            )
        return graph_store

    def _llm_service():
        llm = config.get("llm_service") or getattr(agent, "llm_service", None)
        if llm is None:
            raise HTTPException(
                status_code=503,
                detail="No LlmService configured for extraction.",
            )
        return llm

    # Extraction runs in a background worker thread so it never blocks the
    # event loop — chat and other endpoints keep responding while it runs.
    # ``_extract_state`` is polled by GET /metric-graph/extract/status.
    _extract_state: Dict[str, Any] = {
        "status": "idle",       # idle | running | done | error
        "error": None,
        "tables_total": 0,
        "started_at": None,
        "finished_at": None,
    }
    _extract_executor = ThreadPoolExecutor(max_workers=1)

    def _run_extract_blocking(tables, llm, full: bool):
        """Run extract -> validate -> normalize in the worker thread.

        Updates ``_draft`` / ``_extract_state`` directly (single-writer: only
        this worker touches them while running), so no asyncio task is needed
        and the event loop is never blocked.

        ``full`` controls merge semantics:

        * full extraction — the new draft *replaces* whatever was there before,
          and the imported list is reset;
        * per-table extraction — the tables being extracted are first *removed*
          from the existing draft (entities + dangling relationships), then the
          new result is *appended*. Other tables' results are untouched.
        """
        try:
            extractor = MetricGraphExtractor(llm, max_gleaning=max_gleaning)
            result = asyncio.run(extractor.extract(tables, max_concurrency=max_concurrency))
            result = extractor.validate(result, tables)
            new_draft = MetricGraphDraft.from_extraction(result)

            if full:
                draft = new_draft
                # Full extraction is a fresh draft: clear the imported list (incl. disk),
                # otherwise the stale list would wrongly hide newly extracted same-name metrics.
                _imported["names"] = set()
                _save_imported(_imported["names"])
            else:
                table_set = {t.table_name for t in tables}
                existing = _draft["draft"]
                removed = existing.removed_names_for_tables(table_set) if existing else set()
                draft = existing.without_tables(table_set) if existing else MetricGraphDraft()
                draft.extend(new_draft)
                # On re-extracting a table, drop that table's old entity names from the
                # imported list so the fresh same-name metrics become visible again; other
                # tables' imported status is unchanged.
                if removed and _imported["names"]:
                    _imported["names"] -= removed
                    _save_imported(_imported["names"])

            _draft["draft"] = draft
            _save_draft(draft)
            _extract_state.update(status="done", finished_at=time.time())
        except Exception as e:  # noqa: BLE001 — surface error via status
            _extract_state.update(status="error", error=str(e), finished_at=time.time())

    @app.post("/api/easyq2sql/v1/metric-graph/extract")
    async def extract_metric_graph(body: Optional[ExtractRequest] = None) -> Dict[str, Any]:
        """Kick off LLM extraction in the background; returns immediately.

        Supports two modes:

        * full extraction — no ``tables`` in the body (or an empty list);
        * single/multi-table extraction — ``tables`` names the subset of
          already-synced schema tables to extract.

        Poll GET /metric-graph/extract/status until ``done``, then read the
        draft via GET /metric-graph/draft.
        """
        _require_schema_store()
        if _extract_state["status"] == "running":
            raise HTTPException(
                status_code=409,
                detail="Extraction is already running. Poll /metric-graph/extract/status.",
            )

        context = _get_context(agent)
        all_tables = await schema_store.list_all_tables(context)
        if not all_tables:
            raise HTTPException(
                status_code=400,
                detail="No table schemas available. Sync schemas first.",
            )

        if body and body.tables:
            wanted = {t.strip() for t in body.tables if t and t.strip()}
            tables = [t for t in all_tables if t.table_name in wanted]
            missing = wanted - {t.table_name for t in all_tables}
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail="These tables are not yet synced in the schema: "
                           + ", ".join(sorted(missing)),
                )
            if not tables:
                raise HTTPException(
                    status_code=400,
                    detail="No tables matched for extraction.",
                )
            full = False
        else:
            tables = all_tables
            full = True

        llm = _llm_service()
        _extract_state.update(
            status="running",
            error=None,
            tables_total=len(tables),
            started_at=time.time(),
            finished_at=None,
        )
        _extract_executor.submit(_run_extract_blocking, tables, llm, full)
        return {
            "status": "running",
            "tables_total": len(tables),
            "tables": [t.table_name for t in tables],
        }

    @app.get("/api/easyq2sql/v1/metric-graph/extract/status")
    async def extract_status() -> Dict[str, Any]:
        """Return the background extraction state."""
        return dict(_extract_state)

    @app.get("/api/easyq2sql/v1/metric-graph/draft")
    async def get_draft() -> Dict[str, Any]:
        """Return the current draft (or 404 if none)."""
        draft = _require_draft()
        # Imported metrics are hidden from the view, but the draft body (incl. the on-disk JSON) is unchanged.
        visible = draft.without_entities(_imported["names"])
        grouped = visible.grouped()
        return {
            "entities": [e.model_dump() for e in visible.entities],
            "relationships": [r.model_dump() for r in visible.relationships],
            "grouped": {k: [e.model_dump() for e in v] for k, v in grouped.items()},
            "counts": {k: len(v) for k, v in grouped.items()},
        }

    def _clear_draft(tables: Optional[List[str]]) -> Dict[str, Any]:
        """Clear the draft — fully, or scoped to the given tables.

        Full clear (``tables`` falsy) removes the whole draft + imported list.
        Scoped clear removes just those tables' entities (and dangling
        relationships); if nothing remains the draft file is removed and the
        draft becomes empty. Returns a small status payload for the frontend.
        """
        draft = _draft["draft"]
        if draft is None:
            return {"status": "ok", "cleared": 0}

        if tables:
            table_set = {t.strip() for t in tables if t and t.strip()}
            removed = draft.removed_names_for_tables(table_set)
            remaining = draft.without_tables(table_set)
            if remaining.entities or remaining.relationships:
                _draft["draft"] = remaining
                _save_draft(remaining)
            else:
                _draft["draft"] = None
                try:
                    if os.path.exists(draft_path):
                        os.remove(draft_path)
                except OSError:
                    pass
            if removed and _imported["names"]:
                _imported["names"] -= removed
                _save_imported(_imported["names"])
            return {"status": "ok", "cleared": len(removed)}

        # Full clear.
        _draft["draft"] = None
        _imported["names"] = set()
        try:
            if os.path.exists(draft_path):
                os.remove(draft_path)
        except OSError:
            pass
        _save_imported(_imported["names"])
        return {"status": "ok", "cleared": 0}

    @app.delete("/api/easyq2sql/v1/metric-graph/draft")
    async def clear_draft() -> Dict[str, Any]:
        """Clear the entire draft (memory + disk)."""
        return _clear_draft(None)

    @app.post("/api/easyq2sql/v1/metric-graph/draft/clear")
    async def clear_draft_scoped(body: Optional[ClearDraftRequest] = None) -> Dict[str, Any]:
        """Clear the draft — full (no ``tables``) or scoped to named tables."""
        tables = body.tables if body else None
        return _clear_draft(tables)

    @app.post("/api/easyq2sql/v1/metric-graph/draft/import")
    async def import_draft(body: ImportDraftRequest) -> Dict[str, Any]:
        """Import user-selected draft entities into the config stores.

        Only requires that *at least one* store is configured; entities whose
        target store is missing are reported as ``skipped`` by
        ``import_selected`` rather than aborting the whole import.
        """
        draft = _require_draft()
        if not any((atomic_metric_store, derived_metric_store, composite_metric_store)):
            raise HTTPException(
                status_code=503,
                detail="No stores configured (atomic_metric_store / derived_metric_store / "
                       "composite_metric_store); cannot import.",
            )

        context = _get_context(agent)
        report = await import_selected(
            draft,
            body.selected,
            atomic_metric_store=atomic_metric_store,
            derived_metric_store=derived_metric_store,
            composite_metric_store=composite_metric_store,
            context=context,
        )

        # Only record the imported names for frontend hiding; the draft JSON body
        # is not pruned, so downstream parsing of the full extraction result never fails.
        imported_names = {
            name
            for names in report.get("imported", {}).values()
            for name in names
        }
        if imported_names:
            _imported["names"].update(imported_names)
            _save_imported(_imported["names"])

        return report

    @app.post("/api/easyq2sql/v1/metric-graph/sync")
    async def sync_graph() -> Dict[str, Any]:
        """Rebuild the Neo4j metric graph from the relational stores."""
        store = _require_graph_store()
        context = _get_context(agent)

        try:
            await store.connect()
            await store.ensure_indexes()
            stats = await store.sync_from_stores(
                atomic_metric_store=atomic_metric_store,
                derived_metric_store=derived_metric_store,
                composite_metric_store=composite_metric_store,
                context=context,
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            # Fallback: turn Neo4j connect/index/sync failures into structured JSON
            # errors; otherwise FastAPI returns plain-text "Internal Server Error"
            # and the frontend JSON.parse fails with "Unexpected token ...".
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Neo4j sync failed: {e}. Confirm Neo4j is running and "
                    f"NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD are correct "
                    f"(current URI: {getattr(graph_store, 'uri', 'unknown')})"
                ),
            )

        return {"status": "ok", **stats}
