"""Connection workflow provider-call audit tests (mock provider only)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.llm_extraction import LlmRunStatus, LlmTaskType
from app.services.llm_connection_extraction_service import (
    compute_pairs,
    run_same_granularity_connection_extraction,
)
from app.services.llm_extraction_prompt_engineering import (
    DEFAULT_PAIRS_PER_PACK,
    pack_pair_records,
)
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES
from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderResponse, LlmProviderUsage
from app.models.candidate import CandidateBrainRegion


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


def _mock_session(candidates: list[CandidateBrainRegion]) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: next((c for c in candidates if c.id == pk), None))

    async def _execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = candidates
        mock_result.scalar_one_or_none.return_value = None
        return mock_result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _projection_json(c1: CandidateBrainRegion, c2: CandidateBrainRegion) -> dict:
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    pair_id = make_pair_id(c1.id, c2.id)
    return {
        "projections": [{
            "pair_id": pair_id,
            "source_region_candidate_id": str(c1.id),
            "target_region_candidate_id": str(c2.id),
            "source_region_name": c1.en_name,
            "target_region_name": c2.en_name,
            "projection_type": "functional",
            "directionality": "unknown",
            "strength_score": 0.5,
            "confidence_score": 0.6,
            "evidence_level": "moderate",
            "description": "test",
            "evidence_text": "test evidence",
        }],
        "no_connections": [],
        "warnings": [],
    }


def _text_result(raw_text: str, *, transport_ok: bool = True, error: str | None = None) -> LlmProviderTextResult:
    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        transport_ok=transport_ok,
        error=error,
        raw_response_preview=raw_text[:2000],
        request_payload_redacted={},
        response_payload={"json_mode_enabled": True},
        latency_ms=5,
    )


def _run_with_mock_provider(
    candidates: list[CandidateBrainRegion],
    *,
    dry_run: bool = False,
    provider_side_effect=None,
    create_mirror_records: bool = True,
):
    session = _mock_session(candidates)
    if provider_side_effect is None:
        llm_json = _projection_json(candidates[0], candidates[1])
        response = _text_result(json.dumps(llm_json))
        mock_provider = AsyncMock()
        mock_provider.complete_text = AsyncMock(return_value=response)
    else:
        mock_provider = AsyncMock()
        mock_provider.complete_text = provider_side_effect

    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c.id for c in candidates],
                dry_run=dry_run,
                create_mirror_records=create_mirror_records,
                create_triples=False,
                create_evidence=False,
            )
        )
    return result, mock_provider


def test_dry_run_false_mock_provider_called():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    result, mock_provider = _run_with_mock_provider([c1, c2], dry_run=False)
    assert mock_provider.complete_text.await_count >= 1
    assert result.provider_call_count >= 1
    assert result.execution_summary["provider_call_count"] >= 1


def test_provider_call_count_in_execution_summary():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    result, _ = _run_with_mock_provider([c1, c2], dry_run=False)
    assert result.execution_summary is not None
    assert result.execution_summary["provider_call_count"] == result.provider_call_count
    assert result.execution_summary["pack_count"] >= 1


def test_provider_not_called_when_no_packs(monkeypatch):
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    monkeypatch.setattr(
        "app.services.llm_connection_extraction_service.pack_pair_records",
        lambda *_a, **_k: [],
    )
    session = _mock_session([c1, c2])
    mock_provider = AsyncMock()
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
    assert mock_provider.complete_text.await_count == 0
    assert result.provider_call_count == 0
    assert result.status == LlmRunStatus.failed_empty_prompt


def test_provider_empty_response_status():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    empty_response = _text_result("", transport_ok=True, error="DeepSeek response missing content")
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=empty_response)
    session = _mock_session([c1, c2])
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
    assert result.provider_call_count >= 1
    assert result.status in {
        LlmRunStatus.failed_provider_empty_response,
        LlmRunStatus.failed_no_output,
        LlmRunStatus.failed_parse_error,
        LlmRunStatus.failed_provider_error,
    }


def test_provider_returns_projection_writes_mirror_and_output_count():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    result, _ = _run_with_mock_provider([c1, c2], dry_run=False, create_mirror_records=True)
    assert result.mirror_connection_created_count >= 1
    assert result.connection_count >= 1
    assert len(result.created_connection_ids) >= 1
    assert result.status == LlmRunStatus.succeeded


def test_all_no_connections_status():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    pair_id = make_pair_id(c1.id, c2.id)
    llm_json = {
        "projections": [],
        "no_connections": [{
            "pair_id": pair_id,
            "source_region_candidate_id": str(c1.id),
            "target_region_candidate_id": str(c2.id),
            "reason": "insufficient evidence",
        }],
        "warnings": [],
    }
    response = _text_result(json.dumps(llm_json))
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
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
    assert result.status == LlmRunStatus.succeeded_no_edges
    assert result.persistent_status == LlmRunStatus.succeeded
    assert result.no_connection_count == 1
    assert result.mirror_connection_created_count == 0


def test_markdown_wrapped_json_parses_not_parse_error():
    """DeepSeek may wrap JSON in ```json fences; parser must handle it and the run
    must succeed rather than counting a parse error."""
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    pair_id = make_pair_id(c1.id, c2.id)
    llm_json = {
        "projections": [{
            "pair_id": pair_id,
            "source_region_candidate_id": str(c1.id),
            "target_region_candidate_id": str(c2.id),
            "projection_type": "functional",
            "directionality": "unknown",
            "confidence_score": 0.6,
            "evidence_level": "moderate",
        }],
        "no_connections": [],
        "warnings": [],
    }
    markdown = "```json\n" + json.dumps(llm_json) + "\n```"
    response = _text_result(markdown)
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
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
    assert result.execution_summary["parse_error_count"] == 0
    assert result.connection_count >= 1


def test_unparseable_response_is_parse_error_not_transport():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    response = _text_result("抱歉，我无法以 JSON 输出，这是一段纯自然语言解释。")
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
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
    summary = result.execution_summary
    assert summary["parse_error_count"] >= 1
    assert summary["provider_transport_error_count"] == 0
    assert summary["provider_success_count"] >= 1  # content was received over the wire
    assert result.status == LlmRunStatus.failed_parse_error
    # raw_response_preview must be saved for debugging.
    assert summary["pack_summaries"][0].get("raw_response_preview")


def test_transport_error_is_not_parse_error():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    response = _text_result("", transport_ok=False, error="DeepSeek returned HTTP 500")
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
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
    summary = result.execution_summary
    assert summary["provider_transport_error_count"] >= 1
    assert summary["parse_error_count"] == 0


def test_connection_prompt_contains_neuroscience_role():
    tpl = DEFAULT_TEMPLATES["same_granularity_connection_completion_v1"]
    assert "神经科学家" in tpl.system_prompt


def test_connection_prompt_enforces_json_only():
    tpl = DEFAULT_TEMPLATES["same_granularity_connection_completion_v1"]
    assert "只输出一个 JSON object" in tpl.system_prompt
    assert "不要 Markdown" in tpl.system_prompt


def test_projection_function_prompt_enforces_json_only():
    tpl = DEFAULT_TEMPLATES["projection_to_functions_v1"]
    assert "只输出一个 JSON object" in tpl.system_prompt


def test_projection_function_prompt_contains_role():
    tpl = DEFAULT_TEMPLATES["projection_to_functions_v1"]
    assert "脑区连接功能专家" in tpl.system_prompt


def test_prompt_preview_has_display_name():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    result, _ = _run_with_mock_provider([c1, c2], dry_run=True)
    assert result.prompt_preview is not None
    assert result.prompt_preview.get("prompt_display_name")


def test_4560_pairs_split_into_packs_without_loss():
    ids = [uuid.uuid4() for _ in range(96)]
    pairs = compute_pairs(ids, pair_strategy="all_pairs", center_candidate_id=None)
    assert len(pairs) == 4560
    records = [{"pair_id": f"{a}::{b}"} for a, b in [(str(p[0]), str(p[1])) for p in pairs]]
    packs = pack_pair_records(records, pairs_per_pack=DEFAULT_PAIRS_PER_PACK)
    assert len(packs) >= 1
    covered = sum(len(p) for p in packs)
    assert covered == 4560


def test_composite_workflow_connection_failure_blocks_function_step():
    from app.schemas.llm_composite_workflow import CompositeStepStatus
    from app.services import llm_composite_workflow_service as composite_svc
    from app.services.llm_connection_extraction_service import ConnectionExtractionResult

    result = ConnectionExtractionResult(
        run_id=uuid.uuid4(),
        status=LlmRunStatus.failed_provider_not_called,
        provider_call_count=0,
        pair_count=10,
    )
    assert composite_svc._connection_step_status(result) == CompositeStepStatus.failed
    override, fn_skip = composite_svc._connection_workflow_overrides(result)
    assert override == "failed"
    assert fn_skip == CompositeStepStatus.skipped_dependency_failed


def test_created_connection_ids_used_for_projection_function_resolution():
    from app.services import llm_composite_workflow_service as composite_svc
    from app.services.llm_connection_extraction_service import ConnectionExtractionResult

    conn_id = uuid.uuid4()
    result = ConnectionExtractionResult(
        run_id=uuid.uuid4(),
        created_connection_ids=[conn_id],
        status=LlmRunStatus.succeeded,
    )

    async def _resolve():
        ids = await composite_svc._resolve_projection_ids(
            AsyncMock(),
            MagicMock(),
            result,
            result.run_id,
        )
        return ids

    ids = asyncio.run(_resolve())
    assert ids == [conn_id]
