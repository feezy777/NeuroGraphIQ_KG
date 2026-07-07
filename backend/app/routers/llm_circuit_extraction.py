"""Circuit pack extraction REST API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_circuit_extraction import CircuitExtractionRun
from app.schemas.llm_circuit_extraction import (
    CircuitExtractionRequest,
    CircuitExtractionRunRead,
    CircuitExtractionStartResponse,
)
from app.services import llm_circuit_pack_service as svc

router = APIRouter()


@router.post("/run")
async def run_extraction(
    body: CircuitExtractionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    if body.dry_run:
        from app.services.llm_circuit_pack_service import build_circuit_pack_plan
        plan = build_circuit_pack_plan(
            len(body.candidate_ids), body.candidates_per_pack, body.shuffle_rounds,
        )
        logger = __import__('logging').getLogger(__name__)
        logger.info("[circuit-dry-run][pack-plan] %s", plan)
        return {
            "dry_run": True,
            "estimated_packs": plan["pack_count"],
            "estimated_llm_calls": plan["pack_count"],
            "candidate_count": plan["candidate_count"],
        }

    start = await svc.run_circuit_pack_extraction(session, body)
    background_tasks.add_task(
        svc.execute_circuit_extraction_background,
        start.run_id,
        body.model_dump(mode="json"),
    )
    return start


@router.get("/runs")
async def list_runs(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    base = sa_select(CircuitExtractionRun)
    if status:
        base = base.where(CircuitExtractionRun.status == status)

    count_q = sa_select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_q)).scalar_one()

    q = (
        base.order_by(CircuitExtractionRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(q)).scalars().all()
    return {
        "items": [CircuitExtractionRunRead.model_validate(r) for r in rows],
        "total": total,
    }


@router.get("/runs/{run_id}", response_model=CircuitExtractionRunRead)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    detail = await svc.get_circuit_extraction_run(session, run_id)
    if detail is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"run {run_id} not found"})
    return detail


@router.post("/runs/{run_id}/cancel", response_model=CircuitExtractionRunRead)
async def cancel_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await svc.cancel_circuit_extraction_run(session, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"run {run_id} not found"})
    return CircuitExtractionRunRead.model_validate(run)


@router.post("/runs/{run_id}/retry-failed-packs", response_model=CircuitExtractionRunRead)
async def retry_failed_packs(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Re-run only the packs that failed in a previous run."""
    run = await session.get(CircuitExtractionRun, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"run {run_id} not found"})
    if run.status not in ("partially_succeeded", "succeeded"):
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "message": "Can only retry completed runs"})

    failed_packs = [p for p in (run.pack_results_json or []) if p.get("status") == "failed"]
    if not failed_packs:
        return CircuitExtractionRunRead.model_validate(run)

    request_data = run.request_json or {}
    request_data["candidate_ids"] = request_data.get("candidate_ids", [])
    request_data["skip_existing"] = False  # Force re-extract on retry
    request = CircuitExtractionRequest.model_validate(request_data)

    # Reset failed counts and re-run
    run.status = "running"
    run.failed_packs = 0
    run.started_at = datetime.now(timezone.utc)
    await session.commit()

    background_tasks.add_task(
        svc.execute_circuit_extraction_background, run_id, request.model_dump(mode="json"),
    )
    return CircuitExtractionRunRead.model_validate(run)
