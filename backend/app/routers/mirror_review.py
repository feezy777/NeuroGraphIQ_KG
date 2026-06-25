"""Mirror KG Human Review API (Step 8)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.mirror_review import (
    MirrorReviewActionRequest,
    MirrorReviewActionResponse,
    MirrorReviewDetail,
    MirrorReviewQueueItem,
    MirrorReviewQueueResponse,
    MirrorReviewRecordListResponse,
    MirrorReviewRecordRead,
    MirrorReviewTargetTypeInfo,
    MirrorReviewTargetTypesResponse,
)
from app.services import mirror_review_service as mrs
from app.services.mirror_review_service import QueueScope

router = APIRouter()


def _split_query_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return values
    if len(values) == 1 and "," in values[0]:
        return [v.strip() for v in values[0].split(",") if v.strip()]
    return values


@router.get("/queue", response_model=MirrorReviewQueueResponse)
async def list_review_queue(
    target_types: list[str] | None = Query(default=None),
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    source_version: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: list[str] | None = Query(default=None),
    review_status: list[str] | None = Query(default=None),
    promotion_status: list[str] | None = Query(default=None),
    has_blocker: bool | None = None,
    has_error: bool | None = None,
    has_warning: bool | None = None,
    has_model_conflict: bool | None = None,
    has_cross_conflict: bool | None = None,
    consensus_status: str | None = None,
    verification_status: str | None = None,
    recommended_review_priority: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        items, total = await mrs.list_mirror_review_queue(
            session,
            QueueScope(
                target_types=_split_query_list(target_types),
                resource_id=resource_id,
                batch_id=batch_id,
                source_atlas=source_atlas,
                source_version=source_version,
                granularity_level=granularity_level,
                granularity_family=granularity_family,
                mirror_statuses=mirror_status,
                review_statuses=review_status,
                promotion_statuses=promotion_status,
                has_blocker=has_blocker,
                has_error=has_error,
                has_warning=has_warning,
                has_model_conflict=has_model_conflict,
                has_cross_conflict=has_cross_conflict,
                consensus_status=consensus_status,
                verification_status=verification_status,
                recommended_review_priority=recommended_review_priority,
                search=search,
                limit=limit,
                offset=offset,
            ),
        )
    except mrs.InvalidTargetTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MirrorReviewQueueResponse(
        items=[MirrorReviewQueueItem.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/detail/{target_type}/{target_id}", response_model=MirrorReviewDetail)
async def get_review_detail(
    target_type: str,
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        detail = await mrs.get_mirror_review_detail(session, target_type, target_id)
    except mrs.InvalidTargetTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrs.TargetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MirrorReviewDetail.model_validate(detail)


@router.post("/action", response_model=MirrorReviewActionResponse)
async def submit_review_action(
    body: MirrorReviewActionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        record, updated, warnings = await mrs.perform_mirror_review_action(
            session,
            target_type=body.target_type,
            target_id=body.target_id,
            action=body.action,
            reviewer=body.reviewer,
            reviewer_note=body.reviewer_note,
            edit_patch_json=body.edit_patch_json,
            allow_with_warnings=body.allow_with_warnings,
        )
    except mrs.InvalidTargetTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrs.TargetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mrs.ReviewerNoteRequiredError as exc:
        raise HTTPException(status_code=400, detail="reviewer_note is required") from exc
    except mrs.ReviewerReasonRequiredError as exc:
        raise HTTPException(status_code=400, detail="reviewer_note is required for approve with warnings/conflicts") from exc
    except mrs.DomainActionOnSignalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrs.SignalActionOnDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrs.EditPatchEmptyError as exc:
        raise HTTPException(status_code=400, detail="edit_patch_json is empty") from exc
    except mrs.ForbiddenEditFieldError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrs.InvalidReviewActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mrs.MirrorObjectNotValidatedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "MIRROR_OBJECT_NOT_VALIDATED", "message": str(exc)},
        ) from exc
    except mrs.MirrorObjectHasBlockersError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "MIRROR_OBJECT_HAS_BLOCKERS", "message": str(exc), "summary": exc.summary},
        ) from exc
    except mrs.TargetAlreadyPromotedError as exc:
        raise HTTPException(status_code=409, detail="target already promoted") from exc
    except mrs.TargetNotReviewableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MirrorReviewActionResponse(
        review_record_id=record.id,
        target_type=body.target_type,
        target_id=body.target_id,
        action=body.action,
        from_mirror_status=record.from_mirror_status,
        to_mirror_status=record.to_mirror_status,
        from_review_status=record.from_review_status,
        to_review_status=record.to_review_status,
        promotion_status=updated.get("promotion_status"),
        updated_object=updated,
        warnings=warnings,
    )


@router.get("/records", response_model=MirrorReviewRecordListResponse)
async def list_records(
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    action: str | None = None,
    reviewer: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mrs.list_review_records(
        session,
        target_type=target_type,
        target_id=target_id,
        action=action,
        reviewer=reviewer,
        resource_id=resource_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    return MirrorReviewRecordListResponse(
        items=[MirrorReviewRecordRead.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/target-types", response_model=MirrorReviewTargetTypesResponse)
async def list_target_types():
    return MirrorReviewTargetTypesResponse(
        items=[MirrorReviewTargetTypeInfo.model_validate(i) for i in mrs.list_review_target_types()],
    )
