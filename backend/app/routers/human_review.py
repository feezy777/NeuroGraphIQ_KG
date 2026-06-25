from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.candidate import CandidateBrainRegionRead, CandidateStatus
from app.schemas.human_review import (
    CandidateReviewRecordListResponse,
    CandidateReviewRecordRead,
    HumanReviewOptionsResponse,
    PendingReviewListResponse,
    ReviewAction,
    ReviewActionResponse,
    ReviewDecisionRequest,
    ReviewSubmitRequest,
)
from app.schemas.candidate import InvalidCandidateTransitionError
from app.services import human_review_service

router = APIRouter()
candidate_router = APIRouter()


def _action_response(candidate, record) -> ReviewActionResponse:
    return ReviewActionResponse(
        candidate=CandidateBrainRegionRead.model_validate(candidate),
        record=CandidateReviewRecordRead.model_validate(record),
    )


@router.get("/options", response_model=HumanReviewOptionsResponse)
async def get_human_review_options():
    return HumanReviewOptionsResponse(
        actions=[e.value for e in ReviewAction],
        decision_actions=[
            ReviewAction.approve.value,
            ReviewAction.reject.value,
            ReviewAction.request_changes.value,
            ReviewAction.mark_uncertain.value,
        ],
        pending_status=CandidateStatus.manual_review_pending.value,
        approved_status=CandidateStatus.manual_approved.value,
        rejected_status=CandidateStatus.manual_rejected.value,
    )


@router.get("/pending", response_model=PendingReviewListResponse)
async def list_pending_review(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await human_review_service.list_pending_candidates(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        limit=limit,
        offset=offset,
    )
    return PendingReviewListResponse(
        items=[CandidateBrainRegionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/records", response_model=CandidateReviewRecordListResponse)
async def list_review_records(
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    action: ReviewAction | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await human_review_service.list_records(
        session,
        batch_id=batch_id,
        resource_id=resource_id,
        action=action.value if action else None,
        limit=limit,
        offset=offset,
    )
    return CandidateReviewRecordListResponse(
        items=[CandidateReviewRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/records/{record_id}", response_model=CandidateReviewRecordRead)
async def get_review_record(record_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await human_review_service.get_record(session, record_id)
    except human_review_service.ReviewRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail="review record not found") from exc
    return CandidateReviewRecordRead.model_validate(row)


@candidate_router.post("/{candidate_id}/submit-review", response_model=ReviewActionResponse)
async def submit_candidate_to_review(
    candidate_id: uuid.UUID,
    body: ReviewSubmitRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        candidate, record = await human_review_service.submit_candidate_to_review(
            session, candidate_id, reviewed_by=body.reviewed_by, reason=body.reason
        )
    except human_review_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="candidate brain region not found") from exc
    except InvalidCandidateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_response(candidate, record)


@candidate_router.post("/{candidate_id}/review", response_model=ReviewActionResponse)
async def review_candidate(
    candidate_id: uuid.UUID,
    body: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        candidate, record = await human_review_service.decide_candidate(
            session,
            candidate_id,
            action=body.action,
            reviewed_by=body.reviewed_by,
            reason=body.reason,
        )
    except human_review_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="candidate brain region not found") from exc
    except human_review_service.InvalidReviewActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except human_review_service.CandidateNotInReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidCandidateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_response(candidate, record)


@candidate_router.get(
    "/{candidate_id}/review-records", response_model=CandidateReviewRecordListResponse
)
async def list_candidate_review_records(
    candidate_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await human_review_service.list_candidate_records(
        session, candidate_id, limit=limit, offset=offset
    )
    return CandidateReviewRecordListResponse(
        items=[CandidateReviewRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
