"""Dual-model verification execution API (Step 8.12)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.mirror_dual_model_verification import (
    DualModelVerificationRequest,
    DualModelVerificationResponse,
    DualModelVerificationResultListResponse,
    DualModelVerificationResultPreview,
    DualModelVerificationRunListResponse,
)
from app.schemas.mirror_macro_clinical import (
    MirrorDualModelVerificationResultRead,
    MirrorDualModelVerificationRunRead,
)
from app.services import mirror_dual_model_verification_service as dm_svc
from app.services import mirror_macro_clinical_service as mc_svc
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_providers import UnknownProviderError
from app.services.mirror_dual_model_verification_service import VerificationScope

router = APIRouter()


def _scope_from_body(scope) -> VerificationScope:
    if scope is None:
        return VerificationScope()
    return VerificationScope(
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        source_version=scope.source_version,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
    )


@router.post("/run", response_model=DualModelVerificationResponse)
async def run_dual_model_verification(
    body: DualModelVerificationRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await dm_svc.run_dual_model_verification(
            session,
            object_type=body.object_type,
            object_ids=body.object_ids,
            scope=_scope_from_body(body.scope),
            model_a_provider=body.model_a_provider,
            model_a_name=body.model_a_name,
            model_b_provider=body.model_b_provider,
            model_b_name=body.model_b_name,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_objects=body.max_objects,
            include_cross_validation_context=body.include_cross_validation_context,
            include_evidence_context=body.include_evidence_context,
            include_review_context=body.include_review_context,
            create_results=body.create_results,
        )
    except dm_svc.InvalidObjectTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except dm_svc.EmptyObjectsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except dm_svc.TooManyObjectsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except dm_svc.ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except dm_svc.CrossAtlasObjectError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_ATLAS", "message": str(exc)}) from exc
    except dm_svc.CrossGranularityObjectError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_GRANULARITY", "message": str(exc)}) from exc
    except dm_svc.SameProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preview = [DualModelVerificationResultPreview(**p) for p in result.results_preview]
    return DualModelVerificationResponse(
        run_id=result.run_id,
        object_type=result.object_type,
        object_count=result.object_count,
        model_a_provider=result.model_a_provider,
        model_a_run_id=result.model_a_run_id,
        model_b_provider=result.model_b_provider,
        model_b_run_id=result.model_b_run_id,
        consensus_supported_count=result.consensus_supported_count,
        consensus_rejected_count=result.consensus_rejected_count,
        model_conflict_count=result.model_conflict_count,
        insufficient_information_count=result.insufficient_information_count,
        needs_human_review_count=result.needs_human_review_count,
        result_count=result.result_count,
        dry_run=result.dry_run,
        model_a_system_prompt=result.model_a_system_prompt,
        model_a_user_prompt=result.model_a_user_prompt,
        model_b_system_prompt=result.model_b_system_prompt,
        model_b_user_prompt=result.model_b_user_prompt,
        results_preview=preview,
        warnings=result.warnings,
    )


@router.get("/runs", response_model=DualModelVerificationRunListResponse)
async def list_runs(
    verification_task_type: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mc_svc.list_dual_model_verification_runs(
        session,
        verification_task_type=verification_task_type,
        status=status,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return DualModelVerificationRunListResponse(
        items=[MirrorDualModelVerificationRunRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=MirrorDualModelVerificationRunRead)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await mc_svc.get_dual_model_verification_run(session, run_id)
        return MirrorDualModelVerificationRunRead.model_validate(row)
    except mc_svc.MirrorDualModelRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/results", response_model=DualModelVerificationResultListResponse)
async def list_results(
    run_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    consensus_status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mc_svc.list_dual_model_verification_results(
        session,
        run_id=run_id,
        object_type=object_type,
        object_id=object_id,
        consensus_status=consensus_status,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return DualModelVerificationResultListResponse(
        items=[MirrorDualModelVerificationResultRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
