"""Final macro_clinical browser API (Step 8.16, read-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.final_macro_clinical_browser import (
    FinalBrowserSearchResponse,
    FinalCircuitDetailResponse,
    FinalGraphResponse,
    FinalObjectDetailResponse,
    FinalProjectionDetailResponse,
    FinalRegionNeighborhoodResponse,
)
from app.services import final_macro_clinical_browser_service as fmbs

router = APIRouter()


def _split_query_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out: list[str] = []
    for v in values:
        out.extend(part.strip() for part in v.split(",") if part.strip())
    return out or None


@router.get("/browser/search", response_model=FinalBrowserSearchResponse)
async def search_objects(
    query: str | None = None,
    target_types: list[str] | None = Query(default=None),
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    final_status: str | None = None,
    region_candidate_id: uuid.UUID | None = None,
    circuit_id: uuid.UUID | None = None,
    projection_id: uuid.UUID | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await fmbs.search_final_objects(
            session,
            query=query,
            target_types=_split_query_list(target_types),
            source_atlas=source_atlas,
            granularity_level=granularity_level,
            granularity_family=granularity_family,
            resource_id=resource_id,
            batch_id=batch_id,
            final_status=final_status,
            region_candidate_id=region_candidate_id,
            circuit_id=circuit_id,
            projection_id=projection_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/browser/region/{region_candidate_id}", response_model=FinalRegionNeighborhoodResponse)
async def region_neighborhood(
    region_candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    return await fmbs.get_final_region_neighborhood(session, region_candidate_id)


@router.get("/browser/circuit/{final_circuit_id}", response_model=FinalCircuitDetailResponse)
async def circuit_detail(
    final_circuit_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    result = await fmbs.get_final_circuit_detail(session, final_circuit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="circuit not found")
    return result


@router.get("/browser/projection/{final_projection_id}", response_model=FinalProjectionDetailResponse)
async def projection_detail(
    final_projection_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    result = await fmbs.get_final_projection_detail(session, final_projection_id)
    if result is None:
        raise HTTPException(status_code=404, detail="projection not found")
    return result


@router.get("/browser/object/{target_type}/{final_id}", response_model=FinalObjectDetailResponse)
async def object_detail(
    target_type: str,
    final_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await fmbs.get_final_object_detail(session, target_type, final_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="final object not found")
    return result


@router.get("/browser/graph", response_model=FinalGraphResponse)
async def graph_view(
    center_type: str = Query(...),
    center_id: uuid.UUID = Query(...),
    depth: int = Query(default=1, ge=1, le=3),
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    include_functions: bool = True,
    include_evidence: bool = False,
    include_triples: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await fmbs.get_final_graph(
            session,
            center_type=center_type,
            center_id=center_id,
            depth=depth,
            source_atlas=source_atlas,
            granularity_level=granularity_level,
            include_functions=include_functions,
            include_evidence=include_evidence,
            include_triples=include_triples,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
