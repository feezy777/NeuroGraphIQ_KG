"""Shared helpers for Mirror KG rule validation (Step 7 / 8.13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.mirror_kg import (
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.schemas.mirror_kg import (
    ConnectionType,
    Directionality,
    FunctionCategory,
    FunctionRelationType,
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
)
from app.schemas.mirror_validation import MirrorValidationResultStatus, MirrorValidationSeverity

VALID_MIRROR_STATUSES = frozenset({
    MirrorStatus.llm_suggested,
    MirrorStatus.rule_checked,
    MirrorStatus.human_review_pending,
    MirrorStatus.human_approved,
    MirrorStatus.human_rejected,
    MirrorStatus.promoted_to_final,
    MirrorStatus.superseded,
})

VALID_REVIEW_STATUSES = frozenset({
    MirrorReviewStatus.pending,
    MirrorReviewStatus.approved,
    MirrorReviewStatus.rejected,
    MirrorReviewStatus.needs_revision,
    MirrorReviewStatus.not_required,
})

VALID_PROMOTION_STATUSES = frozenset({
    MirrorPromotionStatus.not_promoted,
    MirrorPromotionStatus.promoted,
    MirrorPromotionStatus.failed,
    MirrorPromotionStatus.blocked,
})

VALID_CONNECTION_TYPES = frozenset({
    ConnectionType.structural_connection,
    ConnectionType.functional_connectivity,
    ConnectionType.effective_connectivity,
    ConnectionType.projection,
    ConnectionType.association,
    ConnectionType.coactivation,
    ConnectionType.uncertain_connection,
    ConnectionType.unknown,
})

VALID_DIRECTIONALITIES = frozenset({
    Directionality.directed,
    Directionality.undirected,
    Directionality.bidirectional,
    Directionality.unknown,
})

VALID_FUNCTION_CATEGORIES = frozenset({
    FunctionCategory.motor,
    FunctionCategory.sensory,
    FunctionCategory.visual,
    FunctionCategory.auditory,
    FunctionCategory.language,
    FunctionCategory.memory,
    FunctionCategory.emotion,
    FunctionCategory.executive_control,
    FunctionCategory.attention,
    FunctionCategory.autonomic,
    FunctionCategory.default_mode,
    FunctionCategory.salience,
    FunctionCategory.reward,
    FunctionCategory.cognitive,
    FunctionCategory.unknown,
})

VALID_RELATION_TYPES = frozenset({
    FunctionRelationType.involved_in,
    FunctionRelationType.associated_with,
    FunctionRelationType.necessary_for,
    FunctionRelationType.modulates,
    FunctionRelationType.participates_in,
    FunctionRelationType.uncertain_association,
    FunctionRelationType.unknown,
})


@dataclass
class ValidationCheck:
    rule_code: str
    severity: str
    status: str
    message: str
    details_json: dict[str, Any] = field(default_factory=dict)


def build_validation_result(
    rule_code: str,
    *,
    severity: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> ValidationCheck:
    return ValidationCheck(
        rule_code=rule_code,
        severity=severity,
        status=status,
        message=message,
        details_json=details or {},
    )


def norm_label(label: str | None) -> str:
    return (label or "").strip().lower()


def float_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_common_fields(
    obj: MirrorRegionConnection | MirrorRegionFunction | MirrorRegionCircuit | MirrorKgTriple,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []

    atlas = (getattr(obj, "source_atlas", None) or "").strip()
    if not atlas:
        checks.append(build_validation_result(
            "RULE_COMMON_SOURCE_ATLAS_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="source_atlas is required",
        ))

    gran = (getattr(obj, "granularity_level", None) or "").strip()
    if not gran:
        checks.append(build_validation_result(
            "RULE_COMMON_GRANULARITY_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="granularity_level is required",
        ))

    if not obj.resource_id and not obj.batch_id:
        checks.append(build_validation_result(
            "RULE_COMMON_RESOURCE_OR_BATCH_TRACE",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="both resource_id and batch_id are missing",
        ))

    conf = float_confidence(getattr(obj, "confidence", None))
    if conf is not None and (conf < 0 or conf > 1):
        checks.append(build_validation_result(
            "RULE_COMMON_CONFIDENCE_RANGE",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"confidence {conf} is outside 0–1",
            details={"confidence": conf},
        ))
    elif conf is not None and conf < 0.5:
        checks.append(build_validation_result(
            "RULE_COMMON_LOW_CONFIDENCE",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message=f"confidence {conf} is below 0.5",
            details={"confidence": conf},
        ))

    evidence = (getattr(obj, "evidence_text", None) or "").strip()
    if not evidence:
        checks.append(build_validation_result(
            "RULE_COMMON_EVIDENCE_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="evidence_text is missing",
        ))

    uncertainty = (getattr(obj, "uncertainty_reason", None) or "").strip()
    if not uncertainty:
        checks.append(build_validation_result(
            "RULE_COMMON_UNCERTAINTY_RECOMMENDED",
            severity=MirrorValidationSeverity.info,
            status=MirrorValidationResultStatus.passed,
            message="uncertainty_reason not provided (informational)",
        ))

    ms = getattr(obj, "mirror_status", None)
    rs = getattr(obj, "review_status", None)
    ps = getattr(obj, "promotion_status", None)
    if ms not in VALID_MIRROR_STATUSES:
        checks.append(build_validation_result(
            "RULE_COMMON_STATUS_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"mirror_status '{ms}' is invalid",
        ))
    if rs not in VALID_REVIEW_STATUSES:
        checks.append(build_validation_result(
            "RULE_COMMON_STATUS_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"review_status '{rs}' is invalid",
        ))
    if ps not in VALID_PROMOTION_STATUSES:
        checks.append(build_validation_result(
            "RULE_COMMON_STATUS_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"promotion_status '{ps}' is invalid",
        ))

    if rs == MirrorReviewStatus.rejected or ms == MirrorStatus.human_rejected:
        checks.append(build_validation_result(
            "RULE_COMMON_ALREADY_REJECTED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="object was rejected; not recommended for review queue",
        ))

    return checks
