"""Mirror KG Rule Validation API (Step 7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.mirror_validation import (
    MirrorValidationRequest,
    MirrorValidationResponse,
    MirrorValidationResultListResponse,
    MirrorValidationResultPreview,
    MirrorValidationResultRead,
    MirrorValidationRunDetailRead,
    MirrorValidationRunListResponse,
    MirrorValidationRunRead,
)
from app.services import mirror_rule_validation_service as mrv_svc
from app.services.mirror_rule_validation_service import ValidationScope

router = APIRouter()


def _scope_from_body(scope) -> ValidationScope:
    if scope is None:
        return ValidationScope()
    return ValidationScope(
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        source_version=scope.source_version,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        mirror_statuses=scope.mirror_status,
        review_statuses=scope.review_status,
        promotion_statuses=scope.promotion_status,
    )


def _filters_from_body(filters) -> mrv_svc.ValidationFilters:
    if filters is None:
        return mrv_svc.ValidationFilters()
    return mrv_svc.ValidationFilters(
        circuit_id=filters.circuit_id,
        projection_id=filters.projection_id,
        object_type=filters.object_type,
        validation_status=filters.validation_status,
        consensus_status=filters.consensus_status,
        verification_status=filters.verification_status,
    )


@router.post("/run", response_model=MirrorValidationResponse)
async def run_validation(
    body: MirrorValidationRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await mrv_svc.run_mirror_rule_validation(
            session,
            target_types=body.target_types,
            scope=_scope_from_body(body.scope),
            filters=_filters_from_body(body.filters),
            connection_ids=body.connection_ids,
            function_ids=body.function_ids,
            circuit_ids=body.circuit_ids,
            triple_ids=body.triple_ids,
            projection_ids=body.projection_ids,
            circuit_step_ids=body.circuit_step_ids,
            projection_function_ids=body.projection_function_ids,
            membership_ids=body.membership_ids,
            cross_validation_result_ids=body.cross_validation_result_ids,
            dual_model_result_ids=body.dual_model_result_ids,
            dry_run=body.dry_run,
            apply_status_update=body.apply_status_update,
            limit=body.limit,
        )
    except mrv_svc.EmptyTargetTypesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrv_svc.InvalidTargetTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrv_svc.LimitExceededError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrv_svc.ExplicitIdNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "TARGET_NOT_FOUND", "message": str(exc), "target_type": exc.target_type},
        ) from exc
    except mrv_svc.ScopeMismatchError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SCOPE_MISMATCH",
                "message": str(exc),
                "target_type": exc.target_type,
                "target_id": exc.target_id,
            },
        ) from exc

    preview = [
        MirrorValidationResultPreview(
            target_type=p["target_type"],
            target_id=p["target_id"],
            rule_code=p["rule_code"],
            severity=p["severity"],
            status=p["status"],
            message=p["message"],
            details_json=p.get("details_json", {}),
        )
        for p in result.results_preview
    ]
    return MirrorValidationResponse(
        dry_run=result.dry_run,
        run_id=result.run_id,
        target_counts=result.target_counts,
        passed_count=result.passed_count,
        warning_count=result.warning_count,
        failed_count=result.failed_count,
        blocked_count=result.blocked_count,
        high_review_priority_count=result.high_review_priority_count,
        result_count=result.result_count,
        status_updates=result.status_updates,
        results_preview=preview,
        warnings=result.warnings,
    )


@router.get("/runs", response_model=MirrorValidationRunListResponse)
async def list_runs(
    target_type: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mrv_svc.list_validation_runs(
        session,
        target_type=target_type,
        status=status,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return MirrorValidationRunListResponse(
        items=[MirrorValidationRunRead.model_validate(r) for r in items],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=MirrorValidationRunDetailRead)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        run = await mrv_svc.get_validation_run(session, run_id)
    except mrv_svc.MirrorValidationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="validation run not found") from exc
    _, result_total = await mrv_svc.list_validation_results(session, run_id=run_id, limit=1)
    summary = {
        "result_count": result_total,
        "passed_count": run.passed_count,
        "warning_count": run.warning_count,
        "failed_count": run.failed_count,
        "blocked_count": run.blocked_count,
    }
    base = MirrorValidationRunRead.model_validate(run)
    return MirrorValidationRunDetailRead(**base.model_dump(), results_summary=summary)


@router.get("/results", response_model=MirrorValidationResultListResponse)
async def list_results(
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule_code: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mrv_svc.list_validation_results(
        session,
        run_id=run_id,
        target_type=target_type,
        target_id=target_id,
        severity=severity,
        status=status,
        rule_code=rule_code,
        resource_id=resource_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    return MirrorValidationResultListResponse(
        items=[MirrorValidationResultRead.model_validate(r) for r in items],
        total=total,
    )
