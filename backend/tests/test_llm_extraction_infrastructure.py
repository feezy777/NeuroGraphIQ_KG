"""LLM Extraction Infrastructure Foundation tests (no external network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.llm_json_utils import (
    normalize_region_field_completion_output,
    parse_llm_json_response,
)
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage
from app.services.llm_extraction_service import (
    BatchTooLargeError,
    build_region_field_prompt,
    list_llm_providers,
    list_llm_task_types,
)


def test_parse_llm_json_response_strips_code_fence():
    raw = '```json\n{"cn_name_suggestion": "测试"}\n```'
    parsed = parse_llm_json_response(raw)
    assert parsed["cn_name_suggestion"] == "测试"


def test_parse_llm_json_response_invalid_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json_response("not json at all")


def test_normalize_region_field_completion_clamps_confidence():
    out = normalize_region_field_completion_output({"confidence": 1.5, "suggested_cn_name": "x"})
    assert out["confidence"] == 1.0
    assert out["cn_name_suggestion"] == "x"


def test_list_llm_task_types_marks_implemented():
    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types["region_field_completion"] is True
    assert types["same_granularity_connection_completion"] is True
    assert types["triple_candidate_generation"] is False
    assert types["regions_to_circuits"] is False
    assert types["circuit_to_steps"] is True
    assert types["circuit_steps_to_projections"] is True
    assert types["circuit_to_functions"] is True
    assert types["projections_to_circuits"] is True
    assert types["dual_model_verification"] is True
    assert types["projection_to_functions"] is True


def test_planned_macro_clinical_task_types_return_501():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    for task_type in (
        "regions_to_circuits",
        "circuit_projection_cross_validation",
        "macro_clinical_triple_generation",
    ):
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": task_type,
                "provider": "deepseek",
                "candidate_ids": [str(uuid.uuid4())],
            },
        )
        assert resp.status_code == 501, task_type
        assert resp.json()["detail"]["code"] == "LLM_TASK_NOT_IMPLEMENTED"


def test_macro_clinical_prompt_defaults_registered():
    from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES

    for key in (
        "regions_to_circuits_v1",
        "circuit_to_steps_v1",
        "circuit_steps_to_projections_v1",
        "projections_to_circuits_v1",
        "circuit_projection_cross_validation_v1",
        "dual_model_verification_v1",
        "region_to_functions_v1",
        "circuit_to_functions_v1",
        "circuit_to_functions_extraction_v1",
        "projection_to_functions_v1",
        "macro_clinical_triple_generation_v1",
        "evidence_uncertainty_review_v1",
    ):
        tpl = DEFAULT_TEMPLATES[key]
        assert tpl.output_schema_json
        assert tpl.task_type
        assert len(tpl.system_prompt) > 20
        assert len(tpl.user_prompt_template) > 20


def test_providers_api_no_api_key(tmp_path, monkeypatch):
    from app.main import app
    from app.services import settings_service

    monkeypatch.setattr(settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json")
    client = TestClient(app)
    resp = client.get("/api/llm-extraction/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert "api_key" not in json.dumps(body).lower()
    names = {p["name"]: p for p in body["providers"]}
    assert "deepseek" in names
    assert "kimi" in names
    assert names["deepseek"]["configured"] is False


def test_task_types_api():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/llm-extraction/task-types")
    assert resp.status_code == 200
    body = resp.json()
    by_type = {t["task_type"]: t["implemented"] for t in body["task_types"]}
    assert by_type["region_field_completion"] is True
    assert by_type["same_granularity_function_completion"] is True
    assert by_type["same_granularity_circuit_completion"] is True


def test_run_task_not_implemented_returns_501():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/llm-extraction/run-task",
        json={
            "task_type": "triple_candidate_generation",
            "provider": "deepseek",
            "candidate_ids": [str(uuid.uuid4())],
        },
    )
    assert resp.status_code == 501
    assert resp.json()["detail"]["code"] == "LLM_TASK_NOT_IMPLEMENTED"


def test_build_region_field_prompt_renders_candidate_fields():
    from app.models.candidate import CandidateBrainRegion

    cand = CandidateBrainRegion(
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
    system, user, prompt_json = build_region_field_prompt(cand, "region_field_completion_v1")
    assert "神经科学" in system
    assert str(cand.id) in user
    assert prompt_json["template_key"] == "region_field_completion_v1"


def test_dry_run_does_not_call_provider(monkeypatch):
    from app.services import llm_extraction_service as svc
    from app.models.candidate import CandidateBrainRegion

    candidate_id = uuid.uuid4()
    candidate = CandidateBrainRegion(
        id=candidate_id,
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="AAL3",
        source_version="v1",
        raw_name="test",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="candidate_created",
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=candidate)
    session.add = lambda obj: None
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    mock_provider = AsyncMock()
    monkeypatch.setattr(svc, "get_llm_provider", lambda name: mock_provider)

    run, items, legacy = asyncio.run(
        svc.run_region_field_completion(
            session,
            provider_name="deepseek",
            model_name="deepseek-chat",
            candidate_ids=[candidate_id],
            prompt_template_key="region_field_completion_v1",
            temperature=0.2,
            max_tokens=2000,
            dry_run=True,
        )
    )

    mock_provider.complete_json.assert_not_called()
    assert run.input_count == 1
    assert len(items) == 1
    assert items[0].normalized_output_json.get("dry_run") is True
    assert legacy == []


def test_mock_deepseek_provider_success_persists_fields(monkeypatch):
    from app.services import llm_extraction_service as svc
    from app.models.candidate import CandidateBrainRegion

    candidate_id = uuid.uuid4()
    candidate = CandidateBrainRegion(
        id=candidate_id,
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="AAL3",
        source_version="v1",
        raw_name="test",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="candidate_created",
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=candidate)
    session.add = lambda obj: None
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    async def fake_persist(session, cand, **kwargs):
        row = AsyncMock()
        row.id = uuid.uuid4()
        return row

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"cn_name_suggestion":"海马","confidence":0.8}',
        parsed_json={"cn_name_suggestion": "海马", "confidence": 0.8},
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=10,
    )

    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    monkeypatch.setattr(svc, "get_llm_provider", lambda name: mock_provider)
    monkeypatch.setattr(
        svc,
        "get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )
    monkeypatch.setattr(svc, "_persist_extraction", fake_persist)

    run, items, legacy = asyncio.run(
        svc.run_region_field_completion(
            session,
            provider_name="deepseek",
            model_name="deepseek-chat",
            candidate_ids=[candidate_id],
            prompt_template_key="region_field_completion_v1",
            temperature=0.2,
            max_tokens=2000,
            dry_run=False,
        )
    )

    assert items[0].raw_response_text is not None
    assert items[0].parsed_response_json["cn_name_suggestion"] == "海马"
    assert items[0].normalized_output_json["cn_name_suggestion"] == "海马"
    assert len(legacy) == 1


def test_invalid_json_item_failed(monkeypatch):
    from app.services import llm_extraction_service as svc
    from app.models.candidate import CandidateBrainRegion

    candidate_id = uuid.uuid4()
    candidate = CandidateBrainRegion(
        id=candidate_id,
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="AAL3",
        source_version="v1",
        raw_name="test",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="candidate_created",
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=candidate)
    session.add = lambda obj: None
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="broken",
        parsed_json=None,
        usage=LlmProviderUsage(),
        finish_reason=None,
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    monkeypatch.setattr(svc, "get_llm_provider", lambda name: mock_provider)
    monkeypatch.setattr(
        svc,
        "get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    _, items, _ = asyncio.run(
        svc.run_region_field_completion(
            session,
            provider_name="deepseek",
            model_name=None,
            candidate_ids=[candidate_id],
            prompt_template_key="region_field_completion_v1",
            temperature=0.2,
            max_tokens=2000,
            dry_run=False,
        )
    )
    assert items[0].status == "failed"
    assert items[0].raw_response_text == "broken"


def test_provider_not_configured_raises():
    from app.services import llm_extraction_service as svc

    session = AsyncMock()
    with patch.object(
        svc,
        "get_deepseek_runtime_config",
        return_value=type("C", (), {"api_key": "", "default_model": "deepseek-chat"})(),
    ):
        with pytest.raises(svc.ProviderNotConfiguredServiceError):
            asyncio.run(
                svc.run_region_field_completion(
                    session,
                    provider_name="deepseek",
                    model_name=None,
                    candidate_ids=[uuid.uuid4()],
                    prompt_template_key="region_field_completion_v1",
                    temperature=0.2,
                    max_tokens=2000,
                    dry_run=False,
                )
            )


def test_list_providers_configured_flags(tmp_path, monkeypatch):
    from app.services import settings_service

    monkeypatch.setattr(settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json")
    settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"api_key": "sk-test-key-1234"}}}
    )
    providers = {p.name: p for p in list_llm_providers()}
    assert providers["deepseek"].configured is True
    assert providers["kimi"].configured is False
