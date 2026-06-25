"""Dual-model verification execution tests (mock providers, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership
from app.schemas.mirror_dual_model_verification import DualModelConsensusStatus, DualModelDecision
from app.services import mirror_dual_model_verification_service as dm_svc
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


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


def _membership(circuit_id: uuid.UUID, projection_id: uuid.UUID, **kwargs) -> MirrorCircuitProjectionMembership:
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        projection_id=projection_id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="Macro96",
        source_method="circuit_to_projection",
        verification_status="circuit_supported",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorCircuitProjectionMembership(**defaults)


def _model_decision(decision: str, confidence: float = 0.8) -> dm_svc.ModelDecision:
    return dm_svc.ModelDecision(
        object_id=uuid.uuid4(),
        decision=decision,
        confidence=confidence,
        evidence_text="evidence",
        uncertainty_reason=None,
        risk_flags=[],
        recommended_review_priority="normal",
        raw={"decision": decision},
    )


def test_compare_consensus_supported():
    oid = uuid.uuid4()
    obj = dm_svc.VerificationObject(
        object_type="circuit",
        object_id=oid,
        resource_id=None,
        batch_id=None,
        source_atlas="Macro96",
        source_version=None,
        granularity_level="macro",
        granularity_family="macro_clinical",
        label="test",
        payload={},
    )
    ma = _model_decision(DualModelDecision.support, 0.8)
    mb = _model_decision(DualModelDecision.support, 0.7)
    ma.object_id = oid
    mb.object_id = oid
    result = dm_svc.compare_dual_model_outputs(obj, ma, mb)
    assert result["consensus_status"] == DualModelConsensusStatus.consensus_supported
    assert result["consensus_score"] is not None
    assert result["consensus_score"] >= 0.75


def test_compare_consensus_rejected():
    oid = uuid.uuid4()
    obj = dm_svc.VerificationObject(
        object_type="circuit", object_id=oid, resource_id=None, batch_id=None,
        source_atlas="Macro96", source_version=None, granularity_level="macro",
        granularity_family="macro_clinical", label="test", payload={},
    )
    ma = _model_decision(DualModelDecision.reject, 0.85)
    mb = _model_decision(DualModelDecision.reject, 0.82)
    ma.object_id = mb.object_id = oid
    result = dm_svc.compare_dual_model_outputs(obj, ma, mb)
    assert result["consensus_status"] == DualModelConsensusStatus.consensus_rejected
    assert result["recommended_review_priority"] == "high"


def test_compare_model_conflict():
    oid = uuid.uuid4()
    obj = dm_svc.VerificationObject(
        object_type="circuit", object_id=oid, resource_id=None, batch_id=None,
        source_atlas="Macro96", source_version=None, granularity_level="macro",
        granularity_family="macro_clinical", label="test", payload={},
    )
    ma = _model_decision(DualModelDecision.support, 0.8)
    mb = _model_decision(DualModelDecision.reject, 0.75)
    ma.object_id = mb.object_id = oid
    result = dm_svc.compare_dual_model_outputs(obj, ma, mb)
    assert result["consensus_status"] == DualModelConsensusStatus.model_conflict
    assert "model_a=support" in result["conflict_summary"]


def test_compare_needs_human_review():
    oid = uuid.uuid4()
    obj = dm_svc.VerificationObject(
        object_type="circuit", object_id=oid, resource_id=None, batch_id=None,
        source_atlas="Macro96", source_version=None, granularity_level="macro",
        granularity_family="macro_clinical", label="test", payload={},
    )
    ma = _model_decision(DualModelDecision.support, 0.7)
    mb = _model_decision(DualModelDecision.uncertain, 0.5)
    ma.object_id = mb.object_id = oid
    result = dm_svc.compare_dual_model_outputs(obj, ma, mb)
    assert result["consensus_status"] == DualModelConsensusStatus.needs_human_review


def test_compare_insufficient_information_missing_model():
    oid = uuid.uuid4()
    obj = dm_svc.VerificationObject(
        object_type="circuit", object_id=oid, resource_id=None, batch_id=None,
        source_atlas="Macro96", source_version=None, granularity_level="macro",
        granularity_family="macro_clinical", label="test", payload={},
    )
    result = dm_svc.compare_dual_model_outputs(obj, None, None)
    assert result["consensus_status"] == DualModelConsensusStatus.insufficient_information
    assert "MODEL_OUTPUT_MISSING_OBJECT" in result["conflict_summary"]


def test_parse_model_verification_response():
    oid = uuid.uuid4()
    raw = json.dumps({
        "verification": [{
            "object_id": str(oid),
            "decision": "support",
            "confidence": 0.9,
            "evidence_text": "ok",
            "recommended_review_priority": "normal",
        }],
    })
    warnings: list[str] = []
    parsed = dm_svc.parse_model_verification_response(raw, {oid}, warnings)
    assert oid in parsed
    assert parsed[oid].decision == DualModelDecision.support


def test_same_provider_rejected():
    session = AsyncMock()
    with pytest.raises(dm_svc.SameProviderError):
        asyncio.run(
            dm_svc.run_dual_model_verification(
                session,
                object_type="circuit",
                object_ids=[uuid.uuid4()],
                model_a_provider="deepseek",
                model_b_provider="deepseek",
                dry_run=True,
            )
        )


def test_invalid_object_type():
    session = AsyncMock()
    with pytest.raises(dm_svc.InvalidObjectTypeError):
        asyncio.run(
            dm_svc.run_dual_model_verification(
                session,
                object_type="invalid_type",
                dry_run=True,
            )
        )


def test_dry_run_no_provider_no_persist():
    c = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c)

    outcome = asyncio.run(
        dm_svc.run_dual_model_verification(
            session,
            object_type="circuit",
            object_ids=[c.id],
            dry_run=True,
        )
    )
    assert outcome.dry_run is True
    assert outcome.model_a_run_id is None
    assert outcome.model_b_run_id is None
    assert outcome.run_id is None
    assert outcome.model_a_system_prompt
    assert outcome.model_b_system_prompt
    session.commit.assert_not_called()


def test_cross_atlas_rejected():
    c1 = _circuit(source_atlas="Macro96")
    c2 = _circuit(source_atlas="AAL3")
    session = AsyncMock()

    async def _get(model, pk):
        if pk == c1.id:
            return c1
        if pk == c2.id:
            return c2
        return None

    session.get = AsyncMock(side_effect=_get)
    with pytest.raises(dm_svc.CrossAtlasObjectError):
        asyncio.run(
            dm_svc.run_dual_model_verification(
                session,
                object_type="circuit",
                object_ids=[c1.id, c2.id],
                dry_run=True,
            )
        )


def _mock_provider_response(decisions: dict[uuid.UUID, str]) -> LlmProviderResponse:
    verification = [
        {
            "object_id": str(oid),
            "decision": decision,
            "confidence": 0.85,
            "evidence_text": "test evidence",
            "recommended_review_priority": "normal",
        }
        for oid, decision in decisions.items()
    ]
    raw = json.dumps({"verification": verification})
    return LlmProviderResponse(
        provider="mock",
        model="mock",
        raw_text=raw,
        parsed_json={"verification": verification},
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=100,
    )


def test_run_with_mocked_providers_consensus_supported():
    c = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    async def _fake_call(session, **kwargs):
        oid = kwargs["objects"][0].object_id
        run = MagicMock()
        run.id = uuid.uuid4()
        item = MagicMock()
        decisions = {
            oid: dm_svc.ModelDecision(
                object_id=oid,
                decision=DualModelDecision.support,
                confidence=0.85,
                evidence_text="ev",
                uncertainty_reason=None,
                risk_flags=[],
                recommended_review_priority="normal",
                raw={},
            )
        }
        return run, item, decisions, []

    with patch.object(dm_svc, "call_model_provider", side_effect=_fake_call):
        with patch.object(dm_svc, "get_deepseek_runtime_config") as ds:
            with patch.object(dm_svc, "get_kimi_runtime_config") as km:
                ds.return_value = MagicMock(api_key="test-key", default_model="deepseek-chat")
                km.return_value = MagicMock(api_key="test-key", default_model="moonshot-v1-8k")
                outcome = asyncio.run(
                    dm_svc.run_dual_model_verification(
                        session,
                        object_type="circuit",
                        object_ids=[c.id],
                        dry_run=False,
                        create_results=True,
                    )
                )
    assert outcome.consensus_supported_count == 1
    assert outcome.model_a_run_id is not None
    assert outcome.model_b_run_id is not None
    session.commit.assert_called_once()


def test_run_conflict_with_mocked_providers():
    c = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    call_count = 0

    async def _fake_call(session, **kwargs):
        nonlocal call_count
        call_count += 1
        oid = kwargs["objects"][0].object_id
        run = MagicMock()
        run.id = uuid.uuid4()
        item = MagicMock()
        decision = DualModelDecision.support if call_count == 1 else DualModelDecision.reject
        decisions = {
            oid: dm_svc.ModelDecision(
                object_id=oid,
                decision=decision,
                confidence=0.85,
                evidence_text="ev",
                uncertainty_reason=None,
                risk_flags=[],
                recommended_review_priority="normal",
                raw={},
            )
        }
        return run, item, decisions, []

    with patch.object(dm_svc, "call_model_provider", side_effect=_fake_call):
        with patch.object(dm_svc, "get_deepseek_runtime_config") as ds:
            with patch.object(dm_svc, "get_kimi_runtime_config") as km:
                ds.return_value = MagicMock(api_key="test-key", default_model="deepseek-chat")
                km.return_value = MagicMock(api_key="test-key", default_model="moonshot-v1-8k")
                outcome = asyncio.run(
                    dm_svc.run_dual_model_verification(
                        session,
                        object_type="circuit",
                        object_ids=[c.id],
                        dry_run=False,
                    )
                )
    assert outcome.model_conflict_count == 1


def test_api_dry_run():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.mirror_dual_model_verification_service.run_dual_model_verification",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = dm_svc.DualModelVerificationOutcome(
            run_id=None,
            object_type="circuit",
            object_count=1,
            model_a_provider="deepseek",
            model_a_run_id=None,
            model_b_provider="kimi",
            model_b_run_id=None,
            consensus_supported_count=0,
            consensus_rejected_count=0,
            model_conflict_count=0,
            insufficient_information_count=1,
            needs_human_review_count=0,
            result_count=1,
            dry_run=True,
            model_a_system_prompt="sys a",
            model_a_user_prompt="user a",
            model_b_system_prompt="sys b",
            model_b_user_prompt="user b",
            results_preview=[],
            warnings=[],
        )
        resp = client.post(
            "/api/mirror-kg/dual-model-verification/run",
            json={"object_type": "circuit", "object_ids": [str(uuid.uuid4())], "dry_run": True},
        )
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True


def test_task_type_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types["dual_model_verification"] is True


def test_run_task_supports_dual_model_verification():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.mirror_dual_model_verification_service.run_dual_model_verification",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = dm_svc.DualModelVerificationOutcome(
            run_id=uuid.uuid4(),
            object_type="circuit",
            object_count=1,
            model_a_provider="deepseek",
            model_a_run_id=uuid.uuid4(),
            model_b_provider="kimi",
            model_b_run_id=uuid.uuid4(),
            consensus_supported_count=1,
            consensus_rejected_count=0,
            model_conflict_count=0,
            insufficient_information_count=0,
            needs_human_review_count=0,
            result_count=1,
            dry_run=False,
            results_preview=[],
            warnings=[],
        )
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "dual_model_verification",
                "object_type": "circuit",
                "object_ids": [str(uuid.uuid4())],
                "dry_run": False,
            },
        )
        assert resp.status_code == 200
        mock_run.assert_called_once()


def test_planned_task_types_still_501():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    for task_type in ("regions_to_circuits", "macro_clinical_triple_generation"):
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={"task_type": task_type, "provider": "deepseek", "dry_run": True},
        )
        assert resp.status_code == 501
