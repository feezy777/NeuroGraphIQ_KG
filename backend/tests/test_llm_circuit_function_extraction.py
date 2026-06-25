"""Circuit-to-functions extraction tests (Step 10.6.3 — mock provider, no real DeepSeek)."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitFunction
from app.services import mirror_macro_clinical_service
from app.services.llm_circuit_function_extraction_service import (
    MirrorCircuitFunctionsTableMissingError,
    build_compact_circuit_function_context,
    extract_function_seed_from_circuit,
    normalize_circuit_functions,
    parse_circuit_function_extraction_response,
    run_circuit_to_functions_extraction,
    upsert_mirror_circuit_function,
)
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        source_version="v1",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="sensorimotor loop",
        circuit_type="sensorimotor_circuit",
        function_association="sensorimotor integration",
        description="Integrates sensory and motor processing.",
        confidence=Decimal("0.72"),
        evidence_text="Derived from circuit-level association.",
        uncertainty_reason=None,
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _provider_response(**kwargs) -> LlmProviderResponse:
    payload = kwargs.pop("parsed_json", {
        "circuit_functions": [{
            "function_term_en": "sensorimotor integration",
            "function_term_cn": "感觉运动整合",
            "function_domain": "sensorimotor",
            "function_role": "integration",
            "effect_type": None,
            "confidence_score": 0.68,
            "evidence_level": "low",
            "description": "Circuit-level sensorimotor integration.",
            "remark": "Generated from circuit-level function association.",
            "evidence_text": "Derived from circuit-level association.",
        }],
        "warnings": [],
    })
    return LlmProviderResponse(
        provider="mock",
        model="mock-model",
        raw_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=0,
        **kwargs,
    )


def test_extract_function_seed_from_circuit():
    circuit = _circuit()
    seed = extract_function_seed_from_circuit(circuit)
    assert seed is not None
    assert seed["function_term_en"] == "sensorimotor integration"
    assert seed["function_domain"] == "sensorimotor"
    assert seed["function_role"] == "integration"
    assert seed["confidence_score"] == 0.72


def test_extract_function_seed_none_without_signal():
    circuit = _circuit(function_association=None, description=None, evidence_text=None)
    assert extract_function_seed_from_circuit(circuit) is None


def test_build_compact_context_excludes_full_attributes():
    circuit = _circuit(
        normalized_payload_json={
            "attributes": {"huge": "x" * 5000},
            "formal_field_overlay": {"name_cn": "感觉运动环路"},
        }
    )
    ctx = build_compact_circuit_function_context(circuit, related_steps=[], region_summary=[])
    assert "huge" not in json.dumps(ctx)
    assert ctx["name_cn"] == "感觉运动环路"
    assert ctx["function_association"] == "sensorimotor integration"


def test_parse_and_normalize_rejects_legacy_fields():
    parsed = parse_circuit_function_extraction_response({
        "circuit_functions": [{
            "function_term_en": "memory consolidation",
            "function_term_cn": "记忆巩固",
            "function_association": "should be ignored",
            "confidence_score": 1.5,
            "evidence_level": "moderate",
        }]
    })
    functions, warnings = normalize_circuit_functions(parsed)
    assert len(functions) == 1
    assert functions[0]["confidence_score"] == 1.0
    assert any("legacy field ignored" in w for w in warnings)


def test_dry_run_returns_prompt_preview_without_provider():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.add = MagicMock()
    session.flush = AsyncMock()

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch.object(
        mirror_macro_clinical_service,
        "list_circuit_steps",
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch(
        "app.services.llm_circuit_function_extraction_service.mirror_kg_service.get_mirror_circuit",
        new_callable=AsyncMock,
        return_value=(circuit, []),
    ), patch(
        "app.services.llm_circuit_function_extraction_service.get_llm_provider",
    ) as mock_provider:
        import asyncio

        result = asyncio.run(
            run_circuit_to_functions_extraction(
                session,
                circuit_ids=[circuit.id],
                dry_run=True,
            )
        )
    mock_provider.assert_not_called()
    session.add.assert_not_called()
    assert result.dry_run is True
    assert result.prompt_preview is not None
    assert result.prompt_preview["seed_count"] == 1
    assert result.estimated_model_calls == 1
    assert len(result.prompt_preview["examples"]) == 1


def test_dry_run_skips_circuit_without_function_signal():
    circuit = _circuit(function_association=None, description=None, evidence_text=None)
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        import asyncio

        result = asyncio.run(
            run_circuit_to_functions_extraction(
                session,
                circuit_ids=[circuit.id],
                dry_run=True,
            )
        )
    assert result.skipped_count == 1
    assert result.skipped[0]["reason"] == "skipped_no_function_signal"
    assert result.prompt_preview["seed_count"] == 0


def test_dry_run_false_mock_provider_persists_mirror_circuit_function():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    created_row = MirrorCircuitFunction(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        granularity_level=circuit.granularity_level,
        source_atlas=circuit.source_atlas,
        function_term_en="sensorimotor integration",
        function_term_cn="感觉运动整合",
        function_domain="sensorimotor",
        function_role="integration",
        confidence_score=Decimal("0.68"),
        attributes={"source": "circuit_to_functions_extraction"},
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )

    mock_provider = MagicMock()
    mock_provider.complete_json = AsyncMock(return_value=_provider_response())

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch.object(
        mirror_macro_clinical_service,
        "list_circuit_steps",
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch.object(
        mirror_macro_clinical_service,
        "create_circuit_function",
        new_callable=AsyncMock,
        return_value=created_row,
    ), patch(
        "app.services.llm_circuit_function_extraction_service.mirror_kg_service.get_mirror_circuit",
        new_callable=AsyncMock,
        return_value=(circuit, []),
    ), patch(
        "app.services.llm_circuit_function_extraction_service.get_llm_provider",
        return_value=mock_provider,
    ), patch(
        "app.services.llm_circuit_function_extraction_service.get_deepseek_runtime_config",
        return_value=MagicMock(api_key="test-key", default_model="deepseek-chat", enabled=True),
    ):
        import asyncio

        result = asyncio.run(
            run_circuit_to_functions_extraction(
                session,
                circuit_ids=[circuit.id],
                dry_run=False,
            )
        )

    mock_provider.complete_json.assert_called_once()
    assert result.created_count == 1
    assert len(result.created_ids) == 1
    assert result.created_targets[0]["target_type"] == "circuit_function"
    assert result.created_targets[0]["count"] == 1


def test_duplicate_run_does_not_create_second_row():
    circuit = _circuit()
    existing = MirrorCircuitFunction(
        id=uuid.uuid4(),
        circuit_id=circuit.id,
        granularity_level=circuit.granularity_level,
        source_atlas=circuit.source_atlas,
        function_term_en="sensorimotor integration",
        function_term_cn="感觉运动整合",
        function_domain="sensorimotor",
        function_role="integration",
        confidence_score=Decimal("0.68"),
        evidence_level="low",
        description="existing",
        attributes={"source": "circuit_to_functions_extraction", "seed": {}, "compact_context": {}},
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    fn = {
        "function_term_en": "sensorimotor integration",
        "function_term_cn": "感觉运动整合",
        "function_domain": "sensorimotor",
        "function_role": "integration",
        "confidence_score": 0.68,
        "evidence_level": "low",
        "description": "existing",
    }
    seed = extract_function_seed_from_circuit(circuit)
    compact = build_compact_circuit_function_context(circuit)

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([existing], 1),
    ), patch.object(
        mirror_macro_clinical_service,
        "create_circuit_function",
        new_callable=AsyncMock,
    ) as mock_create:
        import asyncio

        action, row_id = asyncio.run(
            upsert_mirror_circuit_function(
                session,
                circuit=circuit,
                parsed_function=fn,
                seed=seed or {},
                compact_context=compact,
                overwrite_policy="fill_missing_only",
                run=None,
                item=None,
                warnings=[],
            )
        )
    mock_create.assert_not_called()
    assert row_id == existing.id
    assert action in ("skipped", "updated")


def test_malformed_provider_json_does_not_raise():
    circuit = _circuit()
    session = AsyncMock()
    session.get = AsyncMock(return_value=circuit)
    session.add = MagicMock()
    session.flush = AsyncMock()

    mock_provider = MagicMock()
    mock_provider.complete_json = AsyncMock(
        return_value=LlmProviderResponse(
            provider="mock",
            model="mock-model",
            raw_text="not json at all",
            parsed_json=None,
            usage=LlmProviderUsage(),
            finish_reason="stop",
            request_payload_redacted={},
            response_payload={},
            latency_ms=0,
        )
    )

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch.object(
        mirror_macro_clinical_service,
        "list_circuit_steps",
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch(
        "app.services.llm_circuit_function_extraction_service.mirror_kg_service.get_mirror_circuit",
        new_callable=AsyncMock,
        return_value=(circuit, []),
    ), patch(
        "app.services.llm_circuit_function_extraction_service.get_llm_provider",
        return_value=mock_provider,
    ), patch(
        "app.services.llm_circuit_function_extraction_service.get_deepseek_runtime_config",
        return_value=MagicMock(api_key="test-key", default_model="deepseek-chat", enabled=True),
    ):
        import asyncio

        result = asyncio.run(
            run_circuit_to_functions_extraction(
                session,
                circuit_ids=[circuit.id],
                dry_run=False,
            )
        )
    assert result.failed_count == 1
    assert result.errors


def test_api_migration_not_initialized_returns_503():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_circuit_function_extraction_service.run_circuit_to_functions_extraction",
        new_callable=AsyncMock,
        side_effect=MirrorCircuitFunctionsTableMissingError("backend/migrations/033_mirror_circuit_functions.sql"),
    ):
        resp = client.post(
            "/api/llm-extraction/circuit-to-functions",
            json={"circuit_ids": [str(uuid.uuid4())], "dry_run": True},
        )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED"


def test_api_dry_run_route_registered():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    circuit = _circuit()
    with patch(
        "app.services.llm_circuit_function_extraction_service.run_circuit_to_functions_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        from app.services.llm_circuit_function_extraction_service import CircuitToFunctionsResult

        mock_run.return_value = CircuitToFunctionsResult(
            status="preview",
            circuit_count=1,
            dry_run=True,
            prompt_preview={"seed_count": 1},
        )
        resp = client.post(
            "/api/llm-extraction/circuit-to-functions",
            json={"circuit_ids": [str(circuit.id)], "dry_run": True},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["target_type"] == "circuit_function"


def test_normalize_decimal_json_serializable():
    parsed = parse_circuit_function_extraction_response({
        "circuit_functions": [{
            "function_term_en": "sensorimotor integration",
            "function_term_cn": "感觉运动整合",
            "confidence_score": 0.875,
            "evidence_level": "low",
        }]
    })
    functions, _ = normalize_circuit_functions(parsed)
    json.dumps(functions)
    assert functions[0]["confidence_score"] == 0.875
