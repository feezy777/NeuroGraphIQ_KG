"""Macro clinical Mirror Human Review tests (Step 8.14, no LLM)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.models.mirror_review import MirrorHumanReviewRecord
from app.models.mirror_validation import MirrorRuleValidationResult
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_review import MirrorReviewAction
from app.services import mirror_review_service as mrs
from app.services import mirror_review_macro_clinical as mc


def _connection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        connection_type="projection",
        directionality="directed",
        confidence=0.8,
        evidence_text="evidence",
        mirror_status=MirrorStatus.rule_checked,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


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
        mirror_status=MirrorStatus.rule_checked,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _step(circuit: MirrorRegionCircuit, **kwargs) -> MirrorCircuitStep:
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        region_candidate_id=uuid.uuid4(),
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        step_order=1,
        step_name="step1",
        step_type="region",
        role="participant",
        confidence=0.8,
        evidence_text="ev",
        mirror_status=MirrorStatus.rule_checked,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    defaults.update(kwargs)
    return MirrorCircuitStep(**defaults)


def _validation(target_type: str, target_id: uuid.UUID, *, severity: str = "info") -> MirrorRuleValidationResult:
    return MirrorRuleValidationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        target_type=target_type,
        target_id=target_id,
        rule_code="RULE_TEST",
        severity=severity,
        status=severity,
        message="test",
    )


def _mock_session_get(obj):
    session = AsyncMock()
    session.get = AsyncMock(return_value=obj)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_execute_chain(*result_lists):
    return AsyncMock(side_effect=[
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=lst))))
        for lst in result_lists
    ])


def test_queue_sort_key_prioritizes_blockers():
    urgent = {"recommended_review_priority": "urgent", "latest_validation_summary": {"blocker_count": 1, "error_count": 0}, "updated_at": None}
    normal = {"recommended_review_priority": "normal", "latest_validation_summary": {"blocker_count": 0, "error_count": 0}, "updated_at": None}
    assert mc.queue_sort_key(urgent) < mc.queue_sort_key(normal)


def test_compute_gating_blocks_approve_on_error():
    conn = _connection()
    g = mc.compute_gating("projection", conn, {"validated": True, "has_blocker": False, "has_error": True}, is_signal=False)
    assert g["can_approve"] is False
    assert "error present" in g["gating_reasons"]


def test_compute_gating_signal_no_approve():
    sig = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="projection",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="kimi",
        model_b_decision="support",
        consensus_status="consensus_supported",
    )
    g = mc.compute_gating("dual_model_verification_result", sig, {}, is_signal=True)
    assert g["can_approve"] is False
    assert g["can_accept_signal"] is True


def test_approve_domain_success():
    conn = _connection()
    val = _validation("connection", conn.id)
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([val], [])
    record, updated, _ = asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="connection", target_id=conn.id,
        action=MirrorReviewAction.approve, reviewer="r1",
    ))
    assert conn.mirror_status == MirrorStatus.human_approved
    assert conn.review_status == MirrorReviewStatus.approved
    assert conn.promotion_status == MirrorPromotionStatus.not_promoted
    assert isinstance(record, MirrorHumanReviewRecord)


def test_approve_blocker_raises():
    conn = _connection()
    val = _validation("connection", conn.id, severity="blocker")
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([val], [])
    with pytest.raises(mrs.MirrorObjectHasBlockersError):
        asyncio.run(mrs.perform_mirror_review_action(
            session, target_type="connection", target_id=conn.id,
            action=MirrorReviewAction.approve, reviewer="r1",
        ))


def test_approve_warning_requires_reason():
    conn = _connection(evidence_text="")
    val = _validation("connection", conn.id, severity="warning")
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([val], [])
    with pytest.raises(mrs.ReviewerReasonRequiredError):
        asyncio.run(mrs.perform_mirror_review_action(
            session, target_type="connection", target_id=conn.id,
            action=MirrorReviewAction.approve, reviewer="r1",
        ))


def test_approve_warning_with_reason_ok():
    conn = _connection(evidence_text="")
    val = _validation("connection", conn.id, severity="warning")
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([val], [])
    _, _, warnings = asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="connection", target_id=conn.id,
        action=MirrorReviewAction.approve, reviewer="r1", reviewer_note="ok",
    ))
    assert conn.mirror_status == MirrorStatus.human_approved
    assert warnings


def test_reject_sets_blocked():
    conn = _connection()
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([], [])
    asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="connection", target_id=conn.id,
        action=MirrorReviewAction.reject, reviewer="r1", reviewer_note="bad",
    ))
    assert conn.promotion_status == MirrorPromotionStatus.blocked


def test_comment_no_status_change():
    conn = _connection()
    before_ms = conn.mirror_status
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([], [])
    asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="connection", target_id=conn.id,
        action=MirrorReviewAction.comment, reviewer="r1", reviewer_note="note",
    ))
    assert conn.mirror_status == before_ms


def test_edit_whitelist_circuit_step():
    circuit = _circuit()
    step = _step(circuit)
    mrs.apply_safe_edit_patch("circuit_step", step, {"step_name": "new"})
    assert step.step_name == "new"


def test_edit_forbidden_id():
    circuit = _circuit()
    step = _step(circuit)
    with pytest.raises(mrs.ForbiddenEditFieldError):
        mrs.apply_safe_edit_patch("circuit_step", step, {"source_atlas": "Other"})


def test_approve_signal_raises():
    sig = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="projection",
        object_id=uuid.uuid4(),
        model_a_provider="a",
        model_a_decision="support",
        model_b_provider="b",
        model_b_decision="reject",
        consensus_status="model_conflict",
    )
    session = _mock_session_get(sig)
    session.execute = _mock_execute_chain([], [])
    with pytest.raises(mrs.DomainActionOnSignalError):
        asyncio.run(mrs.perform_mirror_review_action(
            session, target_type="dual_model_verification_result", target_id=sig.id,
            action=MirrorReviewAction.approve, reviewer="r1",
        ))


def test_accept_signal_no_domain_change():
    proj = _connection()
    sig = MirrorDualModelVerificationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        object_type="projection",
        object_id=proj.id,
        model_a_provider="a",
        model_a_decision="support",
        model_b_provider="b",
        model_b_decision="support",
        consensus_status="consensus_supported",
    )
    before_rs = proj.review_status

    async def _get(model, pk):
        if pk == sig.id:
            return sig
        if pk == proj.id:
            return proj
        return None

    session = AsyncMock()
    session.get = AsyncMock(side_effect=_get)
    session.execute = _mock_execute_chain([], [])
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="dual_model_verification_result", target_id=sig.id,
        action=MirrorReviewAction.accept_signal, reviewer="r1",
    ))
    assert proj.review_status == before_rs


def test_dismiss_signal_ok():
    sig = MirrorCircuitProjectionCrossValidationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        projection_id=uuid.uuid4(),
        validation_status="conflict",
        support_level="none",
    )
    session = _mock_session_get(sig)
    session.execute = _mock_execute_chain([], [])
    record, _, _ = asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="circuit_projection_cross_validation_result", target_id=sig.id,
        action=MirrorReviewAction.dismiss_signal, reviewer="r1",
    ))
    assert record.action == MirrorReviewAction.dismiss_signal


def test_flag_for_followup_domain():
    conn = _connection()
    session = _mock_session_get(conn)
    session.execute = _mock_execute_chain([], [])
    record, _, _ = asyncio.run(mrs.perform_mirror_review_action(
        session, target_type="connection", target_id=conn.id,
        action=MirrorReviewAction.flag_for_followup, reviewer="r1",
    ))
    assert record.action == MirrorReviewAction.flag_for_followup
    assert conn.review_status == MirrorReviewStatus.pending


def test_signal_action_on_domain_raises():
    conn = _connection()
    with pytest.raises(mrs.SignalActionOnDomainError):
        mrs.validate_review_eligibility(
            MirrorReviewAction.accept_signal, "connection", conn, {"validated": True},
        )


def test_list_target_types():
    types = mrs.list_review_target_types()
    tts = {t["target_type"] for t in types}
    assert "circuit_step" in tts
    assert "dual_model_verification_result" in tts


def test_membership_edit_whitelist():
    mem = MirrorCircuitProjectionMembership(
        id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        projection_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        role_in_circuit="link",
        verification_status="model_conflict",
        mirror_status=MirrorStatus.rule_checked,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    mrs.apply_safe_edit_patch("circuit_projection_membership", mem, {"role_in_circuit": "hub"})
    assert mem.role_in_circuit == "hub"


def test_projection_function_edit():
    pf = MirrorProjectionFunction(
        id=uuid.uuid4(),
        projection_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        mirror_status=MirrorStatus.rule_checked,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    mrs.apply_safe_edit_patch("projection_function", pf, {"function_term": "attention"})
    assert pf.function_term == "attention"


def test_compute_priority_model_conflict():
    p = mc.compute_review_priority({}, consensus_status="model_conflict")
    assert p == "urgent"


def test_is_signal_target():
    assert mc.is_signal_target("dual_model_verification_result")
    assert not mc.is_signal_target("circuit_step")
