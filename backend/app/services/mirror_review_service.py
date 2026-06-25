"""Mirror KG Human Review — manual review queue for mirror objects (Step 8).

Reads/writes mirror connections/functions/circuits/triples and mirror_human_review_records.
Does NOT call LLM; does NOT write final_* / kg_*; does NOT promote.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_review import MirrorHumanReviewRecord
from app.models.mirror_validation import MirrorRuleValidationResult
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.schemas.mirror_review import MirrorReviewAction
from app.schemas.mirror_validation import MirrorValidationSeverity
from app.services import mirror_review_macro_clinical as mc_review

VALID_TARGET_TYPES = mc_review.VALID_MACRO_REVIEW_TARGET_TYPES

DEFAULT_QUEUE_MIRROR_STATUSES = frozenset({
    MirrorStatus.rule_checked,
    MirrorStatus.human_review_pending,
    MirrorStatus.llm_suggested,
})

DEFAULT_QUEUE_REVIEW_STATUSES = frozenset({
    MirrorReviewStatus.pending,
    MirrorReviewStatus.needs_revision,
})

DEFAULT_QUEUE_PROMOTION_STATUSES = frozenset({
    MirrorPromotionStatus.not_promoted,
    MirrorPromotionStatus.blocked,
})

EXCLUDED_DEFAULT_MIRROR_STATUSES = frozenset({
    MirrorStatus.human_rejected,
    MirrorStatus.promoted_to_final,
    MirrorStatus.superseded,
})

EDITABLE_FIELDS: dict[str, frozenset[str]] = dict(mc_review.EDITABLE_FIELDS)

PROVENANCE_FIELDS = frozenset({
    "id", "resource_id", "batch_id", "llm_run_id", "llm_item_id",
    "source_atlas", "source_version", "granularity_level", "granularity_family",
    "created_at", "updated_at", "created_by", "updated_by",
    "source_region_candidate_id", "target_region_candidate_id", "region_candidate_id",
    "subject_id", "object_id", "subject_type", "object_type", "triple_scope",
    "source_mirror_connection_id", "source_mirror_function_id", "source_mirror_circuit_id",
    "raw_payload_json", "normalized_payload_json", "promotion_status",
})


class TargetNotFoundError(Exception):
    def __init__(self, target_type: str, target_id: str):
        self.target_type = target_type
        self.target_id = target_id
        super().__init__(f"{target_type} not found: {target_id}")


class InvalidTargetTypeError(Exception):
    def __init__(self, value: str):
        self.value = value
        super().__init__(f"invalid target_type: {value}")


class InvalidReviewActionError(Exception):
    pass


class ReviewerNoteRequiredError(Exception):
    pass


class ReviewerReasonRequiredError(Exception):
    pass


class SignalActionOnDomainError(Exception):
    pass


class DomainActionOnSignalError(Exception):
    pass


class EditPatchEmptyError(Exception):
    pass


class ForbiddenEditFieldError(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"field not editable: {field}")


class MirrorObjectNotValidatedError(Exception):
    pass


class MirrorObjectHasBlockersError(Exception):
    def __init__(self, summary: dict[str, Any]):
        self.summary = summary
        super().__init__("object has blocker/error validation results")


class TargetAlreadyPromotedError(Exception):
    pass


class TargetNotReviewableError(Exception):
    pass


class ReviewRecordNotFoundError(Exception):
    pass


@dataclass
class QueueScope:
    target_types: list[str] | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_statuses: list[str] | None = None
    review_statuses: list[str] | None = None
    promotion_statuses: list[str] | None = None
    has_blocker: bool | None = None
    has_error: bool | None = None
    has_warning: bool | None = None
    has_model_conflict: bool | None = None
    has_cross_conflict: bool | None = None
    consensus_status: str | None = None
    verification_status: str | None = None
    recommended_review_priority: str | None = None
    search: str | None = None
    limit: int = 50
    offset: int = 0


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def object_to_json(obj: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for col in obj.__table__.columns:
        data[col.name] = _json_safe(getattr(obj, col.name))
    return data


def build_before_after_json(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return before, after


async def get_target(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> Any:
    if target_type not in VALID_TARGET_TYPES:
        raise InvalidTargetTypeError(target_type)
    model = mc_review.MODEL_MAP.get(target_type)
    if model is None:
        raise InvalidTargetTypeError(target_type)
    row = await session.get(model, target_id)
    if row is None:
        raise TargetNotFoundError(target_type, str(target_id))
    return row


async def get_latest_validation_summary(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                select(MirrorRuleValidationResult)
                .where(
                    MirrorRuleValidationResult.target_type == target_type,
                    MirrorRuleValidationResult.target_id == target_id,
                )
                .order_by(MirrorRuleValidationResult.created_at.desc())
                .limit(200)
            )
        ).scalars().all()
    )
    if not rows:
        return {
            "validated": False,
            "result_count": 0,
            "has_blocker": False,
            "has_error": False,
            "has_warning": False,
            "blocker_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "results": [],
        }

    blocker = error = warning = info = 0
    result_items: list[dict[str, Any]] = []
    for r in rows:
        if r.severity == MirrorValidationSeverity.blocker:
            blocker += 1
        elif r.severity == MirrorValidationSeverity.error:
            error += 1
        elif r.severity == MirrorValidationSeverity.warning:
            warning += 1
        else:
            info += 1
        result_items.append({
            "rule_code": r.rule_code,
            "severity": r.severity,
            "status": r.status,
            "message": r.message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "validated": True,
        "result_count": len(rows),
        "has_blocker": blocker > 0,
        "has_error": error > 0,
        "has_warning": warning > 0,
        "blocker_count": blocker,
        "error_count": error,
        "warning_count": warning,
        "info_count": info,
        "results": result_items[:20],
    }


async def get_evidence_summary(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> dict[str, Any]:
    evidence_type_map = {
        "connection": "mirror_connection",
        "projection": "mirror_connection",
        "function": "mirror_function",
        "region_function": "mirror_function",
        "circuit": "mirror_circuit",
        "triple": "mirror_triple",
        "circuit_step": "mirror_circuit_step",
        "projection_function": "mirror_projection_function",
        "circuit_projection_membership": "mirror_circuit_projection_membership",
    }
    et = evidence_type_map.get(target_type, target_type)
    rows = list(
        (
            await session.execute(
                select(MirrorEvidenceRecord).where(
                    MirrorEvidenceRecord.evidence_target_type == et,
                    MirrorEvidenceRecord.evidence_target_id == target_id,
                )
            )
        ).scalars().all()
    )
    return {
        "count": len(rows),
        "records": [
            {
                "id": str(r.id),
                "evidence_type": r.evidence_type,
                "evidence_text": r.evidence_text,
                "confidence": float(r.confidence) if r.confidence is not None else None,
                "llm_run_id": str(r.llm_run_id) if r.llm_run_id else None,
            }
            for r in rows[:20]
        ],
    }


def _display_label(target_type: str, obj: Any) -> str:
    return mc_review.display_label(target_type, obj)


def _summary(target_type: str, obj: Any) -> str:
    return mc_review.summary_text(target_type, obj)


def _apply_scope_filters(q, model, scope: QueueScope, *, use_defaults: bool):
    if scope.resource_id:
        q = q.where(model.resource_id == scope.resource_id)
    if scope.batch_id:
        q = q.where(model.batch_id == scope.batch_id)
    if scope.source_atlas:
        q = q.where(model.source_atlas == scope.source_atlas)
    if scope.granularity_level:
        q = q.where(model.granularity_level == scope.granularity_level)
    if scope.granularity_family:
        q = q.where(model.granularity_family == scope.granularity_family)

    if scope.mirror_statuses:
        q = q.where(model.mirror_status.in_(scope.mirror_statuses))
    elif use_defaults:
        q = q.where(model.mirror_status.in_(DEFAULT_QUEUE_MIRROR_STATUSES))

    if scope.review_statuses:
        q = q.where(model.review_status.in_(scope.review_statuses))
    elif use_defaults:
        q = q.where(model.review_status.in_(DEFAULT_QUEUE_REVIEW_STATUSES))

    if scope.promotion_statuses:
        q = q.where(model.promotion_status.in_(scope.promotion_statuses))
    elif use_defaults:
        q = q.where(model.promotion_status.in_(DEFAULT_QUEUE_PROMOTION_STATUSES))

    if scope.search:
        pattern = f"%{scope.search}%"
        if model is MirrorRegionConnection:
            q = q.where(or_(
                model.connection_type.ilike(pattern),
                model.evidence_text.ilike(pattern),
            ))
        elif model is MirrorRegionFunction:
            q = q.where(or_(
                model.function_term.ilike(pattern),
                model.evidence_text.ilike(pattern),
            ))
        elif model is MirrorRegionCircuit:
            q = q.where(or_(
                model.circuit_name.ilike(pattern),
                model.evidence_text.ilike(pattern),
            ))
        elif model is MirrorKgTriple:
            q = q.where(or_(
                model.subject_label.ilike(pattern),
                model.predicate.ilike(pattern),
                model.object_label.ilike(pattern),
            ))
    return q


async def _row_to_queue_item(
    session: AsyncSession,
    target_type: str,
    obj: Any,
) -> dict[str, Any]:
    val_type = mc_review.normalize_target_type(target_type)
    if target_type in mc_review.SIGNAL_TARGET_TYPES:
        val_type = target_type
    val_summary = await get_latest_validation_summary(session, val_type, obj.id)
    ev_summary = await get_evidence_summary(session, target_type, obj.id)
    is_signal = mc_review.is_signal_target(target_type)

    cross_status = getattr(obj, "validation_status", None) if target_type == "circuit_projection_cross_validation_result" else None
    consensus_status = getattr(obj, "consensus_status", None) if target_type == "dual_model_verification_result" else None
    verification_status = getattr(obj, "verification_status", None) if target_type == "circuit_projection_membership" else None

    if is_signal:
        statuses = await mc_review.get_signal_status(session, target_type, obj.id)
        mirror_status = statuses["mirror_status"]
        review_status = statuses["review_status"]
        promotion_status = statuses["promotion_status"]
    else:
        mirror_status = obj.mirror_status
        review_status = obj.review_status
        promotion_status = obj.promotion_status

    evidence_empty = not (getattr(obj, "evidence_text", None) or "").strip()
    priority = mc_review.compute_review_priority(
        val_summary,
        cross_status=cross_status,
        consensus_status=consensus_status,
        verification_status=verification_status,
        evidence_empty=evidence_empty,
        is_signal=is_signal,
    )
    gating = mc_review.compute_gating(target_type, obj, val_summary, is_signal=is_signal)
    conf = float(obj.confidence) if getattr(obj, "confidence", None) is not None else None
    label = _display_label(target_type, obj)
    summ = _summary(target_type, obj)

    return {
        "target_type": target_type,
        "target_id": obj.id,
        "display_label": label,
        "target_label": label,
        "summary": summ,
        "target_summary": summ,
        "resource_id": getattr(obj, "resource_id", None),
        "batch_id": getattr(obj, "batch_id", None),
        "source_atlas": getattr(obj, "source_atlas", None),
        "granularity_level": getattr(obj, "granularity_level", None),
        "granularity_family": getattr(obj, "granularity_family", None),
        "mirror_status": mirror_status,
        "review_status": review_status,
        "promotion_status": promotion_status,
        "confidence": conf,
        "evidence_text": getattr(obj, "evidence_text", None),
        "uncertainty_reason": getattr(obj, "uncertainty_reason", None),
        "latest_validation_summary": val_summary,
        "evidence_count": ev_summary["count"],
        "llm_run_id": getattr(obj, "llm_run_id", None),
        "llm_item_id": getattr(obj, "llm_item_id", None),
        "recommended_review_priority": priority,
        "blocker_count": val_summary.get("blocker_count", 0),
        "error_count": val_summary.get("error_count", 0),
        "warning_count": val_summary.get("warning_count", 0),
        "info_count": val_summary.get("info_count", 0),
        "consensus_status": consensus_status,
        "verification_status": verification_status,
        "cross_validation_status": cross_status,
        "can_approve": gating["can_approve"],
        "gating_reasons": gating["gating_reasons"],
        "object_category": "signal_object" if is_signal else "domain_object",
        "created_at": getattr(obj, "created_at", None),
        "updated_at": getattr(obj, "updated_at", None),
    }


async def list_mirror_review_queue(
    session: AsyncSession,
    scope: QueueScope,
) -> tuple[list[dict[str, Any]], int]:
    types = scope.target_types or [
        "connection", "function", "circuit", "triple",
        "projection", "circuit_step", "projection_function",
        "circuit_projection_membership",
        "circuit_projection_cross_validation_result",
        "dual_model_verification_result",
    ]
    for t in types:
        if t not in VALID_TARGET_TYPES:
            raise InvalidTargetTypeError(t)

    use_defaults = (
        scope.mirror_statuses is None
        and scope.review_statuses is None
        and scope.promotion_statuses is None
    )

    all_items: list[dict[str, Any]] = []
    fetch_limit = min(scope.limit + scope.offset + 200, 2000)

    domain_pairs: list[tuple[str, Any]] = []
    if "connection" in types:
        domain_pairs.append(("connection", MirrorRegionConnection))
    if "projection" in types:
        domain_pairs.append(("projection", MirrorRegionConnection))
    if "function" in types or "region_function" in types:
        tt = "region_function" if "region_function" in types and "function" not in types else "function"
        if ("function", MirrorRegionFunction) not in domain_pairs and ("region_function", MirrorRegionFunction) not in domain_pairs:
            domain_pairs.append((tt, MirrorRegionFunction))
    if "circuit" in types:
        domain_pairs.append(("circuit", MirrorRegionCircuit))
    if "triple" in types:
        domain_pairs.append(("triple", MirrorKgTriple))
    if "circuit_step" in types:
        domain_pairs.append(("circuit_step", MirrorCircuitStep))
    if "projection_function" in types:
        domain_pairs.append(("projection_function", MirrorProjectionFunction))
    if "circuit_projection_membership" in types:
        domain_pairs.append(("circuit_projection_membership", MirrorCircuitProjectionMembership))

    for tt, model in domain_pairs:
        q = _apply_scope_filters(select(model), model, scope, use_defaults=use_defaults)
        rows = list((await session.execute(q.order_by(model.updated_at.desc()).limit(fetch_limit))).scalars().all())
        for r in rows:
            all_items.append(await _row_to_queue_item(session, tt, r))

    if "circuit_projection_cross_validation_result" in types:
        q = select(MirrorCircuitProjectionCrossValidationResult)
        if scope.resource_id:
            q = q.where(MirrorCircuitProjectionCrossValidationResult.resource_id == scope.resource_id)
        if scope.batch_id:
            q = q.where(MirrorCircuitProjectionCrossValidationResult.batch_id == scope.batch_id)
        if scope.source_atlas:
            q = q.where(MirrorCircuitProjectionCrossValidationResult.source_atlas == scope.source_atlas)
        if scope.granularity_level:
            q = q.where(MirrorCircuitProjectionCrossValidationResult.granularity_level == scope.granularity_level)
        rows = list((await session.execute(
            q.order_by(MirrorCircuitProjectionCrossValidationResult.created_at.desc()).limit(fetch_limit)
        )).scalars().all())
        for r in rows:
            all_items.append(await _row_to_queue_item(session, "circuit_projection_cross_validation_result", r))

    if "dual_model_verification_result" in types:
        q = select(MirrorDualModelVerificationResult)
        if scope.resource_id:
            q = q.where(MirrorDualModelVerificationResult.resource_id == scope.resource_id)
        if scope.batch_id:
            q = q.where(MirrorDualModelVerificationResult.batch_id == scope.batch_id)
        if scope.source_atlas:
            q = q.where(MirrorDualModelVerificationResult.source_atlas == scope.source_atlas)
        if scope.consensus_status:
            q = q.where(MirrorDualModelVerificationResult.consensus_status == scope.consensus_status)
        rows = list((await session.execute(
            q.order_by(MirrorDualModelVerificationResult.created_at.desc()).limit(fetch_limit)
        )).scalars().all())
        for r in rows:
            all_items.append(await _row_to_queue_item(session, "dual_model_verification_result", r))

    def _filter_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = items
        if scope.has_blocker is not None:
            out = [i for i in out if bool(
                (i["latest_validation_summary"].get("has_blocker") or i["latest_validation_summary"].get("has_error"))
            ) == scope.has_blocker]
        if scope.has_error is not None:
            out = [i for i in out if i["latest_validation_summary"].get("has_error") == scope.has_error]
        if scope.has_warning is not None:
            out = [i for i in out if i["latest_validation_summary"].get("has_warning") == scope.has_warning]
        if scope.has_model_conflict is not None:
            out = [i for i in out if (i.get("consensus_status") == "model_conflict") == scope.has_model_conflict]
        if scope.has_cross_conflict is not None:
            out = [i for i in out if (i.get("cross_validation_status") == "conflict") == scope.has_cross_conflict]
        if scope.verification_status:
            out = [i for i in out if i.get("verification_status") == scope.verification_status]
        if scope.recommended_review_priority:
            out = [i for i in out if i.get("recommended_review_priority") == scope.recommended_review_priority]
        return out

    all_items = _filter_items(all_items)
    all_items.sort(key=mc_review.queue_sort_key)
    total = len(all_items)
    page = all_items[scope.offset: scope.offset + scope.limit]
    return page, total


async def _load_llm_trace(session: AsyncSession, obj: Any) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    if obj.llm_run_id:
        run = await session.get(LlmExtractionRun, obj.llm_run_id)
        if run:
            trace["run"] = {
                "id": str(run.id),
                "task_type": run.task_type,
                "provider": run.provider,
                "model_name": run.model_name,
                "status": run.status,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
    if obj.llm_item_id:
        item = await session.get(LlmExtractionItem, obj.llm_item_id)
        if item:
            trace["item"] = {
                "id": str(item.id),
                "item_type": item.item_type,
                "status": item.status,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
    return trace


def _allowed_actions(target_type: str, obj: Any, val_summary: dict[str, Any], gating: dict[str, Any]) -> list[str]:
    if mc_review.is_signal_target(target_type):
        actions = [MirrorReviewAction.comment, MirrorReviewAction.flag_for_followup]
        if gating.get("can_accept_signal"):
            actions.insert(0, MirrorReviewAction.accept_signal)
        if gating.get("can_dismiss_signal"):
            actions.insert(1, MirrorReviewAction.dismiss_signal)
        return actions

    if getattr(obj, "promotion_status", None) == MirrorPromotionStatus.promoted:
        return [MirrorReviewAction.comment, MirrorReviewAction.flag_for_followup]

    actions = [MirrorReviewAction.comment, MirrorReviewAction.flag_for_followup]
    if target_type in EDITABLE_FIELDS:
        actions.append(MirrorReviewAction.edit)
    if getattr(obj, "review_status", None) == MirrorReviewStatus.approved and getattr(obj, "mirror_status", None) == MirrorStatus.human_approved:
        actions.extend([MirrorReviewAction.reject, MirrorReviewAction.needs_revision])
    elif getattr(obj, "mirror_status", None) == MirrorStatus.human_rejected:
        actions.append(MirrorReviewAction.needs_revision)
    else:
        if gating.get("can_approve"):
            actions.append(MirrorReviewAction.approve)
        if gating.get("can_reject"):
            actions.extend([MirrorReviewAction.reject, MirrorReviewAction.needs_revision])
    return actions


async def get_mirror_review_detail(
    session: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> dict[str, Any]:
    if target_type not in VALID_TARGET_TYPES:
        raise InvalidTargetTypeError(target_type)
    obj = await get_target(session, target_type, target_id)
    obj_json = object_to_json(obj)
    is_signal = mc_review.is_signal_target(target_type)

    val_type = mc_review.normalize_target_type(target_type)
    if is_signal:
        val_type = target_type
    val_summary = await get_latest_validation_summary(session, val_type, target_id)
    ev_summary = await get_evidence_summary(session, target_type, target_id)

    ctx = await mc_review.build_detail_context(session, target_type, obj)
    if target_type == "circuit" and "circuit_regions" not in obj_json:
        regions = list(
            (await session.execute(
                select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == target_id)
            )).scalars().all()
        )
        obj_json["circuit_regions"] = [object_to_json(r) for r in regions]

    val_rows = list(
        (await session.execute(
            select(MirrorRuleValidationResult)
            .where(
                MirrorRuleValidationResult.target_type == val_type,
                MirrorRuleValidationResult.target_id == target_id,
            )
            .order_by(MirrorRuleValidationResult.created_at.desc())
            .limit(50)
        )).scalars().all()
    )

    review_rows = list(
        (await session.execute(
            select(MirrorHumanReviewRecord)
            .where(
                MirrorHumanReviewRecord.target_type == target_type,
                MirrorHumanReviewRecord.target_id == target_id,
            )
            .order_by(MirrorHumanReviewRecord.created_at.desc())
            .limit(50)
        )).scalars().all()
    )

    cross_status = getattr(obj, "validation_status", None) if target_type == "circuit_projection_cross_validation_result" else None
    consensus_status = getattr(obj, "consensus_status", None) if target_type == "dual_model_verification_result" else None
    verification_status = getattr(obj, "verification_status", None) if target_type == "circuit_projection_membership" else None
    evidence_empty = not (getattr(obj, "evidence_text", None) or "").strip()
    priority = mc_review.compute_review_priority(
        val_summary,
        cross_status=cross_status,
        consensus_status=consensus_status,
        verification_status=verification_status,
        evidence_empty=evidence_empty,
        is_signal=is_signal,
    )
    gating = mc_review.compute_gating(target_type, obj, val_summary, is_signal=is_signal)
    editable = sorted(EDITABLE_FIELDS.get(target_type, frozenset()))

    return {
        "target_type": target_type,
        "target_id": target_id,
        "object_json": obj_json,
        "object_payload": obj_json,
        "evidence_records": ev_summary.get("records", []),
        "validation_results": [object_to_json(r) for r in val_rows],
        "cross_validation_results": ctx.get("cross_validation_results", []),
        "dual_model_results": ctx.get("dual_model_results", []),
        "related_objects": ctx.get("related_objects", {}),
        "review_records": [object_to_json(r) for r in review_rows],
        "llm_trace": await _load_llm_trace(session, obj) if not is_signal else {},
        "editable_fields": editable,
        "allowed_actions": _allowed_actions(target_type, obj, val_summary, gating),
        "latest_validation_summary": val_summary,
        "gating": gating,
        "recommended_review_priority": priority,
        "object_category": "signal_object" if is_signal else "domain_object",
    }


def validate_review_eligibility(
    action: str,
    target_type: str,
    obj: Any,
    val_summary: dict[str, Any],
    *,
    allow_with_warnings: bool = True,
    reviewer_note: str | None = None,
) -> list[str]:
    warnings: list[str] = []
    if mc_review.is_signal_target(target_type):
        if action in (MirrorReviewAction.approve, MirrorReviewAction.reject, MirrorReviewAction.needs_revision, MirrorReviewAction.edit):
            raise DomainActionOnSignalError(f"{action} not allowed on signal object")
        return warnings

    if action in (MirrorReviewAction.accept_signal, MirrorReviewAction.dismiss_signal):
        raise SignalActionOnDomainError(f"{action} only allowed on signal objects")

    if getattr(obj, "promotion_status", None) == MirrorPromotionStatus.promoted:
        raise TargetAlreadyPromotedError()

    if action == MirrorReviewAction.approve:
        if getattr(obj, "mirror_status", None) == MirrorStatus.human_rejected:
            raise TargetNotReviewableError("rejected object cannot be approved without revision")
        if getattr(obj, "review_status", None) == MirrorReviewStatus.approved:
            raise TargetNotReviewableError("already approved")
        if not val_summary.get("validated"):
            raise MirrorObjectNotValidatedError()
        if val_summary.get("has_blocker") or val_summary.get("has_error"):
            raise MirrorObjectHasBlockersError(val_summary)
        if val_summary.get("has_warning") and not allow_with_warnings:
            raise TargetNotReviewableError("warnings present and allow_with_warnings=false")
        if val_summary.get("has_warning"):
            warnings.append("validation warnings present")
        requires_reason = bool(val_summary.get("has_warning"))
        if not (getattr(obj, "evidence_text", None) or "").strip():
            requires_reason = True
            warnings.append("evidence empty")
        if target_type == "circuit_projection_membership" and getattr(obj, "verification_status", "") == "model_conflict":
            requires_reason = True
            warnings.append("membership model_conflict")
        if requires_reason and not (reviewer_note or "").strip():
            raise ReviewerReasonRequiredError()

    return warnings


def apply_safe_edit_patch(
    target_type: str,
    obj: Any,
    patch: dict[str, Any],
) -> dict[str, Any]:
    if not patch:
        raise EditPatchEmptyError()
    tt = mc_review.normalize_target_type(target_type)
    if target_type in EDITABLE_FIELDS:
        tt = target_type
    allowed = EDITABLE_FIELDS.get(tt) or EDITABLE_FIELDS.get(target_type)
    if not allowed:
        raise InvalidReviewActionError(f"edit not supported for {target_type}")
    for key in patch:
        if key in PROVENANCE_FIELDS:
            raise ForbiddenEditFieldError(key)
        if key not in allowed:
            raise ForbiddenEditFieldError(key)
    applied: dict[str, Any] = {}
    for key, value in patch.items():
        setattr(obj, key, value)
        applied[key] = value
    return applied


async def create_review_record(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    obj: Any,
    reviewer: str,
    reviewer_note: str | None,
    before_json: dict[str, Any],
    after_json: dict[str, Any],
    edit_patch_json: dict[str, Any] | None = None,
    from_mirror_status: str | None = None,
    to_mirror_status: str | None = None,
    from_review_status: str | None = None,
    to_review_status: str | None = None,
    from_promotion_status: str | None = None,
    to_promotion_status: str | None = None,
    validation_summary_json: dict[str, Any] | None = None,
    evidence_summary_json: dict[str, Any] | None = None,
) -> MirrorHumanReviewRecord:
    record = MirrorHumanReviewRecord(
        id=uuid.uuid4(),
        target_type=target_type,
        target_id=target_id,
        action=action,
        from_mirror_status=from_mirror_status,
        to_mirror_status=to_mirror_status,
        from_review_status=from_review_status,
        to_review_status=to_review_status,
        from_promotion_status=from_promotion_status,
        to_promotion_status=to_promotion_status,
        reviewer=reviewer,
        reviewer_note=reviewer_note,
        edit_patch_json=edit_patch_json or {},
        before_json=before_json,
        after_json=after_json,
        validation_summary_json=validation_summary_json or {},
        evidence_summary_json=evidence_summary_json or {},
        resource_id=getattr(obj, "resource_id", None),
        batch_id=getattr(obj, "batch_id", None),
        source_atlas=getattr(obj, "source_atlas", None),
        source_version=getattr(obj, "source_version", None),
        granularity_level=getattr(obj, "granularity_level", None),
        granularity_family=getattr(obj, "granularity_family", None),
    )
    session.add(record)
    return record


def update_target_review_status(
    obj: Any,
    *,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
) -> None:
    if mirror_status is not None:
        obj.mirror_status = mirror_status
    if review_status is not None:
        obj.review_status = review_status
    if promotion_status is not None:
        obj.promotion_status = promotion_status


async def perform_mirror_review_action(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    reviewer: str,
    reviewer_note: str | None = None,
    edit_patch_json: dict[str, Any] | None = None,
    allow_with_warnings: bool = True,
) -> tuple[MirrorHumanReviewRecord, dict[str, Any], list[str]]:
    if target_type not in VALID_TARGET_TYPES:
        raise InvalidTargetTypeError(target_type)
    valid_actions = {
        MirrorReviewAction.approve,
        MirrorReviewAction.reject,
        MirrorReviewAction.needs_revision,
        MirrorReviewAction.edit,
        MirrorReviewAction.comment,
        MirrorReviewAction.accept_signal,
        MirrorReviewAction.dismiss_signal,
        MirrorReviewAction.flag_for_followup,
    }
    if action not in valid_actions:
        raise InvalidReviewActionError(f"invalid action: {action}")

    is_signal = mc_review.is_signal_target(target_type)
    if action in (MirrorReviewAction.reject, MirrorReviewAction.needs_revision, MirrorReviewAction.comment):
        if not (reviewer_note or "").strip():
            raise ReviewerNoteRequiredError()

    if action in (MirrorReviewAction.accept_signal, MirrorReviewAction.dismiss_signal) and not is_signal:
        raise SignalActionOnDomainError(f"{action} only allowed on signal objects")

    if action in (MirrorReviewAction.approve, MirrorReviewAction.reject, MirrorReviewAction.needs_revision, MirrorReviewAction.edit) and is_signal:
        raise DomainActionOnSignalError(f"{action} not allowed on signal object")

    obj = await get_target(session, target_type, target_id)
    before = object_to_json(obj)
    val_type = mc_review.normalize_target_type(target_type)
    if is_signal:
        val_type = target_type
    val_summary = await get_latest_validation_summary(session, val_type, target_id)
    ev_summary = await get_evidence_summary(session, target_type, target_id)

    from_ms = getattr(obj, "mirror_status", None)
    from_rs = getattr(obj, "review_status", None)
    from_ps = getattr(obj, "promotion_status", None)
    to_ms: str | None = None
    to_rs: str | None = None
    to_ps: str | None = None
    patch = edit_patch_json or {}
    warnings: list[str] = []

    if action not in (MirrorReviewAction.accept_signal, MirrorReviewAction.dismiss_signal, MirrorReviewAction.flag_for_followup, MirrorReviewAction.comment):
        warnings = validate_review_eligibility(
            action, target_type, obj, val_summary,
            allow_with_warnings=allow_with_warnings,
            reviewer_note=reviewer_note,
        )

    if action == MirrorReviewAction.edit and not patch:
        raise EditPatchEmptyError()

    if action == MirrorReviewAction.approve:
        to_ms = MirrorStatus.human_approved
        to_rs = MirrorReviewStatus.approved
        update_target_review_status(obj, mirror_status=to_ms, review_status=to_rs)

    elif action == MirrorReviewAction.reject:
        to_ms = MirrorStatus.human_rejected
        to_rs = MirrorReviewStatus.rejected
        to_ps = MirrorPromotionStatus.blocked
        update_target_review_status(obj, mirror_status=to_ms, review_status=to_rs, promotion_status=to_ps)

    elif action == MirrorReviewAction.needs_revision:
        to_ms = MirrorStatus.human_review_pending
        to_rs = MirrorReviewStatus.needs_revision
        to_ps = MirrorPromotionStatus.not_promoted
        update_target_review_status(obj, mirror_status=to_ms, review_status=to_rs, promotion_status=to_ps)

    elif action == MirrorReviewAction.edit:
        apply_safe_edit_patch(target_type, obj, patch)
        to_ms = MirrorStatus.human_review_pending
        to_rs = MirrorReviewStatus.needs_revision
        to_ps = MirrorPromotionStatus.not_promoted
        update_target_review_status(obj, mirror_status=to_ms, review_status=to_rs, promotion_status=to_ps)
        warnings.append("edit requires re-validation before approve")

    elif action in (MirrorReviewAction.accept_signal, MirrorReviewAction.dismiss_signal, MirrorReviewAction.flag_for_followup, MirrorReviewAction.comment):
        pass

    after = object_to_json(obj)
    state_changing = action not in (MirrorReviewAction.comment, MirrorReviewAction.flag_for_followup, MirrorReviewAction.accept_signal, MirrorReviewAction.dismiss_signal)
    record = await create_review_record(
        session,
        target_type=target_type,
        target_id=target_id,
        action=action,
        obj=obj,
        reviewer=reviewer,
        reviewer_note=reviewer_note,
        before_json=before,
        after_json=after,
        edit_patch_json=patch if action == MirrorReviewAction.edit else {},
        from_mirror_status=from_ms,
        to_mirror_status=to_ms if state_changing else None,
        from_review_status=from_rs,
        to_review_status=to_rs if state_changing else None,
        from_promotion_status=from_ps,
        to_promotion_status=to_ps if state_changing else None,
        validation_summary_json=val_summary,
        evidence_summary_json=ev_summary,
    )
    await session.commit()
    await session.refresh(record)
    if not is_signal or action in (MirrorReviewAction.edit, MirrorReviewAction.approve, MirrorReviewAction.reject, MirrorReviewAction.needs_revision):
        await session.refresh(obj)
    return record, after, warnings


def list_review_target_types() -> list[dict[str, Any]]:
    return list(mc_review.TARGET_TYPE_META)


async def list_review_records(
    session: AsyncSession,
    *,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    action: str | None = None,
    reviewer: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorHumanReviewRecord], int]:
    q = select(MirrorHumanReviewRecord)
    count_q = select(func.count()).select_from(MirrorHumanReviewRecord)
    if target_type:
        q = q.where(MirrorHumanReviewRecord.target_type == target_type)
        count_q = count_q.where(MirrorHumanReviewRecord.target_type == target_type)
    if target_id:
        q = q.where(MirrorHumanReviewRecord.target_id == target_id)
        count_q = count_q.where(MirrorHumanReviewRecord.target_id == target_id)
    if action:
        q = q.where(MirrorHumanReviewRecord.action == action)
        count_q = count_q.where(MirrorHumanReviewRecord.action == action)
    if reviewer:
        q = q.where(MirrorHumanReviewRecord.reviewer == reviewer)
        count_q = count_q.where(MirrorHumanReviewRecord.reviewer == reviewer)
    if resource_id:
        q = q.where(MirrorHumanReviewRecord.resource_id == resource_id)
        count_q = count_q.where(MirrorHumanReviewRecord.resource_id == resource_id)
    if batch_id:
        q = q.where(MirrorHumanReviewRecord.batch_id == batch_id)
        count_q = count_q.where(MirrorHumanReviewRecord.batch_id == batch_id)
    total = int((await session.execute(count_q)).scalar_one())
    rows = list(
        (await session.execute(
            q.order_by(MirrorHumanReviewRecord.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return rows, total
