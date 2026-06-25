"""Mirror KG Promotion API (Step 9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.mirror_promotion import (
    MirrorPromotionRecordListResponse,
    MirrorPromotionRecordRead,
    MirrorPromotionRequest,
    MirrorPromotionResponse,
    MirrorPromotionRunDetail,
    MirrorPromotionRunListResponse,
    MirrorPromotionRunRead,
)
from app.services import mirror_promotion_service as mps

router = APIRouter()


@router.post("/preview", response_model=MirrorPromotionResponse)
async def preview_mirror_promotion(
    body: MirrorPromotionRequest,
    session: AsyncSession = Depends(get_db),
):
    body = body.model_copy(update={"dry_run": True})
    try:
        return await mps.build_promotion_preview(session, body)
    except mps.EmptyTargetTypesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mps.InvalidTargetTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run", response_model=MirrorPromotionResponse)
async def run_mirror_promotion(
    body: MirrorPromotionRequest,
    session: AsyncSession = Depends(get_db),
):
    body = body.model_copy(update={"dry_run": False})
    try:
        return await mps.run_mirror_promotion(session, body)
    except mps.EmptyTargetTypesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mps.InvalidTargetTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mps.MissingOperatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mps.MissingReasonError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mps.ConfirmationMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs", response_model=MirrorPromotionRunListResponse)
async def list_promotion_runs(
    target_type: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mps.list_promotion_runs(
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
    return MirrorPromotionRunListResponse(
        items=[MirrorPromotionRunRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=MirrorPromotionRunDetail)
async def get_promotion_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await mps.get_promotion_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Promotion run not found")

    from app.models.mirror_promotion import MirrorPromotionRecord

    summary_rows = (
        await session.execute(
            select(MirrorPromotionRecord.status, func.count())
            .where(MirrorPromotionRecord.run_id == run_id)
            .group_by(MirrorPromotionRecord.status)
        )
    ).all()
    records_summary = {status: int(cnt) for status, cnt in summary_rows}

    data = MirrorPromotionRunRead.model_validate(run).model_dump()
    return MirrorPromotionRunDetail(**data, records_summary=records_summary)


@router.get("/records", response_model=MirrorPromotionRecordListResponse)
async def list_promotion_records(
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    mirror_target_id: uuid.UUID | None = None,
    final_target_type: str | None = None,
    final_target_id: uuid.UUID | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await mps.list_promotion_records(
        session,
        run_id=run_id,
        target_type=target_type,
        mirror_target_id=mirror_target_id,
        final_target_type=final_target_type,
        final_target_id=final_target_id,
        status=status,
        resource_id=resource_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    return MirrorPromotionRecordListResponse(
        items=[MirrorPromotionRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
