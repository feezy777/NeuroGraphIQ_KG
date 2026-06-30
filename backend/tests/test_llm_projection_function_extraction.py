"""Projection-to-functions extraction tests (mock provider, no network)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorRegionConnection
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import FunctionCategory, FunctionRelationType
from app.services.llm_projection_function_extraction_service import (
    CrossAtlasProjectionError,
    CrossGranularityProjectionError,
    EmptyProjectionsError,
    InvalidProjectionError,
    ProjectionNotFoundError,
    TooManyProjectionsError,
    build_projection_to_functions_prompt,
    normalize_projection_function_candidates,
    persist_projection_functions,
    run_projection_to_functions_extraction,
    validate_projections_homogeneous,
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
        evidence_text="proj evidence",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def test_empty_projection_ids_api():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/projection-to-functions",
        json={"provider": "deepseek", "projection_ids": [], "dry_run": True},
    )
    assert resp.status_code in (400, 422), f"expected 400 or 422, got {resp.status_code}"


def test_too_many_projection_ids_api():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/projection-to-functions",
        json={
            "provider": "deepseek",
            "projection_ids": [str(uuid.uuid4()) for _ in range(31)],
            "dry_run": True,
        },
    )
    assert resp.status_code in (400, 422), f"expected 400 or 422, got {resp.status_code}"


def test_provider_not_configured():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_projection_function_extraction_service.get_deepseek_runtime_config",
        return_value=MagicMock(api_key="", default_model="deepseek-chat"),
    ):
        resp = client.post(
            "/api/llm-extraction/projection-to-functions",
            json={"provider": "deepseek", "projection_ids": [str(uuid.uuid4())], "dry_run": False},
        )
    assert resp.status_code == 400


def test_projection_not_found():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_projection_function_extraction_service.run_projection_to_functions_extraction",
        new_callable=AsyncMock,
        side_effect=ProjectionNotFoundError("missing"),
    ):
        resp = client.post(
            "/api/llm-extraction/projection-to-functions",
            json={"provider": "deepseek", "projection_ids": [str(uuid.uuid4())], "dry_run": True},
        )
    assert resp.status_code == 404


def test_cross_atlas_rejected():
    c1 = _candidate(source_atlas="AAL3")
    c2 = _candidate(source_atlas="Macro96")
    p1 = _projection(c1, c1)
    p2 = _projection(c2, c2)
    with pytest.raises(CrossAtlasProjectionError):
        validate_projections_homogeneous([p1, p2])


def test_cross_granularity_rejected():
    c1 = _candidate(granularity_level="macro")
    c2 = _candidate(granularity_level="micro")
    p1 = _projection(c1, c1)
    p2 = _projection(c2, c2)
    with pytest.raises(CrossGranularityProjectionError):
        validate_projections_homogeneous([p1, p2])


def test_missing_source_atlas():
    c1 = _candidate()
    p1 = _projection(c1, c1, source_atlas="")
    with pytest.raises(InvalidProjectionError):
        validate_projections_homogeneous([p1])


def test_missing_granularity_level():
    c1 = _candidate()
    p1 = _projection(c1, c1, granularity_level="")
    with pytest.raises(InvalidProjectionError):
        validate_projections_homogeneous([p1])


def test_dry_run_no_provider_no_db():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {
        proj.id: proj,
        c1.id: c1,
        c2.id: c2,
    }.get(pk))
    session.add = MagicMock()

    with patch("app.services.llm_projection_function_extraction_service.get_llm_provider") as mock_prov, \
         patch(
             "app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.list_circuit_projection_memberships",
             new_callable=AsyncMock,
             return_value=([], 0),
         ):
        result = asyncio.run(
            run_projection_to_functions_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[proj.id],
                dry_run=True,
            )
        )
        mock_prov.assert_not_called()

    assert result.dry_run is True
    assert result.system_prompt
    assert result.user_prompt
    assert "Hippocampus" in result.user_prompt or str(proj.id) in result.user_prompt
    assert result.run_id is None
    session.add.assert_not_called()


def test_prompt_includes_projections_and_context():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    circuit_context = [{
        "membership_id": str(uuid.uuid4()),
        "projection_id": str(proj.id),
        "circuit_name": "limbic loop",
        "role_in_circuit": "main_path",
    }]
    system, user, _ = build_projection_to_functions_prompt(
        [proj],
        {c1.id: c1, c2.id: c2},
        circuit_context,
        max_functions_per_projection=5,
    )
    assert system
    assert str(proj.id) in user
    assert "limbic loop" in user
    assert "Hippocampus" in user


def test_normalize_skips_unknown_projection_id():
    allowed = {uuid.uuid4()}
    parsed = {
        "projection_functions": [{
            "projection_id": str(uuid.uuid4()),
            "function_term": "memory",
            "function_category": "memory",
        }]
    }
    norm, warnings = normalize_projection_function_candidates(parsed, allowed_projection_ids=allowed)
    assert norm == []
    assert warnings


def test_normalize_skips_empty_function_term():
    pid = uuid.uuid4()
    parsed = {
        "projection_functions": [{
            "projection_id": str(pid),
            "function_term": "  ",
            "function_category": "memory",
        }]
    }
    norm, warnings = normalize_projection_function_candidates(parsed, allowed_projection_ids={pid})
    assert norm == []
    assert warnings


def test_normalize_coerces_invalid_enums():
    pid = uuid.uuid4()
    parsed = {
        "projection_functions": [{
            "projection_id": str(pid),
            "function_term": "Memory",
            "function_category": "bad_cat",
            "relation_type": "bad_rel",
        }]
    }
    norm, warnings = normalize_projection_function_candidates(parsed, allowed_projection_ids={pid})
    assert len(norm) == 1
    assert norm[0]["function_category"] == FunctionCategory.unknown
    assert norm[0]["relation_type"] == FunctionRelationType.unknown
    assert warnings


def test_max_functions_per_projection():
    pid = uuid.uuid4()
    parsed = {
        "projection_functions": [
            {
                "projection_id": str(pid),
                "function_term": f"func{i}",
                "function_category": "cognitive",
            }
            for i in range(5)
        ]
    }
    norm, warnings = normalize_projection_function_candidates(
        parsed, allowed_projection_ids={pid}, max_functions_per_projection=3
    )
    assert len(norm) == 3
    assert any("max_functions_per_projection" in w for w in warnings)


def test_mock_deepseek_creates_run_item():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {
        proj.id: proj,
        c1.id: c1,
        c2.id: c2,
    }.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
    ))

    llm_json = {
        "projection_functions": [{
            "projection_id": str(proj.id),
            "function_term": "memory encoding",
            "function_category": "memory",
            "relation_type": "participates_in",
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
    pf = MagicMock()
    pf.id = uuid.uuid4()

    with patch("app.services.llm_projection_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_projection_function_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.list_circuit_projection_memberships",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch("app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.create_projection_function", return_value=pf) as cpf, \
         patch("app.services.llm_projection_function_extraction_service.mirror_kg_service.create_mirror_triple") as cmt:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        cmt.return_value = MagicMock()
        result = asyncio.run(
            run_projection_to_functions_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[proj.id],
                dry_run=False,
                create_mirror_records=True,
                create_triples=True,
                create_evidence=True,
            )
        )

    assert result.function_count == 1
    assert result.run_id is not None
    assert result.item_id is not None
    assert result.mirror_projection_function_created_count == 1
    assert result.triple_created_count == 1
    assert any("PROJECTION_FUNCTION_EVIDENCE_STORED_ON_OBJECT_ONLY" in w for w in result.warnings)
    cpf.assert_called_once()
    cmt.assert_called_once()


def test_mock_kimi_creates_run_item():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {proj.id: proj, c1.id: c1, c2.id: c2}.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
    ))

    llm_json = {
        "projection_functions": [{
            "projection_id": str(proj.id),
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

    with patch("app.services.llm_projection_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_projection_function_extraction_service.get_kimi_runtime_config") as cfg, \
         patch(
             "app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.list_circuit_projection_memberships",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch("app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.create_projection_function") as cpf:
        cpf.return_value = MagicMock(id=uuid.uuid4())
        cfg.return_value = MagicMock(api_key="sk-test", default_model="moonshot-v1-8k")
        result = asyncio.run(
            run_projection_to_functions_extraction(
                session,
                provider_name="kimi",
                model_name="moonshot-v1-8k",
                projection_ids=[proj.id],
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
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {proj.id: proj, c1.id: c1, c2.id: c2}.get(pk))
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

    with patch("app.services.llm_projection_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_projection_function_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.list_circuit_projection_memberships",
             new_callable=AsyncMock,
             return_value=([], 0),
         ):
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_projection_to_functions_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[proj.id],
                dry_run=False,
                create_mirror_records=False,
            )
        )

    assert result.status in {"failed", "failed_parse_error"}


def test_create_mirror_records_false_skips_persist():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: {proj.id: proj, c1.id: c1, c2.id: c2}.get(pk))
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    llm_json = {
        "projection_functions": [{
            "projection_id": str(proj.id),
            "function_term": "relay",
            "function_category": "cognitive",
            "relation_type": "associated_with",
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

    with patch("app.services.llm_projection_function_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_projection_function_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.list_circuit_projection_memberships",
             new_callable=AsyncMock,
             return_value=([], 0),
         ), \
         patch("app.services.llm_projection_function_extraction_service.mirror_macro_clinical_service.create_projection_function") as cpf:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_projection_to_functions_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                projection_ids=[proj.id],
                dry_run=False,
                create_mirror_records=False,
                create_triples=False,
                create_evidence=False,
            )
        )
        cpf.assert_not_called()

    assert result.function_count == 1
    assert result.mirror_projection_function_created_count == 0


def test_duplicate_projection_function_skipped():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    proj = _projection(c1, c2)
    run = LlmExtractionRun(
        id=uuid.uuid4(),
        task_type=LlmTaskType.projection_to_functions,
        provider="deepseek",
        model_name="deepseek-chat",
        granularity_level=proj.granularity_level,
        granularity_family=proj.granularity_family,
        source_atlas=proj.source_atlas,
        resource_id=proj.resource_id,
        batch_id=proj.batch_id,
    )
    item = LlmExtractionItem(id=uuid.uuid4(), run_id=run.id, task_type=run.task_type, item_index=0)
    functions = [{
        "projection_id": str(proj.id),
        "function_term": "Memory",
        "function_term_key": "memory",
        "function_category": "memory",
        "relation_type": "associated_with",
        "confidence": 0.6,
        "evidence_text": "ev",
        "normalized_payload_json": {
            "macro_clinical_semantic_type": "projection_function",
            "source_projection_id": str(proj.id),
        },
    }]
    session = AsyncMock()
    existing = MagicMock()
    existing.function_term = "memory"
    id_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[uuid.uuid4()]))))
    row_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing]))))
    session.execute = AsyncMock(side_effect=[id_result, row_result])
    session.get = AsyncMock(return_value=existing)

    created, skipped, _, _, warnings = asyncio.run(
        persist_projection_functions(
            session,
            run=run,
            item=item,
            functions=functions,
            projection_map={proj.id: proj},
            candidate_map={c1.id: c1, c2.id: c2},
            create_triples=False,
            create_evidence=False,
        )
    )
    assert created == 0
    assert skipped == 1
    assert any("EXISTING_PROJECTION_FUNCTION_SKIPPED" in w for w in warnings)


def test_task_types_projection_to_functions_implemented():
    from app.services.llm_extraction_service import list_llm_task_types

    types = {t.task_type: t.implemented for t in list_llm_task_types()}
    assert types["projection_to_functions"] is True


def test_run_task_projection_to_functions():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.services.llm_projection_function_extraction_service.run_projection_to_functions_extraction",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(
            run_id=uuid.uuid4(),
            item_id=uuid.uuid4(),
            task_type=LlmTaskType.projection_to_functions,
            provider="deepseek",
            model_name="deepseek-chat",
            status="succeeded",
            projection_count=1,
            circuit_context_count=0,
            function_count=1,
            mirror_projection_function_created_count=1,
            mirror_projection_function_skipped_duplicate_count=0,
            triple_created_count=0,
            evidence_created_count=0,
            dry_run=False,
            system_prompt=None,
            user_prompt=None,
            warnings=[],
        )
        pid = uuid.uuid4()
        resp = client.post(
            "/api/llm-extraction/run-task",
            json={
                "task_type": "projection_to_functions",
                "provider": "deepseek",
                "projection_ids": [str(pid)],
                "dry_run": False,
            },
        )
    assert resp.status_code == 200
    mock_run.assert_called_once()


def test_planned_task_types_still_501():
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


def test_does_not_write_final_or_kg():
    import inspect

    from app.services import llm_projection_function_extraction_service as svc

    source = inspect.getsource(svc)
    assert "FinalRegion" not in source
    assert "create_final" not in source
    assert "kg_region" not in source
