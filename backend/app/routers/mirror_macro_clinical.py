"""Mirror KG macro_clinical alignment API (Step 8.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.macro_clinical_promotion_candidate import (
    CircuitFunctionPromotionAttemptResponse,
    CircuitFunctionPromotionCandidateListResponse,
    CircuitFunctionPromotionPreviewResponse,
)
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitProjectionMembershipCreate,
    MirrorCircuitProjectionMembershipListResponse,
    MirrorCircuitProjectionMembershipRead,
    MirrorCircuitFunctionListResponse,
    MirrorCircuitFunctionRead,
    MirrorCircuitStepCreate,
    MirrorCircuitStepListResponse,
    MirrorCircuitStepRead,
    MirrorDualModelVerificationResultCreate,
    MirrorDualModelVerificationResultListResponse,
    MirrorDualModelVerificationResultRead,
    MirrorDualModelVerificationRunCreate,
    MirrorDualModelVerificationRunListResponse,
    MirrorDualModelVerificationRunRead,
    MirrorProjectionFunctionCreate,
    MirrorProjectionFunctionListResponse,
    MirrorProjectionFunctionRead,
)
from app.services import macro_clinical_promotion_candidate_service as promo_svc
from app.services import mirror_macro_clinical_service as svc

router = APIRouter()


def _400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _404(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _503_circuit_functions_not_initialized(
    exc: svc.MirrorCircuitFunctionsNotInitializedError,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED",
            "message": (
                "mirror_circuit_functions table is not initialized. "
                "Please run backend/migrations/033_mirror_circuit_functions.sql."
            ),
            "migration": exc.migration_path,
        },
    )


@router.get("/circuit-steps", response_model=MirrorCircuitStepListResponse)
async def list_circuit_steps(
    circuit_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await svc.list_circuit_steps(
        session,
        circuit_id=circuit_id,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        llm_run_id=llm_run_id,
        limit=limit,
        offset=offset,
    )
    return MirrorCircuitStepListResponse(
        items=[MirrorCircuitStepRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/circuit-steps", response_model=MirrorCircuitStepRead, status_code=201)
async def create_circuit_step(
    body: MirrorCircuitStepCreate,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.create_circuit_step(session, body)
        await session.commit()
        return MirrorCircuitStepRead.model_validate(row)
    except svc.MirrorCircuitNotFoundError as exc:
        raise _404(exc) from exc
    except (
        svc.SameGranularityValidationError,
        svc.DuplicateStepOrderError,
    ) as exc:
        raise _400(exc) from exc


@router.get("/circuit-steps/{step_id}", response_model=MirrorCircuitStepRead)
async def get_circuit_step(
    step_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.get_circuit_step(session, step_id)
        return MirrorCircuitStepRead.model_validate(row)
    except svc.MirrorCircuitStepNotFoundError as exc:
        raise _404(exc) from exc


@router.get("/projection-functions", response_model=MirrorProjectionFunctionListResponse)
async def list_projection_functions(
    projection_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await svc.list_projection_functions(
        session,
        projection_id=projection_id,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        llm_run_id=llm_run_id,
        limit=limit,
        offset=offset,
    )
    return MirrorProjectionFunctionListResponse(
        items=[MirrorProjectionFunctionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/projection-functions", response_model=MirrorProjectionFunctionRead, status_code=201)
async def create_projection_function(
    body: MirrorProjectionFunctionCreate,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.create_projection_function(session, body)
        await session.commit()
        return MirrorProjectionFunctionRead.model_validate(row)
    except svc.MirrorProjectionNotFoundError as exc:
        raise _404(exc) from exc
    except svc.SameGranularityValidationError as exc:
        raise _400(exc) from exc


@router.get("/projection-functions/{projection_function_id}", response_model=MirrorProjectionFunctionRead)
async def get_projection_function(
    projection_function_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.get_projection_function(session, projection_function_id)
        return MirrorProjectionFunctionRead.model_validate(row)
    except svc.MirrorProjectionFunctionNotFoundError as exc:
        raise _404(exc) from exc


@router.get("/circuit-functions", response_model=MirrorCircuitFunctionListResponse)
async def list_circuit_functions(
    circuit_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    function_domain: str | None = None,
    function_role: str | None = None,
    effect_type: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    validation_status: str | None = None,
    promotion_status: str | None = None,
    status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        items, total = await svc.list_mirror_circuit_functions(
            session,
            circuit_id=circuit_id,
            resource_id=resource_id,
            batch_id=batch_id,
            source_atlas=source_atlas,
            granularity_level=granularity_level,
            granularity_family=granularity_family,
            function_domain=function_domain,
            function_role=function_role,
            effect_type=effect_type,
            mirror_status=mirror_status,
            review_status=review_status,
            validation_status=validation_status,
            promotion_status=promotion_status,
            status=status,
            llm_run_id=llm_run_id,
            q=q,
            limit=limit,
            offset=offset,
        )
    except svc.MirrorCircuitFunctionsNotInitializedError as exc:
        raise _503_circuit_functions_not_initialized(exc) from exc
    return MirrorCircuitFunctionListResponse(
        items=[MirrorCircuitFunctionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
        warnings=[],
    )


@router.get("/circuit-functions/{circuit_function_id}", response_model=MirrorCircuitFunctionRead)
async def get_circuit_function(
    circuit_function_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.get_mirror_circuit_function(session, circuit_function_id)
        return MirrorCircuitFunctionRead.model_validate(row)
    except svc.MirrorCircuitFunctionsNotInitializedError as exc:
        raise _503_circuit_functions_not_initialized(exc) from exc
    except svc.MirrorCircuitFunctionNotFoundError as exc:
        raise _404(exc) from exc


@router.get("/circuit-projection-memberships", response_model=MirrorCircuitProjectionMembershipListResponse)
async def list_circuit_projection_memberships(
    circuit_id: uuid.UUID | None = None,
    projection_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    verification_status: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await svc.list_circuit_projection_memberships(
        session,
        circuit_id=circuit_id,
        projection_id=projection_id,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        verification_status=verification_status,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        limit=limit,
        offset=offset,
    )
    return MirrorCircuitProjectionMembershipListResponse(
        items=[MirrorCircuitProjectionMembershipRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/circuit-projection-memberships",
    response_model=MirrorCircuitProjectionMembershipRead,
    status_code=201,
)
async def create_circuit_projection_membership(
    body: MirrorCircuitProjectionMembershipCreate,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.create_circuit_projection_membership(session, body)
        await session.commit()
        return MirrorCircuitProjectionMembershipRead.model_validate(row)
    except (svc.MirrorCircuitNotFoundError, svc.MirrorProjectionNotFoundError) as exc:
        raise _404(exc) from exc
    except (
        svc.SameGranularityValidationError,
        svc.InvalidStepReferenceError,
        svc.DuplicateMembershipError,
    ) as exc:
        raise _400(exc) from exc


@router.get(
    "/circuit-projection-memberships/{membership_id}",
    response_model=MirrorCircuitProjectionMembershipRead,
)
async def get_circuit_projection_membership(
    membership_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.get_circuit_projection_membership(session, membership_id)
        return MirrorCircuitProjectionMembershipRead.model_validate(row)
    except svc.MirrorMembershipNotFoundError as exc:
        raise _404(exc) from exc


@router.get("/dual-model-verification/runs", response_model=MirrorDualModelVerificationRunListResponse)
async def list_dual_model_verification_runs(
    verification_task_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await svc.list_dual_model_verification_runs(
        session,
        verification_task_type=verification_task_type,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        status=status,
        limit=limit,
        offset=offset,
    )
    return MirrorDualModelVerificationRunListResponse(
        items=[MirrorDualModelVerificationRunRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/dual-model-verification/runs", response_model=MirrorDualModelVerificationRunRead, status_code=201)
async def create_dual_model_verification_run(
    body: MirrorDualModelVerificationRunCreate,
    session: AsyncSession = Depends(get_db),
):
    row = await svc.create_dual_model_verification_run(session, body)
    await session.commit()
    return MirrorDualModelVerificationRunRead.model_validate(row)


@router.get("/dual-model-verification/runs/{run_id}", response_model=MirrorDualModelVerificationRunRead)
async def get_dual_model_verification_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.get_dual_model_verification_run(session, run_id)
        return MirrorDualModelVerificationRunRead.model_validate(row)
    except svc.MirrorDualModelRunNotFoundError as exc:
        raise _404(exc) from exc


@router.get("/dual-model-verification/results", response_model=MirrorDualModelVerificationResultListResponse)
async def list_dual_model_verification_results(
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
    items, total = await svc.list_dual_model_verification_results(
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
    return MirrorDualModelVerificationResultListResponse(
        items=[MirrorDualModelVerificationResultRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/dual-model-verification/results",
    response_model=MirrorDualModelVerificationResultRead,
    status_code=201,
)
async def create_dual_model_verification_result(
    body: MirrorDualModelVerificationResultCreate,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.create_dual_model_verification_result(session, body)
        await session.commit()
        return MirrorDualModelVerificationResultRead.model_validate(row)
    except svc.MirrorDualModelRunNotFoundError as exc:
        raise _404(exc) from exc
    except svc.VerificationObjectNotFoundError as exc:
        raise _404(exc) from exc


@router.get(
    "/dual-model-verification/results/{result_id}",
    response_model=MirrorDualModelVerificationResultRead,
)
async def get_dual_model_verification_result(
    result_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await svc.get_dual_model_verification_result(session, result_id)
        return MirrorDualModelVerificationResultRead.model_validate(row)
    except svc.MirrorDualModelResultNotFoundError as exc:
        raise _404(exc) from exc


def _403_promotion(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": code, "message": message})


def _503_formal_table_not_initialized() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "FORMAL_CIRCUIT_FUNCTION_TABLE_NOT_INITIALIZED",
            "message": "macro_clinical.circuit_function formal table is not initialized in this environment.",
        },
    )


@router.get(
    "/promotion-candidates",
    response_model=CircuitFunctionPromotionCandidateListResponse,
)
async def list_promotion_candidates(
    target_type: str = Query(..., description="Promotion target type, e.g. circuit_function"),
    circuit_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    if target_type != "circuit_function":
        raise HTTPException(status_code=400, detail=f"unsupported target_type: {target_type}")
    try:
        return await promo_svc.list_circuit_function_promotion_candidates(
            session,
            circuit_id=circuit_id,
            resource_id=resource_id,
            batch_id=batch_id,
            review_status=review_status,
            promotion_status=promotion_status,
            limit=limit,
            offset=offset,
        )
    except svc.MirrorCircuitFunctionsNotInitializedError as exc:
        raise _503_circuit_functions_not_initialized(exc) from exc


@router.get(
    "/promotion-candidates/circuit_function/{source_id}/preview",
    response_model=CircuitFunctionPromotionPreviewResponse,
)
async def preview_circuit_function_promotion_candidate(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await promo_svc.preview_circuit_function_promotion_candidate(session, source_id)
    except svc.MirrorCircuitFunctionsNotInitializedError as exc:
        raise _503_circuit_functions_not_initialized(exc) from exc
    except promo_svc.CircuitFunctionPromotionCandidateNotFoundError as exc:
        raise _404(exc) from exc


@router.post(
    "/promotion-candidates/circuit_function/{source_id}/promote",
    response_model=CircuitFunctionPromotionAttemptResponse,
)
async def attempt_circuit_function_promotion(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await promo_svc.attempt_circuit_function_promotion(session, source_id)
    except svc.MirrorCircuitFunctionsNotInitializedError as exc:
        raise _503_circuit_functions_not_initialized(exc) from exc
    except promo_svc.CircuitFunctionPromotionCandidateNotFoundError as exc:
        raise _404(exc) from exc
    except promo_svc.ReviewRequiredForPromotionError:
        raise _403_promotion(
            "REVIEW_REQUIRED",
            "Manual review approval is required before circuit_function promotion.",
        ) from None
    except promo_svc.FormalCircuitFunctionTableNotInitializedError:
        raise _503_formal_table_not_initialized() from None
    except promo_svc.CircuitFunctionActualPromotionDisabledError as exc:
        raise _403_promotion(exc.code, "Actual circuit_function promotion is not enabled in this release.") from None
