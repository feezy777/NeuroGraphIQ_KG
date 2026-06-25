"""Final DB Query — read-only API for final_brain_regions.

This module provides query/browse/search access to the official final brain
region store. It never writes to any table (no INSERT / UPDATE / DELETE).
Does NOT trigger promotion, review, or LLM. Does NOT expose kg_*.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.promotion import (
    FinalBrainRegionListResponse,
    FinalBrainRegionRead,
    FinalRegionStatus,
    PromotionRecordListResponse,
    PromotionRecordRead,
)
from app.services import final_db_query_service as fqs
from app.services import promotion_service

router = APIRouter()


@router.get("/options")
async def get_final_db_options():
    return {
        "status": [e.value for e in FinalRegionStatus],
        "laterality": ["left", "right", "bilateral", "midline", "unknown"],
        "description": "Read-only query API for final_brain_regions. No writes.",
    }


@router.get("", response_model=FinalBrainRegionListResponse)
async def list_final_brain_regions(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    source_version: str | None = None,
    laterality: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: FinalRegionStatus | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await fqs.list_final_regions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        source_version=source_version,
        laterality=laterality,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        status=status.value if status else None,
        keyword=keyword or None,
        limit=limit,
        offset=offset,
    )
    return FinalBrainRegionListResponse(
        items=[FinalBrainRegionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary")
async def get_final_region_summary(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db),
):
    return await fqs.summary(session, resource_id=resource_id, batch_id=batch_id)


@router.get("/{final_region_id}", response_model=FinalBrainRegionRead)
async def get_final_brain_region(
    final_region_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        row = await fqs.get_final_region(session, final_region_id)
    except fqs.FinalRegionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="final brain region not found") from exc
    return FinalBrainRegionRead.model_validate(row)


@router.get("/{final_region_id}/provenance")
async def get_final_region_provenance(
    final_region_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    """Return the final region plus all promotion records (full audit trail)."""
    try:
        region, records = await fqs.get_final_region_provenance(session, final_region_id)
    except fqs.FinalRegionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="final brain region not found") from exc
    return {
        "final_region": FinalBrainRegionRead.model_validate(region),
        "promotion_records": [PromotionRecordRead.model_validate(r) for r in records],
    }


@router.get("/{final_region_id}/promotion-records", response_model=PromotionRecordListResponse)
async def list_final_region_promotion_records(
    final_region_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        region = await fqs.get_final_region(session, final_region_id)
    except fqs.FinalRegionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="final brain region not found") from exc

    items, total = await promotion_service.list_promotion_records(
        session, candidate_id=region.candidate_id, limit=limit, offset=offset
    )
    return PromotionRecordListResponse(
        items=[PromotionRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
