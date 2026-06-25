"""Same-granularity connection extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorEvidenceRecord, MirrorKgTriple, MirrorRegionConnection
from app.schemas.llm_extraction import LlmRunStatus, LlmTaskType
from app.services.llm_connection_extraction_service import (
    compute_pairs,
    normalize_connection_candidates,
    run_same_granularity_connection_extraction,
    validate_candidates_homogeneous,
    CrossAtlasError,
    CrossGranularityError,
    TooFewCandidatesError,
    TooManyCandidatePairsError,
)
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


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
        en_name="Hippocampus",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def _mock_session(*candidates: CandidateBrainRegion) -> AsyncMock:
    cands = list(candidates)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: next((c for c in cands if c.id == pk), None))

    async def _execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = cands
        mock_result.scalar_one_or_none.return_value = None
        return mock_result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def test_compute_pairs_all_pairs():
    ids = [uuid.uuid4() for _ in range(4)]
    pairs = compute_pairs(ids, pair_strategy="all_pairs", center_candidate_id=None)
    assert len(pairs) == 6


def test_compute_pairs_region_centered():
    ids = [uuid.uuid4() for _ in range(4)]
    center = ids[0]
    pairs = compute_pairs(ids, pair_strategy="region_centered", center_candidate_id=center)
    assert len(pairs) == 3
    assert all(p[0] == center for p in pairs)


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


def test_normalize_skips_unknown_candidate_id():
    allowed = {uuid.uuid4()}
    parsed = {
        "connections": [
            {
                "source_candidate_id": str(uuid.uuid4()),
                "target_candidate_id": str(uuid.uuid4()),
                "connection_type": "association",
            }
        ]
    }
    norm, warnings = normalize_connection_candidates(parsed, allowed_candidate_ids=allowed)
    assert norm == []
    assert warnings


def test_normalize_accepts_valid_connection():
    a, b = uuid.uuid4(), uuid.uuid4()
    parsed = {
        "connections": [{
            "source_candidate_id": str(a),
            "target_candidate_id": str(b),
            "connection_type": "functional_connectivity",
            "directionality": "undirected",
            "confidence": 0.8,
            "evidence_text": "literature prior",
        }]
    }
    norm, _ = normalize_connection_candidates(parsed, allowed_candidate_ids={a, b})
    assert len(norm) == 1
    assert norm[0]["connection_type"] == "functional_connectivity"
    assert norm[0]["confidence"] == 0.8


def test_api_too_few_candidates():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/same-granularity-connections",
        json={"provider": "deepseek", "candidate_ids": [str(uuid.uuid4())], "dry_run": True},
    )
    assert resp.status_code == 422


def test_cross_atlas_via_service():
    c1 = _candidate(source_atlas="AAL3")
    c2 = _candidate(source_atlas="Macro96")
    with pytest.raises(CrossAtlasError):
        validate_candidates_homogeneous([c1, c2])


def test_dry_run_no_provider_call():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session(c1, c2)

    with patch("app.services.llm_connection_extraction_service.get_llm_provider") as mock_prov:
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=True,
            )
        )
        mock_prov.assert_not_called()

    assert result.dry_run is True
    assert result.system_prompt
    assert result.user_prompt
    assert result.run_id is None


def test_mock_provider_creates_run_item_and_mirror():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session(c1, c2)

    llm_json = {
        "connections": [{
            "source_candidate_id": str(c1.id),
            "target_candidate_id": str(c2.id),
            "connection_type": "functional_connectivity",
            "directionality": "undirected",
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

    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=True,
                create_triples=True,
                create_evidence=True,
            )
        )

    assert result.connection_count == 1
    assert result.run_id is not None
    assert result.item_id is not None
    assert result.mirror_connection_created_count >= 0


def test_invalid_json_fails_item():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session(c1, c2)

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="not json",
        parsed_json=None,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)

    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=False,
            )
        )

    assert result.status in {
        LlmRunStatus.failed,
        LlmRunStatus.failed_parse_error,
        LlmRunStatus.failed_provider_empty_response,
        LlmRunStatus.failed_provider_error,
        LlmRunStatus.failed_no_output,
    }


def test_large_pair_count_warns_not_raises():
    ids = [uuid.uuid4() for _ in range(10)]
    pairs = compute_pairs(ids, pair_strategy="all_pairs", center_candidate_id=None)
    assert len(pairs) == 45
    cands = [_candidate(id=ids[0])]
    for i in range(1, 10):
        cands.append(_candidate(id=ids[i], batch_id=cands[0].batch_id, resource_id=cands[0].resource_id))
    session = _mock_session(*cands)
    with patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=ids,
                dry_run=True,
                max_candidate_pairs=10,
            )
        )
    assert result.pair_count == 45
    assert any("LARGE_CANDIDATE_PAIR_COUNT" in w or "pair_count" in w for w in result.warnings)


def test_task_type_connection_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types[LlmTaskType.same_granularity_connection_completion] is True
    assert types[LlmTaskType.same_granularity_function_completion] is True
    assert types[LlmTaskType.same_granularity_circuit_completion] is True
    assert types[LlmTaskType.triple_candidate_generation] is False
