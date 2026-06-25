"""Final KG read-only list/get service (Step 9)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.final_kg import (
    FinalEvidenceRecord,
    FinalKgTriple,
    FinalRegionCircuit,
    FinalRegionConnection,
    FinalRegionFunction,
)


async def _list_model(
    session: AsyncSession,
    model: type,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    final_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    extra_filters: list[Any] | None = None,
) -> tuple[list[Any], int]:
    stmt = select(model)
    count_stmt = select(func.count()).select_from(model)
    if resource_id:
        stmt = stmt.where(model.resource_id == resource_id)
        count_stmt = count_stmt.where(model.resource_id == resource_id)
    if batch_id:
        stmt = stmt.where(model.batch_id == batch_id)
        count_stmt = count_stmt.where(model.batch_id == batch_id)
    if source_atlas:
        stmt = stmt.where(model.source_atlas == source_atlas)
        count_stmt = count_stmt.where(model.source_atlas == source_atlas)
    if granularity_level:
        stmt = stmt.where(model.granularity_level == granularity_level)
        count_stmt = count_stmt.where(model.granularity_level == granularity_level)
    if final_status and hasattr(model, "final_status"):
        stmt = stmt.where(model.final_status == final_status)
        count_stmt = count_stmt.where(model.final_status == final_status)
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(model.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
    )
    return rows, int(total)


async def list_final_connections(
    session: AsyncSession,
    **kwargs: Any,
) -> tuple[list[FinalRegionConnection], int]:
    return await _list_model(session, FinalRegionConnection, **kwargs)


async def get_final_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
) -> FinalRegionConnection | None:
    return await session.get(FinalRegionConnection, connection_id)


async def list_final_functions(
    session: AsyncSession,
    **kwargs: Any,
) -> tuple[list[FinalRegionFunction], int]:
    return await _list_model(session, FinalRegionFunction, **kwargs)


async def get_final_function(
    session: AsyncSession,
    function_id: uuid.UUID,
) -> FinalRegionFunction | None:
    return await session.get(FinalRegionFunction, function_id)


async def list_final_circuits(
    session: AsyncSession,
    **kwargs: Any,
) -> tuple[list[FinalRegionCircuit], int]:
    return await _list_model(session, FinalRegionCircuit, **kwargs)


async def get_final_circuit(
    session: AsyncSession,
    circuit_id: uuid.UUID,
) -> FinalRegionCircuit | None:
    return await session.get(FinalRegionCircuit, circuit_id)


async def list_final_triples(
    session: AsyncSession,
    **kwargs: Any,
) -> tuple[list[FinalKgTriple], int]:
    return await _list_model(session, FinalKgTriple, **kwargs)


async def get_final_triple(
    session: AsyncSession,
    triple_id: uuid.UUID,
) -> FinalKgTriple | None:
    return await session.get(FinalKgTriple, triple_id)


async def list_final_evidence(
    session: AsyncSession,
    *,
    evidence_target_type: str | None = None,
    evidence_target_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FinalEvidenceRecord], int]:
    extra: list[Any] = []
    if evidence_target_type:
        extra.append(FinalEvidenceRecord.evidence_target_type == evidence_target_type)
    if evidence_target_id:
        extra.append(FinalEvidenceRecord.evidence_target_id == evidence_target_id)
    return await _list_model(
        session,
        FinalEvidenceRecord,
        resource_id=resource_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
        extra_filters=extra,
    )
