"""Mirror KG circuit-projection cross validation tests (deterministic, no LLM)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership, MirrorCircuitStep
from app.schemas.mirror_cross_validation import CircuitProjectionCrossValidationStatus
from app.schemas.mirror_macro_clinical import (
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
)
from app.services import mirror_circuit_projection_cross_validation_service as cv_svc


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="limbic circuit",
        circuit_type="limbic_circuit",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _projection(c1_id: uuid.UUID, c2_id: uuid.UUID, **kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=c1_id,
        target_region_candidate_id=c2_id,
        connection_type="structural_connection",
        directionality="directed",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def _step(circuit_id: uuid.UUID, region_id: uuid.UUID, order: int = 1, **kwargs) -> MirrorCircuitStep:
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        region_candidate_id=region_id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="Macro96",
        step_order=order,
        step_name="step",
        step_type="region",
        role="source",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorCircuitStep(**defaults)


def _membership(
    circuit: MirrorRegionCircuit,
    projection: MirrorRegionConnection,
    *,
    source_method: str,
    verification_status: str,
    source_step_id: uuid.UUID | None = None,
    target_step_id: uuid.UUID | None = None,
    **kwargs,
) -> MirrorCircuitProjectionMembership:
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        projection_id=projection.id,
        source_step_id=source_step_id,
        target_step_id=target_step_id,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="Macro96",
        source_method=source_method,
        verification_status=verification_status,
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorCircuitProjectionMembership(**defaults)


def test_compute_agreement_score_bidirectional_strong():
    score = cv_svc.compute_agreement_score(
        has_forward=True,
        has_reverse=True,
        source_step_agreement=True,
        target_step_agreement=True,
        scope_agreement=True,
        direction_agreement=True,
        scope_mismatch=False,
        entities_missing=False,
    )
    assert score == 1.0


def test_compute_agreement_score_scope_mismatch_capped():
    score = cv_svc.compute_agreement_score(
        has_forward=True,
        has_reverse=True,
        source_step_agreement=True,
        target_step_agreement=True,
        scope_agreement=False,
        direction_agreement=True,
        scope_mismatch=True,
        entities_missing=False,
    )
    assert score <= 0.3


def test_compute_agreement_score_missing_entities():
    score = cv_svc.compute_agreement_score(
        has_forward=True,
        has_reverse=True,
        source_step_agreement=None,
        target_step_agreement=None,
        scope_agreement=None,
        direction_agreement=None,
        scope_mismatch=False,
        entities_missing=True,
    )
    assert score is None


def test_circuit_supported_only():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=p, forward=fwd, reverse=None,
        source_step=None, target_step=None,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.circuit_supported_only


def test_projection_supported_only():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=p, forward=None, reverse=rev,
        source_step=None, target_step=None,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.projection_supported_only


def test_bidirectional_supported_strong():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    s1 = _step(c.id, r1, 1)
    s2 = _step(c.id, r2, 2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=p, forward=fwd, reverse=rev,
        source_step=s1, target_step=s2,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.bidirectionally_supported
    assert result.support_level == "strong"
    assert result.agreement_score == 1.0


def test_bidirectional_step_mismatch_moderate():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    s1 = _step(c.id, r1, 1)
    s2 = _step(c.id, r2, 2)
    s3 = _step(c.id, r2, 3)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
        source_step_id=s1.id,
        target_step_id=s3.id,
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=p, forward=fwd, reverse=rev,
        source_step=s1, target_step=s2,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.bidirectionally_supported
    assert result.conflict_reason == "STEP_MISMATCH"


def test_scope_mismatch_conflict():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
        source_atlas="Macro96",
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
        source_atlas="AAL3",
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=p, forward=fwd, reverse=rev,
        source_step=None, target_step=None,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.conflict
    assert result.conflict_reason == "SCOPE_MISMATCH"


def test_direction_step_conflict():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    s1 = _step(c.id, r2, 1)
    s2 = _step(c.id, r1, 2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=p, forward=fwd, reverse=rev,
        source_step=s1, target_step=s2,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.conflict
    assert result.conflict_reason == "DIRECTION_STEP_CONFLICT"


def test_insufficient_evidence_missing_circuit():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
    )
    result = cv_svc.compare_membership_pair(
        circuit=None, projection=p, forward=fwd, reverse=None,
        source_step=None, target_step=None,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.insufficient_evidence


def test_insufficient_evidence_missing_projection():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
    )
    result = cv_svc.compare_membership_pair(
        circuit=c, projection=None, forward=fwd, reverse=None,
        source_step=None, target_step=None,
    )
    assert result.validation_status == CircuitProjectionCrossValidationStatus.insufficient_evidence


def test_apply_updates_bidirectional():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
    )
    pair = cv_svc.ComparedPair(
        circuit_id=c.id,
        projection_id=p.id,
        forward=fwd,
        reverse=rev,
        validation_status=CircuitProjectionCrossValidationStatus.bidirectionally_supported,
        support_level="strong",
        agreement_score=1.0,
        source_step_agreement=True,
        target_step_agreement=True,
        direction_agreement=True,
        scope_agreement=True,
        conflict_reason=None,
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    count = asyncio.run(
        cv_svc.apply_membership_verification_updates(
            session, [pair], apply_updates=True, update_bidirectional=True, update_conflicts=False,
        )
    )
    assert count == 2
    assert fwd.verification_status == MirrorMembershipVerificationStatus.bidirectionally_supported
    assert rev.verification_status == MirrorMembershipVerificationStatus.bidirectionally_supported
    assert fwd.review_status == "pending"
    assert fwd.promotion_status == "not_promoted"


def test_apply_updates_conflict_only_when_enabled():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
        source_atlas="Other",
    )
    pair = cv_svc.ComparedPair(
        circuit_id=c.id,
        projection_id=p.id,
        forward=fwd,
        reverse=rev,
        validation_status=CircuitProjectionCrossValidationStatus.conflict,
        support_level="conflicting",
        agreement_score=0.2,
        source_step_agreement=None,
        target_step_agreement=None,
        direction_agreement=None,
        scope_agreement=False,
        conflict_reason="SCOPE_MISMATCH",
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    count_off = asyncio.run(
        cv_svc.apply_membership_verification_updates(
            session, [pair], apply_updates=True, update_bidirectional=True, update_conflicts=False,
        )
    )
    assert count_off == 0
    assert fwd.verification_status == MirrorMembershipVerificationStatus.circuit_supported

    count_on = asyncio.run(
        cv_svc.apply_membership_verification_updates(
            session, [pair], apply_updates=True, update_bidirectional=True, update_conflicts=True,
        )
    )
    assert count_on == 2
    assert fwd.verification_status == MirrorMembershipVerificationStatus.model_conflict


def test_dry_run_no_persist():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[fwd]))))
    )
    session.get = AsyncMock(side_effect=lambda model, pk: c if model is MirrorRegionCircuit else p)
    session.add = MagicMock()
    session.commit = AsyncMock()

    outcome = asyncio.run(
        cv_svc.run_circuit_projection_cross_validation(session, dry_run=True, apply_updates=True)
    )
    assert outcome.dry_run is True
    assert outcome.run_id is None
    assert outcome.updated_membership_count == 0
    assert len(outcome.results_preview) >= 1
    session.add.assert_not_called()
    session.commit.assert_not_called()
    assert fwd.verification_status == MirrorMembershipVerificationStatus.circuit_supported


def test_dry_run_false_writes_run():
    c = _circuit()
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    p = _projection(r1, r2)
    s1 = _step(c.id, r1, 1)
    s2 = _step(c.id, r2, 2)
    fwd = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.circuit_to_projection,
        verification_status=MirrorMembershipVerificationStatus.circuit_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )
    rev = _membership(
        c, p,
        source_method=MirrorMembershipSourceMethod.projection_to_circuit,
        verification_status=MirrorMembershipVerificationStatus.projection_supported,
        source_step_id=s1.id,
        target_step_id=s2.id,
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[fwd, rev]))
            )
        )
    )

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return c
        if model is MirrorRegionConnection:
            return p
        if model is MirrorCircuitStep:
            if pk == s1.id:
                return s1
            if pk == s2.id:
                return s2
        return None

    session.get = AsyncMock(side_effect=_get)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    outcome = asyncio.run(
        cv_svc.run_circuit_projection_cross_validation(
            session, dry_run=False, apply_updates=True, update_bidirectional=True,
        )
    )
    assert outcome.bidirectionally_supported_count == 1
    assert outcome.updated_membership_count == 2
    session.commit.assert_called_once()
    assert session.add.call_count >= 2
    assert fwd.verification_status == MirrorMembershipVerificationStatus.bidirectionally_supported


def test_api_dry_run():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.mirror_circuit_projection_cross_validation_service.run_circuit_projection_cross_validation",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = cv_svc.CrossValidationOutcome(
            run_id=None,
            dry_run=True,
            apply_updates=False,
            membership_count=2,
            circuit_supported_count=1,
            projection_supported_count=0,
            bidirectionally_supported_count=1,
            conflict_count=0,
            insufficient_evidence_count=0,
            updated_membership_count=0,
            results_preview=[{
                "circuit_id": uuid.uuid4(),
                "projection_id": uuid.uuid4(),
                "circuit_to_projection_membership_id": uuid.uuid4(),
                "projection_to_circuit_membership_id": uuid.uuid4(),
                "validation_status": "bidirectionally_supported",
                "support_level": "strong",
                "agreement_score": 1.0,
                "source_step_agreement": True,
                "target_step_agreement": True,
                "direction_agreement": True,
                "scope_agreement": True,
                "conflict_reason": None,
                "details_json": {},
            }],
            warnings=[],
        )
        resp = client.post(
            "/api/mirror-kg/circuit-projection-cross-validation/run",
            json={"dry_run": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["run_id"] is None
        assert len(data["results_preview"]) == 1


def test_api_list_runs_and_results():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.mirror_circuit_projection_cross_validation_service.list_cross_validation_runs",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = client.get("/api/mirror-kg/circuit-projection-cross-validation/runs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    with patch(
        "app.services.mirror_circuit_projection_cross_validation_service.list_cross_validation_results",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = client.get("/api/mirror-kg/circuit-projection-cross-validation/results")
        assert resp.status_code == 200


def test_no_llm_provider_called():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.llm_providers.factory.get_llm_provider",
    ) as mock_provider:
        with patch(
            "app.services.mirror_circuit_projection_cross_validation_service.run_circuit_projection_cross_validation",
            new_callable=AsyncMock,
            return_value=cv_svc.CrossValidationOutcome(
                run_id=None, dry_run=True, apply_updates=False,
                membership_count=0, circuit_supported_count=0,
                projection_supported_count=0, bidirectionally_supported_count=0,
                conflict_count=0, insufficient_evidence_count=0,
                updated_membership_count=0, results_preview=[], warnings=[],
            ),
        ):
            client.post(
                "/api/mirror-kg/circuit-projection-cross-validation/run",
                json={"dry_run": True},
            )
        mock_provider.assert_not_called()
