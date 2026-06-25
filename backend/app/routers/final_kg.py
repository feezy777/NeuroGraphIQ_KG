"""Final KG read-only API (Step 9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.final_kg import (
    FinalEvidenceRecordRead,
    FinalKgTripleRead,
    FinalListResponse,
    FinalRegionCircuitRead,
    FinalRegionConnectionRead,
    FinalRegionFunctionRead,
)
from app.services import final_kg_service as fks

router = APIRouter()


@router.get("/connections", response_model=FinalListResponse)
async def list_connections(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    final_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await fks.list_final_connections(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        final_status=final_status,
        limit=limit,
        offset=offset,
    )
    return FinalListResponse(
        items=[FinalRegionConnectionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/connections/{connection_id}", response_model=FinalRegionConnectionRead)
async def get_connection(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    row = await fks.get_final_connection(session, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Final connection not found")
    return FinalRegionConnectionRead.model_validate(row)


@router.get("/functions", response_model=FinalListResponse)
async def list_functions(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    final_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await fks.list_final_functions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        final_status=final_status,
        limit=limit,
        offset=offset,
    )
    return FinalListResponse(
        items=[FinalRegionFunctionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/functions/{function_id}", response_model=FinalRegionFunctionRead)
async def get_function(
    function_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    row = await fks.get_final_function(session, function_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Final function not found")
    return FinalRegionFunctionRead.model_validate(row)


@router.get("/circuits", response_model=FinalListResponse)
async def list_circuits(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    final_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await fks.list_final_circuits(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        final_status=final_status,
        limit=limit,
        offset=offset,
    )
    return FinalListResponse(
        items=[FinalRegionCircuitRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/circuits/{circuit_id}", response_model=FinalRegionCircuitRead)
async def get_circuit(
    circuit_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    row = await fks.get_final_circuit(session, circuit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Final circuit not found")
    return FinalRegionCircuitRead.model_validate(row)


@router.get("/triples", response_model=FinalListResponse)
async def list_triples(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    final_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await fks.list_final_triples(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        final_status=final_status,
        limit=limit,
        offset=offset,
    )
    return FinalListResponse(
        items=[FinalKgTripleRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/triples/{triple_id}", response_model=FinalKgTripleRead)
async def get_triple(
    triple_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    row = await fks.get_final_triple(session, triple_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Final triple not found")
    return FinalKgTripleRead.model_validate(row)


@router.get("/evidence", response_model=FinalListResponse)
async def list_evidence(
    evidence_target_type: str | None = None,
    evidence_target_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await fks.list_final_evidence(
        session,
        evidence_target_type=evidence_target_type,
        evidence_target_id=evidence_target_id,
        resource_id=resource_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    return FinalListResponse(
        items=[FinalEvidenceRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
