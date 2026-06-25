"""Same-granularity function extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import FunctionCategory, FunctionRelationType
from app.services.llm_function_extraction_service import (
    CrossAtlasError,
    CrossGranularityError,
    EmptyCandidatesError,
    TooManyCandidatesError,
    normalize_function_candidates,
    run_same_granularity_function_extraction,
    validate_candidates_homogeneous,
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
        raw_name="Frontal_L",
        en_name="Frontal",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def test_empty_candidates_raises():
    with pytest.raises(EmptyCandidatesError):
        asyncio.run(
            run_same_granularity_function_extraction(
                AsyncMock(),
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[],
                dry_run=True,
            )
        )


def test_cross_atlas_rejected():
    c1 = _candidate(source_atlas="AAL3")
    c2 = _candidate(source_atlas="Macro96")
    with pytest.raises(CrossAtlasError):
        validate_candidates_homogeneous([c1, c2])


def test_cross_granularity_rejected():
    c1 = _candidate(granularity_level="macro")
    c2 = _candidate(granularity_level="micro")
    with pytest.raises(CrossGranularityError):
        validate_candidates_homogeneous([c1, c2])


def test_api_empty_candidate_ids():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/same-granularity-functions",
        json={"provider": "deepseek", "candidate_ids": [], "dry_run": True},
    )
    assert resp.status_code == 422


def test_api_accepts_many_candidates_schema():
    """Schema no longer caps candidate_ids count; service may 404 if IDs missing."""
    from app.schemas.llm_extraction import SameGranularityFunctionExtractionRequest

    ids = [uuid.uuid4() for _ in range(96)]
    req = SameGranularityFunctionExtractionRequest(provider="deepseek", candidate_ids=ids, dry_run=True)
    assert len(req.candidate_ids) == 96


def test_normalize_skips_unknown_candidate_id():
    allowed = {uuid.uuid4()}
    parsed = {
        "functions": [{
            "region_candidate_id": str(uuid.uuid4()),
            "function_term": "memory",
            "function_category": "memory",
        }]
    }
    norm, warnings = normalize_function_candidates(parsed, allowed_candidate_ids=allowed)
    assert norm == []
    assert warnings


def test_normalize_skips_empty_function_term():
    rid = uuid.uuid4()
    parsed = {
        "functions": [{
            "region_candidate_id": str(rid),
            "function_term": "  ",
            "function_category": "memory",
        }]
    }
    norm, warnings = normalize_function_candidates(parsed, allowed_candidate_ids={rid})
    assert norm == []
    assert warnings


def test_normalize_coerces_invalid_category_and_relation():
    rid = uuid.uuid4()
    parsed = {
        "functions": [{
            "region_candidate_id": str(rid),
            "function_term": "Memory",
            "function_category": "not_a_category",
            "relation_type": "not_a_relation",
        }]
    }
    norm, warnings = normalize_function_candidates(parsed, allowed_candidate_ids={rid})
    assert len(norm) == 1
    assert norm[0]["function_category"] == FunctionCategory.unknown
    assert norm[0]["relation_type"] == FunctionRelationType.unknown
    assert warnings


def test_max_functions_per_region():
    rid = uuid.uuid4()
    parsed = {
        "functions": [
            {
                "region_candidate_id": str(rid),
                "function_term": f"func{i}",
                "function_category": "cognitive",
            }
            for i in range(5)
        ]
    }
    norm, warnings = normalize_function_candidates(
        parsed, allowed_candidate_ids={rid}, max_functions_per_region=3
    )
    assert len(norm) == 5
    assert any("max_functions_per_region" in w for w in warnings)
    assert any("max_functions_per_region" in w for w in warnings)


def test_dry_run_no_provider_call():
    c1 = _candidate()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c1)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    with patch("app.services.llm_function_extraction_service.get_llm_provider") as mock_prov:
        result = asyncio.run(
            run_same_granularity_function_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id],
                dry_run=True,
            )
        )
        mock_prov.assert_not_called()

    assert result.dry_run is True
    assert result.system_prompt
    assert result.user_prompt
    assert result.run_id is None


def test_mock_deepseek_creates_run_item():
    c1 = _candidate()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c1)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    llm_json = {
        "functions": [{
            "region_candidate_id": str(c1.id),
            "function_term": "memory",
            "function_category": "memory",
            "relation_type": "associated_with",
            "confidence": 0.7,
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

    with patch("app.services.llm_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_function_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch("app.services.llm_function_extraction_service.mirror_kg_service.create_mirror_function") as cmf, \
         patch("app.services.llm_function_extraction_service.mirror_kg_service.create_mirror_triple") as cmt, \
         patch("app.services.llm_function_extraction_service.mirror_kg_service.create_mirror_evidence") as cme:
        mf = MagicMock()
        mf.id = uuid.uuid4()
        cmf.return_value = mf
        cmt.return_value = MagicMock()
        cme.return_value = MagicMock()
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_function_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id],
                dry_run=False,
                create_mirror_records=True,
                create_triples=True,
                create_evidence=True,
            )
        )

    assert result.function_count == 1
    assert result.run_id is not None
    assert result.item_id is not None
    assert result.mirror_function_created_count == 1
    assert result.triple_created_count == 1
    assert result.evidence_created_count == 1
    cmf.assert_called_once()
    cmt.assert_called_once()
    cme.assert_called_once()


def test_mock_kimi_creates_run_item():
    c1 = _candidate()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c1)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    llm_json = {
        "functions": [{
            "region_candidate_id": str(c1.id),
            "function_term": "attention",
            "function_category": "attention",
            "relation_type": "involved_in",
            "confidence": 0.5,
        }]
    }
    response = LlmProviderResponse(
        provider="kimi",
        model="moonshot-v1-8k",
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

    with patch("app.services.llm_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_function_extraction_service.get_kimi_runtime_config") as cfg, \
         patch("app.services.llm_function_extraction_service.mirror_kg_service.create_mirror_function") as cmf:
        cmf.return_value = MagicMock(id=uuid.uuid4())
        cfg.return_value = MagicMock(api_key="sk-test", default_model="moonshot-v1-8k")
        result = asyncio.run(
            run_same_granularity_function_extraction(
                session,
                provider_name="kimi",
                model_name="moonshot-v1-8k",
                candidate_ids=[c1.id],
                dry_run=False,
                create_mirror_records=True,
                create_triples=False,
                create_evidence=False,
            )
        )

    assert result.function_count == 1
    assert result.provider == "kimi"


def test_invalid_json_fails_item():
    c1 = _candidate()
    session = AsyncMock()
    session.get = AsyncMock(return_value=c1)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="not json at all",
        parsed_json=None,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)

    with patch("app.services.llm_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_function_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_function_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id],
                dry_run=False,
                create_mirror_records=False,
            )
        )

    assert result.status == "failed"


def test_duplicate_function_skipped():
    from app.services.llm_function_extraction_service import persist_function_mirror_records
    from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun

    c1 = _candidate()
    run = LlmExtractionRun(
        id=uuid.uuid4(),
        task_type=LlmTaskType.same_granularity_function_completion,
        provider="deepseek",
        model_name="deepseek-chat",
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
        source_atlas=c1.source_atlas,
        resource_id=c1.resource_id,
        batch_id=c1.batch_id,
    )
    item = LlmExtractionItem(id=uuid.uuid4(), run_id=run.id, task_type=run.task_type, item_index=0)
    functions = [{
        "region_candidate_id": str(c1.id),
        "function_term": "Memory",
        "function_term_key": "memory",
        "function_category": "memory",
        "relation_type": "associated_with",
        "confidence": 0.6,
        "evidence_text": "ev",
        "raw": {},
    }]

    session = AsyncMock()
    existing = MagicMock()
    existing.function_term = "memory"
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[uuid.uuid4()])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))),
        ]
    )

    created, skipped, _, _, _ = asyncio.run(
        persist_function_mirror_records(
            session,
            run=run,
            item=item,
            functions=functions,
            candidate_map={c1.id: c1},
            create_triples=False,
            create_evidence=False,
        )
    )
    assert created == 0
    assert skipped == 1


def test_run_task_supports_function_completion():
    from app.main import app

    c1 = _candidate()
    client = TestClient(app)
    with patch(
        "app.services.llm_function_extraction_service.run_same_granularity_function_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        from app.services.llm_function_extraction_service import FunctionExtractionResult

        mock_run.return_value = FunctionExtractionResult(
            run_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            candidate_count=1,
            function_count=1,
            dry_run=True,
            status="succeeded",
        )
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "same_granularity_function_completion",
                "provider": "deepseek",
                "candidate_ids": [str(c1.id)],
                "dry_run": True,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True


def test_task_type_function_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types[LlmTaskType.same_granularity_function_completion] is True
    assert types[LlmTaskType.same_granularity_circuit_completion] is True
    assert types[LlmTaskType.triple_candidate_generation] is False
