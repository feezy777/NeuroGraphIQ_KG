"""Circuit-to-steps extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorCircuitRegion, MirrorRegionCircuit
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_macro_clinical import MirrorCircuitStepRole, MirrorCircuitStepType
from app.services.llm_circuit_step_extraction_service import (
    CrossAtlasRegionError,
    InvolvedRegion,
    MirrorCircuitNotFoundError,
    build_circuit_to_steps_prompt,
    normalize_circuit_steps,
    run_circuit_to_steps_extraction,
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
        description="test circuit",
        confidence=0.7,
        evidence_text="evidence",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _involved(cand: CandidateBrainRegion, **kwargs) -> InvolvedRegion:
    defaults = dict(
        region_candidate_id=cand.id,
        en_name=cand.en_name,
        cn_name=cand.cn_name,
        laterality=cand.laterality,
        source_atlas=cand.source_atlas,
        granularity_level=cand.granularity_level,
        granularity_family=cand.granularity_family,
        role="source",
        sort_order=0,
        label=cand.en_name or "region",
    )
    defaults.update(kwargs)
    return InvolvedRegion(**defaults)


def test_api_circuit_not_found():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_circuit_step_extraction_service.run_circuit_to_steps_extraction",
        new_callable=AsyncMock,
        side_effect=MirrorCircuitNotFoundError("missing"),
    ):
        resp = client.post(
            "/api/llm-extraction/circuit-to-steps",
            json={"provider": "deepseek", "circuit_id": str(uuid.uuid4()), "dry_run": True},
        )
    assert resp.status_code == 404


def test_api_provider_not_configured():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    circuit = _circuit()
    with patch(
        "app.services.llm_circuit_step_extraction_service.run_circuit_to_steps_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        from app.services.llm_extraction_service import ProviderNotConfiguredServiceError

        mock_run.side_effect = ProviderNotConfiguredServiceError("deepseek", "not configured")
        resp = client.post(
            "/api/llm-extraction/circuit-to-steps",
            json={"provider": "deepseek", "circuit_id": str(circuit.id), "dry_run": False},
        )
    assert resp.status_code == 400


def test_dry_run_no_provider_no_db_writes():
    circuit = _circuit()
    c1 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    c2 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    cr1 = MirrorCircuitRegion(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        region_candidate_id=c1.id,
        role="source",
        sort_order=0,
    )
    cr2 = MirrorCircuitRegion(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        region_candidate_id=c2.id,
        role="target",
        sort_order=1,
    )

    with patch("app.services.llm_circuit_step_extraction_service.get_llm_provider") as mock_prov, \
         patch(
             "app.services.llm_circuit_step_extraction_service.mirror_kg_service.get_mirror_circuit",
             new_callable=AsyncMock,
         ) as gmc:
        gmc.return_value = (circuit, [cr1, cr2])
        session.get = AsyncMock(side_effect=lambda _m, pk: {
            circuit.id: circuit,
            c1.id: c1,
            c2.id: c2,
        }.get(pk))

        result = asyncio.run(
            run_circuit_to_steps_extraction(
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
    assert "Hippocampus" in result.user_prompt or str(c1.id) in result.user_prompt
    assert result.run_id is None
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_dry_run_prompt_includes_regions():
    circuit = _circuit()
    c1 = _candidate()
    regions = [_involved(c1)]
    system, user, _ = build_circuit_to_steps_prompt(circuit, regions)
    assert system
    assert circuit.circuit_name in user or str(circuit.id) in user
    assert str(c1.id) in user


def test_no_circuit_regions_warning():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)

    with patch(
        "app.services.llm_circuit_step_extraction_service.mirror_kg_service.get_mirror_circuit",
        new_callable=AsyncMock,
        return_value=(circuit, []),
    ):
        result = asyncio.run(
            run_circuit_to_steps_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                circuit_id=circuit.id,
                dry_run=True,
                include_circuit_regions=True,
            )
        )
    assert any("NO_CIRCUIT_REGIONS" in w for w in result.warnings)


def test_cross_atlas_region_rejected():
    circuit = _circuit(source_atlas="Macro96")
    bad = _candidate(source_atlas="AAL3")
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    cr = MirrorCircuitRegion(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        region_candidate_id=bad.id,
        role="source",
        sort_order=0,
    )

    with patch(
        "app.services.llm_circuit_step_extraction_service.mirror_kg_service.get_mirror_circuit",
        new_callable=AsyncMock,
        return_value=(circuit, [cr]),
    ), patch.object(session, "get", new=AsyncMock(side_effect=lambda _m, pk: {
        circuit.id: circuit,
        bad.id: bad,
    }.get(pk))):
        with pytest.raises(CrossAtlasRegionError):
            asyncio.run(
                run_circuit_to_steps_extraction(
                    session,
                    provider_name="deepseek",
                    model_name="deepseek-chat",
                    circuit_id=circuit.id,
                    dry_run=True,
                )
            )


def test_normalize_step_order_missing_and_invalid():
    a = uuid.uuid4()
    regions = [
        InvolvedRegion(
            region_candidate_id=a,
            en_name="Amygdala",
            cn_name=None,
            laterality="left",
            source_atlas="Macro96",
            granularity_level="macro",
            granularity_family="macro_clinical",
            role="source",
            sort_order=0,
            label="Amygdala",
        )
    ]
    parsed = {
        "circuit_steps": [
            {"step_name": "step1", "step_type": "region", "region_candidate_id": str(a)},
            {"step_order": 0, "step_name": "bad", "step_type": "region", "region_candidate_id": str(a)},
            {"step_order": 2, "step_name": "step2", "step_type": "region", "region_candidate_id": str(a)},
            {"step_order": 2, "step_name": "dup2", "step_type": "region", "region_candidate_id": str(a)},
        ]
    }
    norm, warnings = normalize_circuit_steps(parsed, involved_regions=regions, max_steps=12)
    assert len(norm) == 2
    assert norm[0]["step_order"] == 1
    assert norm[1]["step_order"] == 2
    assert any("duplicate step_order" in w for w in warnings)


def test_normalize_unknown_region_skipped():
    a, b = uuid.uuid4(), uuid.uuid4()
    regions = [_involved(_candidate(id=a))]
    parsed = {
        "circuit_steps": [
            {"step_order": 1, "step_name": "ok", "step_type": "region", "region_candidate_id": str(a)},
            {"step_order": 2, "step_name": "bad", "step_type": "region", "region_candidate_id": str(b)},
        ]
    }
    norm, warnings = normalize_circuit_steps(parsed, involved_regions=regions)
    assert len(norm) == 1
    assert any("unknown region_candidate_id" in w for w in warnings)


def test_normalize_coerces_step_type_and_role():
    a = uuid.uuid4()
    regions = [_involved(_candidate(id=a))]
    parsed = {
        "circuit_steps": [{
            "step_order": 1,
            "step_name": "x",
            "step_type": "bad_type",
            "role": "bad_role",
            "region_candidate_id": str(a),
        }]
    }
    norm, warnings = normalize_circuit_steps(parsed, involved_regions=regions)
    assert norm[0]["step_type"] == MirrorCircuitStepType.unknown
    assert norm[0]["role"] == MirrorCircuitStepRole.unknown
    assert warnings


def test_normalize_empty_step_name_fallback():
    a = uuid.uuid4()
    regions = [_involved(_candidate(id=a, en_name="Thalamus"))]
    parsed = {
        "circuit_steps": [{
            "step_order": 1,
            "step_name": "  ",
            "step_type": "region",
            "region_candidate_id": str(a),
        }]
    }
    norm, _ = normalize_circuit_steps(parsed, involved_regions=regions)
    assert norm[0]["step_name"] == "Thalamus"


def test_normalize_max_steps_truncation():
    a = uuid.uuid4()
    regions = [_involved(_candidate(id=a))]
    parsed = {
        "circuit_steps": [
            {
                "step_order": i,
                "step_name": f"s{i}",
                "step_type": "functional_stage",
            }
            for i in range(1, 10)
        ]
    }
    norm, warnings = normalize_circuit_steps(parsed, involved_regions=regions, max_steps=3)
    assert len(norm) == 3
    assert any("max_steps" in w for w in warnings)


def _run_mock_extraction(
    *,
    provider_name: str = "deepseek",
    create_mirror_records: bool = True,
    llm_json: dict | None = None,
    raw_invalid: bool = False,
):
    circuit = _circuit()
    c1 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    c2 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    session = AsyncMock()
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    cr1 = MirrorCircuitRegion(id=uuid.uuid4(), circuit_id=circuit.id, region_candidate_id=c1.id, role="source", sort_order=0)
    cr2 = MirrorCircuitRegion(id=uuid.uuid4(), circuit_id=circuit.id, region_candidate_id=c2.id, role="target", sort_order=1)

    if llm_json is None:
        llm_json = {
            "circuit_steps": [
                {
                    "step_order": 1,
                    "step_name": "hippocampus step",
                    "step_type": "region",
                    "region_candidate_id": str(c1.id),
                    "role": "source",
                    "confidence": 0.8,
                    "evidence_text": "ev1",
                },
                {
                    "step_order": 2,
                    "step_name": "amygdala step",
                    "step_type": "region",
                    "region_candidate_id": str(c2.id),
                    "role": "target",
                    "confidence": 0.7,
                    "evidence_text": "ev2",
                },
            ]
        }

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
    created_steps: list = []

    async def fake_create_step(_session, payload):
        step = MagicMock()
        step.id = uuid.uuid4()
        step.mirror_status = payload.mirror_status
        step.review_status = payload.review_status
        step.promotion_status = payload.promotion_status
        created_steps.append(payload)
        return step

    with patch("app.services.llm_circuit_step_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch(f"app.services.llm_circuit_step_extraction_service.{cfg_patch}") as cfg, \
         patch(
             "app.services.llm_circuit_step_extraction_service.mirror_kg_service.get_mirror_circuit",
             new_callable=AsyncMock,
             return_value=(circuit, [cr1, cr2]),
         ), \
         patch(
             "app.services.llm_circuit_step_extraction_service.mirror_macro_clinical_service.create_circuit_step",
             new_callable=AsyncMock,
             side_effect=fake_create_step,
         ) as ccs:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="test-model")
        session.get = AsyncMock(side_effect=lambda _m, pk: {
            circuit.id: circuit,
            c1.id: c1,
            c2.id: c2,
        }.get(pk))

        result = asyncio.run(
            run_circuit_to_steps_extraction(
                session,
                provider_name=provider_name,
                model_name="test-model",
                circuit_id=circuit.id,
                dry_run=False,
                create_mirror_records=create_mirror_records,
            )
        )

    return result, ccs, created_steps, circuit


def test_mock_deepseek_creates_run_item_and_mirror():
    result, ccs, created, _ = _run_mock_extraction(provider_name="deepseek")
    assert result.run_id is not None
    assert result.item_id is not None
    assert result.step_count == 2
    assert result.mirror_step_created_count == 2
    assert result.status == "succeeded"
    assert ccs.call_count == 2
    assert created[0].mirror_status == "llm_suggested"
    assert created[0].review_status == "pending"
    assert created[0].promotion_status == "not_promoted"


def test_mock_kimi_creates_run_item():
    result, _, _, _ = _run_mock_extraction(provider_name="kimi")
    assert result.run_id is not None
    assert result.status == "succeeded"


def test_invalid_json_fails_item():
    result, _, _, _ = _run_mock_extraction(raw_invalid=True, create_mirror_records=False)
    assert result.status == "failed"


def test_create_mirror_records_false_skips_mirror():
    result, ccs, _, _ = _run_mock_extraction(create_mirror_records=False)
    assert result.run_id is not None
    assert result.step_count == 2
    assert result.mirror_step_created_count == 0
    ccs.assert_not_called()


def test_duplicate_step_order_skipped_on_persist():
    circuit = _circuit()
    c1 = _candidate(batch_id=circuit.batch_id, resource_id=circuit.resource_id)
    session = AsyncMock()
    existing = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    llm_json = {
        "circuit_steps": [{
            "step_order": 1,
            "step_name": "s1",
            "step_type": "region",
            "region_candidate_id": str(c1.id),
            "role": "source",
            "evidence_text": "e",
        }]
    }
    response = LlmProviderResponse(
        provider="deepseek",
        model="m",
        raw_text=json.dumps(llm_json),
        parsed_json=llm_json,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    cr = MirrorCircuitRegion(id=uuid.uuid4(), circuit_id=circuit.id, region_candidate_id=c1.id, role="source", sort_order=0)

    with patch("app.services.llm_circuit_step_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_circuit_step_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_circuit_step_extraction_service.mirror_kg_service.get_mirror_circuit",
             new_callable=AsyncMock,
             return_value=(circuit, [cr]),
         ), \
         patch(
             "app.services.llm_circuit_step_extraction_service.mirror_macro_clinical_service.create_circuit_step",
             new_callable=AsyncMock,
         ) as ccs:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="m")
        session.get = AsyncMock(side_effect=lambda _m, pk: {circuit.id: circuit, c1.id: c1}.get(pk))
        result = asyncio.run(
            run_circuit_to_steps_extraction(
                session,
                provider_name="deepseek",
                model_name="m",
                circuit_id=circuit.id,
                dry_run=False,
                create_mirror_records=True,
            )
        )

    assert result.mirror_step_skipped_duplicate_count == 1
    assert result.mirror_step_created_count == 0
    ccs.assert_not_called()
    assert any("EXISTING_STEP_ORDER" in w for w in result.warnings)


def test_task_type_circuit_to_steps_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types[LlmTaskType.circuit_to_steps] is True
    assert types[LlmTaskType.regions_to_circuits] is False


def test_run_task_supports_circuit_to_steps():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.llm_circuit_step_extraction_service.run_circuit_to_steps_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        from app.services.llm_circuit_step_extraction_service import CircuitToStepsResult

        cid = uuid.uuid4()
        mock_run.return_value = CircuitToStepsResult(
            run_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            circuit_id=cid,
            input_region_count=2,
            step_count=2,
            dry_run=True,
            status="succeeded",
        )
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "circuit_to_steps",
                "provider": "deepseek",
                "circuit_id": str(cid),
                "dry_run": True,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["task_type"] == "circuit_to_steps"


def test_run_task_planned_types_still_501():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    for task_type in ("regions_to_circuits",):
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": task_type,
                "provider": "deepseek",
                "candidate_ids": [str(uuid.uuid4())],
            },
        )
        assert resp.status_code == 501, task_type


def test_no_final_or_kg_writes():
    import app.services.llm_circuit_step_extraction_service as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "create_final" not in source
    assert "create_kg" not in source
    assert "final_region" not in source.lower()
