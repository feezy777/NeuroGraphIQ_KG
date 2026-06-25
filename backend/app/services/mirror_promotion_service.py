"""Mirror KG Promotion to Final KG service (Step 9).

Deterministic DB promotion from human_approved Mirror KG objects to final_* tables.
Does NOT call LLM; does NOT write kg_*; does NOT connect to external formal DB.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.final_kg import (
    FinalCircuitRegion,
    FinalEvidenceRecord,
    FinalKgTriple,
    FinalRegionCircuit,
    FinalRegionConnection,
    FinalRegionFunction,
)
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_promotion import MirrorPromotionRecord, MirrorPromotionRun
from app.models.mirror_review import MirrorHumanReviewRecord
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_promotion import (
    MirrorPromotionPreviewItem,
    MirrorPromotionRecordStatus,
    MirrorPromotionRequest,
    MirrorPromotionResponse,
    MirrorPromotionRunStatus,
)
from app.schemas.mirror_review import MirrorReviewAction
from app.services import mirror_review_service as mrs
from app.services.triple_consolidation_service import normalize_triple_key

VALID_TARGET_TYPES = frozenset({"connection", "function", "circuit", "triple"})

MIRROR_EVIDENCE_TYPE = {
    "connection": "mirror_connection",
    "function": "mirror_function",
    "circuit": "mirror_circuit",
    "triple": "mirror_triple",
}

FINAL_EVIDENCE_TYPE = {
    "connection": "final_connection",
    "function": "final_function",
    "circuit": "final_circuit",
    "triple": "final_triple",
}

FINAL_TARGET_TYPE = {
    "connection": "final_connection",
    "function": "final_function",
    "circuit": "final_circuit",
    "triple": "final_triple",
}

PROMOTION_ORDER = ("connection", "function", "circuit", "triple")


class EmptyTargetTypesError(ValueError):
    pass


class InvalidTargetTypeError(ValueError):
    pass


class MissingOperatorError(ValueError):
    pass


class MissingReasonError(ValueError):
    pass


class ConfirmationMismatchError(ValueError):
    pass


@dataclass
class PromotionScope:
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_statuses: list[str] | None = None
    review_statuses: list[str] | None = None
    promotion_statuses: list[str] | None = None
    connection_ids: list[uuid.UUID] | None = None
    function_ids: list[uuid.UUID] | None = None
    circuit_ids: list[uuid.UUID] | None = None
    triple_ids: list[uuid.UUID] | None = None
    limit: int = 1000


def build_required_confirmation(target_types: list[str], eligible_count: int) -> str:
    joined = ",".join(sorted(target_types))
    return f"PROMOTE MIRROR KG TO FINAL: {joined} COUNT {eligible_count}"


async def get_latest_approved_review_record(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> MirrorHumanReviewRecord | None:
    row = await session.execute(
        select(MirrorHumanReviewRecord)
        .where(
            MirrorHumanReviewRecord.target_type == target_type,
            MirrorHumanReviewRecord.target_id == target_id,
            MirrorHumanReviewRecord.action == MirrorReviewAction.approve,
        )
        .order_by(MirrorHumanReviewRecord.created_at.desc())
        .limit(1)
    )
    return row.scalars().first()


async def get_latest_validation_summary(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> dict[str, Any]:
    return await mrs.get_latest_validation_summary(session, target_type, target_id)


def _display_label(target_type: str, obj: Any) -> str:
    return mrs._display_label(target_type, obj)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _connection_endpoint_pair(
    src: uuid.UUID | None,
    tgt: uuid.UUID | None,
    directionality: str,
) -> tuple[str, str]:
    a, b = str(src or ""), str(tgt or "")
    if directionality == "undirected":
        return tuple(sorted([a, b]))
    return (a, b)


async def detect_final_duplicate(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> bool:
    if target_type == "connection":
        pair = _connection_endpoint_pair(
            obj.source_region_candidate_id,
            obj.target_region_candidate_id,
            obj.directionality,
        )
        rows = list(
            (
                await session.execute(
                    select(FinalRegionConnection).where(
                        FinalRegionConnection.final_status == "active",
                        FinalRegionConnection.resource_id == obj.resource_id,
                        FinalRegionConnection.batch_id == obj.batch_id,
                        FinalRegionConnection.source_atlas == obj.source_atlas,
                        FinalRegionConnection.granularity_level == obj.granularity_level,
                        FinalRegionConnection.granularity_family == obj.granularity_family,
                        FinalRegionConnection.connection_type == obj.connection_type,
                        FinalRegionConnection.directionality == obj.directionality,
                    )
                )
            ).scalars().all()
        )
        for row in rows:
            existing_pair = _connection_endpoint_pair(
                row.source_region_candidate_id,
                row.target_region_candidate_id,
                row.directionality,
            )
            if existing_pair == pair:
                return True
        return False

    if target_type == "function":
        row = await session.execute(
            select(FinalRegionFunction.id).where(
                FinalRegionFunction.final_status == "active",
                FinalRegionFunction.resource_id == obj.resource_id,
                FinalRegionFunction.batch_id == obj.batch_id,
                FinalRegionFunction.source_atlas == obj.source_atlas,
                FinalRegionFunction.granularity_level == obj.granularity_level,
                FinalRegionFunction.granularity_family == obj.granularity_family,
                FinalRegionFunction.region_candidate_id == obj.region_candidate_id,
                func.lower(func.trim(FinalRegionFunction.function_term)) == _norm(obj.function_term),
                FinalRegionFunction.function_category == obj.function_category,
                FinalRegionFunction.relation_type == obj.relation_type,
            ).limit(1)
        )
        return row.scalar_one_or_none() is not None

    if target_type == "circuit":
        candidates = list(
            (
                await session.execute(
                    select(FinalRegionCircuit).where(
                        FinalRegionCircuit.final_status == "active",
                        FinalRegionCircuit.resource_id == obj.resource_id,
                        FinalRegionCircuit.batch_id == obj.batch_id,
                        FinalRegionCircuit.source_atlas == obj.source_atlas,
                        FinalRegionCircuit.granularity_level == obj.granularity_level,
                        FinalRegionCircuit.granularity_family == obj.granularity_family,
                        func.lower(func.trim(FinalRegionCircuit.circuit_name)) == _norm(obj.circuit_name),
                        FinalRegionCircuit.circuit_type == obj.circuit_type,
                    )
                )
            ).scalars().all()
        )
        if not candidates:
            return False
        mirror_regions = sorted(
            str(r.region_candidate_id or "")
            for r in (
                await session.execute(
                    select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == obj.id)
                )
            ).scalars().all()
        )
        for cand in candidates:
            final_regions = sorted(
                str(r.region_candidate_id or "")
                for r in (
                    await session.execute(
                        select(FinalCircuitRegion).where(FinalCircuitRegion.final_circuit_id == cand.id)
                    )
                ).scalars().all()
            )
            if final_regions == mirror_regions:
                return True
        return False

    if target_type == "triple":
        key = normalize_triple_key(
            subject_type=obj.subject_type,
            subject_id=obj.subject_id,
            subject_label=obj.subject_label,
            predicate=obj.predicate,
            object_type=obj.object_type,
            object_id=obj.object_id,
            object_label=obj.object_label,
            triple_scope=obj.triple_scope,
            source_atlas=obj.source_atlas,
            granularity_level=obj.granularity_level,
            granularity_family=obj.granularity_family,
            resource_id=obj.resource_id,
            batch_id=obj.batch_id,
        )
        rows = list(
            (
                await session.execute(
                    select(FinalKgTriple).where(
                        FinalKgTriple.final_status == "active",
                        FinalKgTriple.resource_id == obj.resource_id,
                        FinalKgTriple.batch_id == obj.batch_id,
                        FinalKgTriple.source_atlas == obj.source_atlas,
                        FinalKgTriple.granularity_level == obj.granularity_level,
                        FinalKgTriple.granularity_family == obj.granularity_family,
                        FinalKgTriple.triple_scope == obj.triple_scope,
                        FinalKgTriple.predicate == obj.predicate,
                        FinalKgTriple.subject_type == obj.subject_type,
                        FinalKgTriple.object_type == obj.object_type,
                    )
                )
            ).scalars().all()
        )
        for row in rows:
            if normalize_triple_key(
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                subject_label=row.subject_label,
                predicate=row.predicate,
                object_type=row.object_type,
                object_id=row.object_id,
                object_label=row.object_label,
                triple_scope=row.triple_scope,
                source_atlas=row.source_atlas,
                granularity_level=row.granularity_level,
                granularity_family=row.granularity_family,
                resource_id=row.resource_id,
                batch_id=row.batch_id,
            ) == key:
                return True
        return False

    return False


async def validate_promotion_eligibility(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> tuple[bool, str | None, uuid.UUID | None, dict[str, Any]]:
    if obj is None:
        return False, "TARGET_NOT_FOUND", None, {}

    if obj.mirror_status != MirrorStatus.human_approved:
        return False, "NOT_HUMAN_APPROVED", None, {}

    if obj.review_status != MirrorReviewStatus.approved:
        return False, "REVIEW_STATUS_NOT_APPROVED", None, {}

    if obj.promotion_status == MirrorPromotionStatus.blocked:
        return False, "PROMOTION_BLOCKED", None, {}

    if (
        obj.promotion_status == MirrorPromotionStatus.promoted
        or obj.mirror_status == MirrorStatus.promoted_to_final
    ):
        return False, "ALREADY_PROMOTED", None, {}

    approve_record = await get_latest_approved_review_record(session, target_type, obj.id)
    if approve_record is None:
        return False, "NO_APPROVE_REVIEW_RECORD", None, {}

    val_summary = await get_latest_validation_summary(session, target_type, obj.id)
    if val_summary.get("has_blocker") or val_summary.get("has_error"):
        return False, "HAS_VALIDATION_BLOCKER", approve_record.id, val_summary

    if not obj.source_atlas:
        return False, "MISSING_SOURCE_ATLAS", approve_record.id, val_summary

    if not obj.granularity_level:
        return False, "MISSING_GRANULARITY", approve_record.id, val_summary

    if await detect_final_duplicate(session, target_type, obj):
        return False, "DUPLICATE_FINAL_EXISTS", approve_record.id, val_summary

    return True, None, approve_record.id, val_summary


def _scope_from_request(request: MirrorPromotionRequest) -> PromotionScope:
    scope = request.scope
    default_mirror = [MirrorStatus.human_approved]
    default_review = [MirrorReviewStatus.approved]
    default_promotion = [MirrorPromotionStatus.not_promoted]
    return PromotionScope(
        resource_id=scope.resource_id if scope else None,
        batch_id=scope.batch_id if scope else None,
        source_atlas=scope.source_atlas if scope else None,
        source_version=scope.source_version if scope else None,
        granularity_level=scope.granularity_level if scope else None,
        granularity_family=scope.granularity_family if scope else None,
        mirror_statuses=(scope.mirror_status if scope and scope.mirror_status else default_mirror),
        review_statuses=(scope.review_status if scope and scope.review_status else default_review),
        promotion_statuses=(scope.promotion_status if scope and scope.promotion_status else default_promotion),
        connection_ids=request.connection_ids,
        function_ids=request.function_ids,
        circuit_ids=request.circuit_ids,
        triple_ids=request.triple_ids,
        limit=request.limit,
    )


def _apply_common_filters(stmt: Any, model: Any, scope: PromotionScope) -> Any:
    if scope.resource_id:
        stmt = stmt.where(model.resource_id == scope.resource_id)
    if scope.batch_id:
        stmt = stmt.where(model.batch_id == scope.batch_id)
    if scope.source_atlas:
        stmt = stmt.where(model.source_atlas == scope.source_atlas)
    if scope.source_version:
        stmt = stmt.where(model.source_version == scope.source_version)
    if scope.granularity_level:
        stmt = stmt.where(model.granularity_level == scope.granularity_level)
    if scope.granularity_family:
        stmt = stmt.where(model.granularity_family == scope.granularity_family)
    if scope.mirror_statuses:
        stmt = stmt.where(model.mirror_status.in_(scope.mirror_statuses))
    if scope.review_statuses:
        stmt = stmt.where(model.review_status.in_(scope.review_statuses))
    if scope.promotion_statuses:
        stmt = stmt.where(model.promotion_status.in_(scope.promotion_statuses))
    return stmt


async def collect_promotion_targets(
    session: AsyncSession,
    target_types: list[str],
    scope: PromotionScope,
) -> list[tuple[str, Any]]:
    targets: list[tuple[str, Any]] = []
    per_type_limit = scope.limit

    if "connection" in target_types:
        stmt = select(MirrorRegionConnection)
        if scope.connection_ids:
            stmt = stmt.where(MirrorRegionConnection.id.in_(scope.connection_ids))
        else:
            stmt = _apply_common_filters(stmt, MirrorRegionConnection, scope)
        stmt = stmt.order_by(MirrorRegionConnection.created_at.asc()).limit(per_type_limit)
        for row in (await session.execute(stmt)).scalars().all():
            targets.append(("connection", row))

    if "function" in target_types:
        stmt = select(MirrorRegionFunction)
        if scope.function_ids:
            stmt = stmt.where(MirrorRegionFunction.id.in_(scope.function_ids))
        else:
            stmt = _apply_common_filters(stmt, MirrorRegionFunction, scope)
        stmt = stmt.order_by(MirrorRegionFunction.created_at.asc()).limit(per_type_limit)
        for row in (await session.execute(stmt)).scalars().all():
            targets.append(("function", row))

    if "circuit" in target_types:
        stmt = select(MirrorRegionCircuit)
        if scope.circuit_ids:
            stmt = stmt.where(MirrorRegionCircuit.id.in_(scope.circuit_ids))
        else:
            stmt = _apply_common_filters(stmt, MirrorRegionCircuit, scope)
        stmt = stmt.order_by(MirrorRegionCircuit.created_at.asc()).limit(per_type_limit)
        for row in (await session.execute(stmt)).scalars().all():
            targets.append(("circuit", row))

    if "triple" in target_types:
        stmt = select(MirrorKgTriple)
        if scope.triple_ids:
            stmt = stmt.where(MirrorKgTriple.id.in_(scope.triple_ids))
        else:
            stmt = _apply_common_filters(stmt, MirrorKgTriple, scope)
        stmt = stmt.order_by(MirrorKgTriple.created_at.asc()).limit(per_type_limit)
        for row in (await session.execute(stmt)).scalars().all():
            targets.append(("triple", row))

    ordered: list[tuple[str, Any]] = []
    by_type: dict[str, list[tuple[str, Any]]] = {t: [] for t in PROMOTION_ORDER}
    for tt, obj in targets:
        if tt in by_type:
            by_type[tt].append((tt, obj))
    for tt in PROMOTION_ORDER:
        if tt in target_types:
            ordered.extend(by_type[tt])
    return ordered


async def build_promotion_preview_item(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> MirrorPromotionPreviewItem:
    eligible, reason, review_id, val_summary = await validate_promotion_eligibility(
        session, target_type, obj
    )
    duplicate = reason == "DUPLICATE_FINAL_EXISTS"
    conf = float(obj.confidence) if obj.confidence is not None else None
    planned = "promote" if eligible else ("skip_duplicate" if duplicate else "skip_ineligible")
    return MirrorPromotionPreviewItem(
        target_type=target_type,
        mirror_target_id=obj.id,
        display_label=_display_label(target_type, obj),
        eligible=eligible,
        ineligible_reason=reason,
        final_target_type=FINAL_TARGET_TYPE.get(target_type),
        planned_action=planned,
        duplicate=duplicate,
        confidence=conf,
        review_record_id=review_id,
        validation_summary=val_summary,
    )


async def build_promotion_preview(
    session: AsyncSession,
    request: MirrorPromotionRequest,
) -> MirrorPromotionResponse:
    if not request.target_types:
        raise EmptyTargetTypesError("target_types must not be empty")
    for tt in request.target_types:
        if tt not in VALID_TARGET_TYPES:
            raise InvalidTargetTypeError(f"Invalid target_type: {tt}")

    scope = _scope_from_request(request)
    targets = await collect_promotion_targets(session, request.target_types, scope)
    preview_items: list[MirrorPromotionPreviewItem] = []
    warnings: list[str] = []

    eligible_count = 0
    skipped_ineligible = 0
    skipped_duplicate = 0

    for target_type, obj in targets:
        item = await build_promotion_preview_item(session, target_type, obj)
        preview_items.append(item)
        if item.eligible:
            eligible_count += 1
        elif item.duplicate:
            skipped_duplicate += 1
        else:
            skipped_ineligible += 1
        if item.validation_summary and item.validation_summary.get("has_warning"):
            warnings.append(f"WARNING on {target_type}:{obj.id}")

    required = build_required_confirmation(request.target_types, eligible_count)
    return MirrorPromotionResponse(
        dry_run=True,
        required_confirmation=required,
        object_count=len(targets),
        eligible_count=eligible_count,
        promoted_count=0,
        skipped_duplicate_count=skipped_duplicate,
        skipped_ineligible_count=skipped_ineligible,
        failed_count=0,
        preview_items=preview_items,
        warnings=sorted(set(warnings)),
    )


def create_promotion_run(
    *,
    target_types: list[str],
    scope_json: dict[str, Any],
    scope: PromotionScope,
    dry_run: bool,
    required_confirmation: str | None,
    operator: str | None,
    reason: str | None,
    confirmation_text: str | None,
) -> MirrorPromotionRun:
    return MirrorPromotionRun(
        id=uuid.uuid4(),
        target_types=target_types,
        scope_json=scope_json,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        source_version=scope.source_version,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        status=MirrorPromotionRunStatus.running,
        dry_run=dry_run,
        required_confirmation=required_confirmation,
        operator=operator,
        reason=reason,
        confirmation_text=confirmation_text,
        started_at=datetime.now(timezone.utc),
    )


def create_promotion_record(
    *,
    run_id: uuid.UUID,
    target_type: str,
    mirror_target_id: uuid.UUID,
    status: str,
    before_json: dict[str, Any],
    after_json: dict[str, Any],
    final_json: dict[str, Any],
    review_record_id: uuid.UUID | None,
    final_target_type: str | None = None,
    final_target_id: uuid.UUID | None = None,
    message: str | None = None,
    obj: Any = None,
) -> MirrorPromotionRecord:
    return MirrorPromotionRecord(
        id=uuid.uuid4(),
        run_id=run_id,
        target_type=target_type,
        mirror_target_id=mirror_target_id,
        final_target_type=final_target_type,
        final_target_id=final_target_id,
        review_record_id=review_record_id,
        status=status,
        message=message,
        before_mirror_json=before_json,
        after_mirror_json=after_json,
        final_object_json=final_json,
        resource_id=getattr(obj, "resource_id", None),
        batch_id=getattr(obj, "batch_id", None),
        source_atlas=getattr(obj, "source_atlas", None),
        granularity_level=getattr(obj, "granularity_level", None),
        granularity_family=getattr(obj, "granularity_family", None),
    )


def update_mirror_source_after_promotion(obj: Any) -> None:
    obj.promotion_status = MirrorPromotionStatus.promoted
    obj.mirror_status = MirrorStatus.promoted_to_final


async def _lookup_final_id_for_mirror(
    session: AsyncSession,
    model: type,
    mirror_id_col: Any,
    mirror_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if not mirror_id:
        return None
    row = await session.execute(
        select(model.id).where(mirror_id_col == mirror_id, model.final_status == "active").limit(1)
    )
    return row.scalar_one_or_none()


async def promote_evidence_for_target(
    session: AsyncSession,
    *,
    target_type: str,
    mirror_obj: Any,
    final_obj_id: uuid.UUID,
    review_record_id: uuid.UUID | None,
    promotion_record_id: uuid.UUID,
    warnings: list[str],
) -> int:
    mirror_ev_type = MIRROR_EVIDENCE_TYPE[target_type]
    final_ev_type = FINAL_EVIDENCE_TYPE[target_type]
    count = 0

    mirror_rows = list(
        (
            await session.execute(
                select(MirrorEvidenceRecord).where(
                    MirrorEvidenceRecord.evidence_target_type == mirror_ev_type,
                    MirrorEvidenceRecord.evidence_target_id == mirror_obj.id,
                )
            )
        ).scalars().all()
    )

    for mev in mirror_rows:
        existing = await session.execute(
            select(FinalEvidenceRecord.id).where(
                FinalEvidenceRecord.source_mirror_evidence_id == mev.id,
                FinalEvidenceRecord.evidence_target_id == final_obj_id,
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue
        fev = FinalEvidenceRecord(
            evidence_target_type=final_ev_type,
            evidence_target_id=final_obj_id,
            source_mirror_evidence_id=mev.id,
            resource_id=mev.resource_id,
            batch_id=mev.batch_id,
            llm_run_id=mev.llm_run_id,
            llm_item_id=mev.llm_item_id,
            review_record_id=review_record_id,
            promotion_record_id=promotion_record_id,
            evidence_type=mev.evidence_type,
            evidence_text=mev.evidence_text,
            source_document_id=mev.source_document_id,
            source_reference_text=mev.source_reference_text,
            citation_json=mev.citation_json or {},
            confidence=mev.confidence,
            uncertainty_reason=mev.uncertainty_reason,
        )
        session.add(fev)
        count += 1

    if count == 0 and getattr(mirror_obj, "evidence_text", None):
        existing_inline = await session.execute(
            select(FinalEvidenceRecord.id).where(
                FinalEvidenceRecord.evidence_target_type == final_ev_type,
                FinalEvidenceRecord.evidence_target_id == final_obj_id,
                FinalEvidenceRecord.source_mirror_evidence_id.is_(None),
            ).limit(1)
        )
        if not existing_inline.scalar_one_or_none():
            session.add(
                FinalEvidenceRecord(
                    evidence_target_type=final_ev_type,
                    evidence_target_id=final_obj_id,
                    source_mirror_evidence_id=None,
                    resource_id=mirror_obj.resource_id,
                    batch_id=mirror_obj.batch_id,
                    llm_run_id=mirror_obj.llm_run_id,
                    llm_item_id=mirror_obj.llm_item_id,
                    review_record_id=review_record_id,
                    promotion_record_id=promotion_record_id,
                    evidence_type="llm_explanation",
                    evidence_text=mirror_obj.evidence_text,
                )
            )
            count += 1
    elif count == 0:
        warnings.append(f"NO_EVIDENCE_RECORDS_PROMOTED:{target_type}:{mirror_obj.id}")

    return count


async def promote_connection(
    session: AsyncSession,
    *,
    obj: MirrorRegionConnection,
    run: MirrorPromotionRun,
    review_record_id: uuid.UUID,
    warnings: list[str],
) -> tuple[MirrorPromotionRecord, FinalRegionConnection]:
    before = mrs.object_to_json(obj)
    final = FinalRegionConnection(
        source_mirror_connection_id=obj.id,
        source_region_candidate_id=obj.source_region_candidate_id,
        target_region_candidate_id=obj.target_region_candidate_id,
        source_region_final_id=obj.source_region_final_id,
        target_region_final_id=obj.target_region_final_id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=review_record_id,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        connection_type=obj.connection_type,
        directionality=obj.directionality,
        strength=obj.strength,
        modality=obj.modality,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        final_status="active",
        raw_payload_json=obj.raw_payload_json or {},
        normalized_payload_json=obj.normalized_payload_json or {},
    )
    session.add(final)
    await session.flush()

    record = create_promotion_record(
        run_id=run.id,
        target_type="connection",
        mirror_target_id=obj.id,
        status=MirrorPromotionRecordStatus.promoted,
        before_json=before,
        after_json=before,
        final_json={},
        review_record_id=review_record_id,
        final_target_type="final_connection",
        final_target_id=final.id,
        obj=obj,
    )
    session.add(record)
    await session.flush()

    final.promotion_record_id = record.id
    update_mirror_source_after_promotion(obj)
    after = mrs.object_to_json(obj)
    record.after_mirror_json = after
    record.final_object_json = mrs.object_to_json(final)

    await promote_evidence_for_target(
        session,
        target_type="connection",
        mirror_obj=obj,
        final_obj_id=final.id,
        review_record_id=review_record_id,
        promotion_record_id=record.id,
        warnings=warnings,
    )
    return record, final


async def promote_function(
    session: AsyncSession,
    *,
    obj: MirrorRegionFunction,
    run: MirrorPromotionRun,
    review_record_id: uuid.UUID,
    warnings: list[str],
) -> tuple[MirrorPromotionRecord, FinalRegionFunction]:
    before = mrs.object_to_json(obj)
    final = FinalRegionFunction(
        source_mirror_function_id=obj.id,
        region_candidate_id=obj.region_candidate_id,
        region_final_id=obj.region_final_id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=review_record_id,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        function_term=obj.function_term,
        function_category=obj.function_category,
        relation_type=obj.relation_type,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        final_status="active",
        raw_payload_json=obj.raw_payload_json or {},
        normalized_payload_json=obj.normalized_payload_json or {},
    )
    session.add(final)
    await session.flush()

    record = create_promotion_record(
        run_id=run.id,
        target_type="function",
        mirror_target_id=obj.id,
        status=MirrorPromotionRecordStatus.promoted,
        before_json=before,
        after_json=before,
        final_json={},
        review_record_id=review_record_id,
        final_target_type="final_function",
        final_target_id=final.id,
        obj=obj,
    )
    session.add(record)
    await session.flush()

    final.promotion_record_id = record.id
    update_mirror_source_after_promotion(obj)
    record.after_mirror_json = mrs.object_to_json(obj)
    record.final_object_json = mrs.object_to_json(final)

    await promote_evidence_for_target(
        session,
        target_type="function",
        mirror_obj=obj,
        final_obj_id=final.id,
        review_record_id=review_record_id,
        promotion_record_id=record.id,
        warnings=warnings,
    )
    return record, final


async def promote_circuit(
    session: AsyncSession,
    *,
    obj: MirrorRegionCircuit,
    run: MirrorPromotionRun,
    review_record_id: uuid.UUID,
    warnings: list[str],
) -> tuple[MirrorPromotionRecord, FinalRegionCircuit]:
    before = mrs.object_to_json(obj)
    final = FinalRegionCircuit(
        source_mirror_circuit_id=obj.id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=review_record_id,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        circuit_name=obj.circuit_name,
        circuit_type=obj.circuit_type,
        function_association=obj.function_association,
        description=obj.description,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        final_status="active",
        raw_payload_json=obj.raw_payload_json or {},
        normalized_payload_json=obj.normalized_payload_json or {},
    )
    session.add(final)
    await session.flush()

    mirror_regions = list(
        (
            await session.execute(
                select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == obj.id)
            )
        ).scalars().all()
    )
    for mr in mirror_regions:
        session.add(
            FinalCircuitRegion(
                final_circuit_id=final.id,
                source_mirror_circuit_region_id=mr.id,
                region_candidate_id=mr.region_candidate_id,
                region_final_id=mr.region_final_id,
                role=mr.role,
                sort_order=mr.sort_order,
            )
        )

    record = create_promotion_record(
        run_id=run.id,
        target_type="circuit",
        mirror_target_id=obj.id,
        status=MirrorPromotionRecordStatus.promoted,
        before_json=before,
        after_json=before,
        final_json={},
        review_record_id=review_record_id,
        final_target_type="final_circuit",
        final_target_id=final.id,
        obj=obj,
    )
    session.add(record)
    await session.flush()

    final.promotion_record_id = record.id
    update_mirror_source_after_promotion(obj)
    record.after_mirror_json = mrs.object_to_json(obj)
    record.final_object_json = mrs.object_to_json(final)

    await promote_evidence_for_target(
        session,
        target_type="circuit",
        mirror_obj=obj,
        final_obj_id=final.id,
        review_record_id=review_record_id,
        promotion_record_id=record.id,
        warnings=warnings,
    )
    return record, final


async def promote_triple(
    session: AsyncSession,
    *,
    obj: MirrorKgTriple,
    run: MirrorPromotionRun,
    review_record_id: uuid.UUID,
    warnings: list[str],
) -> tuple[MirrorPromotionRecord, FinalKgTriple]:
    before = mrs.object_to_json(obj)

    src_final_conn = await _lookup_final_id_for_mirror(
        session, FinalRegionConnection, FinalRegionConnection.source_mirror_connection_id, obj.source_mirror_connection_id
    )
    src_final_func = await _lookup_final_id_for_mirror(
        session, FinalRegionFunction, FinalRegionFunction.source_mirror_function_id, obj.source_mirror_function_id
    )
    src_final_circ = await _lookup_final_id_for_mirror(
        session, FinalRegionCircuit, FinalRegionCircuit.source_mirror_circuit_id, obj.source_mirror_circuit_id
    )
    if obj.source_mirror_connection_id and not src_final_conn:
        warnings.append(f"MISSING_SOURCE_FINAL_CONNECTION:{obj.id}")
    if obj.source_mirror_function_id and not src_final_func:
        warnings.append(f"MISSING_SOURCE_FINAL_FUNCTION:{obj.id}")
    if obj.source_mirror_circuit_id and not src_final_circ:
        warnings.append(f"MISSING_SOURCE_FINAL_CIRCUIT:{obj.id}")

    final = FinalKgTriple(
        source_mirror_triple_id=obj.id,
        subject_type=obj.subject_type,
        subject_id=obj.subject_id,
        subject_label=obj.subject_label,
        predicate=obj.predicate,
        object_type=obj.object_type,
        object_id=obj.object_id,
        object_label=obj.object_label,
        triple_scope=obj.triple_scope,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=review_record_id,
        source_final_connection_id=src_final_conn,
        source_final_function_id=src_final_func,
        source_final_circuit_id=src_final_circ,
        source_mirror_connection_id=obj.source_mirror_connection_id,
        source_mirror_function_id=obj.source_mirror_function_id,
        source_mirror_circuit_id=obj.source_mirror_circuit_id,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        final_status="active",
        raw_payload_json=obj.raw_payload_json or {},
        normalized_payload_json=obj.normalized_payload_json or {},
    )
    session.add(final)
    await session.flush()

    record = create_promotion_record(
        run_id=run.id,
        target_type="triple",
        mirror_target_id=obj.id,
        status=MirrorPromotionRecordStatus.promoted,
        before_json=before,
        after_json=before,
        final_json={},
        review_record_id=review_record_id,
        final_target_type="final_triple",
        final_target_id=final.id,
        obj=obj,
    )
    session.add(record)
    await session.flush()

    final.promotion_record_id = record.id
    update_mirror_source_after_promotion(obj)
    record.after_mirror_json = mrs.object_to_json(obj)
    record.final_object_json = mrs.object_to_json(final)

    await promote_evidence_for_target(
        session,
        target_type="triple",
        mirror_obj=obj,
        final_obj_id=final.id,
        review_record_id=review_record_id,
        promotion_record_id=record.id,
        warnings=warnings,
    )
    return record, final


async def run_mirror_promotion(
    session: AsyncSession,
    request: MirrorPromotionRequest,
) -> MirrorPromotionResponse:
    if not request.target_types:
        raise EmptyTargetTypesError("target_types must not be empty")
    for tt in request.target_types:
        if tt not in VALID_TARGET_TYPES:
            raise InvalidTargetTypeError(f"Invalid target_type: {tt}")

    scope = _scope_from_request(request)
    preview = await build_promotion_preview(session, request)

    if request.dry_run:
        return preview

    if not request.operator or not request.operator.strip():
        raise MissingOperatorError("operator is required for promotion run")
    if not request.reason or not request.reason.strip():
        raise MissingReasonError("reason is required for promotion run")
    if request.confirmation_text != preview.required_confirmation:
        raise ConfirmationMismatchError("confirmation_text does not match required_confirmation")

    run = create_promotion_run(
        target_types=request.target_types,
        scope_json=request.scope.model_dump(mode="json") if request.scope else {},
        scope=scope,
        dry_run=False,
        required_confirmation=preview.required_confirmation,
        operator=request.operator.strip(),
        reason=request.reason.strip(),
        confirmation_text=request.confirmation_text,
    )
    run.object_count = preview.object_count
    run.eligible_count = preview.eligible_count
    session.add(run)

    warnings = list(preview.warnings)
    promotion_record_ids: list[uuid.UUID] = []
    final_object_ids: dict[str, list[uuid.UUID]] = {
        "final_connection": [],
        "final_function": [],
        "final_circuit": [],
        "final_triple": [],
    }

    promoted = 0
    skipped_dup = 0
    skipped_inelig = 0
    failed = 0

    try:
        targets = await collect_promotion_targets(session, request.target_types, scope)
        for target_type, obj in targets:
            before = mrs.object_to_json(obj)
            eligible, reason, review_id, _ = await validate_promotion_eligibility(
                session, target_type, obj
            )
            if not eligible:
                status = (
                    MirrorPromotionRecordStatus.skipped_duplicate
                    if reason == "DUPLICATE_FINAL_EXISTS"
                    else MirrorPromotionRecordStatus.skipped_ineligible
                )
                if status == MirrorPromotionRecordStatus.skipped_duplicate:
                    skipped_dup += 1
                else:
                    skipped_inelig += 1
                rec = create_promotion_record(
                    run_id=run.id,
                    target_type=target_type,
                    mirror_target_id=obj.id,
                    status=status,
                    before_json=before,
                    after_json=before,
                    final_json={},
                    review_record_id=review_id,
                    message=reason,
                    obj=obj,
                )
                session.add(rec)
                promotion_record_ids.append(rec.id)
                continue

            try:
                if target_type == "connection":
                    rec, final = await promote_connection(
                        session, obj=obj, run=run, review_record_id=review_id, warnings=warnings
                    )
                    final_object_ids["final_connection"].append(final.id)
                elif target_type == "function":
                    rec, final = await promote_function(
                        session, obj=obj, run=run, review_record_id=review_id, warnings=warnings
                    )
                    final_object_ids["final_function"].append(final.id)
                elif target_type == "circuit":
                    rec, final = await promote_circuit(
                        session, obj=obj, run=run, review_record_id=review_id, warnings=warnings
                    )
                    final_object_ids["final_circuit"].append(final.id)
                else:
                    rec, final = await promote_triple(
                        session, obj=obj, run=run, review_record_id=review_id, warnings=warnings
                    )
                    final_object_ids["final_triple"].append(final.id)
                promoted += 1
                promotion_record_ids.append(rec.id)
            except Exception as exc:
                failed += 1
                rec = create_promotion_record(
                    run_id=run.id,
                    target_type=target_type,
                    mirror_target_id=obj.id,
                    status=MirrorPromotionRecordStatus.failed,
                    before_json=before,
                    after_json=before,
                    final_json={},
                    review_record_id=review_id,
                    message=str(exc),
                    obj=obj,
                )
                session.add(rec)
                promotion_record_ids.append(rec.id)

        run.promoted_count = promoted
        run.skipped_duplicate_count = skipped_dup
        run.skipped_ineligible_count = skipped_inelig
        run.failed_count = failed
        run.finished_at = datetime.now(timezone.utc)

        if failed > 0 and promoted > 0:
            run.status = MirrorPromotionRunStatus.partially_succeeded
        elif failed > 0:
            run.status = MirrorPromotionRunStatus.failed
        else:
            run.status = MirrorPromotionRunStatus.succeeded

        await session.commit()
    except Exception as exc:
        await session.rollback()
        run.status = MirrorPromotionRunStatus.failed
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        await session.commit()
        raise

    return MirrorPromotionResponse(
        run_id=run.id,
        dry_run=False,
        required_confirmation=preview.required_confirmation,
        object_count=preview.object_count,
        eligible_count=preview.eligible_count,
        promoted_count=promoted,
        skipped_duplicate_count=skipped_dup,
        skipped_ineligible_count=skipped_inelig,
        failed_count=failed,
        preview_items=preview.preview_items,
        promotion_record_ids=promotion_record_ids,
        final_object_ids=final_object_ids,
        warnings=sorted(set(warnings)),
    )


async def list_promotion_runs(
    session: AsyncSession,
    *,
    target_type: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorPromotionRun], int]:
    stmt = select(MirrorPromotionRun)
    count_stmt = select(func.count()).select_from(MirrorPromotionRun)
    if target_type:
        stmt = stmt.where(MirrorPromotionRun.target_types.contains([target_type]))
        count_stmt = count_stmt.where(MirrorPromotionRun.target_types.contains([target_type]))
    if status:
        stmt = stmt.where(MirrorPromotionRun.status == status)
        count_stmt = count_stmt.where(MirrorPromotionRun.status == status)
    if resource_id:
        stmt = stmt.where(MirrorPromotionRun.resource_id == resource_id)
        count_stmt = count_stmt.where(MirrorPromotionRun.resource_id == resource_id)
    if batch_id:
        stmt = stmt.where(MirrorPromotionRun.batch_id == batch_id)
        count_stmt = count_stmt.where(MirrorPromotionRun.batch_id == batch_id)
    if source_atlas:
        stmt = stmt.where(MirrorPromotionRun.source_atlas == source_atlas)
        count_stmt = count_stmt.where(MirrorPromotionRun.source_atlas == source_atlas)
    if granularity_level:
        stmt = stmt.where(MirrorPromotionRun.granularity_level == granularity_level)
        count_stmt = count_stmt.where(MirrorPromotionRun.granularity_level == granularity_level)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(MirrorPromotionRun.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
    )
    return rows, int(total)


async def get_promotion_run(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> MirrorPromotionRun | None:
    return await session.get(MirrorPromotionRun, run_id)


async def list_promotion_records(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    mirror_target_id: uuid.UUID | None = None,
    final_target_type: str | None = None,
    final_target_id: uuid.UUID | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorPromotionRecord], int]:
    stmt = select(MirrorPromotionRecord)
    count_stmt = select(func.count()).select_from(MirrorPromotionRecord)
    filters = [
        (run_id, MirrorPromotionRecord.run_id == run_id),
        (target_type, MirrorPromotionRecord.target_type == target_type),
        (mirror_target_id, MirrorPromotionRecord.mirror_target_id == mirror_target_id),
        (final_target_type, MirrorPromotionRecord.final_target_type == final_target_type),
        (final_target_id, MirrorPromotionRecord.final_target_id == final_target_id),
        (status, MirrorPromotionRecord.status == status),
        (resource_id, MirrorPromotionRecord.resource_id == resource_id),
        (batch_id, MirrorPromotionRecord.batch_id == batch_id),
    ]
    for val, cond in filters:
        if val is not None:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(MirrorPromotionRecord.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
    )
    return rows, int(total)
