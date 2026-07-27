"""Molecular Circuit Extraction v2 — REST API routes."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.molecular_circuit_extraction import (
    MolecularCircuitActionResponse,
    MolecularCircuitCandidateListResponse,
    MolecularCircuitCandidateRead,
    MolecularCircuitExtractionRequest,
    MolecularCircuitProgressResponse,
    MolecularCircuitRunListResponse,
    MolecularCircuitRunRead,
    MolecularCircuitStartResponse,
)
from app.services import molecular_circuit_extraction_service as svc

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/start", response_model=MolecularCircuitStartResponse, status_code=202)
async def start_molecular_circuit_extraction(
    request: MolecularCircuitExtractionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Start a molecular circuit extraction run (async background)."""
    if request.dry_run:
        # Dry run: only graph generation, no LLM calls
        from app.services.molecular_circuit_graph_engine import (
            GraphEngineConfig,
            build_graph_and_generate_candidates,
        )
        graph_result = await build_graph_and_generate_candidates(
            session,
            GraphEngineConfig(),
        )
        return MolecularCircuitStartResponse(
            run_id=uuid.uuid4(),
            status="dry_run",
            candidate_count=574,
            pack_count=0,
            estimated_candidates=len(graph_result.candidates),
        )

    run = await svc.create_extraction_run(session, request)
    background_tasks.add_task(
        svc.execute_molecular_circuit_extraction,
        run.id,
        request.model_dump(mode="json"),
    )
    # Rough estimate
    estimated_packs = max(1, 70000 // request.pack_candidate_limit)
    return MolecularCircuitStartResponse(
        run_id=run.id,
        status=run.status,
        candidate_count=574,
        pack_count=estimated_packs,
        estimated_candidates=70000,
    )


@router.get("/runs", response_model=MolecularCircuitRunListResponse)
async def list_runs(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await svc.list_extraction_runs(
        session, status=status, limit=limit, offset=offset
    )
    return MolecularCircuitRunListResponse(
        items=[MolecularCircuitRunRead.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=MolecularCircuitRunRead)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await svc.get_extraction_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return MolecularCircuitRunRead.model_validate(run)


@router.get("/runs/{run_id}/progress", response_model=MolecularCircuitProgressResponse)
async def get_progress(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await svc.get_extraction_progress(session, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel", response_model=MolecularCircuitActionResponse)
async def cancel_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await svc.cancel_extraction_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return MolecularCircuitActionResponse(
        run_id=run.id,
        status=run.status,
        message="Run cancelled",
    )


@router.post("/runs/{run_id}/pause", response_model=MolecularCircuitActionResponse)
async def pause_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await svc.pause_extraction_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return MolecularCircuitActionResponse(
        run_id=run.id,
        status=run.status,
        message="Pause requested",
    )


@router.post("/runs/{run_id}/resume", response_model=MolecularCircuitActionResponse)
async def resume_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await svc.resume_extraction_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return MolecularCircuitActionResponse(
        run_id=run.id,
        status=run.status,
        message="Run resumed",
    )


@router.get("/candidates", response_model=MolecularCircuitCandidateListResponse)
async def list_candidates(
    extraction_run_id: uuid.UUID | None = None,
    confidence_level: str | None = None,
    topology_type: str | None = None,
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """List molecular circuit candidates with optional filters."""
    from sqlalchemy import func, select
    from app.models.molecular_circuit_candidate import MirrorMolecularCircuitCandidate

    q = select(MirrorMolecularCircuitCandidate)
    if extraction_run_id:
        q = q.where(MirrorMolecularCircuitCandidate.extraction_run_id == extraction_run_id)
    if confidence_level:
        q = q.where(MirrorMolecularCircuitCandidate.confidence_level == confidence_level)
    if topology_type:
        q = q.where(MirrorMolecularCircuitCandidate.topology_type == topology_type)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(count_q)).scalar_one()
    q = q.order_by(MirrorMolecularCircuitCandidate.overall_confidence.desc().nullslast())
    q = q.offset(offset).limit(limit)
    rows = (await session.execute(q)).scalars().all()

    return MolecularCircuitCandidateListResponse(
        items=[MolecularCircuitCandidateRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
