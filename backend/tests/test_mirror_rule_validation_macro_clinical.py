"""Macro clinical Mirror KG rule validation tests (Step 8.13, no LLM)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_kg import MirrorKgTriple, MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.schemas.mirror_kg import MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_macro_clinical import (
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
)
from app.schemas.mirror_validation import MirrorValidationSeverity
from app.services import mirror_rule_validation_macro_clinical as mc
from app.services import mirror_rule_validation_service as mrv


def _candidate(**kwargs) -> CandidateBrainRegion:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="Macro96",
        source_version="v1",
        raw_name="Hippocampus",
        en_name="Hippocampus",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="limbic",
        circuit_type="limbic_circuit",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _projection(**kwargs) -> MirrorRegionConnection:
    c1 = kwargs.pop("_c1", None) or _candidate()
    c2 = kwargs.pop("_c2", None) or _candidate()
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=c1.batch_id,
        resource_id=c1.resource_id,
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        connection_type="projection",
        directionality="directed",
        confidence=0.8,
        evidence_text="ev",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    conn = MirrorRegionConnection(**defaults)
    conn._c1, conn._c2 = c1, c2  # noqa: SLF001
    return conn


def _step(circuit: MirrorRegionCircuit, **kwargs) -> MirrorCircuitStep:
    cand = kwargs.pop("_c", None) or _candidate()
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        region_candidate_id=cand.id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        step_order=1,
        step_name="step1",
        step_type="region",
        role="participant",
        confidence=0.8,
        evidence_text="ev",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorCircuitStep(**defaults)


def _has_code(checks, code: str) -> bool:
    return any(c.rule_code == code for c in checks)


def test_circuit_step_ok():
    circuit = _circuit()
    cand = _candidate()
    step = _step(circuit, _c=cand)
    checks = mc.validate_circuit_step(
        step, circuit=circuit, candidate_map={cand.id: cand}, order_dup={},
    )
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_circuit_step_circuit_missing():
    step = _step(_circuit())
    checks = mc.validate_circuit_step(step, circuit=None, candidate_map={}, order_dup={})
    assert _has_code(checks, "CIRCUIT_STEP_CIRCUIT_MISSING")


def test_circuit_step_order_invalid():
    circuit = _circuit()
    step = _step(circuit, step_order=0)
    checks = mc.validate_circuit_step(step, circuit=circuit, candidate_map={}, order_dup={})
    assert _has_code(checks, "CIRCUIT_STEP_ORDER_INVALID")


def test_circuit_step_region_missing():
    circuit = _circuit()
    step = _step(circuit, region_candidate_id=uuid.uuid4())
    checks = mc.validate_circuit_step(step, circuit=circuit, candidate_map={}, order_dup={})
    assert _has_code(checks, "CIRCUIT_STEP_REGION_MISSING")


def test_circuit_step_region_scope_mismatch():
    circuit = _circuit()
    cand = _candidate(source_atlas="Other")
    step = _step(circuit, _c=cand)
    checks = mc.validate_circuit_step(step, circuit=circuit, candidate_map={cand.id: cand}, order_dup={})
    assert _has_code(checks, "CIRCUIT_STEP_REGION_SCOPE_MISMATCH")


def test_circuit_step_evidence_empty():
    circuit = _circuit()
    step = _step(circuit, evidence_text="")
    checks = mc.validate_circuit_step(step, circuit=circuit, candidate_map={}, order_dup={})
    assert _has_code(checks, "CIRCUIT_STEP_EVIDENCE_EMPTY")


def test_projection_function_ok():
    proj = _projection()
    pf = MirrorProjectionFunction(
        id=uuid.uuid4(),
        projection_id=proj.id,
        source_atlas=proj.source_atlas,
        granularity_level=proj.granularity_level,
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        confidence=0.8,
        evidence_text="ev",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_projection_function(pf, projection=proj, duplicate_keys={})
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_projection_function_projection_missing():
    pf = MirrorProjectionFunction(
        id=uuid.uuid4(),
        projection_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_projection_function(pf, projection=None, duplicate_keys={})
    assert _has_code(checks, "PROJECTION_FUNCTION_PROJECTION_MISSING")


def test_projection_function_scope_mismatch():
    proj = _projection()
    pf = MirrorProjectionFunction(
        id=uuid.uuid4(),
        projection_id=proj.id,
        source_atlas="Other",
        granularity_level="macro",
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_projection_function(pf, projection=proj, duplicate_keys={})
    assert _has_code(checks, "PROJECTION_FUNCTION_SCOPE_MISMATCH")


def test_projection_function_term_empty():
    proj = _projection()
    pf = MirrorProjectionFunction(
        id=uuid.uuid4(),
        projection_id=proj.id,
        source_atlas=proj.source_atlas,
        granularity_level=proj.granularity_level,
        function_term="",
        function_category="memory",
        relation_type="associated_with",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_projection_function(pf, projection=proj, duplicate_keys={})
    assert _has_code(checks, "PROJECTION_FUNCTION_TERM_EMPTY")


def test_membership_ok():
    circuit = _circuit()
    proj = _projection()
    m = MirrorCircuitProjectionMembership(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
        confidence=0.8,
        evidence_text="ev",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_circuit_projection_membership(
        m, circuit=circuit, projection=proj, step_map={}, cross_results=[], duplicate_keys={},
    )
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_membership_circuit_missing():
    proj = _projection()
    m = MirrorCircuitProjectionMembership(
        id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        projection_id=proj.id,
        source_atlas="Macro96",
        granularity_level="macro",
        source_method="unknown",
        verification_status="unverified",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_circuit_projection_membership(
        m, circuit=None, projection=proj, step_map={}, cross_results=[], duplicate_keys={},
    )
    assert _has_code(checks, "MEMBERSHIP_CIRCUIT_MISSING")


def test_membership_scope_mismatch():
    circuit = _circuit()
    proj = _projection(source_atlas="Other")
    m = MirrorCircuitProjectionMembership(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        source_method="unknown",
        verification_status="unverified",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_circuit_projection_membership(
        m, circuit=circuit, projection=proj, step_map={}, cross_results=[], duplicate_keys={},
    )
    assert _has_code(checks, "MEMBERSHIP_SCOPE_MISMATCH")


def test_membership_bidirectional_without_cross():
    circuit = _circuit()
    proj = _projection()
    m = MirrorCircuitProjectionMembership(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        source_method="circuit_to_projection",
        verification_status=MirrorMembershipVerificationStatus.bidirectionally_supported,
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_circuit_projection_membership(
        m, circuit=circuit, projection=proj, step_map={}, cross_results=[], duplicate_keys={},
    )
    assert _has_code(checks, "MEMBERSHIP_BIDIRECTIONAL_WITHOUT_CROSS_RESULT")


def test_membership_model_conflict_review():
    circuit = _circuit()
    proj = _projection()
    m = MirrorCircuitProjectionMembership(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        source_method="unknown",
        verification_status=MirrorMembershipVerificationStatus.model_conflict,
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.validate_circuit_projection_membership(
        m, circuit=circuit, projection=proj, step_map={}, cross_results=[], duplicate_keys={},
    )
    assert _has_code(checks, "MEMBERSHIP_MODEL_CONFLICT_REVIEW_REQUIRED")
    assert mc.is_high_review_check(next(c for c in checks if c.rule_code.endswith("REVIEW_REQUIRED")))


def test_cross_validation_bidirectional_info():
    circuit = _circuit()
    proj = _projection()
    cr = MirrorCircuitProjectionCrossValidationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        validation_status="bidirectionally_supported",
        support_level="strong",
        circuit_to_projection_membership_id=uuid.uuid4(),
        projection_to_circuit_membership_id=uuid.uuid4(),
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
    )
    checks = mc.validate_cross_validation_result(cr, circuit=circuit, projection=proj)
    assert _has_code(checks, "CROSS_RESULT_BIDIRECTIONALLY_SUPPORTED")
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_cross_validation_conflict_not_blocker():
    circuit = _circuit()
    proj = _projection()
    cr = MirrorCircuitProjectionCrossValidationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        validation_status="conflict",
        support_level="conflicting",
        conflict_reason="direction mismatch",
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
    )
    checks = mc.validate_cross_validation_result(cr, circuit=circuit, projection=proj)
    assert _has_code(checks, "CROSS_RESULT_CONFLICT_REVIEW_REQUIRED")
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_cross_validation_insufficient_evidence():
    circuit = _circuit()
    proj = _projection()
    cr = MirrorCircuitProjectionCrossValidationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=proj.id,
        validation_status="insufficient_evidence",
        support_level="weak",
        details_json={"reason": "missing reverse"},
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
    )
    checks = mc.validate_cross_validation_result(cr, circuit=circuit, projection=proj)
    assert _has_code(checks, "CROSS_RESULT_INSUFFICIENT_EVIDENCE")


def test_dual_consensus_supported_info():
    dr = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="circuit",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="kimi",
        model_b_decision="support",
        consensus_status="consensus_supported",
        recommended_review_priority="normal",
    )
    checks = mc.validate_dual_model_verification_result(dr, object_exists=True)
    assert _has_code(checks, "DUAL_RESULT_CONSENSUS_SUPPORTED")


def test_dual_consensus_rejected_not_blocker():
    dr = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="circuit",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="reject",
        model_b_provider="kimi",
        model_b_decision="reject",
        consensus_status="consensus_rejected",
        recommended_review_priority="high",
    )
    checks = mc.validate_dual_model_verification_result(dr, object_exists=True)
    assert _has_code(checks, "DUAL_RESULT_CONSENSUS_REJECTED_REVIEW_REQUIRED")
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_dual_model_conflict_review():
    dr = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="circuit",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="kimi",
        model_b_decision="reject",
        consensus_status="model_conflict",
        conflict_summary="support vs reject",
        recommended_review_priority="high",
    )
    checks = mc.validate_dual_model_verification_result(dr, object_exists=True)
    assert _has_code(checks, "DUAL_RESULT_MODEL_CONFLICT_REVIEW_REQUIRED")


def test_dual_same_provider_error():
    dr = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="circuit",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="deepseek",
        model_b_decision="support",
        consensus_status="consensus_supported",
        recommended_review_priority="normal",
    )
    checks = mc.validate_dual_model_verification_result(dr, object_exists=True)
    assert _has_code(checks, "DUAL_RESULT_SAME_PROVIDER")


def test_dual_object_missing_blocker():
    dr = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="circuit",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="kimi",
        model_b_decision="support",
        consensus_status="consensus_supported",
        recommended_review_priority="normal",
    )
    checks = mc.validate_dual_model_verification_result(dr, object_exists=False)
    assert _has_code(checks, "DUAL_RESULT_OBJECT_MISSING")


def test_projection_without_membership_warning():
    proj = _projection()
    c1, c2 = proj._c1, proj._c2  # noqa: SLF001
    checks = mc.validate_projection_macro(
        proj, candidate_map={c1.id: c1, c2.id: c2}, membership_count=0, duplicate_keys={},
    )
    assert _has_code(checks, "PROJECTION_WITHOUT_MEMBERSHIP")


def test_triple_macro_predicate_mismatch():
    triple = MirrorKgTriple(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        subject_type="region_candidate",
        subject_label="A",
        predicate="circuit_contains_projection",
        object_type="region_candidate",
        object_label="B",
        triple_scope="same_granularity",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.supplement_triple_macro_clinical(triple)
    assert _has_code(checks, "TRIPLE_MACRO_PREDICATE_SUBJECT_MISMATCH")


def test_triple_macro_predicate_ok():
    triple = MirrorKgTriple(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        subject_type="circuit",
        subject_label="limbic",
        predicate="circuit_contains_projection",
        object_type="connection",
        object_label="proj",
        triple_scope="same_granularity",
        evidence_text="ev",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    checks = mc.supplement_triple_macro_clinical(triple)
    assert not any(c.severity == MirrorValidationSeverity.blocker for c in checks)


def test_invalid_target_type():
    with pytest.raises(mrv.InvalidTargetTypeError):
        asyncio.run(
            mrv.run_mirror_rule_validation(
                AsyncMock(),
                target_types=["invalid_type"],
                dry_run=True,
            )
        )


def test_circuit_step_apply_rule_checked():
    circuit = _circuit()
    step = _step(circuit)
    outcome = mrv.ValidationOutcome(
        target_type="circuit_step",
        target_id=step.id,
        checks=[],
        mirror_status=step.mirror_status,
    )
    stats = asyncio.run(
        mrv.apply_rule_checked_status_updates(
            AsyncMock(), [outcome], objects_by_type={"circuit_step": [step]},
        )
    )
    assert step.mirror_status == MirrorStatus.rule_checked
    assert stats["eligible_rule_checked"] == 1


def test_cross_result_no_mirror_status_update():
    outcome = mrv.ValidationOutcome(
        target_type="circuit_projection_cross_validation_result",
        target_id=uuid.uuid4(),
        checks=[],
    )
    stats = asyncio.run(
        mrv.apply_rule_checked_status_updates(AsyncMock(), [outcome], objects_by_type={}),
    )
    assert stats["eligible_rule_checked"] == 0
