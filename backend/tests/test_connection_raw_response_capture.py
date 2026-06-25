"""Raw response capture, JSONB persistence, and progress API tests for connection extraction."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.llm_composite_workflow import CompositeStepStatus
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_connection_extraction_service import run_same_granularity_connection_extraction
from app.services.llm_connection_parse_diagnostics import (
    INVARIANT_PACK_SUMMARIES_MISSING,
    INVARIANT_PROVIDER_SUCCESS_INCONSISTENT,
    build_execution_summary,
    merge_provider_audit,
    validate_connection_progress_invariants,
)
from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit
from app.services.llm_json_utils import raw_response_preview
from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderUsage


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


def _mock_session(candidates):
    stored: dict[str, object] = {}

    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    async def _execute(_stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = candidates
        result.scalar_one_or_none.return_value = None
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.refresh.side_effect = lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None
    session._stored = stored
    return session


def _text_result(raw_text: str, *, transport_ok: bool = True, error: str | None = None) -> LlmProviderTextResult:
    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        transport_ok=transport_ok,
        error=error,
        raw_response_preview=raw_response_preview(raw_text),
        response_payload={"json_mode_enabled": True},
        request_payload_redacted={"json_mode_enabled": True},
    )


def _wire_complete_text(mock_provider, side_effect=None, return_value=None):
    if side_effect is not None:
        mock_provider.complete_text = AsyncMock(side_effect=side_effect)
    else:
        mock_provider.complete_text = AsyncMock(return_value=return_value)


def test_natural_language_response_captures_preview_and_audit():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    mock_provider = AsyncMock()
    _wire_complete_text(mock_provider, return_value=_text_result("这是自然语言，不是 JSON"))
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
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary
    assert summary["provider_success_count"] >= 1
    assert summary["parse_error_count"] >= 1
    assert summary["provider_transport_error_count"] == 0
    assert summary["provider_empty_response_count"] == 0
    assert summary["pack_summaries"]
    assert "自然语言" in str(summary["pack_summaries"][0].get("raw_response_preview", ""))
    assert summary["pack_summaries"][0].get("parse_error")


def test_invariants_detect_missing_pack_summaries_and_audit_anomaly():
    bad = ConnectionExecutionAudit(
        provider_call_count=1,
        parse_error_count=1,
    ).to_dict()
    errors = validate_connection_progress_invariants(bad)
    codes = {e["code"] for e in errors}
    assert INVARIANT_PACK_SUMMARIES_MISSING in codes
    assert INVARIANT_PROVIDER_SUCCESS_INCONSISTENT in codes

    audit = ConnectionExecutionAudit(
        provider_call_count=1,
        provider_success_count=1,
        parse_error_count=1,
    )
    traces = [{
        "pack_id": 0,
        "response_received": True,
        "raw_response_preview": "preview",
        "parse_error": "bad json",
        "parse_error_type": "json_decode_error",
    }]
    summary = build_execution_summary(audit, traces)
    assert not validate_connection_progress_invariants(summary)
    provider_audit = merge_provider_audit(summary)
    assert provider_audit["pack_summaries"]


def test_connection_progress_step_read_exposes_pack_summaries():
    from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep

    workflow_run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=2,
        pair_count=1,
    )
    conn_step = LlmCompositeWorkflowStep(
        id=uuid.uuid4(),
        workflow_run_id=workflow_run.id,
        step_order=1,
        step_key="extract_connections",
        status=CompositeStepStatus.running.value,
        response_json={},
    )
    summary = build_execution_summary(
        ConnectionExecutionAudit(
            provider_call_count=1,
            provider_success_count=1,
            parse_error_count=1,
            pack_count=1,
        ),
        [{
            "pack_id": 0,
            "response_received": True,
            "raw_response_preview": "mock preview text",
            "parse_error": "invalid json",
            "parse_error_type": "json_decode_error",
        }],
    )
    from app.services.llm_connection_parse_diagnostics import merge_provider_audit

    provider_audit = merge_provider_audit(summary)
    conn_step.response_json = {
        "execution_summary": summary,
        "provider_audit": provider_audit,
        "pack_summaries": summary.get("pack_summaries", []),
    }
    workflow_run.result_summary_json = {
        "provider_audit": provider_audit,
        "pack_summaries": summary.get("pack_summaries", []),
        "parse_error_count": summary.get("parse_error_count", 0),
    }

    step_read = composite_svc._step_read(conn_step)
    assert step_read.execution_summary.get("pack_summaries")
    assert step_read.execution_summary["pack_summaries"][0]["raw_response_preview"]

    run_read = composite_svc._run_read(workflow_run, [conn_step])
    assert run_read.provider_audit.get("pack_summaries") or run_read.result_summary.get("pack_summaries")


def test_debug_single_pack_limits_provider_calls():
    candidates = [_candidate(), _candidate(batch_id=_candidate().batch_id)]
    candidates[1].batch_id = candidates[0].batch_id
    candidates[1].resource_id = candidates[0].resource_id
    mock_provider = AsyncMock()
    _wire_complete_text(mock_provider, return_value=_text_result("not json"))
    session = _mock_session(candidates)
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[candidates[0].id, candidates[1].id],
                dry_run=False,
                create_mirror_records=False,
                debug_single_pack=True,
            )
        )
    assert mock_provider.complete_text.await_count <= 2
    assert result.execution_summary.get("debug_mode") is True
    assert result.execution_summary.get("pack_summaries")
