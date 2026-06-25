"""Debug single-pack connection extraction: complete_text → pack_summaries → progress API."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep
from app.models.llm_extraction import LlmExtractionRun
from app.schemas.llm_composite_workflow import CompositeStepStatus
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_connection_extraction_service import (
    compute_pairs,
    run_same_granularity_connection_extraction,
)
from app.services.llm_connection_parse_diagnostics import build_debug_execution_extra
from app.services.llm_extraction_prompt_engineering import DEFAULT_PAIRS_PER_PACK, pack_pair_records
from app.services.llm_json_utils import raw_response_preview
from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderUsage


MOCK_RAW_TEXT = "这是自然语言 mock raw_text，不是 JSON。"


def _candidate(**kwargs):
    from app.models.candidate import CandidateBrainRegion

    cid = kwargs.pop("id", uuid.uuid4())
    batch_id = kwargs.pop("batch_id", uuid.uuid4())
    resource_id = kwargs.pop("resource_id", uuid.uuid4())
    return CandidateBrainRegion(
        id=cid,
        batch_id=batch_id,
        resource_id=resource_id,
        source_atlas=kwargs.pop("source_atlas", "test_atlas"),
        granularity_level=kwargs.pop("granularity_level", "region"),
        granularity_family=kwargs.pop("granularity_family", "macro"),
        en_name=kwargs.pop("en_name", "Region A"),
        cn_name=kwargs.pop("cn_name", "脑区A"),
        **kwargs,
    )


def _text_result(raw_text: str, *, transport_ok: bool = True, error: str | None = None) -> LlmProviderTextResult:
    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        transport_ok=transport_ok,
        error=error,
        raw_response_preview=raw_response_preview(raw_text),
        response_payload={"json_mode_enabled": True, "raw_response_keys": ["choices"]},
        request_payload_redacted={"model": "deepseek-chat"},
        latency_ms=5,
    )


def _mock_session(candidates):
    stored_runs: list[LlmExtractionRun] = []

    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    async def _execute(_stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = candidates
        result.scalar_one_or_none.return_value = None
        return result

    def _add(obj):
        if isinstance(obj, LlmExtractionRun) and not getattr(obj, "id", None):
            obj.id = uuid.uuid4()
            stored_runs.append(obj)

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=_add)
    session._stored_runs = stored_runs
    return session


def _wire_complete_text(mock_provider, raw_text: str = MOCK_RAW_TEXT):
    mock_provider.complete_text = AsyncMock(return_value=_text_result(raw_text))


def _many_candidates(count: int = 10):
    batch_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    return [
        _candidate(id=uuid.uuid4(), batch_id=batch_id, resource_id=resource_id, en_name=f"R{i}")
        for i in range(count)
    ]


def test_debug_execution_extra_fields():
    extra = build_debug_execution_extra(
        debug_mode=True,
        debug_single_pack=True,
        debug_max_packs=1,
        original_pack_count=114,
        executed_pack_count=1,
    )
    assert extra["planned_pack_count"] == 114
    assert extra["executed_pack_count"] == 1
    assert extra["skipped_debug_pack_count"] == 113
    assert extra["debug_single_pack"] is True


def test_debug_single_pack_executes_one_provider_call_and_captures_preview():
    candidates = _many_candidates(10)
    mock_provider = AsyncMock()
    _wire_complete_text(mock_provider)
    session = _mock_session(candidates)
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c.id for c in candidates],
                dry_run=False,
                create_mirror_records=False,
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary or {}
    assert mock_provider.complete_text.await_count == 1
    assert summary["provider_call_count"] == 1
    assert summary["prompt_sent_count"] == 1
    assert summary["provider_success_count"] == 1
    assert summary["parse_error_count"] == 1
    assert summary["provider_transport_error_count"] == 0
    assert summary["provider_empty_response_count"] == 0
    assert summary["executed_pack_count"] == 1
    assert summary["planned_pack_count"] >= 1
    assert summary["pack_summaries"]
    pack0 = summary["pack_summaries"][0]
    assert "自然语言" in str(pack0.get("raw_response_preview", ""))
    assert pack0.get("parse_error")
    assert not hasattr(mock_provider, "complete_json") or mock_provider.complete_json.await_count == 0


def test_scope_json_persists_pack_summaries_after_commit():
    candidates = _many_candidates(6)
    mock_provider = AsyncMock()
    _wire_complete_text(mock_provider)
    session = _mock_session(candidates)
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c.id for c in candidates],
                dry_run=False,
                create_mirror_records=False,
                debug_single_pack=True,
            )
        )
    assert session._stored_runs
    run = session._stored_runs[0]
    persisted = (run.scope_json or {}).get("execution_summary") or {}
    assert persisted.get("pack_summaries")
    assert persisted["pack_summaries"][0].get("raw_response_preview")


def test_progress_api_exposes_pack_summaries():
    workflow_run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=10,
        pair_count=45,
    )
    conn_step = LlmCompositeWorkflowStep(
        id=uuid.uuid4(),
        workflow_run_id=workflow_run.id,
        step_order=1,
        step_key="extract_connections",
        status=CompositeStepStatus.running.value,
        response_json={},
    )
    summary = {
        "provider_call_count": 1,
        "provider_success_count": 1,
        "parse_error_count": 1,
        "pack_summaries": [{
            "pack_id": 0,
            "raw_response_preview": MOCK_RAW_TEXT,
            "parse_error": "invalid json",
            "parse_error_type": "json_decode_error",
            "response_char_count": len(MOCK_RAW_TEXT),
        }],
    }
    from app.services.llm_connection_parse_diagnostics import merge_provider_audit

    provider_audit = merge_provider_audit(summary)
    conn_step.response_json = {
        "execution_summary": summary,
        "provider_audit": provider_audit,
        "pack_summaries": summary["pack_summaries"],
    }
    workflow_run.result_summary_json = {
        "provider_audit": provider_audit,
        "pack_summaries": summary["pack_summaries"],
        "parse_error_count": 1,
    }
    step_read = composite_svc._step_read(conn_step)
    assert step_read.execution_summary.get("pack_summaries")
    run_read = composite_svc._run_read(workflow_run, [conn_step])
    assert run_read.provider_audit.get("pack_summaries") or run_read.result_summary.get("pack_summaries")


def test_raw_responses_debug_endpoint_returns_pack_summaries():
    workflow_run_id = uuid.uuid4()
    llm_run_id = uuid.uuid4()
    pack_summary = {
        "pack_id": 0,
        "status": "parse_error",
        "response_char_count": len(MOCK_RAW_TEXT),
        "raw_response_preview": MOCK_RAW_TEXT,
        "parse_error": "invalid json",
        "parse_error_type": "json_decode_error",
    }
    workflow_run = LlmCompositeWorkflowRun(
        id=workflow_run_id,
        workflow_type="connection_with_function",
        status="failed",
        dry_run=False,
        candidate_count=10,
        pair_count=45,
        result_summary_json={
            "parse_error_count": 1,
            "pack_summaries": [pack_summary],
        },
    )
    conn_step = LlmCompositeWorkflowStep(
        id=uuid.uuid4(),
        workflow_run_id=workflow_run_id,
        step_order=1,
        step_key="extract_connections",
        status=CompositeStepStatus.failed.value,
        llm_run_id=llm_run_id,
        response_json={
            "execution_summary": {"parse_error_count": 1, "pack_summaries": [pack_summary]},
            "pack_summaries": [pack_summary],
        },
    )
    llm_run = LlmExtractionRun(
        id=llm_run_id,
        task_type="same_granularity_connection_completion",
        provider="deepseek",
        model_name="deepseek-chat",
        scope_type="manual_selection",
        scope_json={"execution_summary": {"pack_summaries": [pack_summary]}},
        status="failed",
        input_count=1,
    )

    session = AsyncMock()

    async def _get(model, pk):
        if model is LlmCompositeWorkflowRun and pk == workflow_run_id:
            return workflow_run
        if model is LlmExtractionRun and pk == llm_run_id:
            return llm_run
        return None

    async def _execute(_stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [conn_step]
        return result

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(side_effect=_execute)

    payload = asyncio.run(
        composite_svc.get_composite_workflow_raw_responses_debug(session, workflow_run_id)
    )
    assert payload is not None
    assert len(payload.items) >= 1
    assert payload.items[0].raw_response_preview
    assert payload.diagnostic_error is None


def test_planned_vs_executed_pack_count_with_many_pairs():
    candidates = _many_candidates(10)
    pairs = compute_pairs(
        [c.id for c in candidates],
        pair_strategy="all_pairs",
        center_candidate_id=None,
    )
    pair_records = [{"pair_id": f"p{i}", "source_region_candidate_id": candidates[0].id, "target_region_candidate_id": candidates[1].id} for i in range(len(pairs))]
    packs = pack_pair_records(pair_records, pairs_per_pack=DEFAULT_PAIRS_PER_PACK)
    assert len(packs) >= 2
    mock_provider = AsyncMock()
    _wire_complete_text(mock_provider)
    session = _mock_session(candidates)
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c.id for c in candidates],
                dry_run=False,
                create_mirror_records=False,
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary or {}
    assert summary["executed_pack_count"] == 1
    assert summary["planned_pack_count"] == len(packs)
    assert summary["skipped_debug_pack_count"] == len(packs) - 1
    assert mock_provider.complete_text.await_count == 1
