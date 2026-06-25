"""Final macro_clinical promotion API (Step 8.15)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.final_macro_clinical import (
    FinalMacroClinicalPromotionRecordListResponse,
    FinalMacroClinicalPromotionRequest,
    FinalMacroClinicalPromotionResponse,
    FinalMacroClinicalPromotionRunListResponse,
    FinalMacroClinicalPromotionRunRead,
    FinalObjectListResponse,
    FinalObjectRead,
)
from app.services import final_macro_clinical_promotion_service as fmps

router = APIRouter()


@router.post("/promotion/run", response_model=FinalMacroClinicalPromotionResponse)
async def run_promotion(
    body: FinalMacroClinicalPromotionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await fmps.run_final_macro_clinical_promotion(session, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/promotion/runs", response_model=FinalMacroClinicalPromotionRunListResponse)
async def list_runs(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    return await fmps.list_promotion_runs(session, status=status, limit=limit, offset=offset)


@router.get("/promotion/runs/{run_id}", response_model=FinalMacroClinicalPromotionRunRead)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    result = await fmps.list_promotion_runs(session, run_id=run_id, limit=1, offset=0)
    if not result.items:
        raise HTTPException(status_code=404, detail="run not found")
    return result.items[0]


@router.get("/promotion/records", response_model=FinalMacroClinicalPromotionRecordListResponse)
async def list_records(
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    mirror_object_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    return await fmps.list_promotion_records(
        session,
        run_id=run_id,
        target_type=target_type,
        mirror_object_id=mirror_object_id,
        limit=limit,
        offset=offset,
    )


@router.get("/objects/{target_type}", response_model=FinalObjectListResponse)
async def list_objects(
    target_type: str,
    source_mirror_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await fmps.list_final_objects(
            session,
            target_type=target_type,
            source_mirror_id=source_mirror_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/objects/{target_type}/{final_id}", response_model=FinalObjectRead)
async def get_object(
    target_type: str,
    final_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        obj = await fmps.get_final_object(session, target_type=target_type, final_object_id=final_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if obj is None:
        raise HTTPException(status_code=404, detail="final object not found")
    return obj
