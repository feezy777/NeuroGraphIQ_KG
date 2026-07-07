"""Connection pool REST API — analogous to candidate_pool but for MirrorRegionConnection records."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.connection_pool import (
    ConnectionPoolCreateRequest,
    ConnectionPoolListResponse,
    ConnectionPoolMembersDeleteRequest,
    ConnectionPoolMembersRequest,
    ConnectionPoolRead,
    ConnectionPoolReplaceRequest,
)
from app.services import connection_pool_service as svc

router = APIRouter()


@router.post("", response_model=ConnectionPoolRead, status_code=201)
async def create_pool(
    body: ConnectionPoolCreateRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return ConnectionPoolRead.model_validate(
            await svc.create_pool(
                session,
                name=body.name,
                connection_ids=body.connection_ids,
                scope_atlas=body.scope_atlas,
                scope_granularity=body.scope_granularity,
                source=body.source,
                resource_id=body.resource_id,
                batch_id=body.batch_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": str(exc)})


@router.post("/replace", response_model=ConnectionPoolRead)
async def replace_pool(
    body: ConnectionPoolReplaceRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return ConnectionPoolRead.model_validate(
            await svc.replace_pool_for_scope(
                session,
                name=body.name,
                connection_ids=body.connection_ids,
                scope_atlas=body.scope_atlas,
                scope_granularity=body.scope_granularity,
                source=body.source,
                resource_id=body.resource_id,
                batch_id=body.batch_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": str(exc)})


@router.get("", response_model=ConnectionPoolListResponse)
async def list_pools(
    scope_atlas: str | None = Query(None),
    scope_granularity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    rows, total = await svc.list_pools(
        session,
        scope_atlas=scope_atlas,
        scope_granularity=scope_granularity,
        limit=limit,
        offset=offset,
    )
    return ConnectionPoolListResponse(
        items=[ConnectionPoolRead.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{pool_id}", response_model=ConnectionPoolRead)
async def get_pool(
    pool_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    pool = await svc.get_pool(session, pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Pool {pool_id} not found"})
    return ConnectionPoolRead.model_validate(pool)


@router.delete("/{pool_id}", status_code=204)
async def delete_pool(
    pool_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    ok = await svc.delete_pool(session, pool_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Pool {pool_id} not found"})


@router.post("/{pool_id}/members", response_model=ConnectionPoolRead)
async def add_members(
    pool_id: uuid.UUID,
    body: ConnectionPoolMembersRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return ConnectionPoolRead.model_validate(
            await svc.add_members(session, pool_id, body.connection_ids)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@router.delete("/{pool_id}/members", response_model=ConnectionPoolRead)
async def remove_members(
    pool_id: uuid.UUID,
    body: ConnectionPoolMembersDeleteRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return ConnectionPoolRead.model_validate(
            await svc.remove_members(session, pool_id, body.connection_ids)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
