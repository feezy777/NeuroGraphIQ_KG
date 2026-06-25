"""Macro clinical Mirror KG rule validation (Step 8.13).

Deterministic checks for circuit_step, projection_function, membership,
cross_validation_result, dual_model_verification_result, projection alias, and
macro_clinical circuit/triple supplements. No LLM; no final_*/kg_*.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_kg import MirrorKgTriple, MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.schemas.mirror_cross_validation import CircuitProjectionCrossValidationStatus
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitStepRole,
    MirrorCircuitStepType,
    MirrorDualModelConsensusStatus,
    MirrorDualModelDecision,
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
    MirrorReviewPriority,
)
from app.schemas.mirror_kg import ConnectionType
from app.schemas.mirror_validation import MirrorValidationResultStatus, MirrorValidationSeverity
from app.services.mirror_rule_validation_helpers import (
    ValidationCheck,
    build_validation_result,
    float_confidence as _float_confidence,
    norm_label as _norm_label,
    validate_common_fields,
    VALID_CONNECTION_TYPES,
    VALID_DIRECTIONALITIES,
    VALID_FUNCTION_CATEGORIES,
    VALID_MIRROR_STATUSES,
    VALID_PROMOTION_STATUSES,
    VALID_RELATION_TYPES,
    VALID_REVIEW_STATUSES,
)

VALID_STEP_TYPES = frozenset({
    MirrorCircuitStepType.region,
    MirrorCircuitStepType.region_group,
    MirrorCircuitStepType.relay,
    MirrorCircuitStepType.hub,
    MirrorCircuitStepType.modulator,
    MirrorCircuitStepType.functional_stage,
    MirrorCircuitStepType.unknown,
})

VALID_STEP_ROLES = frozenset({
    MirrorCircuitStepRole.source,
    MirrorCircuitStepRole.target,
    MirrorCircuitStepRole.relay,
    MirrorCircuitStepRole.hub,
    MirrorCircuitStepRole.modulator,
    MirrorCircuitStepRole.participant,
    MirrorCircuitStepRole.unknown,
})

VALID_SOURCE_METHODS = frozenset({
    MirrorMembershipSourceMethod.circuit_to_projection,
    MirrorMembershipSourceMethod.projection_to_circuit,
    MirrorMembershipSourceMethod.dual_model_consensus,
    MirrorMembershipSourceMethod.human_curated,
    MirrorMembershipSourceMethod.deterministic,
    MirrorMembershipSourceMethod.unknown,
})

VALID_VERIFICATION_STATUSES = frozenset({
    MirrorMembershipVerificationStatus.unverified,
    MirrorMembershipVerificationStatus.circuit_supported,
    MirrorMembershipVerificationStatus.projection_supported,
    MirrorMembershipVerificationStatus.bidirectionally_supported,
    MirrorMembershipVerificationStatus.model_conflict,
    MirrorMembershipVerificationStatus.human_approved,
    MirrorMembershipVerificationStatus.human_rejected,
    MirrorMembershipVerificationStatus.unknown,
})

VALID_CROSS_VALIDATION_STATUSES = frozenset({
    CircuitProjectionCrossValidationStatus.bidirectionally_supported,
    CircuitProjectionCrossValidationStatus.circuit_supported_only,
    CircuitProjectionCrossValidationStatus.projection_supported_only,
    CircuitProjectionCrossValidationStatus.conflict,
    CircuitProjectionCrossValidationStatus.insufficient_evidence,
    CircuitProjectionCrossValidationStatus.unknown,
})

VALID_CROSS_SUPPORT_LEVELS = frozenset({"strong", "moderate", "weak", "conflicting", "unknown"})

VALID_DUAL_OBJECT_TYPES = frozenset({
    "circuit", "projection", "circuit_projection_membership",
    "projection_function", "circuit_step", "triple",
})

VALID_DUAL_CONSENSUS = frozenset({
    MirrorDualModelConsensusStatus.consensus_supported,
    MirrorDualModelConsensusStatus.consensus_rejected,
    MirrorDualModelConsensusStatus.model_conflict,
    MirrorDualModelConsensusStatus.insufficient_information,
    MirrorDualModelConsensusStatus.needs_human_review,
    MirrorDualModelConsensusStatus.unknown,
})

VALID_DUAL_DECISIONS = frozenset({
    MirrorDualModelDecision.support,
    MirrorDualModelDecision.reject,
    MirrorDualModelDecision.uncertain,
    MirrorDualModelDecision.insufficient_information,
    MirrorDualModelDecision.unknown,
})

VALID_REVIEW_PRIORITIES = frozenset({
    MirrorReviewPriority.low,
    MirrorReviewPriority.normal,
    MirrorReviewPriority.high,
    MirrorReviewPriority.urgent,
})

MACRO_CLINICAL_PREDICATES = frozenset({
    "region_has_function",
    "circuit_has_step",
    "circuit_contains_projection",
    "projection_belongs_to_circuit",
    "projection_has_source_region",
    "projection_has_target_region",
    "projection_has_function",
    "circuit_has_function",
    "has_participant_region",
    "associated_with_function",
    "involved_in_function",
    "participates_in_function",
    "possibly_associated_with_function",
})

HIGH_REVIEW_RULE_SUFFIXES = (
    "_REVIEW_REQUIRED",
    "MODEL_CONFLICT",
    "CONSENSUS_REJECTED",
)


def is_high_review_check(check: ValidationCheck) -> bool:
    if check.severity != MirrorValidationSeverity.warning:
        return False
    return any(s in check.rule_code for s in HIGH_REVIEW_RULE_SUFFIXES)


def validate_macro_object_status_fields(obj: Any) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    ms = getattr(obj, "mirror_status", None)
    rs = getattr(obj, "review_status", None)
    ps = getattr(obj, "promotion_status", None)
    if ms is not None and ms not in VALID_MIRROR_STATUSES:
        checks.append(build_validation_result(
            "RULE_COMMON_STATUS_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"mirror_status '{ms}' is invalid",
        ))
    if rs is not None and rs not in VALID_REVIEW_STATUSES:
        checks.append(build_validation_result(
            "RULE_COMMON_STATUS_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"review_status '{rs}' is invalid",
        ))
    if ps is not None and ps not in VALID_PROMOTION_STATUSES:
        checks.append(build_validation_result(
            "RULE_COMMON_STATUS_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"promotion_status '{ps}' is invalid",
        ))
    if ps == "promoted" and rs != "approved":
        checks.append(build_validation_result(
            "RULE_COMMON_PROMOTED_WITHOUT_APPROVAL",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="promoted object without human approval in Mirror stage",
        ))
    return checks


def validate_circuit_step(
    step: MirrorCircuitStep,
    *,
    circuit: MirrorRegionCircuit | None,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    order_dup: dict[tuple[uuid.UUID, int], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_macro_object_status_fields(step)

    if circuit is None:
        checks.append(build_validation_result(
            "CIRCUIT_STEP_CIRCUIT_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"circuit {step.circuit_id} not found",
        ))
    else:
        if step.source_atlas != circuit.source_atlas or step.granularity_level != circuit.granularity_level:
            checks.append(build_validation_result(
                "CIRCUIT_STEP_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="step scope does not match circuit",
            ))

    if step.step_order < 1:
        checks.append(build_validation_result(
            "CIRCUIT_STEP_ORDER_INVALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"step_order {step.step_order} must be >= 1",
        ))
    else:
        key = (step.circuit_id, step.step_order)
        other = order_dup.get(key)
        if other and other != step.id:
            checks.append(build_validation_result(
                "CIRCUIT_STEP_ORDER_DUPLICATE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="duplicate step_order within circuit",
                details={"duplicate_of": str(other)},
            ))
        else:
            order_dup.setdefault(key, step.id)

    if not (step.step_name or "").strip():
        checks.append(build_validation_result(
            "CIRCUIT_STEP_NAME_EMPTY",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="step_name is required",
        ))

    if step.step_type not in VALID_STEP_TYPES:
        checks.append(build_validation_result(
            "CIRCUIT_STEP_TYPE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid step_type: {step.step_type}",
        ))

    if step.role not in VALID_STEP_ROLES:
        checks.append(build_validation_result(
            "CIRCUIT_STEP_ROLE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid role: {step.role}",
        ))

    if step.step_type == MirrorCircuitStepType.region and not step.region_candidate_id:
        checks.append(build_validation_result(
            "CIRCUIT_STEP_REGION_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="region_candidate_id required for step_type=region",
        ))

    if step.region_candidate_id:
        cand = candidate_map.get(step.region_candidate_id)
        if cand is None:
            checks.append(build_validation_result(
                "CIRCUIT_STEP_REGION_MISSING",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"region candidate {step.region_candidate_id} not found",
            ))
        elif cand.source_atlas != step.source_atlas or cand.granularity_level != step.granularity_level:
            checks.append(build_validation_result(
                "CIRCUIT_STEP_REGION_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="region candidate scope mismatch with step",
            ))

    conf = _float_confidence(step.confidence)
    if conf is not None and (conf < 0 or conf > 1):
        checks.append(build_validation_result(
            "CIRCUIT_STEP_CONFIDENCE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"confidence {conf} outside 0–1",
        ))

    if not (step.evidence_text or "").strip():
        checks.append(build_validation_result(
            "CIRCUIT_STEP_EVIDENCE_EMPTY",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="evidence_text is empty",
        ))

    if not (step.uncertainty_reason or "").strip():
        checks.append(build_validation_result(
            "CIRCUIT_STEP_UNCERTAINTY_EMPTY",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="uncertainty_reason is empty",
        ))

    return checks


def validate_projection_function(
    pf: MirrorProjectionFunction,
    *,
    projection: MirrorRegionConnection | None,
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_macro_object_status_fields(pf)

    if projection is None:
        checks.append(build_validation_result(
            "PROJECTION_FUNCTION_PROJECTION_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"projection {pf.projection_id} not found",
        ))
    else:
        if pf.source_atlas != projection.source_atlas or pf.granularity_level != projection.granularity_level:
            checks.append(build_validation_result(
                "PROJECTION_FUNCTION_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="projection_function scope mismatch with projection",
            ))
        if not projection.source_region_candidate_id or not projection.target_region_candidate_id:
            checks.append(build_validation_result(
                "PROJECTION_FUNCTION_PROJECTION_ENDPOINTS",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="projection missing source or target region",
            ))

    term = (pf.function_term or "").strip()
    if not term:
        checks.append(build_validation_result(
            "PROJECTION_FUNCTION_TERM_EMPTY",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="function_term is required",
        ))

    if pf.function_category not in VALID_FUNCTION_CATEGORIES:
        checks.append(build_validation_result(
            "PROJECTION_FUNCTION_CATEGORY_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid function_category: {pf.function_category}",
        ))

    if pf.relation_type not in VALID_RELATION_TYPES:
        checks.append(build_validation_result(
            "PROJECTION_FUNCTION_RELATION_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid relation_type: {pf.relation_type}",
        ))

    if projection and term:
        key = (
            str(pf.projection_id),
            _norm_label(term),
            pf.function_category,
            pf.relation_type,
        )
        other = duplicate_keys.get(key)
        if other and other != pf.id:
            checks.append(build_validation_result(
                "PROJECTION_FUNCTION_DUPLICATE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="duplicate projection_function",
                details={"duplicate_of": str(other)},
            ))
        else:
            duplicate_keys.setdefault(key, pf.id)

    conf = _float_confidence(pf.confidence)
    if conf is not None and (conf < 0 or conf > 1):
        checks.append(build_validation_result(
            "PROJECTION_FUNCTION_CONFIDENCE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"confidence {conf} outside 0–1",
        ))

    if not (pf.evidence_text or "").strip():
        checks.append(build_validation_result(
            "PROJECTION_FUNCTION_EVIDENCE_EMPTY",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="evidence_text is empty",
        ))

    return checks


def validate_circuit_projection_membership(
    m: MirrorCircuitProjectionMembership,
    *,
    circuit: MirrorRegionCircuit | None,
    projection: MirrorRegionConnection | None,
    step_map: dict[uuid.UUID, MirrorCircuitStep],
    cross_results: list[MirrorCircuitProjectionCrossValidationResult],
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_macro_object_status_fields(m)

    if circuit is None:
        checks.append(build_validation_result(
            "MEMBERSHIP_CIRCUIT_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"circuit {m.circuit_id} not found",
        ))
    if projection is None:
        checks.append(build_validation_result(
            "MEMBERSHIP_PROJECTION_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"projection {m.projection_id} not found",
        ))

    if circuit and projection:
        if circuit.source_atlas != projection.source_atlas or circuit.granularity_level != projection.granularity_level:
            checks.append(build_validation_result(
                "MEMBERSHIP_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="circuit and projection scope mismatch",
            ))
        if m.source_atlas != circuit.source_atlas or m.granularity_level != circuit.granularity_level:
            checks.append(build_validation_result(
                "MEMBERSHIP_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="membership scope mismatch with circuit/projection",
            ))

    if m.source_step_id:
        src_step = step_map.get(m.source_step_id)
        if src_step is None:
            checks.append(build_validation_result(
                "MEMBERSHIP_SOURCE_STEP_NOT_IN_CIRCUIT",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="source_step not found",
            ))
        elif src_step.circuit_id != m.circuit_id:
            checks.append(build_validation_result(
                "MEMBERSHIP_SOURCE_STEP_NOT_IN_CIRCUIT",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="source_step does not belong to circuit",
            ))
        elif projection and projection.directionality != "undirected":
            if (
                src_step.region_candidate_id
                and projection.source_region_candidate_id
                and src_step.region_candidate_id != projection.source_region_candidate_id
            ):
                checks.append(build_validation_result(
                    "MEMBERSHIP_SOURCE_STEP_PROJECTION_MISMATCH",
                    severity=MirrorValidationSeverity.warning,
                    status=MirrorValidationResultStatus.warning,
                    message="source_step region does not match projection source region",
                ))

    if m.target_step_id:
        tgt_step = step_map.get(m.target_step_id)
        if tgt_step is None:
            checks.append(build_validation_result(
                "MEMBERSHIP_TARGET_STEP_NOT_IN_CIRCUIT",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="target_step not found",
            ))
        elif tgt_step.circuit_id != m.circuit_id:
            checks.append(build_validation_result(
                "MEMBERSHIP_TARGET_STEP_NOT_IN_CIRCUIT",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="target_step does not belong to circuit",
            ))
        elif projection and projection.directionality != "undirected":
            if (
                tgt_step.region_candidate_id
                and projection.target_region_candidate_id
                and tgt_step.region_candidate_id != projection.target_region_candidate_id
            ):
                checks.append(build_validation_result(
                    "MEMBERSHIP_TARGET_STEP_PROJECTION_MISMATCH",
                    severity=MirrorValidationSeverity.warning,
                    status=MirrorValidationResultStatus.warning,
                    message="target_step region does not match projection target region",
                ))

    if m.source_step_id and m.target_step_id and m.source_step_id == m.target_step_id:
        checks.append(build_validation_result(
            "MEMBERSHIP_SAME_SOURCE_TARGET_STEP",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="source_step_id equals target_step_id",
        ))

    if m.source_method not in VALID_SOURCE_METHODS:
        checks.append(build_validation_result(
            "MEMBERSHIP_SOURCE_METHOD_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid source_method: {m.source_method}",
        ))

    if m.verification_status not in VALID_VERIFICATION_STATUSES:
        checks.append(build_validation_result(
            "MEMBERSHIP_VERIFICATION_STATUS_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid verification_status: {m.verification_status}",
        ))

    if m.source_method == MirrorMembershipSourceMethod.circuit_to_projection:
        if m.verification_status == MirrorMembershipVerificationStatus.projection_supported:
            checks.append(build_validation_result(
                "MEMBERSHIP_SOURCE_METHOD_STATUS_INCONSISTENT",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="circuit_to_projection membership should not be projection_supported alone",
            ))
    if m.source_method == MirrorMembershipSourceMethod.projection_to_circuit:
        if m.verification_status == MirrorMembershipVerificationStatus.circuit_supported:
            checks.append(build_validation_result(
                "MEMBERSHIP_SOURCE_METHOD_STATUS_INCONSISTENT",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="projection_to_circuit membership should not be circuit_supported alone",
            ))

    key = (
        str(m.circuit_id),
        str(m.projection_id),
        str(m.source_step_id or ""),
        str(m.target_step_id or ""),
    )
    other = duplicate_keys.get(key)
    if other and other != m.id:
        checks.append(build_validation_result(
            "MEMBERSHIP_DUPLICATE",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="duplicate membership",
            details={"duplicate_of": str(other)},
        ))
    else:
        duplicate_keys.setdefault(key, m.id)

    conf = _float_confidence(m.confidence)
    if conf is not None and (conf < 0 or conf > 1):
        checks.append(build_validation_result(
            "MEMBERSHIP_CONFIDENCE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"confidence {conf} outside 0–1",
        ))

    if not (m.evidence_text or "").strip():
        checks.append(build_validation_result(
            "MEMBERSHIP_EVIDENCE_EMPTY",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="evidence_text is empty",
        ))

    if m.verification_status == MirrorMembershipVerificationStatus.bidirectionally_supported and not cross_results:
        checks.append(build_validation_result(
            "MEMBERSHIP_BIDIRECTIONAL_WITHOUT_CROSS_RESULT",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="bidirectionally_supported without cross validation result",
        ))

    if m.verification_status == MirrorMembershipVerificationStatus.model_conflict:
        checks.append(build_validation_result(
            "MEMBERSHIP_MODEL_CONFLICT_REVIEW_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="membership model_conflict requires human review",
        ))

    return checks


def validate_cross_validation_result(
    result: MirrorCircuitProjectionCrossValidationResult,
    *,
    circuit: MirrorRegionCircuit | None,
    projection: MirrorRegionConnection | None,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []

    if not result.run_id:
        checks.append(build_validation_result(
            "CROSS_RESULT_RUN_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="run_id is missing",
        ))

    if circuit is None:
        checks.append(build_validation_result(
            "CROSS_RESULT_CIRCUIT_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"circuit {result.circuit_id} not found",
        ))
    if projection is None:
        checks.append(build_validation_result(
            "CROSS_RESULT_PROJECTION_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"projection {result.projection_id} not found",
        ))

    if circuit and projection:
        if result.source_atlas and result.source_atlas != circuit.source_atlas:
            checks.append(build_validation_result(
                "CROSS_RESULT_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="result source_atlas mismatch",
            ))
        if result.granularity_level and result.granularity_level != circuit.granularity_level:
            checks.append(build_validation_result(
                "CROSS_RESULT_SCOPE_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="result granularity mismatch",
            ))

    if result.validation_status not in VALID_CROSS_VALIDATION_STATUSES:
        checks.append(build_validation_result(
            "CROSS_RESULT_STATUS_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid validation_status: {result.validation_status}",
        ))

    if result.support_level not in VALID_CROSS_SUPPORT_LEVELS:
        checks.append(build_validation_result(
            "CROSS_RESULT_SUPPORT_LEVEL_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid support_level: {result.support_level}",
        ))

    score = _float_confidence(result.agreement_score)
    if score is not None and (score < 0 or score > 1):
        checks.append(build_validation_result(
            "CROSS_RESULT_SCORE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"agreement_score {score} outside 0–1",
        ))

    if result.validation_status == CircuitProjectionCrossValidationStatus.bidirectionally_supported:
        if not result.circuit_to_projection_membership_id or not result.projection_to_circuit_membership_id:
            checks.append(build_validation_result(
                "CROSS_RESULT_BIDIRECTIONAL_WITHOUT_BOTH_DIRECTIONS",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="bidirectionally_supported missing forward or reverse membership",
            ))
        else:
            checks.append(build_validation_result(
                "CROSS_RESULT_BIDIRECTIONALLY_SUPPORTED",
                severity=MirrorValidationSeverity.info,
                status=MirrorValidationResultStatus.passed,
                message="bidirectionally_supported cross validation (not human approval)",
            ))

    if result.validation_status == CircuitProjectionCrossValidationStatus.conflict:
        if not (result.conflict_reason or "").strip():
            checks.append(build_validation_result(
                "CROSS_RESULT_CONFLICT_REASON_EMPTY",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="conflict without conflict_reason",
            ))
        checks.append(build_validation_result(
            "CROSS_RESULT_CONFLICT_REVIEW_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="cross validation conflict requires human review (not auto-reject)",
        ))

    if result.validation_status == CircuitProjectionCrossValidationStatus.insufficient_evidence:
        details = result.details_json or {}
        if not details:
            checks.append(build_validation_result(
                "CROSS_RESULT_INSUFFICIENT_EVIDENCE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="insufficient_evidence without details_json explanation",
            ))
        else:
            checks.append(build_validation_result(
                "CROSS_RESULT_INSUFFICIENT_EVIDENCE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="insufficient_evidence cross validation signal",
            ))

    return checks


def validate_dual_model_verification_result(
    result: MirrorDualModelVerificationResult,
    *,
    object_exists: bool,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []

    if not result.run_id:
        checks.append(build_validation_result(
            "DUAL_RESULT_RUN_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="run_id is missing",
        ))

    if result.object_type not in VALID_DUAL_OBJECT_TYPES:
        checks.append(build_validation_result(
            "DUAL_RESULT_OBJECT_TYPE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid object_type: {result.object_type}",
        ))

    if not object_exists:
        checks.append(build_validation_result(
            "DUAL_RESULT_OBJECT_MISSING",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"object {result.object_id} not found for type {result.object_type}",
        ))

    if not (result.model_a_provider or "").strip() or not (result.model_b_provider or "").strip():
        checks.append(build_validation_result(
            "DUAL_RESULT_PROVIDER_MISSING",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message="model provider missing",
        ))

    if (
        result.model_a_provider
        and result.model_b_provider
        and result.model_a_provider.lower() == result.model_b_provider.lower()
    ):
        checks.append(build_validation_result(
            "DUAL_RESULT_SAME_PROVIDER",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message="model_a_provider equals model_b_provider",
        ))

    if result.model_a_decision not in VALID_DUAL_DECISIONS:
        checks.append(build_validation_result(
            "DUAL_RESULT_DECISION_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid model_a_decision: {result.model_a_decision}",
        ))
    if result.model_b_decision not in VALID_DUAL_DECISIONS:
        checks.append(build_validation_result(
            "DUAL_RESULT_DECISION_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid model_b_decision: {result.model_b_decision}",
        ))

    for label, conf in (("model_a", result.model_a_confidence), ("model_b", result.model_b_confidence)):
        c = _float_confidence(conf)
        if c is not None and (c < 0 or c > 1):
            checks.append(build_validation_result(
                "DUAL_RESULT_CONFIDENCE_INVALID",
                severity=MirrorValidationSeverity.error,
                status=MirrorValidationResultStatus.failed,
                message=f"{label} confidence outside 0–1",
            ))

    if result.consensus_status not in VALID_DUAL_CONSENSUS:
        checks.append(build_validation_result(
            "DUAL_RESULT_CONSENSUS_STATUS_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid consensus_status: {result.consensus_status}",
        ))

    score = _float_confidence(result.consensus_score)
    if score is not None and (score < 0 or score > 1):
        checks.append(build_validation_result(
            "DUAL_RESULT_SCORE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"consensus_score {score} outside 0–1",
        ))

    if result.consensus_status == MirrorDualModelConsensusStatus.model_conflict:
        if not (result.conflict_summary or "").strip():
            checks.append(build_validation_result(
                "DUAL_RESULT_CONFLICT_SUMMARY_EMPTY",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="model_conflict without conflict_summary",
            ))
        checks.append(build_validation_result(
            "DUAL_RESULT_MODEL_CONFLICT_REVIEW_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="dual model conflict requires human review (not auto-reject)",
        ))

    if result.consensus_status == MirrorDualModelConsensusStatus.consensus_supported:
        checks.append(build_validation_result(
            "DUAL_RESULT_CONSENSUS_SUPPORTED",
            severity=MirrorValidationSeverity.info,
            status=MirrorValidationResultStatus.passed,
            message="consensus_supported (not human approval)",
        ))

    if result.consensus_status == MirrorDualModelConsensusStatus.consensus_rejected:
        checks.append(build_validation_result(
            "DUAL_RESULT_CONSENSUS_REJECTED_REVIEW_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="consensus_rejected requires human review (not auto-reject)",
        ))

    if result.consensus_status in {
        MirrorDualModelConsensusStatus.insufficient_information,
        MirrorDualModelConsensusStatus.needs_human_review,
    }:
        checks.append(build_validation_result(
            "DUAL_RESULT_INSUFFICIENT_INFORMATION",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="insufficient information or needs human review",
        ))

    if result.recommended_review_priority not in VALID_REVIEW_PRIORITIES:
        checks.append(build_validation_result(
            "DUAL_RESULT_PRIORITY_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid recommended_review_priority: {result.recommended_review_priority}",
        ))

    return checks


def validate_projection_macro(
    conn: MirrorRegionConnection,
    *,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    membership_count: int,
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_common_fields(conn)

    if not conn.source_region_candidate_id:
        checks.append(build_validation_result(
            "PROJECTION_SOURCE_REGION_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="source_region_candidate_id is required for projection",
        ))
    if not conn.target_region_candidate_id:
        checks.append(build_validation_result(
            "PROJECTION_TARGET_REGION_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="target_region_candidate_id is required for projection",
        ))

    for label, cid in (("source", conn.source_region_candidate_id), ("target", conn.target_region_candidate_id)):
        if cid is None:
            continue
        cand = candidate_map.get(cid)
        if cand is None:
            checks.append(build_validation_result(
                "PROJECTION_REGION_MISSING",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"{label} region candidate not found",
            ))
        else:
            if cand.source_atlas != conn.source_atlas or cand.granularity_level != conn.granularity_level:
                checks.append(build_validation_result(
                    "PROJECTION_REGION_SCOPE_MISMATCH",
                    severity=MirrorValidationSeverity.blocker,
                    status=MirrorValidationResultStatus.blocked,
                    message=f"{label} region scope mismatch",
                ))

    if (
        conn.source_region_candidate_id
        and conn.target_region_candidate_id
        and conn.source_region_candidate_id == conn.target_region_candidate_id
        and conn.connection_type not in (ConnectionType.association, ConnectionType.uncertain_connection)
    ):
        checks.append(build_validation_result(
            "PROJECTION_SELF_LOOP",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="self-loop projection",
        ))

    if conn.connection_type not in VALID_CONNECTION_TYPES:
        checks.append(build_validation_result(
            "PROJECTION_TYPE_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid connection_type: {conn.connection_type}",
        ))
    if conn.directionality not in VALID_DIRECTIONALITIES:
        checks.append(build_validation_result(
            "PROJECTION_DIRECTIONALITY_INVALID",
            severity=MirrorValidationSeverity.error,
            status=MirrorValidationResultStatus.failed,
            message=f"invalid directionality: {conn.directionality}",
        ))

    norm = conn.normalized_payload_json or {}
    if norm.get("macro_clinical_semantic_type") == "projection":
        checks.append(build_validation_result(
            "PROJECTION_MACRO_CLINICAL_SEMANTIC",
            severity=MirrorValidationSeverity.info,
            status=MirrorValidationResultStatus.passed,
            message="macro_clinical projection semantic type confirmed",
        ))

    if membership_count == 0:
        checks.append(build_validation_result(
            "PROJECTION_WITHOUT_MEMBERSHIP",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="projection has no circuit_projection_membership",
        ))

    if conn.source_region_candidate_id and conn.target_region_candidate_id:
        pair = tuple(sorted([str(conn.source_region_candidate_id), str(conn.target_region_candidate_id)]))
        key = (conn.source_atlas, conn.granularity_level, pair, conn.connection_type)
        other = duplicate_keys.get(key)
        if other and other != conn.id:
            checks.append(build_validation_result(
                "PROJECTION_DUPLICATE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="duplicate canonical projection",
                details={"duplicate_of": str(other)},
            ))
        else:
            duplicate_keys.setdefault(key, conn.id)

    return checks


def supplement_circuit_macro_clinical(
    circuit: MirrorRegionCircuit,
    *,
    step_count: int,
    membership_count: int,
    cross_conflicts: int,
    dual_conflicts: int,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []

    region_count = step_count  # steps as participant proxy when steps exist
    if step_count >= 2:
        checks.append(build_validation_result(
            "CIRCUIT_MACRO_STEPS_PRESENT",
            severity=MirrorValidationSeverity.info,
            status=MirrorValidationResultStatus.passed,
            message=f"circuit has {step_count} steps",
        ))
    elif membership_count == 0 and not (circuit.function_association or "").strip():
        checks.append(build_validation_result(
            "CIRCUIT_MACRO_SPARSE",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="circuit lacks steps, memberships, and function_association",
        ))

    norm = circuit.normalized_payload_json or {}
    if norm.get("source_method") == "projection_to_circuit":
        supporting = norm.get("supporting_projection_ids") or []
        if not supporting:
            checks.append(build_validation_result(
                "CIRCUIT_MACRO_PROJECTION_SOURCE_EMPTY",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="projection_to_circuit circuit missing supporting_projection_ids",
            ))

    if cross_conflicts > 0:
        checks.append(build_validation_result(
            "CIRCUIT_MACRO_CROSS_CONFLICT_REVIEW_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message=f"circuit has {cross_conflicts} cross validation conflict(s)",
        ))

    if dual_conflicts > 0:
        checks.append(build_validation_result(
            "CIRCUIT_MACRO_DUAL_CONFLICT_REVIEW_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message=f"circuit has {dual_conflicts} dual model conflict(s)",
        ))

    return checks


def supplement_triple_macro_clinical(triple: MirrorKgTriple) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    pred = (triple.predicate or "").strip()
    if pred not in MACRO_CLINICAL_PREDICATES:
        return checks

    st, ot = triple.subject_type, triple.object_type

    predicate_rules: dict[str, tuple[frozenset[str], frozenset[str]]] = {
        "circuit_contains_projection": (frozenset({"circuit"}), frozenset({"connection", "unknown"})),
        "projection_belongs_to_circuit": (frozenset({"connection", "unknown"}), frozenset({"circuit"})),
        "projection_has_source_region": (frozenset({"connection", "unknown"}), frozenset({"region_candidate", "unknown"})),
        "projection_has_target_region": (frozenset({"connection", "unknown"}), frozenset({"region_candidate", "unknown"})),
        "projection_has_function": (frozenset({"connection", "unknown"}), frozenset({"function", "term", "unknown"})),
        "circuit_has_function": (frozenset({"circuit"}), frozenset({"function", "term", "unknown"})),
        "circuit_has_step": (frozenset({"circuit"}), frozenset({"region_candidate", "term", "literal", "unknown"})),
        "region_has_function": (frozenset({"region_candidate", "unknown"}), frozenset({"function", "term", "unknown"})),
    }

    if pred in predicate_rules:
        allowed_sub, allowed_obj = predicate_rules[pred]
        if st not in allowed_sub:
            checks.append(build_validation_result(
                "TRIPLE_MACRO_PREDICATE_SUBJECT_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"predicate {pred} subject_type {st} invalid",
            ))
        if ot not in allowed_obj:
            checks.append(build_validation_result(
                "TRIPLE_MACRO_PREDICATE_OBJECT_MISMATCH",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"predicate {pred} object_type {ot} invalid",
            ))
    else:
        checks.append(build_validation_result(
            "TRIPLE_MACRO_PREDICATE_VALID",
            severity=MirrorValidationSeverity.info,
            status=MirrorValidationResultStatus.passed,
            message=f"macro_clinical predicate {pred} accepted",
        ))

    if not (triple.evidence_text or "").strip():
        checks.append(build_validation_result(
            "TRIPLE_MACRO_EVIDENCE_EMPTY",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="macro_clinical triple evidence_text empty",
        ))

    return checks