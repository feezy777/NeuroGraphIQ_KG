"""Circuit-steps-to-projections extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitStep
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import ConnectionType, Directionality
from app.schemas.mirror_macro_clinical import MirrorCircuitProjectionRole
from app.services.llm_circuit_projection_extraction_service import (
    InvalidMembershipConfigError,
    InvalidStepIdsError,
    MirrorCircuitNotFoundError,
    NoCircuitStepsError,
    build_circuit_steps_to_projections_prompt,
    normalize_projection_candidates,
    run_circuit_steps_to_projections_extraction,
)
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


def _candidate(**kwargs) -> CandidateBrainRegion:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="Macro96",
        source_version="v1",
        raw_name="Hippocampus_L",
        en_name="Hippocampus",
        cn_name="海马",
        laterality="left",
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
        source_version="v1",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="limbic loop",
        circuit_type="limbic_circuit",
        function_association="memory",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _step(circuit: MirrorRegionCircuit, order: int, cand: CandidateBrainRegion, **kwargs) -> MirrorCircuitStep:
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        region_candidate_id=cand.id,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        step_order=order,
        step_name=cand.en_name or "step",
        step_type="region",
        role="source" if order == 1 else "target",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorCircuitStep(**defaults)


def test_api_circuit_not_found():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_circuit_projection_extraction_service.run_circuit_steps_to_projections_extraction",
        new_callable=AsyncMock,
        side_effect=MirrorCircuitNotFoundError("missing"),
    ):
        resp = client.post(
            "/api/llm-extraction/circuit-steps-to-projections",
            json={"provider": "deepseek", "circuit_id": str(uuid.uuid4()), "dry_run": True},
        )
    assert resp.status_code == 404


def test_api_no_steps():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_circuit_projection_extraction_service.run_circuit_steps_to_projections_extraction",
        new_callable=AsyncMock,
        side_effect=NoCircuitStepsError("no steps"),
    ):
        resp = client.post(
            "/api/llm-extraction/circuit-steps-to-projections",
            json={"provider": "deepseek", "circuit_id": str(uuid.uuid4()), "dry_run": True},
        )
    assert resp.status_code == 400


def test_api_membership_requires_projection():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/circuit-steps-to-projections",
        json={
            "provider": "deepseek",
            "circuit_id": str(uuid.uuid4()),
            "create_mirror_records": False,
            "create_memberships": True,
        },
    )
    assert resp.status_code == 400


def test_dry_run_no_provider_no_db():
    circuit = _circuit()
    c1 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    c2 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    s1 = _step(circuit, 1, c1)
    s2 = _step(circuit, 2, c2, role="target")
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.add = MagicMock()

    with patch("app.services.llm_circuit_projection_extraction_service.get_llm_provider") as mock_prov, \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.list_circuit_steps",
             new_callable=AsyncMock,
             return_value=([s1, s2], 2),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.list_mirror_connections",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.load_candidate_map",
             new_callable=AsyncMock,
             return_value={c1.id: c1, c2.id: c2},
         ):
        result = asyncio.run(
            run_circuit_steps_to_projections_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                circuit_id=circuit.id,
                dry_run=True,
            )
        )
        mock_prov.assert_not_called()

    assert result.dry_run is True
    assert result.system_prompt
    assert result.user_prompt
    assert str(s1.id) in result.user_prompt or "Hippocampus" in result.user_prompt
    assert result.run_id is None
    session.add.assert_not_called()


def test_no_steps_raises():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    with patch(
        "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.list_circuit_steps",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        with pytest.raises(NoCircuitStepsError):
            asyncio.run(
                run_circuit_steps_to_projections_extraction(
                    session,
                    provider_name="deepseek",
                    model_name="m",
                    circuit_id=circuit.id,
                    dry_run=True,
                )
            )


def test_invalid_step_ids():
    circuit = _circuit()
    c1 = _candidate()
    s1 = _step(circuit, 1, c1)
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    bad_id = uuid.uuid4()
    with patch(
        "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.list_circuit_steps",
        new_callable=AsyncMock,
        return_value=([s1], 1),
    ):
        with pytest.raises(InvalidStepIdsError):
            asyncio.run(
                run_circuit_steps_to_projections_extraction(
                    session,
                    provider_name="deepseek",
                    model_name="m",
                    circuit_id=circuit.id,
                    step_ids=[bad_id],
                    dry_run=True,
                )
            )


def test_normalize_skips_invalid_projections():
    circuit = _circuit()
    c1 = _candidate()
    c2 = _candidate()
    s1 = _step(circuit, 1, c1)
    s2 = _step(circuit, 2, c2)
    s3 = _step(circuit, 3, _candidate(), region_candidate_id=None)
    parsed = {
        "projections": [
            {
                "source_step_order": 1,
                "target_step_order": 1,
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
                "projection_type": "structural_connection",
                "directionality": "directed",
            },
            {
                "source_step_order": 99,
                "target_step_order": 2,
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
            },
            {
                "source_step_order": 1,
                "target_step_order": 2,
                "source_region_candidate_id": str(uuid.uuid4()),
                "target_region_candidate_id": str(c2.id),
            },
            {
                "source_step_order": 3,
                "target_step_order": 2,
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
            },
            {
                "source_step_order": 1,
                "target_step_order": 2,
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
                "projection_type": "bad_type",
                "directionality": "bad_dir",
                "role_in_circuit": "bad_role",
                "evidence_text": "ev",
            },
        ]
    }
    norm, warnings = normalize_projection_candidates(
        parsed, circuit=circuit, steps=[s1, s2, s3], max_projections=20
    )
    assert len(norm) == 1
    assert norm[0]["projection_type"] == ConnectionType.unknown
    assert norm[0]["directionality"] == Directionality.unknown
    assert norm[0]["role_in_circuit"] == MirrorCircuitProjectionRole.unknown
    assert warnings


def test_normalize_max_projections():
    circuit = _circuit()
    c1 = _candidate()
    c2 = _candidate()
    s1 = _step(circuit, 1, c1)
    s2 = _step(circuit, 2, c2)
    parsed = {
        "projections": [
            {
                "source_step_order": 1,
                "target_step_order": 2,
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
                "projection_type": ConnectionType.structural_connection if i % 2 == 0 else ConnectionType.functional_connectivity,
                "directionality": "directed",
                "evidence_text": "e",
            }
            for i in range(5)
        ]
    }
    norm, warnings = normalize_projection_candidates(
        parsed, circuit=circuit, steps=[s1, s2], max_projections=2
    )
    assert len(norm) == 2
    assert any("max_projections" in w for w in warnings)


def _run_mock_extraction(*, provider_name="deepseek", create_mirror_records=True, create_memberships=None, llm_json=None, raw_invalid=False):
    circuit = _circuit()
    c1 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    c2 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    s1 = _step(circuit, 1, c1)
    s2 = _step(circuit, 2, c2, role="target")

    if create_memberships is None:
        create_memberships = create_mirror_records
    create_triples = create_mirror_records
    create_evidence = create_mirror_records

    if llm_json is None:
        llm_json = {
            "projections": [{
                "source_step_order": 1,
                "target_step_order": 2,
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
                "projection_type": "structural_connection",
                "directionality": "directed",
                "role_in_circuit": "main_path",
                "confidence": 0.7,
                "evidence_text": "test evidence",
            }]
        }

    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {
        circuit.id: circuit,
        c1.id: c1,
        c2.id: c2,
    }.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    response = LlmProviderResponse(
        provider=provider_name,
        model="test-model",
        raw_text="not json" if raw_invalid else json.dumps(llm_json),
        parsed_json=None if raw_invalid else llm_json,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    cfg_patch = "get_deepseek_runtime_config" if provider_name == "deepseek" else "get_kimi_runtime_config"

    created_conns: list = []
    created_mems: list = []
    created_triples: list = []
    created_evidence: list = []

    async def fake_conn(_session, payload):
        row = MagicMock()
        row.id = uuid.uuid4()
        created_conns.append(payload)
        return row

    async def fake_mem(_session, payload):
        row = MagicMock()
        row.id = uuid.uuid4()
        created_mems.append(payload)
        return row

    with patch("app.services.llm_circuit_projection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch(f"app.services.llm_circuit_projection_extraction_service.{cfg_patch}") as cfg, \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.list_circuit_steps",
             new_callable=AsyncMock,
             return_value=([s1, s2], 2),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.list_mirror_connections",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.create_mirror_connection",
             new_callable=AsyncMock,
             side_effect=fake_conn,
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.create_circuit_projection_membership",
             new_callable=AsyncMock,
             side_effect=fake_mem,
         ) as cmem, \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.create_mirror_triple",
             new_callable=AsyncMock,
             side_effect=lambda _s, p: created_triples.append(p) or MagicMock(id=uuid.uuid4()),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.create_mirror_evidence",
             new_callable=AsyncMock,
             side_effect=lambda _s, p: created_evidence.append(p) or MagicMock(id=uuid.uuid4()),
         ):
        cfg.return_value = MagicMock(api_key="sk-test", default_model="test-model")
        result = asyncio.run(
            run_circuit_steps_to_projections_extraction(
                session,
                provider_name=provider_name,
                model_name="test-model",
                circuit_id=circuit.id,
                dry_run=False,
                create_mirror_records=create_mirror_records,
                create_memberships=create_memberships,
                create_triples=create_triples,
                create_evidence=create_evidence,
            )
        )

    return result, created_conns, created_mems, created_triples, created_evidence, cmem


def test_mock_deepseek_creates_run_projection_membership():
    result, conns, mems, triples, evidence, _ = _run_mock_extraction()
    assert result.run_id is not None
    assert result.projection_count == 1
    assert result.mirror_projection_created_count == 1
    assert result.membership_created_count == 1
    assert result.triple_created_count == 4
    assert result.evidence_created_count == 1
    assert conns[0].connection_type == "structural_connection"
    assert mems[0].source_method == "circuit_to_projection"
    assert mems[0].verification_status == "circuit_supported"
    assert mems[0].mirror_status == "llm_suggested"
    assert mems[0].review_status == "pending"
    assert mems[0].promotion_status == "not_promoted"
    assert "macro_clinical_semantic_type" in conns[0].normalized_payload_json


def test_mock_kimi():
    result, _, _, _, _, _ = _run_mock_extraction(provider_name="kimi")
    assert result.status == "succeeded"


def test_invalid_json_fails():
    result, _, _, _, _, _ = _run_mock_extraction(raw_invalid=True)
    assert result.status == "failed"


def test_create_mirror_records_false():
    result, conns, mems, _, _, _ = _run_mock_extraction(
        create_mirror_records=False,
        create_memberships=False,
    )
    assert result.run_id is not None
    assert result.mirror_projection_created_count == 0
    assert conns == []
    assert mems == []


def test_duplicate_projection_reused_for_membership():
    circuit = _circuit()
    c1 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    c2 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    existing = MagicMock()
    existing.id = uuid.uuid4()

    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {
        circuit.id: circuit,
        c1.id: c1,
        c2.id: c2,
    }.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))

    llm_json = {
        "projections": [{
            "source_step_order": 1,
            "target_step_order": 2,
            "source_region_candidate_id": str(c1.id),
            "target_region_candidate_id": str(c2.id),
            "projection_type": "structural_connection",
            "directionality": "directed",
            "evidence_text": "ev",
        }]
    }
    response = LlmProviderResponse(
        provider="deepseek",
        model="m",
        raw_text=json.dumps(llm_json),
        parsed_json=llm_json,
        usage=LlmProviderUsage(1, 1, 2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    s1 = _step(circuit, 1, c1)
    s2 = _step(circuit, 2, c2)

    with patch("app.services.llm_circuit_projection_extraction_service.get_llm_provider") as gp, \
         patch("app.services.llm_circuit_projection_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.list_circuit_steps",
             new_callable=AsyncMock,
             return_value=([s1, s2], 2),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.list_mirror_connections",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.load_candidate_map",
             new_callable=AsyncMock,
             return_value={c1.id: c1, c2.id: c2},
         ), \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_kg_service.create_mirror_connection",
             new_callable=AsyncMock,
         ) as cconn, \
         patch(
             "app.services.llm_circuit_projection_extraction_service.mirror_macro_clinical_service.create_circuit_projection_membership",
             new_callable=AsyncMock,
         ) as cmem:
        gp.return_value.complete_json = AsyncMock(return_value=response)
        cfg.return_value = MagicMock(api_key="sk-test", default_model="m")
        result = asyncio.run(
            run_circuit_steps_to_projections_extraction(
                session,
                provider_name="deepseek",
                model_name="m",
                circuit_id=circuit.id,
                dry_run=False,
            )
        )

    assert result.mirror_projection_skipped_duplicate_count == 1
    assert result.membership_created_count == 1
    cconn.assert_not_called()
    cmem.assert_called_once()
    assert any("EXISTING_PROJECTION_REUSED" in w for w in result.warnings)


def test_task_type_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types[LlmTaskType.circuit_steps_to_projections] is True
    assert types[LlmTaskType.projections_to_circuits] is True


def test_run_task_supports_circuit_steps_to_projections():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.llm_circuit_projection_extraction_service.run_circuit_steps_to_projections_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        from app.services.llm_circuit_projection_extraction_service import CircuitStepsToProjectionsResult

        cid = uuid.uuid4()
        mock_run.return_value = CircuitStepsToProjectionsResult(
            run_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            circuit_id=cid,
            input_step_count=2,
            projection_count=1,
            dry_run=True,
            status="succeeded",
        )
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "circuit_steps_to_projections",
                "provider": "deepseek",
                "circuit_id": str(cid),
                "dry_run": True,
            },
        )
    assert resp.status_code == 200


def test_membership_config_invalid():
    with pytest.raises(InvalidMembershipConfigError):
        asyncio.run(
            run_circuit_steps_to_projections_extraction(
                AsyncMock(),
                provider_name="deepseek",
                model_name="m",
                circuit_id=uuid.uuid4(),
                create_mirror_records=False,
                create_memberships=True,
            )
        )


def test_no_final_or_kg_writes():
    import app.services.llm_circuit_projection_extraction_service as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "create_final" not in source
    assert "create_kg" not in source
