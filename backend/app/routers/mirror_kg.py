"""Mirror KG API — list/create/get for mirror precursor entities (NOT final_*)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.mirror_kg import (
    MirrorEvidenceRecordCreate,
    MirrorEvidenceRecordListResponse,
    MirrorEvidenceRecordRead,
    MirrorKgTripleCreate,
    MirrorKgTripleListResponse,
    MirrorKgTripleRead,
    MirrorRegionCircuitCreate,
    MirrorRegionCircuitListResponse,
    MirrorRegionCircuitRead,
    MirrorRegionConnectionCreate,
    MirrorRegionConnectionListResponse,
    MirrorRegionConnectionRead,
    MirrorRegionFunctionCreate,
    MirrorRegionFunctionListResponse,
    MirrorRegionFunctionRead,
    MirrorCircuitRegionRead,
    MirrorTripleConsolidationRequest,
    MirrorTripleConsolidationResponse,
    MirrorTriplePreviewItem,
)
from app.services import mirror_kg_service
from app.services import triple_consolidation_service as triple_svc
from app.services.triple_consolidation_service import ConsolidationScope
from pydantic import ValidationError

router = APIRouter()


def _circuit_read(circuit, regions) -> MirrorRegionCircuitRead:
    base = MirrorRegionCircuitRead.model_validate(circuit)
    return base.model_copy(
        update={"circuit_regions": [MirrorCircuitRegionRead.model_validate(r) for r in regions]}
    )


@router.get("/connections", response_model=MirrorRegionConnectionListResponse)
async def list_connections(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=0, le=100000, description="0 = unlimited"),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    _limit = None if limit == 0 else limit
    items, total = await mirror_kg_service.list_mirror_connections(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        llm_run_id=llm_run_id,
        llm_item_id=llm_item_id,
        candidate_id=candidate_id,
        search=search,
        limit=_limit,
        offset=offset,
    )
    return MirrorRegionConnectionListResponse(
        items=[MirrorRegionConnectionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/connections", response_model=MirrorRegionConnectionRead, status_code=201)
async def create_connection(
    body: MirrorRegionConnectionCreate,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await mirror_kg_service.create_mirror_connection(session, body)
        await session.commit()
        return MirrorRegionConnectionRead.model_validate(row)
    except mirror_kg_service.SameGranularityValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except mirror_kg_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {exc}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


@router.get("/connections/{connection_id}", response_model=MirrorRegionConnectionRead)
async def get_connection(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await mirror_kg_service.get_mirror_connection(session, connection_id)
    except mirror_kg_service.MirrorConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror connection not found") from exc
    return MirrorRegionConnectionRead.model_validate(row)


@router.patch("/connections/{connection_id}", response_model=MirrorRegionConnectionRead)
async def update_connection(
    connection_id: uuid.UUID,
    body: dict,
    session: AsyncSession = Depends(get_db),
):
    from app.schemas.mirror_kg import MirrorRegionConnectionRead as MRC
    safe_keys = {k for k in MRC.model_fields if k not in ("id", "created_at", "updated_at")}
    updates = {k: v for k, v in body.items() if k in safe_keys}
    if not updates:
        raise HTTPException(status_code=400, detail="no valid fields to update")
    try:
        row = await mirror_kg_service.update_mirror_connection(session, connection_id, updates)
        await session.commit()
        return MirrorRegionConnectionRead.model_validate(row)
    except mirror_kg_service.MirrorConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror connection not found") from exc


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        await mirror_kg_service.delete_mirror_connection(session, connection_id)
        await session.commit()
    except mirror_kg_service.MirrorConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror connection not found") from exc


@router.get("/functions", response_model=MirrorRegionFunctionListResponse)
async def list_functions(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=0, le=100000, description="0 = unlimited"),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    _limit = None if limit == 0 else limit
    items, total = await mirror_kg_service.list_mirror_functions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        llm_run_id=llm_run_id,
        llm_item_id=llm_item_id,
        candidate_id=candidate_id,
        search=search,
        limit=_limit,
        offset=offset,
    )
    return MirrorRegionFunctionListResponse(
        items=[MirrorRegionFunctionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/functions", response_model=MirrorRegionFunctionRead, status_code=201)
async def create_function(
    body: MirrorRegionFunctionCreate,
    session: AsyncSession = Depends(get_db),
):
    row = await mirror_kg_service.create_mirror_function(session, body)
    await session.commit()
    return MirrorRegionFunctionRead.model_validate(row)


@router.get("/functions/{function_id}", response_model=MirrorRegionFunctionRead)
async def get_function(
    function_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await mirror_kg_service.get_mirror_function(session, function_id)
    except mirror_kg_service.MirrorFunctionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror function not found") from exc
    return MirrorRegionFunctionRead.model_validate(row)


@router.patch("/functions/{function_id}", response_model=MirrorRegionFunctionRead)
async def update_function(
    function_id: uuid.UUID,
    body: dict,
    session: AsyncSession = Depends(get_db),
):
    safe_keys = {k for k in MirrorRegionFunctionRead.model_fields if k not in ("id", "created_at", "updated_at")}
    updates = {k: v for k, v in body.items() if k in safe_keys}
    if not updates:
        raise HTTPException(status_code=400, detail="no valid fields to update")
    try:
        row = await mirror_kg_service.update_mirror_function(session, function_id, updates)
        await session.commit()
        return MirrorRegionFunctionRead.model_validate(row)
    except mirror_kg_service.MirrorFunctionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror function not found") from exc


@router.delete("/functions/{function_id}", status_code=204)
async def delete_function(
    function_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        await mirror_kg_service.delete_mirror_function(session, function_id)
        await session.commit()
    except mirror_kg_service.MirrorFunctionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror function not found") from exc


@router.get("/circuits", response_model=MirrorRegionCircuitListResponse)
async def list_circuits(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=0, le=100000, description="0 = unlimited"),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    _limit = None if limit == 0 else limit
    items, total = await mirror_kg_service.list_mirror_circuits(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        llm_run_id=llm_run_id,
        llm_item_id=llm_item_id,
        search=search,
        limit=_limit,
        offset=offset,
    )
    return MirrorRegionCircuitListResponse(
        items=[MirrorRegionCircuitRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/circuits", response_model=MirrorRegionCircuitRead, status_code=201)
async def create_circuit(
    body: MirrorRegionCircuitCreate,
    session: AsyncSession = Depends(get_db),
):
    row = await mirror_kg_service.create_mirror_circuit(session, body)
    await session.commit()
    circuit, regions = await mirror_kg_service.get_mirror_circuit(session, row.id)
    return _circuit_read(circuit, regions)


@router.get("/circuits/{circuit_id}", response_model=MirrorRegionCircuitRead)
async def get_circuit(
    circuit_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        circuit, regions = await mirror_kg_service.get_mirror_circuit(session, circuit_id)
    except mirror_kg_service.MirrorCircuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror circuit not found") from exc
    return _circuit_read(circuit, regions)


@router.patch("/circuits/{circuit_id}", response_model=MirrorRegionCircuitRead)
async def update_circuit(
    circuit_id: uuid.UUID,
    body: dict,
    session: AsyncSession = Depends(get_db),
):
    safe_keys = {k for k in MirrorRegionCircuitRead.model_fields if k not in ("id", "created_at", "updated_at", "circuit_regions")}
    updates = {k: v for k, v in body.items() if k in safe_keys}
    if not updates:
        raise HTTPException(status_code=400, detail="no valid fields to update")
    try:
        row = await mirror_kg_service.update_mirror_circuit(session, circuit_id, updates)
        await session.commit()
        circuit, regions = await mirror_kg_service.get_mirror_circuit(session, row.id)
        return _circuit_read(circuit, regions)
    except mirror_kg_service.MirrorCircuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror circuit not found") from exc


@router.delete("/circuits/{circuit_id}", status_code=204)
async def delete_circuit(
    circuit_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        await mirror_kg_service.delete_mirror_circuit(session, circuit_id)
        await session.commit()
    except mirror_kg_service.MirrorCircuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror circuit not found") from exc


@router.get("/triples", response_model=MirrorKgTripleListResponse)
async def list_triples(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    predicate: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=0, le=100000, description="0 = unlimited"),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    _limit = None if limit == 0 else limit
    items, total = await mirror_kg_service.list_mirror_triples(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        mirror_status=mirror_status,
        review_status=review_status,
        promotion_status=promotion_status,
        llm_run_id=llm_run_id,
        llm_item_id=llm_item_id,
        predicate=predicate,
        search=search,
        limit=_limit,
        offset=offset,
    )
    return MirrorKgTripleListResponse(
        items=[MirrorKgTripleRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/triples", response_model=MirrorKgTripleRead, status_code=201)
async def create_triple(
    body: MirrorKgTripleCreate,
    session: AsyncSession = Depends(get_db),
):
    row = await mirror_kg_service.create_mirror_triple(session, body)
    await session.commit()
    return MirrorKgTripleRead.model_validate(row)


@router.post("/triples/consolidate", response_model=MirrorTripleConsolidationResponse)
async def consolidate_triples(
    body: MirrorTripleConsolidationRequest,
    session: AsyncSession = Depends(get_db),
):
    scope = body.scope
    try:
        result = await triple_svc.consolidate_mirror_triples(
            session,
            source_types=body.source_types,
            scope=ConsolidationScope(
                resource_id=scope.resource_id if scope else None,
                batch_id=scope.batch_id if scope else None,
                source_atlas=scope.source_atlas if scope else None,
                granularity_level=scope.granularity_level if scope else None,
                granularity_family=scope.granularity_family if scope else None,
            ) if scope else ConsolidationScope(),
            mirror_statuses=body.mirror_status,
            review_statuses=body.review_status,
            promotion_statuses=body.promotion_status,
            connection_ids=body.connection_ids,
            function_ids=body.function_ids,
            circuit_ids=body.circuit_ids,
            include_existing=body.include_existing,
            dry_run=body.dry_run,
            limit=body.limit,
        )
    except triple_svc.EmptySourceTypesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except triple_svc.InvalidSourceTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except triple_svc.LimitExceededError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except triple_svc.ExplicitIdNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "SOURCE_NOT_FOUND", "message": str(exc), "source_type": exc.source_type},
        ) from exc
    except triple_svc.ScopeMismatchError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SCOPE_MISMATCH",
                "message": str(exc),
                "source_type": exc.source_type,
                "source_id": exc.source_id,
            },
        ) from exc
    except triple_svc.CrossScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preview = [
        MirrorTriplePreviewItem(
            subject_type=c.subject_type,
            subject_id=c.subject_id,
            subject_label=c.subject_label,
            predicate=c.predicate,
            object_type=c.object_type,
            object_id=c.object_id,
            object_label=c.object_label,
            source_type=c.source_type,
            source_id=c.source_id,
            confidence=c.confidence,
            evidence_text=c.evidence_text,
            duplicate=c.duplicate,
        )
        for c in result.triples_preview
    ]
    return MirrorTripleConsolidationResponse(
        dry_run=result.dry_run,
        source_counts=result.source_counts,
        planned_triple_count=result.planned_triple_count,
        created_triple_count=result.created_triple_count,
        skipped_duplicate_count=result.skipped_duplicate_count,
        skipped_invalid_count=result.skipped_invalid_count,
        existing_triple_count=result.existing_triple_count,
        created_triple_ids=result.created_triple_ids,
        triples_preview=preview,
        warnings=result.warnings,
    )


@router.get("/triples/{triple_id}", response_model=MirrorKgTripleRead)
async def get_triple(
    triple_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await mirror_kg_service.get_mirror_triple(session, triple_id)
    except mirror_kg_service.MirrorTripleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror triple not found") from exc
    return MirrorKgTripleRead.model_validate(row)


@router.get("/evidence", response_model=MirrorEvidenceRecordListResponse)
async def list_evidence(
    evidence_target_type: str | None = None,
    evidence_target_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    granularity_level: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=0, le=100000, description="0 = unlimited"),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    _limit = None if limit == 0 else limit
    items, total = await mirror_kg_service.list_mirror_evidence(
        session,
        evidence_target_type=evidence_target_type,
        evidence_target_id=evidence_target_id,
        resource_id=resource_id,
        batch_id=batch_id,
        llm_run_id=llm_run_id,
        llm_item_id=llm_item_id,
        granularity_level=granularity_level,
        search=search,
        limit=_limit,
        offset=offset,
    )
    return MirrorEvidenceRecordListResponse(
        items=[MirrorEvidenceRecordRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/evidence", response_model=MirrorEvidenceRecordRead, status_code=201)
async def create_evidence(
    body: MirrorEvidenceRecordCreate,
    session: AsyncSession = Depends(get_db),
):
    row = await mirror_kg_service.create_mirror_evidence(session, body)
    await session.commit()
    return MirrorEvidenceRecordRead.model_validate(row)


@router.get("/evidence/{evidence_id}", response_model=MirrorEvidenceRecordRead)
async def get_evidence(
    evidence_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await mirror_kg_service.get_mirror_evidence(session, evidence_id)
    except mirror_kg_service.MirrorEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mirror evidence not found") from exc
    return MirrorEvidenceRecordRead.model_validate(row)
