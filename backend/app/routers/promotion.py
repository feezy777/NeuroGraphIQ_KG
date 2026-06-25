from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.candidate import CandidateStatus, InvalidCandidateTransitionError
from app.schemas.promotion import (
    FinalBrainRegionListResponse,
    FinalBrainRegionRead,
    FinalRegionStatus,
    PromotionOptionsResponse,
    PromotionRecordListResponse,
    PromotionRecordRead,
    PromotionStatus,
    PromoteRequest,
    PromoteResponse,
)
from app.services import promotion_service

router = APIRouter()
candidate_router = APIRouter()


def _promote_response(final_region, record) -> PromoteResponse:
    return PromoteResponse(
        final_region=FinalBrainRegionRead.model_validate(final_region),
        record=PromotionRecordRead.model_validate(record),
    )


@router.get("/options", response_model=PromotionOptionsResponse)
async def get_promotion_options():
    return PromotionOptionsResponse(
        promotion_status=[e.value for e in PromotionStatus],
        final_region_status=[e.value for e in FinalRegionStatus],
        promotable_candidate_status=CandidateStatus.manual_approved.value,
        promoted_candidate_status=CandidateStatus.promoted_to_final.value,
    )


@candidate_router.post("/{candidate_id}/promote", response_model=PromoteResponse)
async def promote_candidate(
    candidate_id: uuid.UUID,
    body: PromoteRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        final_region, record = await promotion_service.promote_candidate(
            session, candidate_id, promoted_by=body.promoted_by, reason=body.reason
        )
    except promotion_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="candidate brain region not found") from exc
    except promotion_service.CandidateNotPromotableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except promotion_service.AlreadyPromotedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "candidate already promoted",
                "candidate_id": str(exc.candidate_id),
                "final_region_id": str(exc.final_region_id),
            },
        ) from exc
    except InvalidCandidateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _promote_response(final_region, record)


@candidate_router.get("/{candidate_id}/final-region", response_model=FinalBrainRegionRead)
async def get_final_region_for_candidate(
    candidate_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    row = await promotion_service.get_final_region_for_candidate(session, candidate_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail="no final region found for this candidate"
        )
    return FinalBrainRegionRead.model_validate(row)


@candidate_router.get(
    "/{candidate_id}/promotion-records", response_model=PromotionRecordListResponse
)
async def list_candidate_promotion_records(
    candidate_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await promotion_service.list_promotion_records(
        session, candidate_id=candidate_id, limit=limit, offset=offset
    )
    return PromotionRecordListResponse(
        items=[PromotionRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/final-regions", response_model=FinalBrainRegionListResponse)
async def list_final_regions(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    status: FinalRegionStatus | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await promotion_service.list_final_regions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )
    return FinalBrainRegionListResponse(
        items=[FinalBrainRegionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/final-regions/{final_region_id}", response_model=FinalBrainRegionRead)
async def get_final_region(
    final_region_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        row = await promotion_service.get_final_region(session, final_region_id)
    except promotion_service.FinalRegionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="final brain region not found") from exc
    return FinalBrainRegionRead.model_validate(row)


@router.get("/records", response_model=PromotionRecordListResponse)
async def list_promotion_records(
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    status: PromotionStatus | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await promotion_service.list_promotion_records(
        session,
        batch_id=batch_id,
        resource_id=resource_id,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )
    return PromotionRecordListResponse(
        items=[PromotionRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/records/{record_id}", response_model=PromotionRecordRead)
async def get_promotion_record(
    record_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        row = await promotion_service.get_promotion_record(session, record_id)
    except promotion_service.PromotionRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail="promotion record not found") from exc
    return PromotionRecordRead.model_validate(row)
