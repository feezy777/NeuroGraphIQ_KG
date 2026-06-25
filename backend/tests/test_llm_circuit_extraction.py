"""Same-granularity circuit extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorRegionConnection, MirrorRegionFunction
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import CircuitRegionRole, CircuitType, MirrorReviewStatus
from app.services.llm_circuit_extraction_service import (
    CrossAtlasError,
    CrossGranularityError,
    InvalidConnectionContextError,
    InvalidFunctionContextError,
    TooFewCandidatesError,
    TooManyCandidatesError,
    _connection_matches_scope,
    _function_matches_scope,
    _validate_connection_context,
    normalize_circuit_candidates,
    run_same_granularity_circuit_extraction,
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
        raw_name="Hippocampus_L",
        en_name="Hippocampus",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def _connection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        connection_type="functional_connectivity",
        directionality="undirected",
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
        mirror_status="llm_suggested",
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def _function(**kwargs) -> MirrorRegionFunction:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        region_candidate_id=uuid.uuid4(),
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
        mirror_status="llm_suggested",
    )
    defaults.update(kwargs)
    return MirrorRegionFunction(**defaults)


def test_too_few_candidates():
    c1 = _candidate()
    with pytest.raises(TooFewCandidatesError):
        validate_candidates_homogeneous([c1])


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


def test_api_too_few_candidates():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/same-granularity-circuits",
        json={"provider": "deepseek", "candidate_ids": [str(uuid.uuid4())], "dry_run": True},
    )
    assert resp.status_code == 422


def test_api_accepts_many_candidates_schema():
    """Schema no longer caps candidate_ids count."""
    from app.schemas.llm_extraction import SameGranularityCircuitExtractionRequest

    ids = [uuid.uuid4() for _ in range(96)]
    req = SameGranularityCircuitExtractionRequest(provider="deepseek", candidate_ids=ids, dry_run=True)
    assert len(req.candidate_ids) == 96


def test_normalize_skips_empty_circuit_name():
    a, b = uuid.uuid4(), uuid.uuid4()
    parsed = {"circuits": [{"circuit_name": "  ", "involved_region_candidate_ids": [str(a), str(b)]}]}
    norm, warnings = normalize_circuit_candidates(parsed, allowed_candidate_ids={a, b})
    assert norm == []
    assert warnings


def test_normalize_skips_unknown_regions_and_insufficient_count():
    a, b = uuid.uuid4(), uuid.uuid4()
    parsed = {
        "circuits": [{
            "circuit_name": "test circuit",
            "circuit_type": "memory_related",
            "involved_region_candidate_ids": [str(a), str(uuid.uuid4())],
        }]
    }
    norm, warnings = normalize_circuit_candidates(
        parsed, allowed_candidate_ids={a, b}, min_regions_per_circuit=2
    )
    assert norm == []
    assert warnings


def test_normalize_coerces_invalid_circuit_type_and_role():
    a, b = uuid.uuid4(), uuid.uuid4()
    parsed = {
        "circuits": [{
            "circuit_name": "Limbic loop",
            "circuit_type": "bad_type",
            "involved_region_candidate_ids": [str(a), str(b)],
            "region_roles": [{"region_candidate_id": str(a), "role": "bad_role"}],
        }]
    }
    norm, warnings = normalize_circuit_candidates(parsed, allowed_candidate_ids={a, b})
    assert len(norm) == 1
    assert norm[0]["circuit_type"] == CircuitType.unknown
    assert norm[0]["circuit_regions"][0]["role"] == CircuitRegionRole.unknown
    assert warnings


def test_max_circuits_no_truncation():
    a, b = uuid.uuid4(), uuid.uuid4()
    parsed = {
        "circuits": [
            {
                "circuit_name": f"circuit {i}",
                "involved_region_candidate_ids": [str(a), str(b)],
            }
            for i in range(5)
        ]
    }
    norm, warnings = normalize_circuit_candidates(
        parsed, allowed_candidate_ids={a, b}, max_circuits=2
    )
    assert len(norm) == 5


def test_dry_run_no_provider_call():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: c1 if pk == c1.id else c2)

    with patch("app.services.llm_circuit_extraction_service.get_llm_provider") as mock_prov, \
         patch("app.services.llm_circuit_extraction_service.load_connection_context", new_callable=AsyncMock) as lc, \
         patch("app.services.llm_circuit_extraction_service.load_function_context", new_callable=AsyncMock) as lf:
        lc.return_value = ([], [])
        lf.return_value = ([], [])
        result = asyncio.run(
            run_same_granularity_circuit_extraction(
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


def test_mock_deepseek_creates_run_item_and_mirror():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {c1.id: c1, c2.id: c2}.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    llm_json = {
        "circuits": [{
            "circuit_name": "memory limbic circuit",
            "circuit_type": "memory_related",
            "involved_region_candidate_ids": [str(c1.id), str(c2.id)],
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

    with patch("app.services.llm_circuit_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_circuit_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch("app.services.llm_circuit_extraction_service.load_connection_context", new_callable=AsyncMock) as lc, \
         patch("app.services.llm_circuit_extraction_service.load_function_context", new_callable=AsyncMock) as lf, \
         patch("app.services.llm_circuit_extraction_service.mirror_kg_service.create_mirror_circuit") as cmc, \
         patch("app.services.llm_circuit_extraction_service.mirror_kg_service.create_mirror_triple") as cmt, \
         patch("app.services.llm_circuit_extraction_service.mirror_kg_service.create_mirror_evidence") as cme:
        lc.return_value = ([], [])
        lf.return_value = ([], [])
        mc = MagicMock()
        mc.id = uuid.uuid4()
        cmc.return_value = mc
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_circuit_extraction(
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

    assert result.circuit_count == 1
    assert result.run_id is not None
    assert result.mirror_circuit_created_count == 1
    assert result.circuit_region_created_count >= 2
    assert result.triple_created_count >= 2
    assert result.evidence_created_count == 1
    cmc.assert_called_once()


def test_invalid_json_fails_item():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: c1 if pk == c1.id else c2)
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

    with patch("app.services.llm_circuit_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_circuit_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch("app.services.llm_circuit_extraction_service.load_connection_context", new_callable=AsyncMock) as lc, \
         patch("app.services.llm_circuit_extraction_service.load_function_context", new_callable=AsyncMock) as lf:
        lc.return_value = ([], [])
        lf.return_value = ([], [])
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_circuit_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=False,
            )
        )

    assert result.status == "failed"


def test_invalid_connection_context_strict():
    c1 = _candidate()
    conn = _connection(source_atlas="AAL3")
    with pytest.raises(InvalidConnectionContextError):
        _validate_connection_context(
            conn,
            source_atlas=c1.source_atlas,
            granularity_level=c1.granularity_level,
            granularity_family=c1.granularity_family,
            resource_id=c1.resource_id,
            batch_id=c1.batch_id,
            strict=True,
        )


def test_connection_scope_filter():
    c1 = _candidate()
    conn_ok = _connection(
        batch_id=c1.batch_id,
        resource_id=c1.resource_id,
        source_atlas=c1.source_atlas,
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
    )
    conn_bad = _connection(source_atlas="AAL3")
    assert _connection_matches_scope(
        conn_ok,
        source_atlas=c1.source_atlas,
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
        resource_id=c1.resource_id,
        batch_id=c1.batch_id,
    )
    assert not _connection_matches_scope(
        conn_bad,
        source_atlas=c1.source_atlas,
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
        resource_id=c1.resource_id,
        batch_id=c1.batch_id,
    )


def test_function_scope_filter():
    c1 = _candidate()
    fn_ok = _function(
        batch_id=c1.batch_id,
        resource_id=c1.resource_id,
        source_atlas=c1.source_atlas,
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
    )
    assert _function_matches_scope(
        fn_ok,
        source_atlas=c1.source_atlas,
        granularity_level=c1.granularity_level,
        granularity_family=c1.granularity_family,
        resource_id=c1.resource_id,
        batch_id=c1.batch_id,
    )


def test_run_task_supports_circuit_completion():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.services.llm_circuit_extraction_service.run_same_granularity_circuit_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        from app.services.llm_circuit_extraction_service import CircuitExtractionResult

        mock_run.return_value = CircuitExtractionResult(
            run_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            candidate_count=2,
            circuit_count=1,
            dry_run=True,
            status="succeeded",
        )
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "same_granularity_circuit_completion",
                "provider": "deepseek",
                "candidate_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                "dry_run": True,
            },
        )
    assert resp.status_code == 200


def test_task_type_circuit_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types[LlmTaskType.same_granularity_circuit_completion] is True
    assert types[LlmTaskType.triple_candidate_generation] is False
