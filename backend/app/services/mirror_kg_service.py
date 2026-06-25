"""Mirror KG service — create/list/get for mirror precursor entities.

Does NOT write final_* / kg_*, does NOT approve or promote.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.schemas.mirror_kg import (
    MirrorEvidenceRecordCreate,
    MirrorKgTripleCreate,
    MirrorRegionCircuitCreate,
    MirrorRegionConnectionCreate,
    MirrorRegionFunctionCreate,
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
)


class MirrorConnectionNotFoundError(Exception):
    pass


class MirrorFunctionNotFoundError(Exception):
    pass


class MirrorCircuitNotFoundError(Exception):
    pass


class MirrorTripleNotFoundError(Exception):
    pass


class MirrorEvidenceNotFoundError(Exception):
    pass


class SameGranularityValidationError(Exception):
    pass


class CandidateNotFoundError(Exception):
    pass


async def _get_candidate_or_none(
    session: AsyncSession, candidate_id: uuid.UUID | None
) -> CandidateBrainRegion | None:
    if candidate_id is None:
        return None
    row = await session.get(CandidateBrainRegion, candidate_id)
    if row is None:
        raise CandidateNotFoundError(str(candidate_id))
    return row


def _canonical_connection_key(
    source_id: uuid.UUID | None,
    target_id: uuid.UUID | None,
    connection_type: str,
    directionality: str,
) -> tuple[str, str, str, str]:
    """Deterministic key for dedup: undirected pairs are sorted."""
    a = str(source_id or "null")
    b = str(target_id or "null")
    if directionality in ("undirected", "bidirectional"):
        a, b = sorted((a, b))
    return (a, b, connection_type, directionality)


async def _find_existing_connection_for_merge(
    session: AsyncSession,
    payload: MirrorRegionConnectionCreate,
) -> MirrorRegionConnection | None:
    """Find a non-superseded, non-promoted existing connection with the same canonical key."""
    key = _canonical_connection_key(
        payload.source_region_candidate_id,
        payload.target_region_candidate_id,
        payload.connection_type,
        payload.directionality,
    )
    src_id, tgt_id, ctype, direc = key

    blocked_review = frozenset({MirrorReviewStatus.rejected})
    blocked_promo = frozenset({MirrorPromotionStatus.failed, MirrorPromotionStatus.promoted})
    active_statuses = frozenset({MirrorStatus.llm_suggested, MirrorStatus.rule_checked, None})

    base = select(MirrorRegionConnection).where(
        MirrorRegionConnection.connection_type == ctype,
        MirrorRegionConnection.directionality == direc,
        MirrorRegionConnection.source_atlas == payload.source_atlas,
        MirrorRegionConnection.granularity_level == payload.granularity_level,
        MirrorRegionConnection.review_status.notin_(blocked_review),
        MirrorRegionConnection.promotion_status.notin_(blocked_promo),
    )
    if payload.source_region_candidate_id and payload.target_region_candidate_id:
        src_uuid = uuid.UUID(src_id)
        tgt_uuid = uuid.UUID(tgt_id)
        if direc in ("undirected", "bidirectional"):
            base = base.where(
                or_(
                    (MirrorRegionConnection.source_region_candidate_id == src_uuid)
                    & (MirrorRegionConnection.target_region_candidate_id == tgt_uuid),
                    (MirrorRegionConnection.source_region_candidate_id == tgt_uuid)
                    & (MirrorRegionConnection.target_region_candidate_id == src_uuid),
                )
            )
        else:
            base = base.where(
                MirrorRegionConnection.source_region_candidate_id == src_uuid,
                MirrorRegionConnection.target_region_candidate_id == tgt_uuid,
            )

    row = (await session.execute(base.order_by(MirrorRegionConnection.created_at.desc()).limit(1))).scalar_one_or_none()
    return row


def _extract_provenance(
    row: MirrorRegionConnection,
) -> dict[str, Any]:
    """Get or initialize provenance_json from a connection record."""
    raw = row.raw_payload_json
    if isinstance(raw, dict) and "provenance" in raw:
        return dict(raw["provenance"])
    return {"llm_run_ids": [], "llm_item_ids": [], "merge_history": []}


def _update_provenance(
    provenance: dict[str, Any],
    llm_run_id: uuid.UUID | None,
    llm_item_id: uuid.UUID | None,
    action: str,
    confidence: float | None,
) -> dict[str, Any]:
    run_ids = provenance.setdefault("llm_run_ids", [])
    item_ids = provenance.setdefault("llm_item_ids", [])
    history = provenance.setdefault("merge_history", [])
    if llm_run_id and str(llm_run_id) not in run_ids:
        run_ids.append(str(llm_run_id))
    if llm_item_id and str(llm_item_id) not in item_ids:
        item_ids.append(str(llm_item_id))
    history.append({
        "run_id": str(llm_run_id) if llm_run_id else None,
        "item_id": str(llm_item_id) if llm_item_id else None,
        "confidence": confidence,
        "action": action,
        "merged_at": datetime.now(timezone.utc).isoformat(),
    })
    return provenance


async def _validate_connection_same_granularity(
    session: AsyncSession,
    payload: MirrorRegionConnectionCreate,
) -> None:
    src = await _get_candidate_or_none(session, payload.source_region_candidate_id)
    tgt = await _get_candidate_or_none(session, payload.target_region_candidate_id)
    if src is None or tgt is None:
        return
    if src.granularity_level != tgt.granularity_level:
        raise SameGranularityValidationError(
            "source and target candidates must share granularity_level"
        )
    if src.granularity_family != tgt.granularity_family:
        raise SameGranularityValidationError(
            "source and target candidates must share granularity_family"
        )
    if src.source_atlas != tgt.source_atlas:
        raise SameGranularityValidationError(
            "source and target candidates must share source_atlas (no cross-atlas merge)"
        )


def _apply_search(stmt, model, search: str | None):
    if not search:
        return stmt
    pattern = f"%{search}%"
    if model is MirrorRegionConnection:
        return stmt.where(
            or_(
                model.evidence_text.ilike(pattern),
                model.connection_type.ilike(pattern),
            )
        )
    if model is MirrorRegionFunction:
        return stmt.where(
            or_(model.function_term.ilike(pattern), model.evidence_text.ilike(pattern))
        )
    if model is MirrorRegionCircuit:
        return stmt.where(
            or_(model.circuit_name.ilike(pattern), model.description.ilike(pattern))
        )
    if model is MirrorKgTriple:
        return stmt.where(
            or_(
                model.subject_label.ilike(pattern),
                model.predicate.ilike(pattern),
                model.object_label.ilike(pattern),
            )
        )
    if model is MirrorEvidenceRecord:
        return stmt.where(model.evidence_text.ilike(pattern))
    return stmt


async def create_mirror_connection(
    session: AsyncSession,
    payload: MirrorRegionConnectionCreate,
) -> MirrorRegionConnection:
    """Create a mirror connection with write-time dedup & merge (Phase 1).

    Returns the connection record. If a duplicate exists with ``review_status=pending``,
    the record is merged (updated or preserved) per the dedup principle.

    The caller can inspect ``row.raw_payload_json.get("provenance", {}).get("merge_history", [])``
    to determine whether the row was created / updated / skipped.
    The last entry's ``action`` field will be ``"created"``, ``"updated"``, or ``"skipped"``.
    """
    await _validate_connection_same_granularity(session, payload)
    existing = await _find_existing_connection_for_merge(session, payload)

    if existing is not None and existing.review_status in (
        MirrorReviewStatus.pending, MirrorReviewStatus.needs_review
    ):
        old_conf = existing.confidence or 0.0
        new_conf = payload.confidence or 0.0

        old_prov = _extract_provenance(existing)
        merged_prov = _update_provenance(
            old_prov,
            llm_run_id=payload.llm_run_id,
            llm_item_id=payload.llm_item_id,
            action="updated" if new_conf > old_conf else "skipped",
            confidence=payload.confidence,
        )

        if new_conf > old_conf:
            # Update existing record with new values (higher confidence)
            update_fields = {
                "connection_type": payload.connection_type,
                "directionality": payload.directionality,
                "strength": payload.strength,
                "modality": payload.modality,
                "confidence": payload.confidence,
                "evidence_text": payload.evidence_text,
                "uncertainty_reason": payload.uncertainty_reason,
                "llm_run_id": payload.llm_run_id,
                "llm_item_id": payload.llm_item_id,
                "mirror_status": MirrorStatus.llm_suggested,
            }
            for key, val in update_fields.items():
                if val is not None or key in ("mirror_status",):
                    setattr(existing, key, val)

        # Update provenance in raw_payload_json
        existing_raw = dict(existing.raw_payload_json or {})
        existing_raw["provenance"] = merged_prov
        existing.raw_payload_json = existing_raw
        flag_modified(existing, "raw_payload_json")

        await session.flush()
        await session.refresh(existing)
        return existing

    # No existing, or existing is already in review/approved → create fresh
    data = payload.model_dump()
    data.setdefault("mirror_status", MirrorStatus.llm_suggested)
    data.setdefault("review_status", MirrorReviewStatus.pending)
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    # Initialize provenance
    raw = dict(data.get("raw_payload_json") or {})
    if "provenance" not in raw:
        raw["provenance"] = _update_provenance(
            {},
            llm_run_id=payload.llm_run_id,
            llm_item_id=payload.llm_item_id,
            action="created",
            confidence=payload.confidence,
        )
    data["raw_payload_json"] = raw
    row = MirrorRegionConnection(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_mirror_connections(
    session: AsyncSession,
    *,
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
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorRegionConnection], int]:
    base = select(MirrorRegionConnection)
    if resource_id:
        base = base.where(MirrorRegionConnection.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorRegionConnection.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorRegionConnection.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorRegionConnection.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorRegionConnection.granularity_family == granularity_family)
    if mirror_status:
        base = base.where(MirrorRegionConnection.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorRegionConnection.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorRegionConnection.promotion_status == promotion_status)
    if llm_run_id:
        base = base.where(MirrorRegionConnection.llm_run_id == llm_run_id)
    if llm_item_id:
        base = base.where(MirrorRegionConnection.llm_item_id == llm_item_id)
    if candidate_id:
        base = base.where(
            or_(
                MirrorRegionConnection.source_region_candidate_id == candidate_id,
                MirrorRegionConnection.target_region_candidate_id == candidate_id,
            )
        )
    base = _apply_search(base, MirrorRegionConnection, search)
    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorRegionConnection.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_mirror_connection(
    session: AsyncSession, connection_id: uuid.UUID
) -> MirrorRegionConnection:
    row = await session.get(MirrorRegionConnection, connection_id)
    if row is None:
        raise MirrorConnectionNotFoundError(str(connection_id))
    return row


async def update_mirror_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    updates: dict,
) -> MirrorRegionConnection:
    row = await get_mirror_connection(session, connection_id)
    for key, val in updates.items():
        if hasattr(row, key) and key not in ("id", "created_at", "updated_at"):
            setattr(row, key, val)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_mirror_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
) -> None:
    row = await get_mirror_connection(session, connection_id)
    await session.delete(row)
    await session.flush()


async def create_mirror_function(
    session: AsyncSession,
    payload: MirrorRegionFunctionCreate,
) -> MirrorRegionFunction:
    data = payload.model_dump()
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    row = MirrorRegionFunction(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_mirror_functions(
    session: AsyncSession,
    *,
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
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorRegionFunction], int]:
    base = select(MirrorRegionFunction)
    if resource_id:
        base = base.where(MirrorRegionFunction.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorRegionFunction.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorRegionFunction.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorRegionFunction.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorRegionFunction.granularity_family == granularity_family)
    if mirror_status:
        base = base.where(MirrorRegionFunction.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorRegionFunction.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorRegionFunction.promotion_status == promotion_status)
    if llm_run_id:
        base = base.where(MirrorRegionFunction.llm_run_id == llm_run_id)
    if llm_item_id:
        base = base.where(MirrorRegionFunction.llm_item_id == llm_item_id)
    if candidate_id:
        base = base.where(MirrorRegionFunction.region_candidate_id == candidate_id)
    base = _apply_search(base, MirrorRegionFunction, search)
    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorRegionFunction.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_mirror_function(
    session: AsyncSession, function_id: uuid.UUID
) -> MirrorRegionFunction:
    row = await session.get(MirrorRegionFunction, function_id)
    if row is None:
        raise MirrorFunctionNotFoundError(str(function_id))
    return row


async def update_mirror_function(
    session: AsyncSession,
    function_id: uuid.UUID,
    updates: dict,
) -> MirrorRegionFunction:
    row = await get_mirror_function(session, function_id)
    for key, val in updates.items():
        if hasattr(row, key) and key not in ("id", "created_at", "updated_at"):
            setattr(row, key, val)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_mirror_function(
    session: AsyncSession,
    function_id: uuid.UUID,
) -> None:
    row = await get_mirror_function(session, function_id)
    await session.delete(row)
    await session.flush()


async def create_mirror_circuit(
    session: AsyncSession,
    payload: MirrorRegionCircuitCreate,
) -> MirrorRegionCircuit:
    data = payload.model_dump(exclude={"circuit_regions"})
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    row = MirrorRegionCircuit(**data)
    session.add(row)
    await session.flush()
    for idx, cr in enumerate(payload.circuit_regions):
        session.add(
            MirrorCircuitRegion(
                circuit_id=row.id,
                region_candidate_id=cr.region_candidate_id,
                region_final_id=cr.region_final_id,
                role=cr.role,
                sort_order=cr.sort_order if cr.sort_order else idx,
            )
        )
    await session.flush()
    await session.refresh(row)
    return row


async def _load_circuit_regions(
    session: AsyncSession, circuit_id: uuid.UUID
) -> list[MirrorCircuitRegion]:
    q = (
        select(MirrorCircuitRegion)
        .where(MirrorCircuitRegion.circuit_id == circuit_id)
        .order_by(MirrorCircuitRegion.sort_order)
    )
    return list((await session.execute(q)).scalars().all())


async def list_mirror_circuits(
    session: AsyncSession,
    *,
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
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorRegionCircuit], int]:
    base = select(MirrorRegionCircuit)
    if resource_id:
        base = base.where(MirrorRegionCircuit.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorRegionCircuit.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorRegionCircuit.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorRegionCircuit.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorRegionCircuit.granularity_family == granularity_family)
    if mirror_status:
        base = base.where(MirrorRegionCircuit.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorRegionCircuit.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorRegionCircuit.promotion_status == promotion_status)
    if llm_run_id:
        base = base.where(MirrorRegionCircuit.llm_run_id == llm_run_id)
    if llm_item_id:
        base = base.where(MirrorRegionCircuit.llm_item_id == llm_item_id)
    base = _apply_search(base, MirrorRegionCircuit, search)
    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorRegionCircuit.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_mirror_circuit(
    session: AsyncSession, circuit_id: uuid.UUID
) -> tuple[MirrorRegionCircuit, list[MirrorCircuitRegion]]:
    row = await session.get(MirrorRegionCircuit, circuit_id)
    if row is None:
        raise MirrorCircuitNotFoundError(str(circuit_id))
    regions = await _load_circuit_regions(session, circuit_id)
    return row, regions


async def update_mirror_circuit(
    session: AsyncSession,
    circuit_id: uuid.UUID,
    updates: dict,
) -> MirrorRegionCircuit:
    row = await session.get(MirrorRegionCircuit, circuit_id)
    if row is None:
        raise MirrorCircuitNotFoundError(str(circuit_id))
    for key, val in updates.items():
        if hasattr(row, key) and key not in ("id", "created_at", "updated_at"):
            setattr(row, key, val)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_mirror_circuit(
    session: AsyncSession,
    circuit_id: uuid.UUID,
) -> None:
    row = await session.get(MirrorRegionCircuit, circuit_id)
    if row is None:
        raise MirrorCircuitNotFoundError(str(circuit_id))
    await session.delete(row)
    await session.flush()


async def create_mirror_triple(
    session: AsyncSession,
    payload: MirrorKgTripleCreate,
) -> MirrorKgTriple:
    data = payload.model_dump()
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    row = MirrorKgTriple(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_mirror_triples(
    session: AsyncSession,
    *,
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
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorKgTriple], int]:
    base = select(MirrorKgTriple)
    if resource_id:
        base = base.where(MirrorKgTriple.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorKgTriple.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorKgTriple.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorKgTriple.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorKgTriple.granularity_family == granularity_family)
    if mirror_status:
        base = base.where(MirrorKgTriple.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorKgTriple.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorKgTriple.promotion_status == promotion_status)
    if llm_run_id:
        base = base.where(MirrorKgTriple.llm_run_id == llm_run_id)
    if llm_item_id:
        base = base.where(MirrorKgTriple.llm_item_id == llm_item_id)
    if predicate:
        base = base.where(MirrorKgTriple.predicate == predicate)
    base = _apply_search(base, MirrorKgTriple, search)
    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorKgTriple.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_mirror_triple(session: AsyncSession, triple_id: uuid.UUID) -> MirrorKgTriple:
    row = await session.get(MirrorKgTriple, triple_id)
    if row is None:
        raise MirrorTripleNotFoundError(str(triple_id))
    return row


async def create_mirror_evidence(
    session: AsyncSession,
    payload: MirrorEvidenceRecordCreate,
) -> MirrorEvidenceRecord:
    row = MirrorEvidenceRecord(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_mirror_evidence(
    session: AsyncSession,
    *,
    evidence_target_type: str | None = None,
    evidence_target_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorEvidenceRecord], int]:
    base = select(MirrorEvidenceRecord)
    if evidence_target_type:
        base = base.where(MirrorEvidenceRecord.evidence_target_type == evidence_target_type)
    if evidence_target_id:
        base = base.where(MirrorEvidenceRecord.evidence_target_id == evidence_target_id)
    if resource_id:
        base = base.where(MirrorEvidenceRecord.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorEvidenceRecord.batch_id == batch_id)
    if llm_run_id:
        base = base.where(MirrorEvidenceRecord.llm_run_id == llm_run_id)
    if llm_item_id:
        base = base.where(MirrorEvidenceRecord.llm_item_id == llm_item_id)
    base = _apply_search(base, MirrorEvidenceRecord, search)
    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorEvidenceRecord.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_mirror_evidence(
    session: AsyncSession, evidence_id: uuid.UUID
) -> MirrorEvidenceRecord:
    row = await session.get(MirrorEvidenceRecord, evidence_id)
    if row is None:
        raise MirrorEvidenceNotFoundError(str(evidence_id))
    return row
