"""Projections-to-circuits reverse extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import CircuitType
from app.schemas.mirror_macro_clinical import (
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
)
from app.services.llm_projection_circuit_extraction_service import (
    CrossAtlasProjectionError,
    CrossGranularityProjectionError,
    EmptyProjectionsError,
    InvalidMembershipConfigError,
    InvalidProjectionError,
    TooFewProjectionsError,
    build_projection_graph_summary,
    build_projections_to_circuits_prompt,
    normalize_inferred_circuit_candidates,
    run_projections_to_circuits_extraction,
    validate_projections_for_circuit_inference,
)
from app.services.llm_projection_function_extraction_service import ProjectionNotFoundError
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


def _projection(c1: CandidateBrainRegion, c2: CandidateBrainRegion, **kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        resource_id=c1.resource_id,
        batch_id=c1.batch_id,
        source_atlas=c1.source_atlas,
        source_version=c1.source_version,
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
        connection_type="structural_connection",
        directionality="directed",
        confidence=0.7,
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
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
        circuit_name="limbic loop",
        circuit_type=CircuitType.memory_related,
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        normalized_payload_json={
            "involved_region_candidate_ids": [],
            "region_set_key": [],
        },
        raw_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def test_api_too_few_projections():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/projections-to-circuits",
        json={"provider": "deepseek", "projection_ids": [str(uuid.uuid4())], "dry_run": True},
    )
    assert resp.status_code == 422


def test_api_too_many_projections():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/projections-to-circuits",
        json={
            "provider": "deepseek",
            "projection_ids": [str(uuid.uuid4()) for _ in range(101)],
            "dry_run": True,
        },
    )
    assert resp.status_code == 422


def test_too_few_raises():
    c1 = _candidate()
    p1 = _projection(c1, c1)
    with pytest.raises(TooFewProjectionsError):
        validate_projections_for_circuit_inference([p1])


def test_cross_atlas():
    c1 = _candidate(source_atlas="AAL3")
    c2 = _candidate(source_atlas="Macro96")
    with pytest.raises(CrossAtlasProjectionError):
        validate_projections_for_circuit_inference([_projection(c1, c1), _projection(c2, c2)])


def test_dry_run_no_provider():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    p1 = _projection(c1, c2)
    p2 = _projection(c2, c1)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {p1.id: p1, p2.id: p2, c1.id: c1, c2.id: c2}.get(pk))
    session.add = MagicMock()

    with patch("app.services.llm_projection_circuit_extraction_service.get_llm_provider") as mock_prov, \
         patch(
             "app.services.llm_projection_circuit_extraction_service.mirror_kg_service.list_mirror_circuits",
             new_callable=AsyncMock,
             return_value=([], 0),
         ):
        result = asyncio.run(
            run_projections_to_circuits_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[p1.id, p2.id],
                dry_run=True,
            )
        )
        mock_prov.assert_not_called()

    assert result.dry_run is True
    assert result.system_prompt
    assert "node_count" in result.user_prompt or "projection_graph_summary" in result.user_prompt
    assert result.run_id is None
    session.add.assert_not_called()


def test_prompt_includes_graph_summary():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    p1 = _projection(c1, c2)
    p2 = _projection(c2, c1)
    summary = build_projection_graph_summary([p1, p2])
    assert summary["edge_count"] == 2
    assert summary["node_count"] >= 1
    _, user, _ = build_projections_to_circuits_prompt(
        [p1, p2], {c1.id: c1, c2.id: c2}, summary, []
    )
    assert "Hippocampus" in user or str(p1.id) in user


def test_normalize_skips_empty_supporting():
    c1 = _candidate()
    c2 = _candidate()
    p1 = _projection(c1, c2)
    parsed = {
        "inferred_circuits": [{
            "circuit_name": "test circuit",
            "supporting_projection_ids": [],
            "involved_region_candidate_ids": [str(c1.id), str(c2.id)],
        }]
    }
    norm, warnings = normalize_inferred_circuit_candidates(
        parsed,
        allowed_projection_ids={p1.id},
        projection_map={p1.id: p1},
        allowed_region_ids={c1.id, c2.id},
    )
    assert norm == []
    assert warnings


def test_normalize_skips_unknown_projection():
    c1 = _candidate()
    c2 = _candidate()
    p1 = _projection(c1, c2)
    parsed = {
        "inferred_circuits": [{
            "circuit_name": "test",
            "supporting_projection_ids": [str(uuid.uuid4())],
        }]
    }
    norm, warnings = normalize_inferred_circuit_candidates(
        parsed,
        allowed_projection_ids={p1.id},
        projection_map={p1.id: p1},
        allowed_region_ids={c1.id, c2.id},
    )
    assert norm == []
    assert warnings


def test_max_circuits_truncation():
    c1 = _candidate()
    c2 = _candidate()
    p1 = _projection(c1, c2)
    parsed = {
        "inferred_circuits": [
            {
                "circuit_name": f"circuit {i}",
                "supporting_projection_ids": [str(p1.id)],
                "involved_region_candidate_ids": [str(c1.id), str(c2.id)],
            }
            for i in range(5)
        ]
    }
    norm, warnings = normalize_inferred_circuit_candidates(
        parsed,
        allowed_projection_ids={p1.id},
        projection_map={p1.id: p1},
        allowed_region_ids={c1.id, c2.id},
        max_circuits=2,
    )
    assert len(norm) == 2
    assert any("max_circuits" in w for w in warnings)


def test_mock_deepseek_creates_run_item():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    p1 = _projection(c1, c2)
    p2 = _projection(c2, c1)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {p1.id: p1, p2.id: p2, c1.id: c1, c2.id: c2}.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    llm_json = {
        "inferred_circuits": [{
            "circuit_name": "memory loop",
            "circuit_type": "memory_related",
            "supporting_projection_ids": [str(p1.id), str(p2.id)],
            "involved_region_candidate_ids": [str(c1.id), str(c2.id)],
            "possible_step_order": [
                {"step_order": 1, "region_candidate_id": str(c1.id), "role": "source", "step_name": "Hippocampus"},
                {"step_order": 2, "region_candidate_id": str(c2.id), "role": "target"},
            ],
            "function_association": "memory",
            "confidence": 0.6,
            "evidence_text": "test evidence",
        }]
    }
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=json.dumps(llm_json),
        parsed_json=llm_json,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    circuit = MagicMock()
    circuit.id = uuid.uuid4()
    circuit.resource_id = c1.resource_id
    circuit.batch_id = c1.batch_id
    circuit.granularity_level = c1.granularity_level
    circuit.granularity_family = c1.granularity_family
    circuit.source_atlas = c1.source_atlas
    circuit.source_version = c1.source_version
    circuit.circuit_name = "memory loop"

    with patch("app.services.llm_projection_circuit_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_projection_circuit_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_projection_circuit_extraction_service.mirror_kg_service.list_mirror_circuits",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch("app.services.llm_projection_circuit_extraction_service.mirror_kg_service.create_mirror_circuit", return_value=circuit) as cc, \
         patch("app.services.llm_projection_circuit_extraction_service.mirror_macro_clinical_service.create_circuit_step") as cs, \
         patch("app.services.llm_projection_circuit_extraction_service.mirror_macro_clinical_service.create_circuit_projection_membership") as cm, \
         patch("app.services.llm_projection_circuit_extraction_service.mirror_macro_clinical_service.list_circuit_steps", new_callable=AsyncMock, return_value=([], 0)), \
         patch("app.services.llm_projection_circuit_extraction_service.mirror_kg_service.create_mirror_triple") as cmt, \
         patch("app.services.llm_projection_circuit_extraction_service.mirror_kg_service.create_mirror_evidence") as cme:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        cs.return_value = MagicMock(id=uuid.uuid4(), region_candidate_id=c1.id, step_order=1)
        cm.return_value = MagicMock()
        cmt.return_value = MagicMock()
        cme.return_value = MagicMock()
        result = asyncio.run(
            run_projections_to_circuits_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[p1.id, p2.id],
                dry_run=False,
                create_mirror_circuits=True,
                create_circuit_steps=True,
                create_memberships=True,
                create_triples=True,
                create_evidence=True,
            )
        )

    assert result.inferred_circuit_count == 1
    assert result.run_id is not None
    assert result.mirror_circuit_created_count == 1
    cc.assert_called_once()
    assert cm.call_count >= 1
    mem_payload = cm.call_args[0][1]
    assert mem_payload.source_method == MirrorMembershipSourceMethod.projection_to_circuit
    assert mem_payload.verification_status == MirrorMembershipVerificationStatus.projection_supported


def test_invalid_json_fails():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    p1 = _projection(c1, c2)
    p2 = _projection(c2, c1)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {p1.id: p1, p2.id: p2, c1.id: c1, c2.id: c2}.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="not json",
        parsed_json=None,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)

    with patch("app.services.llm_projection_circuit_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_projection_circuit_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_projection_circuit_extraction_service.mirror_kg_service.list_mirror_circuits",
             new_callable=AsyncMock,
             return_value=([], 0),
         ):
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_projections_to_circuits_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[p1.id, p2.id],
                dry_run=False,
                create_mirror_circuits=False,
            )
        )
    assert result.status == "failed"


def test_membership_config_invalid():
    with pytest.raises(InvalidMembershipConfigError):
        asyncio.run(
            run_projections_to_circuits_extraction(
                AsyncMock(),
                provider_name="deepseek",
                model_name="m",
                projection_ids=[uuid.uuid4(), uuid.uuid4()],
                dry_run=True,
                create_mirror_circuits=False,
                reuse_existing_circuits=False,
                create_memberships=True,
            )
        )


def test_task_types_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types["projections_to_circuits"] is True


def test_run_task_supports_projections_to_circuits():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_projection_circuit_extraction_service.run_projections_to_circuits_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(
            run_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            task_type=LlmTaskType.projections_to_circuits,
            provider="deepseek",
            model_name="deepseek-chat",
            status="succeeded",
            projection_count=2,
            existing_circuit_context_count=0,
            inferred_circuit_count=1,
            mirror_circuit_created_count=1,
            mirror_circuit_reused_count=0,
            mirror_circuit_skipped_duplicate_count=0,
            circuit_step_created_count=2,
            circuit_step_skipped_duplicate_count=0,
            membership_created_count=2,
            membership_skipped_duplicate_count=0,
            triple_created_count=0,
            evidence_created_count=0,
            dry_run=False,
            system_prompt=None,
            user_prompt=None,
            warnings=[],
        )
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "projections_to_circuits",
                "provider": "deepseek",
                "projection_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            },
        )
    assert resp.status_code == 200


def test_planned_still_501():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    for task_type in ("circuit_projection_cross_validation",):
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={"task_type": task_type, "provider": "deepseek", "candidate_ids": [str(uuid.uuid4())]},
        )
        assert resp.status_code == 501, task_type


def test_does_not_write_final_or_kg():
    import inspect

    from app.services import llm_projection_circuit_extraction_service as svc

    source = inspect.getsource(svc)
    assert "FinalRegion" not in source
    assert "create_final" not in source
