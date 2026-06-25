"""Mirror KG Circuit-Projection Cross Validation API (Step 8.11)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.mirror_cross_validation import (
    MirrorCircuitProjectionCrossValidationRequest,
    MirrorCircuitProjectionCrossValidationResponse,
    MirrorCircuitProjectionCrossValidationResultListResponse,
    MirrorCircuitProjectionCrossValidationResultPreview,
    MirrorCircuitProjectionCrossValidationResultRead,
    MirrorCircuitProjectionCrossValidationRunListResponse,
    MirrorCircuitProjectionCrossValidationRunRead,
)
from app.services import mirror_circuit_projection_cross_validation_service as cv_svc
from app.services.mirror_circuit_projection_cross_validation_service import CrossValidationScope

router = APIRouter()


def _scope_from_body(scope) -> CrossValidationScope:
    if scope is None:
        return CrossValidationScope()
    return CrossValidationScope(
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        source_version=scope.source_version,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        circuit_ids=scope.circuit_ids,
        projection_ids=scope.projection_ids,
        membership_ids=scope.membership_ids,
        include_unverified=scope.include_unverified,
        include_conflicts=scope.include_conflicts,
    )


@router.post("/run", response_model=MirrorCircuitProjectionCrossValidationResponse)
async def run_cross_validation(
    body: MirrorCircuitProjectionCrossValidationRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await cv_svc.run_circuit_projection_cross_validation(
            session,
            scope=_scope_from_body(body.scope),
            dry_run=body.dry_run,
            apply_updates=body.apply_updates,
            update_bidirectional=body.update_bidirectional,
            update_conflicts=body.update_conflicts,
            limit=body.limit,
        )
    except cv_svc.LimitExceededError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preview = [
        MirrorCircuitProjectionCrossValidationResultPreview(**p)
        for p in result.results_preview
    ]
    return MirrorCircuitProjectionCrossValidationResponse(
        run_id=result.run_id,
        dry_run=result.dry_run,
        apply_updates=result.apply_updates,
        membership_count=result.membership_count,
        circuit_supported_count=result.circuit_supported_count,
        projection_supported_count=result.projection_supported_count,
        bidirectionally_supported_count=result.bidirectionally_supported_count,
        conflict_count=result.conflict_count,
        insufficient_evidence_count=result.insufficient_evidence_count,
        updated_membership_count=result.updated_membership_count,
        results_preview=preview,
        warnings=result.warnings,
    )


@router.get("/runs", response_model=MirrorCircuitProjectionCrossValidationRunListResponse)
async def list_runs(
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    rows, total = await cv_svc.list_cross_validation_runs(
        session,
        status=status,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return MirrorCircuitProjectionCrossValidationRunListResponse(
        items=[MirrorCircuitProjectionCrossValidationRunRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=MirrorCircuitProjectionCrossValidationRunRead)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    row = await cv_svc.get_cross_validation_run(session, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Cross validation run not found")
    return MirrorCircuitProjectionCrossValidationRunRead.model_validate(row)


@router.get("/results", response_model=MirrorCircuitProjectionCrossValidationResultListResponse)
async def list_results(
    run_id: uuid.UUID | None = None,
    circuit_id: uuid.UUID | None = None,
    projection_id: uuid.UUID | None = None,
    validation_status: str | None = None,
    support_level: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    rows, total = await cv_svc.list_cross_validation_results(
        session,
        run_id=run_id,
        circuit_id=circuit_id,
        projection_id=projection_id,
        validation_status=validation_status,
        support_level=support_level,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return MirrorCircuitProjectionCrossValidationResultListResponse(
        items=[MirrorCircuitProjectionCrossValidationResultRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
