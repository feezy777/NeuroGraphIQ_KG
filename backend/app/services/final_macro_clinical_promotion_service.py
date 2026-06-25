"""Final macro_clinical promotion service (Step 8.15).

Deterministic DB promotion from human-approved mirror macro clinical objects
to final_* tables.

Rules:
- No LLM calls.
- No kg_* writes.
- Dry run never persists run/record/final writes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.final_kg import (
    FinalEvidenceRecord,
    FinalKgTriple,
    FinalRegionCircuit,
    FinalRegionFunction,
)
from app.models.final_macro_clinical import (
    FinalCircuitFunction,
    FinalCircuitProjectionMembership,
    FinalCircuitStep,
    FinalMacroClinicalPromotionRecord,
    FinalMacroClinicalPromotionRun,
    FinalProjection,
    FinalProjectionFunction,
)
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_kg import (
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_macro_clinical import (
    MirrorCircuitFunction,
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.models.mirror_review import MirrorHumanReviewRecord
from app.schemas.final_macro_clinical import (
    FinalMacroClinicalPromotionRecordPreview,
    FinalMacroClinicalPromotionRecordRead,
    FinalMacroClinicalPromotionRecordListResponse,
    FinalMacroClinicalPromotionRequest,
    FinalMacroClinicalPromotionResponse,
    FinalMacroClinicalPromotionRunRead,
    FinalMacroClinicalPromotionRunListResponse,
    FinalObjectListResponse,
    FinalObjectRead,
    REQUIRED_PROMOTION_CONFIRM_TEXT,
)
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_review import MirrorReviewAction
from app.services import mirror_review_service as mirror_review
from app.services.triple_consolidation_service import normalize_triple_key

REQUIRED_CONFIRM = REQUIRED_PROMOTION_CONFIRM_TEXT

VALID_TARGET_TYPES = frozenset({
    "circuit",
    "circuit_step",
    "projection",
    "projection_function",
    "circuit_projection_membership",
    "region_function",
    "function",
    "circuit_function",
    "triple",
    "evidence",
})

BLOCKED_SIGNAL_TYPES = frozenset({
    "circuit_projection_cross_validation_result",
    "dual_model_verification_result",
})

PROMOTION_ORDER = (
    "circuit",
    "projection",
    "circuit_step",
    "circuit_projection_membership",
    "region_function",
    "function",
    "projection_function",
    "circuit_function",
    "triple",
    "evidence",
)

MIRROR_EVIDENCE_TYPE_BY_TARGET = {
    "projection": "mirror_connection",
    "region_function": "mirror_function",
    "function": "mirror_function",
    "circuit": "mirror_circuit",
    "triple": "mirror_triple",
    "circuit_step": "mirror_circuit_step",
    "projection_function": "mirror_projection_function",
    "circuit_projection_membership": "mirror_circuit_projection_membership",
    "circuit_function": "mirror_circuit_function",
}

FINAL_EVIDENCE_TYPE_BY_TARGET = {
    "projection": "final_projection",
    "region_function": "final_function",
    "function": "final_function",
    "circuit": "final_circuit",
    "triple": "final_triple",
    "circuit_step": "final_circuit_step",
    "projection_function": "final_projection_function",
    "circuit_projection_membership": "final_circuit_projection_membership",
    "circuit_function": "final_circuit_function",
}

FINAL_TABLE_BY_TARGET = {
    "circuit": "final_region_circuits",
    "projection": "final_projections",
    "circuit_step": "final_circuit_steps",
    "projection_function": "final_projection_functions",
    "circuit_projection_membership": "final_circuit_projection_memberships",
    "region_function": "final_region_functions",
    "function": "final_region_functions",
    "circuit_function": "final_circuit_functions",
    "triple": "final_kg_triples",
    "evidence": "final_evidence_records",
}


@dataclass
class PromotionCandidate:
    target_type: str
    obj: Any


@dataclass
class PromotionContext:
    session: AsyncSession
    request: FinalMacroClinicalPromotionRequest
    dry_run: bool
    run: FinalMacroClinicalPromotionRun | None = None
    warnings: list[str] | None = None
    promoted_cache: dict[tuple[str, uuid.UUID], uuid.UUID] | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_json(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    return {col.name: _json_safe(getattr(obj, col.name)) for col in obj.__table__.columns}


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _scope_json(request: FinalMacroClinicalPromotionRequest) -> dict[str, Any]:
    return request.scope.model_dump(mode="json") if request.scope else {}


def _is_projection_connection(obj: MirrorRegionConnection) -> bool:
    return _norm(obj.connection_type) == "projection"


def _build_final_uid(target_type: str, mirror_id: uuid.UUID) -> str:
    return f"final_macro_clinical:{target_type}:{mirror_id}"


async def _latest_approved_review_record(
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


async def _latest_validation_summary(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> dict[str, Any]:
    return await mirror_review.get_latest_validation_summary(session, target_type, target_id)


async def _latest_cross_validation_summary_for_target(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> dict[str, Any]:
    query = None
    if target_type == "circuit_projection_membership":
        query = select(MirrorCircuitProjectionCrossValidationResult).where(
            MirrorCircuitProjectionCrossValidationResult.circuit_id == obj.circuit_id,
            MirrorCircuitProjectionCrossValidationResult.projection_id == obj.projection_id,
        )
    elif target_type == "circuit":
        query = select(MirrorCircuitProjectionCrossValidationResult).where(
            MirrorCircuitProjectionCrossValidationResult.circuit_id == obj.id
        )
    elif target_type == "projection":
        query = select(MirrorCircuitProjectionCrossValidationResult).where(
            MirrorCircuitProjectionCrossValidationResult.projection_id == obj.id
        )
    if query is None:
        return {"result_count": 0, "has_conflict": False, "latest_validation_status": None}
    rows = list((await session.execute(query.order_by(MirrorCircuitProjectionCrossValidationResult.created_at.desc()).limit(20))).scalars().all())
    if not rows:
        return {"result_count": 0, "has_conflict": False, "latest_validation_status": None}
    return {
        "result_count": len(rows),
        "has_conflict": any(_norm(r.validation_status) == "conflict" for r in rows),
        "latest_validation_status": rows[0].validation_status,
    }


async def _latest_dual_model_summary_for_target(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> dict[str, Any]:
    query = select(MirrorDualModelVerificationResult).where(
        MirrorDualModelVerificationResult.object_type == target_type,
        MirrorDualModelVerificationResult.object_id == target_id,
    )
    rows = list((await session.execute(query.order_by(MirrorDualModelVerificationResult.created_at.desc()).limit(20))).scalars().all())
    if not rows:
        return {"result_count": 0, "has_model_conflict": False, "has_consensus_rejected": False, "latest_consensus_status": None}
    return {
        "result_count": len(rows),
        "has_model_conflict": any(_norm(r.consensus_status) == "model_conflict" for r in rows),
        "has_consensus_rejected": any(_norm(r.consensus_status) == "consensus_rejected" for r in rows),
        "latest_consensus_status": rows[0].consensus_status,
    }


async def _risk_flags(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    dual_summary = await _latest_dual_model_summary_for_target(session, target_type, obj.id)
    cross_summary = await _latest_cross_validation_summary_for_target(session, target_type, obj)

    flags: list[str] = []
    if dual_summary.get("has_model_conflict") or _norm(getattr(obj, "verification_status", None)) == "model_conflict":
        flags.append("model_conflict")
    if dual_summary.get("has_consensus_rejected"):
        flags.append("consensus_rejected")
    if cross_summary.get("has_conflict"):
        flags.append("cross_conflict")
    return sorted(set(flags)), dual_summary, cross_summary


def _mark_source_promoted(obj: Any) -> None:
    if hasattr(obj, "promotion_status"):
        obj.promotion_status = MirrorPromotionStatus.promoted
    if hasattr(obj, "mirror_status"):
        obj.mirror_status = MirrorStatus.promoted_to_final


async def find_duplicate_final_object(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> tuple[uuid.UUID | None, str | None]:
    """Duplicate/idempotent check:
    1) source mirror id
    2) business key
    """
    if target_type == "circuit":
        source = await session.execute(
            select(FinalRegionCircuit.id).where(FinalRegionCircuit.source_mirror_circuit_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        row = await session.execute(
            select(FinalRegionCircuit.id).where(
                FinalRegionCircuit.final_status == "active",
                FinalRegionCircuit.resource_id == obj.resource_id,
                FinalRegionCircuit.batch_id == obj.batch_id,
                FinalRegionCircuit.source_atlas == obj.source_atlas,
                FinalRegionCircuit.granularity_level == obj.granularity_level,
                FinalRegionCircuit.granularity_family == obj.granularity_family,
                func.lower(func.trim(FinalRegionCircuit.circuit_name)) == _norm(obj.circuit_name),
                FinalRegionCircuit.circuit_type == obj.circuit_type,
            ).limit(1)
        )
        return row.scalar_one_or_none(), "business_key"

    if target_type == "projection":
        source = await session.execute(
            select(FinalProjection.id).where(FinalProjection.source_mirror_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        rows = list(
            (
                await session.execute(
                    select(FinalProjection).where(
                        FinalProjection.final_status == "active",
                        FinalProjection.resource_id == obj.resource_id,
                        FinalProjection.batch_id == obj.batch_id,
                        FinalProjection.source_atlas == obj.source_atlas,
                        FinalProjection.granularity_level == obj.granularity_level,
                        FinalProjection.granularity_family == obj.granularity_family,
                        FinalProjection.projection_type == obj.connection_type,
                        FinalProjection.directionality == obj.directionality,
                        FinalProjection.source_region_candidate_id == obj.source_region_candidate_id,
                        FinalProjection.target_region_candidate_id == obj.target_region_candidate_id,
                    )
                )
            ).scalars().all()
        )
        return (rows[0].id, "business_key") if rows else (None, None)

    if target_type == "circuit_step":
        source = await session.execute(
            select(FinalCircuitStep.id).where(FinalCircuitStep.source_mirror_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        row = await session.execute(
            select(FinalCircuitStep.id).where(
                FinalCircuitStep.mirror_circuit_id == obj.circuit_id,
                FinalCircuitStep.step_order == obj.step_order,
                func.lower(func.trim(FinalCircuitStep.step_name)) == _norm(obj.step_name),
            ).limit(1)
        )
        return row.scalar_one_or_none(), "business_key"

    if target_type == "projection_function":
        source = await session.execute(
            select(FinalProjectionFunction.id).where(FinalProjectionFunction.source_mirror_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        row = await session.execute(
            select(FinalProjectionFunction.id).where(
                FinalProjectionFunction.mirror_projection_id == obj.projection_id,
                func.lower(func.trim(FinalProjectionFunction.function_term)) == _norm(obj.function_term),
                FinalProjectionFunction.function_category == obj.function_category,
                FinalProjectionFunction.relation_type == obj.relation_type,
            ).limit(1)
        )
        return row.scalar_one_or_none(), "business_key"

    if target_type == "circuit_projection_membership":
        source = await session.execute(
            select(FinalCircuitProjectionMembership.id).where(FinalCircuitProjectionMembership.source_mirror_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        row = await session.execute(
            select(FinalCircuitProjectionMembership.id).where(
                FinalCircuitProjectionMembership.mirror_circuit_id == obj.circuit_id,
                FinalCircuitProjectionMembership.mirror_projection_id == obj.projection_id,
                FinalCircuitProjectionMembership.mirror_source_step_id == obj.source_step_id,
                FinalCircuitProjectionMembership.mirror_target_step_id == obj.target_step_id,
                FinalCircuitProjectionMembership.role_in_circuit == obj.role_in_circuit,
            ).limit(1)
        )
        return row.scalar_one_or_none(), "business_key"

    if target_type in {"region_function", "function"}:
        source = await session.execute(
            select(FinalRegionFunction.id).where(FinalRegionFunction.source_mirror_function_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
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
        return row.scalar_one_or_none(), "business_key"

    if target_type == "circuit_function":
        if not isinstance(obj, MirrorCircuitFunction):
            return None, "business_key"
        source = await session.execute(
            select(FinalCircuitFunction.id).where(FinalCircuitFunction.source_mirror_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        term = obj.function_term_en or obj.function_term_cn or ""
        row = await session.execute(
            select(FinalCircuitFunction.id).where(
                FinalCircuitFunction.mirror_circuit_id == obj.circuit_id,
                func.lower(func.trim(FinalCircuitFunction.function_term)) == _norm(term),
            ).limit(1)
        )
        return row.scalar_one_or_none(), "business_key"

    if target_type == "triple":
        source = await session.execute(
            select(FinalKgTriple.id).where(FinalKgTriple.source_mirror_triple_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
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
            row_key = normalize_triple_key(
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
            )
            if row_key == key:
                return row.id, "business_key"
        return None, None

    if target_type == "evidence":
        source = await session.execute(
            select(FinalEvidenceRecord.id).where(FinalEvidenceRecord.source_mirror_evidence_id == obj.id).limit(1)
        )
        source_id = source.scalar_one_or_none()
        if source_id:
            return source_id, "source_mirror_id"
        row = await session.execute(
            select(FinalEvidenceRecord.id).where(
                FinalEvidenceRecord.evidence_target_type == obj.evidence_target_type.replace("mirror_", "final_"),
                FinalEvidenceRecord.evidence_target_id == obj.evidence_target_id,
                FinalEvidenceRecord.evidence_type == obj.evidence_type,
                func.lower(func.trim(FinalEvidenceRecord.evidence_text)) == _norm(obj.evidence_text),
            ).limit(1)
        )
        return row.scalar_one_or_none(), "business_key"

    return None, None


async def check_promotion_eligibility(
    session: AsyncSession,
    *,
    target_type: str,
    obj: Any,
    allow_conflict_with_human_reason: bool,
) -> tuple[str, str | None, list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return: eligibility_status, reason, risk_flags, validation, review, cross, dual."""
    if target_type in BLOCKED_SIGNAL_TYPES:
        return "not_supported_target_type", "signal objects cannot be promoted", [], {}, {}, {}, {}

    if target_type not in VALID_TARGET_TYPES:
        return "not_supported_target_type", "target_type not supported", [], {}, {}, {}, {}

    if hasattr(obj, "mirror_status") and obj.mirror_status != MirrorStatus.human_approved:
        return "not_human_approved", "mirror_status must be human_approved", [], {}, {}, {}, {}
    if hasattr(obj, "review_status") and obj.review_status != MirrorReviewStatus.approved:
        return "review_not_approved", "review_status must be approved", [], {}, {}, {}, {}
    if hasattr(obj, "promotion_status") and obj.promotion_status not in {
        MirrorPromotionStatus.not_promoted,
        MirrorPromotionStatus.failed,
    }:
        return "already_promoted", "promotion_status must be not_promoted or failed", [], {}, {}, {}, {}

    review_record = await _latest_approved_review_record(session, target_type, obj.id)
    review_summary = {
        "has_approved_review_record": bool(review_record),
        "latest_review_record_id": str(review_record.id) if review_record else None,
        "latest_reviewer_note": (review_record.reviewer_note or "") if review_record else "",
    }
    if review_record is None:
        return "review_not_approved", "latest approve review record missing", [], {}, review_summary, {}, {}

    validation_summary = await _latest_validation_summary(session, target_type, obj.id)
    if validation_summary.get("has_blocker") or validation_summary.get("has_error"):
        return "validation_blocked", "validation has blocker/error", [], validation_summary, review_summary, {}, {}

    duplicate_id, _ = await find_duplicate_final_object(session, target_type, obj)
    if duplicate_id:
        return "duplicate_final_exists", str(duplicate_id), [], validation_summary, review_summary, {}, {}

    risk_flags, dual_summary, cross_summary = await _risk_flags(session, target_type, obj)
    if risk_flags:
        reason = (review_record.reviewer_note or "").strip()
        if not allow_conflict_with_human_reason:
            return "risk_requires_confirmation", "risk flags present and bypass disabled", risk_flags, validation_summary, review_summary, cross_summary, dual_summary
        if not reason:
            return "risk_requires_confirmation", "risk flags require reviewer_note reason", risk_flags, validation_summary, review_summary, cross_summary, dual_summary

    return "eligible", None, risk_flags, validation_summary, review_summary, cross_summary, dual_summary


def _apply_scope_filters(stmt: Any, model: Any, request: FinalMacroClinicalPromotionRequest) -> Any:
    scope = request.scope
    if not scope:
        return stmt
    if scope.resource_id:
        stmt = stmt.where(model.resource_id == scope.resource_id)
    if scope.batch_id:
        stmt = stmt.where(model.batch_id == scope.batch_id)
    if scope.source_atlas:
        stmt = stmt.where(model.source_atlas == scope.source_atlas)
    if scope.source_version and hasattr(model, "source_version"):
        stmt = stmt.where(model.source_version == scope.source_version)
    if scope.granularity_level:
        stmt = stmt.where(model.granularity_level == scope.granularity_level)
    if scope.granularity_family:
        stmt = stmt.where(model.granularity_family == scope.granularity_family)
    return stmt


async def collect_promotion_candidates(
    session: AsyncSession,
    request: FinalMacroClinicalPromotionRequest,
) -> list[PromotionCandidate]:
    candidates: list[PromotionCandidate] = []
    mirror_ids = set(request.mirror_object_ids or [])
    target_types = list(dict.fromkeys(request.target_types))

    for target_type in target_types:
        if target_type not in VALID_TARGET_TYPES:
            continue
        if target_type in BLOCKED_SIGNAL_TYPES:
            continue

        if target_type == "circuit":
            stmt = _apply_scope_filters(select(MirrorRegionCircuit), MirrorRegionCircuit, request)
            if mirror_ids:
                stmt = stmt.where(MirrorRegionCircuit.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorRegionCircuit.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("circuit", row) for row in rows)
            continue

        if target_type == "projection":
            stmt = _apply_scope_filters(select(MirrorRegionConnection), MirrorRegionConnection, request)
            stmt = stmt.where(func.lower(func.trim(MirrorRegionConnection.connection_type)) == "projection")
            if mirror_ids:
                stmt = stmt.where(MirrorRegionConnection.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorRegionConnection.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("projection", row) for row in rows)
            continue

        if target_type == "circuit_step":
            stmt = _apply_scope_filters(select(MirrorCircuitStep), MirrorCircuitStep, request)
            if mirror_ids:
                stmt = stmt.where(MirrorCircuitStep.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorCircuitStep.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("circuit_step", row) for row in rows)
            continue

        if target_type == "projection_function":
            stmt = _apply_scope_filters(select(MirrorProjectionFunction), MirrorProjectionFunction, request)
            if mirror_ids:
                stmt = stmt.where(MirrorProjectionFunction.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorProjectionFunction.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("projection_function", row) for row in rows)
            continue

        if target_type == "circuit_projection_membership":
            stmt = _apply_scope_filters(select(MirrorCircuitProjectionMembership), MirrorCircuitProjectionMembership, request)
            if mirror_ids:
                stmt = stmt.where(MirrorCircuitProjectionMembership.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorCircuitProjectionMembership.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("circuit_projection_membership", row) for row in rows)
            continue

        if target_type in {"region_function", "function"}:
            stmt = _apply_scope_filters(select(MirrorRegionFunction), MirrorRegionFunction, request)
            if mirror_ids:
                stmt = stmt.where(MirrorRegionFunction.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorRegionFunction.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate(target_type, row) for row in rows)
            continue

        if target_type == "circuit_function":
            stmt = _apply_scope_filters(select(MirrorCircuitFunction), MirrorCircuitFunction, request)
            if mirror_ids:
                stmt = stmt.where(MirrorCircuitFunction.id.in_(mirror_ids))
            stmt = stmt.where(
                MirrorCircuitFunction.promotion_status.in_(
                    [MirrorPromotionStatus.not_promoted, MirrorPromotionStatus.failed]
                )
            )
            rows = list(
                (await session.execute(stmt.order_by(MirrorCircuitFunction.created_at.asc()).limit(request.limit)))
                .scalars()
                .all()
            )
            candidates.extend(PromotionCandidate("circuit_function", row) for row in rows)
            continue

        if target_type == "triple":
            stmt = _apply_scope_filters(select(MirrorKgTriple), MirrorKgTriple, request)
            if mirror_ids:
                stmt = stmt.where(MirrorKgTriple.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorKgTriple.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("triple", row) for row in rows)
            continue

        if target_type == "evidence":
            stmt = _apply_scope_filters(select(MirrorEvidenceRecord), MirrorEvidenceRecord, request)
            if mirror_ids:
                stmt = stmt.where(MirrorEvidenceRecord.id.in_(mirror_ids))
            rows = list((await session.execute(stmt.order_by(MirrorEvidenceRecord.created_at.asc()).limit(request.limit))).scalars().all())
            candidates.extend(PromotionCandidate("evidence", row) for row in rows)

    order_index = {tt: idx for idx, tt in enumerate(PROMOTION_ORDER)}
    candidates.sort(key=lambda c: (order_index.get(c.target_type, 999), getattr(c.obj, "created_at", datetime.min)))
    return candidates


async def _find_final_circuit_id_for_mirror(session: AsyncSession, mirror_circuit_id: uuid.UUID) -> uuid.UUID | None:
    row = await session.execute(
        select(FinalRegionCircuit.id).where(FinalRegionCircuit.source_mirror_circuit_id == mirror_circuit_id).limit(1)
    )
    return row.scalar_one_or_none()


async def _find_final_projection_id_for_mirror(session: AsyncSession, mirror_projection_id: uuid.UUID) -> uuid.UUID | None:
    row = await session.execute(
        select(FinalProjection.id).where(FinalProjection.source_mirror_id == mirror_projection_id).limit(1)
    )
    return row.scalar_one_or_none()


async def _find_final_step_id_for_mirror(session: AsyncSession, mirror_step_id: uuid.UUID | None) -> uuid.UUID | None:
    if not mirror_step_id:
        return None
    row = await session.execute(
        select(FinalCircuitStep.id).where(FinalCircuitStep.source_mirror_id == mirror_step_id).limit(1)
    )
    return row.scalar_one_or_none()


async def _find_final_function_id_for_mirror(session: AsyncSession, mirror_function_id: uuid.UUID | None) -> uuid.UUID | None:
    if not mirror_function_id:
        return None
    row = await session.execute(
        select(FinalRegionFunction.id).where(FinalRegionFunction.source_mirror_function_id == mirror_function_id).limit(1)
    )
    return row.scalar_one_or_none()


async def _promote_dependency_if_missing(
    ctx: PromotionContext,
    target_type: str,
    mirror_id: uuid.UUID,
) -> tuple[bool, uuid.UUID | None]:
    key = (target_type, mirror_id)
    if ctx.promoted_cache is not None and key in ctx.promoted_cache:
        return True, ctx.promoted_cache[key]

    if target_type == "circuit":
        existing = await _find_final_circuit_id_for_mirror(ctx.session, mirror_id)
        if existing:
            if ctx.promoted_cache is not None:
                ctx.promoted_cache[key] = existing
            return True, existing
        obj = await ctx.session.get(MirrorRegionCircuit, mirror_id)
    elif target_type == "projection":
        existing = await _find_final_projection_id_for_mirror(ctx.session, mirror_id)
        if existing:
            if ctx.promoted_cache is not None:
                ctx.promoted_cache[key] = existing
            return True, existing
        obj = await ctx.session.get(MirrorRegionConnection, mirror_id)
        if obj and not _is_projection_connection(obj):
            return False, None
    elif target_type == "circuit_step":
        existing = await _find_final_step_id_for_mirror(ctx.session, mirror_id)
        if existing:
            if ctx.promoted_cache is not None:
                ctx.promoted_cache[key] = existing
            return True, existing
        obj = await ctx.session.get(MirrorCircuitStep, mirror_id)
    elif target_type in {"region_function", "function"}:
        existing = await _find_final_function_id_for_mirror(ctx.session, mirror_id)
        if existing:
            if ctx.promoted_cache is not None:
                ctx.promoted_cache[key] = existing
            return True, existing
        obj = await ctx.session.get(MirrorRegionFunction, mirror_id)
    else:
        return False, None

    if obj is None:
        return False, None

    eligibility, _, _, _, _, _, _ = await check_promotion_eligibility(
        ctx.session,
        target_type=target_type,
        obj=obj,
        allow_conflict_with_human_reason=ctx.request.allow_conflict_with_human_reason,
    )
    if eligibility != "eligible":
        return False, None

    promoted = await _promote_by_type(ctx, target_type, obj, dependency_mode=True)
    if promoted is None:
        return False, None
    if ctx.promoted_cache is not None:
        ctx.promoted_cache[key] = promoted.id
    return True, promoted.id


async def _promote_evidence_for_target(
    ctx: PromotionContext,
    *,
    target_type: str,
    mirror_obj: Any,
    final_obj_id: uuid.UUID,
    review_record_id: uuid.UUID | None,
    record: FinalMacroClinicalPromotionRecord | None,
) -> None:
    mirror_ev_type = MIRROR_EVIDENCE_TYPE_BY_TARGET.get(target_type)
    final_ev_type = FINAL_EVIDENCE_TYPE_BY_TARGET.get(target_type)
    if not mirror_ev_type or not final_ev_type:
        return
    rows = list(
        (
            await ctx.session.execute(
                select(MirrorEvidenceRecord).where(
                    MirrorEvidenceRecord.evidence_target_type == mirror_ev_type,
                    MirrorEvidenceRecord.evidence_target_id == mirror_obj.id,
                )
            )
        ).scalars().all()
    )
    for row in rows:
        dup, _ = await find_duplicate_final_object(ctx.session, "evidence", row)
        if dup:
            continue
        if ctx.dry_run:
            continue
        ctx.session.add(
            FinalEvidenceRecord(
                evidence_target_type=final_ev_type,
                evidence_target_id=final_obj_id,
                source_mirror_evidence_id=row.id,
                resource_id=row.resource_id,
                batch_id=row.batch_id,
                llm_run_id=row.llm_run_id,
                llm_item_id=row.llm_item_id,
                review_record_id=review_record_id,
                promotion_record_id=record.id if record else None,
                evidence_type=row.evidence_type,
                evidence_text=row.evidence_text,
                source_document_id=row.source_document_id,
                source_reference_text=row.source_reference_text,
                citation_json=row.citation_json or {},
                confidence=row.confidence,
                uncertainty_reason=row.uncertainty_reason,
            )
        )


async def promote_circuit(
    ctx: PromotionContext,
    obj: MirrorRegionCircuit,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalRegionCircuit:
    final = FinalRegionCircuit(
        source_mirror_circuit_id=obj.id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=review_record_id,
        promotion_record_id=None,
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
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_projection(
    ctx: PromotionContext,
    obj: MirrorRegionConnection,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalProjection:
    final = FinalProjection(
        final_uid=_build_final_uid("projection", obj.id),
        source_mirror_type="projection",
        source_mirror_id=obj.id,
        promotion_run_id=ctx.run.id if ctx.run else None,
        promotion_record_id=None,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        source_region_candidate_id=obj.source_region_candidate_id,
        target_region_candidate_id=obj.target_region_candidate_id,
        projection_type=obj.connection_type,
        directionality=obj.directionality,
        strength=obj.strength,
        modality=obj.modality,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        validation_summary_json={},
        review_summary_json={},
        cross_validation_summary_json={},
        dual_model_summary_json={},
        provenance_json={"source_table": "mirror_region_connections", "source_id": str(obj.id)},
        final_status="active",
    )
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_circuit_step(
    ctx: PromotionContext,
    obj: MirrorCircuitStep,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalCircuitStep | None:
    final_circuit_id = await _find_final_circuit_id_for_mirror(ctx.session, obj.circuit_id)
    if not final_circuit_id and ctx.request.promote_dependencies:
        ok, final_circuit_id = await _promote_dependency_if_missing(ctx, "circuit", obj.circuit_id)
        if not ok:
            return None
    if not final_circuit_id:
        return None

    final = FinalCircuitStep(
        final_uid=_build_final_uid("circuit_step", obj.id),
        source_mirror_type="circuit_step",
        source_mirror_id=obj.id,
        promotion_run_id=ctx.run.id if ctx.run else None,
        promotion_record_id=None,
        final_circuit_id=final_circuit_id,
        mirror_circuit_id=obj.circuit_id,
        region_candidate_id=obj.region_candidate_id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        step_order=obj.step_order,
        step_name=obj.step_name,
        step_type=obj.step_type,
        role=obj.role,
        description=obj.description,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        validation_summary_json={},
        review_summary_json={},
        dual_model_summary_json={},
        provenance_json={"source_table": "mirror_circuit_steps", "source_id": str(obj.id)},
        final_status="active",
    )
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_circuit_projection_membership(
    ctx: PromotionContext,
    obj: MirrorCircuitProjectionMembership,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalCircuitProjectionMembership | None:
    final_circuit_id = await _find_final_circuit_id_for_mirror(ctx.session, obj.circuit_id)
    if not final_circuit_id and ctx.request.promote_dependencies:
        ok, final_circuit_id = await _promote_dependency_if_missing(ctx, "circuit", obj.circuit_id)
        if not ok:
            return None

    final_projection_id = await _find_final_projection_id_for_mirror(ctx.session, obj.projection_id)
    if not final_projection_id and ctx.request.promote_dependencies:
        ok, final_projection_id = await _promote_dependency_if_missing(ctx, "projection", obj.projection_id)
        if not ok:
            return None

    final_source_step_id = await _find_final_step_id_for_mirror(ctx.session, obj.source_step_id)
    final_target_step_id = await _find_final_step_id_for_mirror(ctx.session, obj.target_step_id)

    if obj.source_step_id and not final_source_step_id and ctx.request.promote_dependencies:
        _, final_source_step_id = await _promote_dependency_if_missing(ctx, "circuit_step", obj.source_step_id)
    if obj.target_step_id and not final_target_step_id and ctx.request.promote_dependencies:
        _, final_target_step_id = await _promote_dependency_if_missing(ctx, "circuit_step", obj.target_step_id)

    if not final_circuit_id or not final_projection_id:
        return None

    final = FinalCircuitProjectionMembership(
        final_uid=_build_final_uid("circuit_projection_membership", obj.id),
        source_mirror_type="circuit_projection_membership",
        source_mirror_id=obj.id,
        promotion_run_id=ctx.run.id if ctx.run else None,
        promotion_record_id=None,
        final_circuit_id=final_circuit_id,
        final_projection_id=final_projection_id,
        final_source_step_id=final_source_step_id,
        final_target_step_id=final_target_step_id,
        mirror_circuit_id=obj.circuit_id,
        mirror_projection_id=obj.projection_id,
        mirror_source_step_id=obj.source_step_id,
        mirror_target_step_id=obj.target_step_id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        step_order=obj.step_order,
        role_in_circuit=obj.role_in_circuit,
        source_method=obj.source_method,
        verification_status=obj.verification_status,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        validation_summary_json={},
        review_summary_json={},
        cross_validation_summary_json={},
        dual_model_summary_json={},
        provenance_json={"source_table": "mirror_circuit_projection_memberships", "source_id": str(obj.id)},
        final_status="active",
    )
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_region_function(
    ctx: PromotionContext,
    obj: MirrorRegionFunction,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalRegionFunction:
    final = FinalRegionFunction(
        source_mirror_function_id=obj.id,
        region_candidate_id=obj.region_candidate_id,
        region_final_id=obj.region_final_id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=review_record_id,
        promotion_record_id=None,
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
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_projection_function(
    ctx: PromotionContext,
    obj: MirrorProjectionFunction,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalProjectionFunction | None:
    final_projection_id = await _find_final_projection_id_for_mirror(ctx.session, obj.projection_id)
    if not final_projection_id and ctx.request.promote_dependencies:
        ok, final_projection_id = await _promote_dependency_if_missing(ctx, "projection", obj.projection_id)
        if not ok:
            return None
    if not final_projection_id:
        return None

    final = FinalProjectionFunction(
        final_uid=_build_final_uid("projection_function", obj.id),
        source_mirror_type="projection_function",
        source_mirror_id=obj.id,
        promotion_run_id=ctx.run.id if ctx.run else None,
        promotion_record_id=None,
        final_projection_id=final_projection_id,
        mirror_projection_id=obj.projection_id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        source_atlas=obj.source_atlas,
        source_version=obj.source_version,
        granularity_level=obj.granularity_level,
        granularity_family=obj.granularity_family,
        function_term=obj.function_term,
        function_category=obj.function_category,
        relation_type=obj.relation_type,
        confidence=obj.confidence,
        evidence_text=obj.evidence_text,
        uncertainty_reason=obj.uncertainty_reason,
        validation_summary_json={},
        review_summary_json={},
        dual_model_summary_json={},
        provenance_json={"source_table": "mirror_projection_functions", "source_id": str(obj.id)},
        final_status="active",
    )
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_circuit_function(
    ctx: PromotionContext,
    obj: MirrorCircuitFunction,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalCircuitFunction | None:
    # Step 10.6.6: candidate preview only — no final/macro_clinical writes yet.
    if ctx.warnings is not None:
        ctx.warnings.append(
            "circuit_function promotion is preview-only in Step 10.6.6 — use promotion-candidates preview API"
        )
    return None


async def promote_triple(
    ctx: PromotionContext,
    obj: MirrorKgTriple,
    *,
    review_record_id: uuid.UUID | None,
) -> FinalKgTriple:
    final_source_function_id = await _find_final_function_id_for_mirror(ctx.session, obj.source_mirror_function_id)
    final_source_circuit_id = await _find_final_circuit_id_for_mirror(ctx.session, obj.source_mirror_circuit_id) if obj.source_mirror_circuit_id else None

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
        promotion_record_id=None,
        source_final_connection_id=None,
        source_final_function_id=final_source_function_id,
        source_final_circuit_id=final_source_circuit_id,
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
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def promote_evidence(
    ctx: PromotionContext,
    obj: MirrorEvidenceRecord,
) -> FinalEvidenceRecord:
    final = FinalEvidenceRecord(
        evidence_target_type=obj.evidence_target_type.replace("mirror_", "final_"),
        evidence_target_id=obj.evidence_target_id,
        source_mirror_evidence_id=obj.id,
        resource_id=obj.resource_id,
        batch_id=obj.batch_id,
        llm_run_id=obj.llm_run_id,
        llm_item_id=obj.llm_item_id,
        review_record_id=None,
        promotion_record_id=None,
        evidence_type=obj.evidence_type,
        evidence_text=obj.evidence_text,
        source_document_id=obj.source_document_id,
        source_reference_text=obj.source_reference_text,
        citation_json=obj.citation_json or {},
        confidence=obj.confidence,
        uncertainty_reason=obj.uncertainty_reason,
    )
    ctx.session.add(final)
    await ctx.session.flush()
    return final


async def _promote_by_type(
    ctx: PromotionContext,
    target_type: str,
    obj: Any,
    *,
    dependency_mode: bool = False,
) -> Any | None:
    review_record = await _latest_approved_review_record(ctx.session, target_type, obj.id)
    review_record_id = review_record.id if review_record else None

    if target_type == "circuit":
        return await promote_circuit(ctx, obj, review_record_id=review_record_id)
    if target_type == "projection":
        return await promote_projection(ctx, obj, review_record_id=review_record_id)
    if target_type == "circuit_step":
        return await promote_circuit_step(ctx, obj, review_record_id=review_record_id)
    if target_type == "circuit_projection_membership":
        return await promote_circuit_projection_membership(ctx, obj, review_record_id=review_record_id)
    if target_type in {"region_function", "function"}:
        return await promote_region_function(ctx, obj, review_record_id=review_record_id)
    if target_type == "projection_function":
        return await promote_projection_function(ctx, obj, review_record_id=review_record_id)
    if target_type == "circuit_function":
        return await promote_circuit_function(ctx, obj, review_record_id=review_record_id)
    if target_type == "triple":
        return await promote_triple(ctx, obj, review_record_id=review_record_id)
    if target_type == "evidence":
        return await promote_evidence(ctx, obj)
    if not dependency_mode and ctx.warnings is not None:
        ctx.warnings.append(f"unsupported target type: {target_type}")
    return None


async def run_final_macro_clinical_promotion(
    session: AsyncSession,
    request: FinalMacroClinicalPromotionRequest,
) -> FinalMacroClinicalPromotionResponse:
    if not request.target_types:
        raise ValueError("target_types required")
    invalid = [t for t in request.target_types if t not in VALID_TARGET_TYPES]
    if invalid:
        raise ValueError(f"invalid target_types: {', '.join(sorted(set(invalid)))}")
    if any(t in BLOCKED_SIGNAL_TYPES for t in request.target_types):
        raise ValueError("signal target types are blocked from promotion")

    candidates = await collect_promotion_candidates(session, request)
    preview_items: list[FinalMacroClinicalPromotionRecordPreview] = []

    eligible_count = 0
    blocked_count = 0
    duplicate_count = 0
    risk_flag_count = 0

    for cand in candidates:
        tt, obj = cand.target_type, cand.obj
        status, reason, risk_flags, val_summary, review_summary, cross_summary, dual_summary = await check_promotion_eligibility(
            session,
            target_type=tt,
            obj=obj,
            allow_conflict_with_human_reason=request.allow_conflict_with_human_reason,
        )
        action = "dry_run_preview"
        duplicate_of_final_id: uuid.UUID | None = None

        if status == "eligible":
            eligible_count += 1
        elif status == "duplicate_final_exists":
            duplicate_count += 1
            action = "duplicate"
            try:
                duplicate_of_final_id = uuid.UUID(reason) if reason else None
            except Exception:
                duplicate_of_final_id = None
        else:
            blocked_count += 1
            action = "blocked"

        risk_flag_count += len(risk_flags)

        preview_items.append(
            FinalMacroClinicalPromotionRecordPreview(
                target_type=tt,
                mirror_object_id=obj.id,
                final_table=FINAL_TABLE_BY_TARGET.get(tt),
                final_object_id=None,
                action=action,
                eligibility_status=status,
                reason=reason,
                risk_flags=risk_flags,
                error_message=None,
                duplicate_of_final_id=duplicate_of_final_id,
            )
        )
        # keep summaries available for tests/debug use
        _ = (val_summary, review_summary, cross_summary, dual_summary)

    response = FinalMacroClinicalPromotionResponse(
        run_id=None,
        dry_run=request.dry_run,
        candidate_count=len(candidates),
        eligible_count=eligible_count,
        promoted_count=0,
        skipped_count=0,
        failed_count=0,
        blocked_count=blocked_count,
        duplicate_count=duplicate_count,
        risk_flag_count=risk_flag_count,
        records_preview=preview_items,
        warnings=[],
        required_confirm_text=REQUIRED_CONFIRM,
    )

    if request.dry_run:
        return response

    if request.confirm_text != REQUIRED_CONFIRM:
        raise ValueError("confirm_text mismatch")

    run = FinalMacroClinicalPromotionRun(
        id=uuid.uuid4(),
        scope_json=_scope_json(request),
        target_types=list(dict.fromkeys(request.target_types)),
        dry_run=False,
        confirm_text=request.confirm_text,
        status="running",
        candidate_count=len(candidates),
        eligible_count=eligible_count,
        promoted_count=0,
        skipped_count=0,
        failed_count=0,
        blocked_count=blocked_count,
        duplicate_count=duplicate_count,
        risk_flag_count=risk_flag_count,
        error_message=None,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        created_by=request.created_by,
    )
    session.add(run)
    await session.flush()

    ctx = PromotionContext(
        session=session,
        request=request,
        dry_run=False,
        run=run,
        warnings=[],
        promoted_cache={},
    )

    promoted_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        for cand in candidates:
            tt, obj = cand.target_type, cand.obj
            eligibility_status, reason, risk_flags, val_summary, review_summary, cross_summary, dual_summary = await check_promotion_eligibility(
                session,
                target_type=tt,
                obj=obj,
                allow_conflict_with_human_reason=request.allow_conflict_with_human_reason,
            )

            record = FinalMacroClinicalPromotionRecord(
                id=uuid.uuid4(),
                run_id=run.id,
                target_type=tt,
                mirror_object_id=obj.id,
                final_table=FINAL_TABLE_BY_TARGET.get(tt),
                final_object_id=None,
                action="skipped",
                reason=reason,
                eligibility_status=eligibility_status,
                risk_flags=risk_flags,
                validation_summary_json=val_summary or {},
                review_summary_json=review_summary or {},
                cross_validation_summary_json=cross_summary or {},
                dual_model_summary_json=dual_summary or {},
                duplicate_of_final_id=None,
                error_message=None,
            )
            session.add(record)

            if eligibility_status != "eligible":
                if eligibility_status == "duplicate_final_exists" and reason:
                    try:
                        record.duplicate_of_final_id = uuid.UUID(reason)
                        record.action = "duplicate"
                    except Exception:
                        record.action = "skipped"
                else:
                    record.action = "blocked"
                skipped_count += 1
                continue

            try:
                promoted = await _promote_by_type(ctx, tt, obj)
                if promoted is None:
                    record.action = "blocked"
                    record.eligibility_status = "dependency_missing"
                    record.reason = "required dependency missing"
                    skipped_count += 1
                    continue

                if hasattr(promoted, "promotion_record_id"):
                    promoted.promotion_record_id = record.id
                if hasattr(promoted, "promotion_run_id"):
                    promoted.promotion_run_id = run.id

                if tt != "evidence":
                    _mark_source_promoted(obj)
                    await _promote_evidence_for_target(
                        ctx,
                        target_type=tt,
                        mirror_obj=obj,
                        final_obj_id=promoted.id,
                        review_record_id=uuid.UUID(review_summary["latest_review_record_id"]) if review_summary.get("latest_review_record_id") else None,
                        record=record,
                    )

                record.action = "promoted"
                record.final_object_id = promoted.id
                promoted_count += 1
                if ctx.promoted_cache is not None:
                    ctx.promoted_cache[(tt, obj.id)] = promoted.id
            except Exception as exc:
                record.action = "failed"
                record.eligibility_status = "failed"
                record.error_message = str(exc)
                failed_count += 1

        run.promoted_count = promoted_count
        run.skipped_count = skipped_count
        run.failed_count = failed_count
        run.finished_at = datetime.now(timezone.utc)
        if failed_count > 0 and promoted_count > 0:
            run.status = "partially_succeeded"
        elif failed_count > 0:
            run.status = "failed"
        else:
            run.status = "succeeded"
        await session.commit()
    except Exception as exc:
        await session.rollback()
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        await session.commit()
        raise

    response.run_id = run.id
    response.promoted_count = promoted_count
    response.skipped_count = skipped_count
    response.failed_count = failed_count
    response.dry_run = False
    return response


async def list_promotion_runs(
    session: AsyncSession,
    *,
    status: str | None = None,
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FinalMacroClinicalPromotionRunListResponse:
    stmt = select(FinalMacroClinicalPromotionRun)
    count_stmt = select(func.count()).select_from(FinalMacroClinicalPromotionRun)

    if status:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.status == status)
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.status == status)
    if run_id:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.id == run_id)
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.id == run_id)
    if target_type:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.target_types.contains([target_type]))
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.target_types.contains([target_type]))
    if resource_id:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.scope_json["resource_id"].astext == str(resource_id))
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.scope_json["resource_id"].astext == str(resource_id))
    if batch_id:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.scope_json["batch_id"].astext == str(batch_id))
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.scope_json["batch_id"].astext == str(batch_id))
    if source_atlas:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.scope_json["source_atlas"].astext == source_atlas)
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.scope_json["source_atlas"].astext == source_atlas)
    if granularity_level:
        stmt = stmt.where(FinalMacroClinicalPromotionRun.scope_json["granularity_level"].astext == granularity_level)
        count_stmt = count_stmt.where(FinalMacroClinicalPromotionRun.scope_json["granularity_level"].astext == granularity_level)

    total = int((await session.execute(count_stmt)).scalar_one())
    rows = list(
        (
            await session.execute(
                stmt.order_by(FinalMacroClinicalPromotionRun.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
    )
    return FinalMacroClinicalPromotionRunListResponse(
        items=[FinalMacroClinicalPromotionRunRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def list_promotion_records(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    mirror_object_id: uuid.UUID | None = None,
    final_object_id: uuid.UUID | None = None,
    action: str | None = None,
    eligibility_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FinalMacroClinicalPromotionRecordListResponse:
    stmt = select(FinalMacroClinicalPromotionRecord)
    count_stmt = select(func.count()).select_from(FinalMacroClinicalPromotionRecord)
    filters = [
        (run_id, FinalMacroClinicalPromotionRecord.run_id == run_id),
        (target_type, FinalMacroClinicalPromotionRecord.target_type == target_type),
        (mirror_object_id, FinalMacroClinicalPromotionRecord.mirror_object_id == mirror_object_id),
        (final_object_id, FinalMacroClinicalPromotionRecord.final_object_id == final_object_id),
        (action, FinalMacroClinicalPromotionRecord.action == action),
        (eligibility_status, FinalMacroClinicalPromotionRecord.eligibility_status == eligibility_status),
    ]
    for value, cond in filters:
        if value is not None:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

    total = int((await session.execute(count_stmt)).scalar_one())
    rows = list(
        (
            await session.execute(
                stmt.order_by(FinalMacroClinicalPromotionRecord.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
    )
    return FinalMacroClinicalPromotionRecordListResponse(
        items=[FinalMacroClinicalPromotionRecordRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def list_final_objects(
    session: AsyncSession,
    *,
    target_type: str,
    source_mirror_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FinalObjectListResponse:
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(f"invalid target_type: {target_type}")

    if target_type == "projection":
        model = FinalProjection
        source_col = FinalProjection.source_mirror_id
        label_col = FinalProjection.projection_type
    elif target_type == "circuit_step":
        model = FinalCircuitStep
        source_col = FinalCircuitStep.source_mirror_id
        label_col = FinalCircuitStep.step_name
    elif target_type == "projection_function":
        model = FinalProjectionFunction
        source_col = FinalProjectionFunction.source_mirror_id
        label_col = FinalProjectionFunction.function_term
    elif target_type == "circuit_projection_membership":
        model = FinalCircuitProjectionMembership
        source_col = FinalCircuitProjectionMembership.source_mirror_id
        label_col = FinalCircuitProjectionMembership.role_in_circuit
    elif target_type == "circuit_function":
        model = FinalCircuitFunction
        source_col = FinalCircuitFunction.source_mirror_id
        label_col = FinalCircuitFunction.function_term
    elif target_type in {"region_function", "function"}:
        model = FinalRegionFunction
        source_col = FinalRegionFunction.source_mirror_function_id
        label_col = FinalRegionFunction.function_term
    elif target_type == "circuit":
        model = FinalRegionCircuit
        source_col = FinalRegionCircuit.source_mirror_circuit_id
        label_col = FinalRegionCircuit.circuit_name
    elif target_type == "triple":
        model = FinalKgTriple
        source_col = FinalKgTriple.source_mirror_triple_id
        label_col = FinalKgTriple.predicate
    else:
        model = FinalEvidenceRecord
        source_col = FinalEvidenceRecord.source_mirror_evidence_id
        label_col = FinalEvidenceRecord.evidence_type

    stmt = select(model)
    count_stmt = select(func.count()).select_from(model)
    if source_mirror_id:
        stmt = stmt.where(source_col == source_mirror_id)
        count_stmt = count_stmt.where(source_col == source_mirror_id)

    total = int((await session.execute(count_stmt)).scalar_one())
    rows = list((await session.execute(stmt.order_by(model.created_at.desc()).limit(limit).offset(offset))).scalars().all())

    items = [
        FinalObjectRead(
            id=row.id,
            final_uid=getattr(row, "final_uid", None),
            source_mirror_id=getattr(row, source_col.key, None),
            source_atlas=getattr(row, "source_atlas", None),
            granularity_level=getattr(row, "granularity_level", None),
            label=str(getattr(row, label_col.key, "")) if getattr(row, label_col.key, None) is not None else None,
            confidence=float(getattr(row, "confidence")) if getattr(row, "confidence", None) is not None else None,
            final_status=getattr(row, "final_status", "active"),
            promotion_run_id=getattr(row, "promotion_run_id", None),
            created_at=getattr(row, "created_at", None),
            payload=_row_json(row),
        )
        for row in rows
    ]
    return FinalObjectListResponse(items=items, total=total, limit=limit, offset=offset)


async def get_final_object(
    session: AsyncSession,
    *,
    target_type: str,
    final_object_id: uuid.UUID,
) -> FinalObjectRead | None:
    res = await list_final_objects(session, target_type=target_type, limit=1, offset=0)
    model_map = {
        "projection": FinalProjection,
        "circuit_step": FinalCircuitStep,
        "projection_function": FinalProjectionFunction,
        "circuit_projection_membership": FinalCircuitProjectionMembership,
        "circuit_function": FinalCircuitFunction,
        "region_function": FinalRegionFunction,
        "function": FinalRegionFunction,
        "circuit": FinalRegionCircuit,
        "triple": FinalKgTriple,
        "evidence": FinalEvidenceRecord,
    }
    model = model_map.get(target_type)
    if model is None:
        raise ValueError(f"invalid target_type: {target_type}")
    row = await session.get(model, final_object_id)
    if row is None:
        return None
    return FinalObjectRead(
        id=row.id,
        final_uid=getattr(row, "final_uid", None),
        source_mirror_id=getattr(row, "source_mirror_id", None)
        or getattr(row, "source_mirror_circuit_id", None)
        or getattr(row, "source_mirror_function_id", None)
        or getattr(row, "source_mirror_triple_id", None)
        or getattr(row, "source_mirror_evidence_id", None),
        source_atlas=getattr(row, "source_atlas", None),
        granularity_level=getattr(row, "granularity_level", None),
        label=None,
        confidence=float(getattr(row, "confidence")) if getattr(row, "confidence", None) is not None else None,
        final_status=getattr(row, "final_status", "active"),
        promotion_run_id=getattr(row, "promotion_run_id", None),
        created_at=getattr(row, "created_at", None),
        payload=_row_json(row),
    )
