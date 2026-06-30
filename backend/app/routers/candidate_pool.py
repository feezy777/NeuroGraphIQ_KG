"""Candidate Pool REST API."""

from __future__ import annotations

import uuid

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.candidate_pool import (
    CandidatePoolCreate,
    CandidatePoolMembersAdd,
    CandidatePoolMembersRemove,
    CandidatePoolRead,
    CandidatePoolReplace,
)
from app.services import candidate_pool_service as svc

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/pools", response_model=CandidatePoolRead, status_code=201)
async def create_pool(body: CandidatePoolCreate, db: AsyncSession = Depends(get_db)):
    try:
        pool = await svc.create_pool(
            db,
            name=body.name,
            candidate_ids=body.candidate_ids,
            resource_id=body.resource_id,
            batch_id=body.batch_id,
            source_atlas=body.source_atlas,
            granularity_level=body.granularity_level,
            granularity_family=body.granularity_family,
        )
        await db.commit()
        return pool
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pools/replace", response_model=CandidatePoolRead)
async def replace_pool(body: CandidatePoolReplace, db: AsyncSession = Depends(get_db)):
    """Replace scope pool members atomically (create pool if missing). Safe to retry."""
    try:
        pool = await svc.replace_pool_for_scope(
            db,
            name=body.name,
            candidate_ids=body.candidate_ids,
            resource_id=body.resource_id,
            batch_id=body.batch_id,
            source_atlas=body.source_atlas,
            granularity_level=body.granularity_level,
            granularity_family=body.granularity_family,
        )
        await db.commit()
        return pool
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("[candidate-pool][replace] failed")
        raise HTTPException(status_code=503, detail=str(exc)[:500]) from exc


@router.get("/pools", response_model=dict)
async def list_pools(
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    pools, total = await svc.list_pools(
        db,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        status=status,
        limit=limit,
        offset=offset,
    )
    from app.schemas.candidate_pool import CandidatePoolRead
    return {"items": [CandidatePoolRead.model_validate(p) for p in pools], "total": total}


@router.get("/pools/{pool_id}", response_model=CandidatePoolRead)
async def get_pool(
    pool_id: uuid.UUID,
    include_memberships: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    try:
        pool = await svc.get_pool(db, pool_id, include_memberships=include_memberships)
    except SQLAlchemyError as exc:
        logger.exception("[candidate-pool][get] pool_id=%s", pool_id)
        raise HTTPException(status_code=503, detail=str(exc)[:500]) from exc
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool not found")
    return CandidatePoolRead.model_validate(pool)


@router.post("/pools/{pool_id}/members", response_model=CandidatePoolRead)
async def add_members(pool_id: uuid.UUID, body: CandidatePoolMembersAdd, db: AsyncSession = Depends(get_db)):
    try:
        pool = await svc.add_members(db, pool_id, body.candidate_ids)
        await db.commit()
        return pool
    except KeyError:
        raise HTTPException(status_code=404, detail="Pool not found")


@router.delete("/pools/{pool_id}/members", response_model=CandidatePoolRead)
async def remove_members(pool_id: uuid.UUID, body: CandidatePoolMembersRemove, db: AsyncSession = Depends(get_db)):
    try:
        pool = await svc.remove_members(db, pool_id, body.candidate_ids)
        await db.commit()
        return pool
    except KeyError:
        raise HTTPException(status_code=404, detail="Pool not found")


@router.delete("/pools/{pool_id}", status_code=204)
async def delete_pool(pool_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await svc.delete_pool(db, pool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pool not found")
    await db.commit()
