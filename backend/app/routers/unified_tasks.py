"""Unified background-task aggregation endpoint.

Merges five independent async-run sources (composite_workflow, field_completion,
circuit_extraction, circuit_connection_extraction, molecular_circuit) into one
sorted, lightweight list so the frontend can poll a single endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select as sa_select

from app.database import get_db
from app.models.llm_circuit_extraction import CircuitExtractionRun
from app.models.llm_circuit_connection_extraction import LlmCircuitConnectionExtractionRun
from app.services import llm_composite_workflow_service as composite_svc
from app.services import llm_field_completion_service as fc_svc
from app.services import molecular_circuit_extraction_service as mol_svc

router = APIRouter()
_log = logging.getLogger(__name__)

# ── Unified response schema ─────────────────────────────────────────────────

class UnifiedTaskItem(BaseModel):
    id: str
    type: str  # composite_workflow | field_completion | circuit_extraction | circuit_connection_extraction | molecular_circuit
    status: str
    label: str
    target_type: str | None = None
    target_count: int | None = None
    provider: str | None = None
    model_name: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    meta: dict[str, Any] | None = None  # extras per type (e.g. errors_count, pack_count)

class UnifiedTaskListResponse(BaseModel):
    items: list[UnifiedTaskItem]
    total: int
    limit: int
    offset: int

# ── Helpers ─────────────────────────────────────────────────────────────────

def _ts(v: Any) -> str | None:
    """Serialize a datetime-ish value to ISO-8601 string."""
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)

# ── Endpoint ────────────────────────────────────────────────────────────────

@router.get("/tasks/runs", response_model=UnifiedTaskListResponse)
async def list_unified_tasks(
    status: str | None = Query(None, description="Filter by status"),
    task_type: str | None = Query(None, alias="type", description="Filter by task type"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """Return a merged, time-sorted list of all background-task runs."""

    async def _composite():
        try:
            # Discard service-level total — the unified endpoint recomputes total
            # from the merged list because a DB total per source is meaningless here.
            items, _ = await composite_svc.list_composite_workflow_runs(
                session, status=status, limit=limit, offset=0,
            )
            return [
                UnifiedTaskItem(
                    id=str(r.id),
                    type="composite_workflow",
                    status=r.status or "",
                    label=f"LLM 提取 · {getattr(r, 'workflow_type', '') or ''}",
                    target_type=getattr(r, "workflow_type", None) or None,
                    target_count=getattr(r, "candidate_count", None),
                    provider=getattr(r, "provider", None),
                    model_name=getattr(r, "model_name", None),
                    created_at=_ts(getattr(r, "created_at", None)) or "",
                    started_at=_ts(getattr(r, "started_at", None)),
                    completed_at=_ts(getattr(r, "completed_at", None)),
                )
                for r in items
            ]
        except Exception:
            _log.exception("Failed to fetch composite_workflow runs")
            return []

    async def _field_completion():
        try:
            items, _ = await fc_svc.list_field_completion_runs(
                session, status=status, limit=limit, offset=0,
            )
            return [
                UnifiedTaskItem(
                    id=str(r.id),
                    type="field_completion",
                    status=r.status or "",
                    label=f"字段补全 · {getattr(r, 'target_type', '') or ''}",
                    target_type=getattr(r, "target_type", None),
                    target_count=getattr(r, "target_count", None),
                    provider=getattr(r, "provider", None),
                    model_name=getattr(r, "model_name", None),
                    created_at=_ts(getattr(r, "created_at", None)) or "",
                    started_at=_ts(getattr(r, "started_at", None)),
                    completed_at=_ts(getattr(r, "completed_at", None)),
                )
                for r in items
            ]
        except Exception:
            _log.exception("Failed to fetch field_completion runs")
            return []

    async def _circuit_extraction():
        try:
            base = sa_select(CircuitExtractionRun)
            if status:
                base = base.where(CircuitExtractionRun.status == status)
            q = base.order_by(CircuitExtractionRun.created_at.desc()).limit(limit)
            rows = (await session.execute(q)).scalars().all()
            return [
                UnifiedTaskItem(
                    id=str(r.id),
                    type="circuit_extraction",
                    status=r.status or "",
                    label=f"回路提取 · {r.model_name or r.provider or 'run'}",
                    provider=r.provider,
                    model_name=r.model_name,
                    target_count=getattr(r, "circuit_count", None) or getattr(r, "candidate_count", None),
                    created_at=_ts(r.created_at) or "",
                    started_at=_ts(r.started_at),
                    completed_at=_ts(r.completed_at),
                )
                for r in rows
            ]
        except Exception:
            _log.exception("Failed to fetch circuit_extraction runs")
            return []

    async def _circuit_connection_extraction():
        try:
            q = sa_select(LlmCircuitConnectionExtractionRun)
            if status:
                q = q.where(LlmCircuitConnectionExtractionRun.status == status)
            q = q.order_by(LlmCircuitConnectionExtractionRun.created_at.desc()).limit(limit)
            rows = (await session.execute(q)).scalars().all()
            return [
                UnifiedTaskItem(
                    id=str(r.id),
                    type="circuit_connection_extraction",
                    status=r.status or "",
                    label=f"回路→连接提取 · {getattr(r, 'mode', '') or ''}",
                    target_type=getattr(r, "mode", None),
                    target_count=getattr(r, "circuit_count", None),
                    provider=getattr(r, "provider", None),
                    model_name=getattr(r, "model_name", None),
                    created_at=_ts(getattr(r, "created_at", None)) or "",
                    started_at=_ts(getattr(r, "started_at", None)),
                    completed_at=_ts(getattr(r, "completed_at", None)),
                )
                for r in rows
            ]
        except Exception:
            _log.exception("Failed to fetch circuit_connection_extraction runs")
            return []

    async def _molecular():
        try:
            items, _ = await mol_svc.list_extraction_runs(
                session, status=status, limit=limit, offset=0,
            )
            return [
                UnifiedTaskItem(
                    id=str(r.id),
                    type="molecular_circuit",
                    status=r.status or "",
                    label=f"Molecular 回路 · {getattr(r, 'model_name', None) or getattr(r, 'provider', '') or ''}",
                    target_type="molecular_attr",
                    target_count=getattr(r, "candidate_count", None) or getattr(r, "pack_count", None),
                    provider=getattr(r, "provider", None),
                    model_name=getattr(r, "model_name", None),
                    created_at=_ts(getattr(r, "created_at", None)) or "",
                    started_at=_ts(getattr(r, "started_at", None)),
                    completed_at=_ts(getattr(r, "completed_at", None)),
                )
                for r in items
            ]
        except Exception:
            _log.exception("Failed to fetch molecular_circuit runs")
            return []

    # Run queries sequentially — SQLAlchemy AsyncSession cannot share a single
    # session across concurrent asyncio tasks (InvalidRequestError: "concurrent
    # operations are not permitted").
    merged: list[UnifiedTaskItem] = []
    for coro in (_composite, _field_completion, _circuit_extraction, _circuit_connection_extraction, _molecular):
        try:
            items = await coro()
            if isinstance(items, list):
                merged.extend(items)
        except Exception:
            _log.exception("Sub-query failed for unified tasks")

    # Filter by type if requested
    if task_type:
        merged = [t for t in merged if t.type == task_type]

    # Sort by created_at DESC (newest first)
    merged.sort(key=lambda t: t.created_at, reverse=True)

    total = len(merged)

    # Apply pagination
    paged = merged[offset : offset + limit]

    return UnifiedTaskListResponse(items=paged, total=total, limit=limit, offset=offset)
