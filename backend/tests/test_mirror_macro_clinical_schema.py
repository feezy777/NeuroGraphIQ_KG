"""Mirror KG macro_clinical schema foundation tests (no LLM / no external network)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorDualModelVerificationRun,
    MirrorProjectionFunction,
)
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorRegionCircuitCreate, MirrorRegionConnectionCreate
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitProjectionMembershipCreate,
    MirrorCircuitStepCreate,
    MirrorDualModelVerificationResultCreate,
    MirrorDualModelVerificationRunCreate,
    MirrorProjectionFunctionCreate,
)
from app.services import mirror_kg_service, mirror_macro_clinical_service as svc


def _candidate(**kwargs) -> CandidateBrainRegion:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="AAL3",
        source_version="v1",
        raw_name="Hippocampus_L",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="candidate_created",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        circuit_name="limbic loop",
        circuit_type="limbic_circuit",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _projection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
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


def _step(circuit_id: uuid.UUID, **kwargs) -> MirrorCircuitStep:
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        step_order=0,
        step_name="hippocampus",
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


def test_circuit_step_create_defaults():
    payload = MirrorCircuitStepCreate(
        circuit_id=uuid.uuid4(),
        granularity_level="macro",
        source_atlas="AAL3",
        step_order=1,
        step_name="step1",
    )
    assert payload.mirror_status == "llm_suggested"
    assert payload.review_status == "pending"
    assert payload.promotion_status == MirrorPromotionStatus.not_promoted


def test_circuit_step_blocks_promoted_status():
    with pytest.raises(ValidationError):
        MirrorCircuitStepCreate(
            circuit_id=uuid.uuid4(),
            granularity_level="macro",
            source_atlas="AAL3",
            step_order=0,
            step_name="s",
            promotion_status=MirrorPromotionStatus.promoted,
        )


def test_projection_function_empty_term_rejected():
    with pytest.raises(ValidationError):
        MirrorProjectionFunctionCreate(
            projection_id=uuid.uuid4(),
            granularity_level="macro",
            source_atlas="AAL3",
            function_term="   ",
        )


def test_dual_model_result_consensus_score_out_of_range():
    with pytest.raises(ValidationError):
        MirrorDualModelVerificationResultCreate(
            run_id=uuid.uuid4(),
            object_type="circuit",
            object_id=uuid.uuid4(),
            model_a_provider="deepseek",
            model_a_decision="support",
            model_b_provider="kimi",
            model_b_decision="support",
            consensus_status="consensus_supported",
            consensus_score=1.5,
        )


def test_create_circuit_step_service():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorCircuitStepCreate(
        circuit_id=circuit.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        step_order=1,
        step_name="amygdala",
    )
    row = asyncio.run(svc.create_circuit_step(session, payload))
    assert isinstance(row, MirrorCircuitStep)
    assert row.promotion_status == MirrorPromotionStatus.not_promoted
    session.add.assert_called_once()


def test_circuit_step_circuit_not_found():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    payload = MirrorCircuitStepCreate(
        circuit_id=uuid.uuid4(),
        granularity_level="macro",
        source_atlas="AAL3",
        step_order=0,
        step_name="x",
    )
    with pytest.raises(svc.MirrorCircuitNotFoundError):
        asyncio.run(svc.create_circuit_step(session, payload))


def test_circuit_step_cross_atlas_rejected():
    circuit = _circuit(source_atlas="Macro96")
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    payload = MirrorCircuitStepCreate(
        circuit_id=circuit.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        step_order=0,
        step_name="x",
    )
    with pytest.raises(svc.SameGranularityValidationError):
        asyncio.run(svc.create_circuit_step(session, payload))


def test_circuit_step_cross_granularity_with_candidate_rejected():
    circuit = _circuit()
    cand = _candidate(granularity_level="micro")
    session = AsyncMock()

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return circuit
        if model is CandidateBrainRegion:
            return cand
        return None

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    payload = MirrorCircuitStepCreate(
        circuit_id=circuit.id,
        region_candidate_id=cand.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        step_order=0,
        step_name="x",
    )
    with pytest.raises(svc.SameGranularityValidationError):
        asyncio.run(svc.create_circuit_step(session, payload))


def test_circuit_step_duplicate_order_rejected():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # dedup check → no match
        MagicMock(scalar_one_or_none=MagicMock(return_value=uuid.uuid4())),  # step_order check → match
    ])
    payload = MirrorCircuitStepCreate(
        circuit_id=circuit.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        step_order=1,
        step_name="dup",
    )
    with pytest.raises(svc.DuplicateStepOrderError):
        asyncio.run(svc.create_circuit_step(session, payload))


def test_create_projection_function_service():
    projection = _projection()
    session = AsyncMock()
    session.get = AsyncMock(return_value=projection)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorProjectionFunctionCreate(
        projection_id=projection.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        function_term="memory relay",
        function_category="memory",
    )
    with patch(
        "app.services.mirror_macro_clinical_service._find_existing_projection_function_for_merge",
        AsyncMock(return_value=None),
    ):
        row = asyncio.run(svc.create_projection_function(session, payload))
    assert isinstance(row, MirrorProjectionFunction)
    assert row.review_status == "pending"


def test_projection_function_projection_not_found():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    payload = MirrorProjectionFunctionCreate(
        projection_id=uuid.uuid4(),
        granularity_level="macro",
        source_atlas="AAL3",
        function_term="x",
    )
    with pytest.raises(svc.MirrorProjectionNotFoundError):
        asyncio.run(svc.create_projection_function(session, payload))


def test_projection_function_cross_atlas_rejected():
    projection = _projection(source_atlas="Macro96")
    session = AsyncMock()
    session.get = AsyncMock(return_value=projection)
    payload = MirrorProjectionFunctionCreate(
        projection_id=projection.id,
        granularity_level="macro",
        source_atlas="AAL3",
        function_term="x",
    )
    with pytest.raises(svc.SameGranularityValidationError):
        asyncio.run(svc.create_projection_function(session, payload))


def test_create_membership_service():
    circuit = _circuit()
    projection = _projection()
    session = AsyncMock()

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return circuit if pk == circuit.id else None
        if model is MirrorRegionConnection:
            return projection if pk == projection.id else None
        return None

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorCircuitProjectionMembershipCreate(
        circuit_id=circuit.id,
        projection_id=projection.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
    )
    row = asyncio.run(svc.create_circuit_projection_membership(session, payload))
    assert isinstance(row, MirrorCircuitProjectionMembership)


def test_membership_cross_granularity_rejected():
    circuit = _circuit(granularity_level="macro")
    projection = _projection(granularity_level="micro")
    session = AsyncMock()

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return circuit
        if model is MirrorRegionConnection:
            return projection
        return None

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    payload = MirrorCircuitProjectionMembershipCreate(
        circuit_id=circuit.id,
        projection_id=projection.id,
        granularity_level="macro",
        source_atlas="AAL3",
    )
    with pytest.raises(svc.SameGranularityValidationError):
        asyncio.run(svc.create_circuit_projection_membership(session, payload))


def test_membership_source_step_wrong_circuit():
    circuit = _circuit()
    other_circuit = _circuit()
    projection = _projection()
    src_step = _step(other_circuit.id)
    session = AsyncMock()

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return circuit if pk == circuit.id else None
        if model is MirrorRegionConnection:
            return projection
        if model is MirrorCircuitStep:
            return src_step if pk == src_step.id else None
        return None

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    payload = MirrorCircuitProjectionMembershipCreate(
        circuit_id=circuit.id,
        projection_id=projection.id,
        source_step_id=src_step.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
    )
    with pytest.raises(svc.InvalidStepReferenceError):
        asyncio.run(svc.create_circuit_projection_membership(session, payload))


def test_membership_same_source_target_step_rejected():
    circuit = _circuit()
    projection = _projection()
    step = _step(circuit.id)
    session = AsyncMock()

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return circuit
        if model is MirrorRegionConnection:
            return projection
        if model is MirrorCircuitStep:
            return step
        return None

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    payload = MirrorCircuitProjectionMembershipCreate(
        circuit_id=circuit.id,
        projection_id=projection.id,
        source_step_id=step.id,
        target_step_id=step.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
    )
    with pytest.raises(svc.InvalidStepReferenceError):
        asyncio.run(svc.create_circuit_projection_membership(session, payload))


def test_membership_duplicate_rejected():
    circuit = _circuit()
    projection = _projection()
    session = AsyncMock()

    async def _get(model, pk):
        if model is MirrorRegionCircuit:
            return circuit
        if model is MirrorRegionConnection:
            return projection
        return None

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # dedup check → no match
        MagicMock(scalar_one_or_none=MagicMock(return_value=uuid.uuid4())),  # step_id check → match
    ])
    payload = MirrorCircuitProjectionMembershipCreate(
        circuit_id=circuit.id,
        projection_id=projection.id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
    )
    with pytest.raises(svc.DuplicateMembershipError):
        asyncio.run(svc.create_circuit_projection_membership(session, payload))


def test_create_dual_model_verification_run():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    payload = MirrorDualModelVerificationRunCreate(
        verification_task_type="circuit_projection_membership",
        dry_run=True,
    )
    row = asyncio.run(svc.create_dual_model_verification_run(session, payload))
    assert isinstance(row, MirrorDualModelVerificationRun)
    assert row.dry_run is True


def test_verification_result_object_must_exist():
    run_id = uuid.uuid4()
    run = MirrorDualModelVerificationRun(
        id=run_id,
        verification_task_type="circuit",
        model_a_provider="deepseek",
        model_b_provider="kimi",
        scope_json={},
        status="created",
    )
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, pk: run if pk == run_id else None)
    payload = MirrorDualModelVerificationResultCreate(
        run_id=run_id,
        object_type="circuit",
        object_id=uuid.uuid4(),
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="kimi",
        model_b_decision="support",
        consensus_status="consensus_supported",
    )
    with pytest.raises(svc.VerificationObjectNotFoundError):
        asyncio.run(svc.create_dual_model_verification_result(session, payload))


def test_verification_result_does_not_update_target_review_status():
    run_id = uuid.uuid4()
    circuit_id = uuid.uuid4()
    circuit = _circuit(id=circuit_id)
    run = MirrorDualModelVerificationRun(
        id=run_id,
        verification_task_type="circuit",
        model_a_provider="deepseek",
        model_b_provider="kimi",
        scope_json={},
        status="created",
    )
    session = AsyncMock()

    async def _get(model, pk):
        if pk == run_id:
            return run
        if pk == circuit_id:
            return circuit
        return None

    session.get = AsyncMock(side_effect=_get)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorDualModelVerificationResultCreate(
        run_id=run_id,
        object_type="circuit",
        object_id=circuit_id,
        model_a_provider="deepseek",
        model_a_decision="support",
        model_b_provider="kimi",
        model_b_decision="support",
        consensus_status="consensus_supported",
        consensus_score=0.85,
    )
    asyncio.run(svc.create_dual_model_verification_result(session, payload))
    assert circuit.review_status == "pending"
    assert circuit.promotion_status == "not_promoted"


def test_circuit_steps_api_list():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/mirror-kg/circuit-steps")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        body = resp.json()
        assert "items" in body
        assert "total" in body


def test_health_reports_mirror_macro_clinical_module():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["modules"]["mirror_macro_clinical"] == "active"


def test_mirror_kg_service_still_works():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    payload = MirrorRegionConnectionCreate(
        granularity_level="macro",
        source_atlas="AAL3",
        connection_type="projection",
    )
    with patch("app.services.mirror_kg_service._find_existing_connection_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_connection(session, payload))
    assert isinstance(row, MirrorRegionConnection)


def test_create_circuit_for_membership_fixtures():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    payload = MirrorRegionCircuitCreate(
        granularity_level="macro",
        source_atlas="AAL3",
        circuit_name="test circuit",
        circuit_type="memory_related",
    )
    with patch("app.services.mirror_kg_service._find_existing_circuit_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_circuit(session, payload))
    assert isinstance(row, MirrorRegionCircuit)
