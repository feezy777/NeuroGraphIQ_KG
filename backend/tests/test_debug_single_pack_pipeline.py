"""End-to-end debug_single_pack request + provider_audit.pack_summaries return chain tests."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep
from app.schemas.llm_composite_workflow import CompositeStepStatus, CompositeWorkflowRunRequest, CompositeWorkflowType
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_connection_extraction_service import ConnectionExtractionResult, run_same_granularity_connection_extraction
from app.services.llm_connection_parse_diagnostics import build_execution_summary, merge_provider_audit
from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit
from app.services.llm_json_utils import raw_response_preview
from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderUsage


MOCK_RAW = "natural language mock raw text"


def _candidate(**kwargs):
    from app.models.candidate import CandidateBrainRegion

    cid = kwargs.pop("id", uuid.uuid4())
    batch_id = kwargs.pop("batch_id", uuid.uuid4())
    resource_id = kwargs.pop("resource_id", uuid.uuid4())
    return CandidateBrainRegion(
        id=cid,
        batch_id=batch_id,
        resource_id=resource_id,
        source_atlas="test_atlas",
        granularity_level="region",
        granularity_family="macro",
        en_name=kwargs.pop("en_name", "Region A"),
        cn_name=kwargs.pop("cn_name", "脑区A"),
        **kwargs,
    )


def _text_result(raw_text: str) -> LlmProviderTextResult:
    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        transport_ok=True,
        raw_response_preview=raw_response_preview(raw_text),
        response_payload={"json_mode_enabled": True},
        request_payload_redacted={},
    )


def test_normalize_request_forces_debug_max_packs_when_single_pack():
    req = CompositeWorkflowRunRequest(
        workflow_type=CompositeWorkflowType.connection_with_function,
        candidate_ids=[uuid.uuid4(), uuid.uuid4()],
        debug_single_pack=True,
    )
    normalized = composite_svc.normalize_composite_request(req)
    assert normalized.debug_single_pack is True
    assert normalized.debug_max_packs == 1


def test_build_connection_request_forces_debug_max_packs():
    req = CompositeWorkflowRunRequest(
        workflow_type=CompositeWorkflowType.connection_with_function,
        candidate_ids=[uuid.uuid4(), uuid.uuid4()],
        debug_single_pack=True,
        debug_max_packs=99,
    )
    conn_req = composite_svc.build_connection_extraction_request(req)
    assert conn_req.debug_single_pack is True
    assert conn_req.debug_max_packs == 1


def test_finalize_workflow_run_preserves_provider_audit_pack_summaries():
    workflow_run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=10,
        pair_count=45,
        result_summary_json={
            "provider_call_count": 1,
            "parse_error_count": 1,
            "pack_summaries": [{"pack_id": 0, "raw_response_preview": MOCK_RAW}],
            "provider_audit": {"pack_summaries": [{"pack_id": 0, "raw_response_preview": MOCK_RAW}]},
        },
    )
    pack_summary = {
        "pack_id": 0,
        "status": "parse_error",
        "raw_response_preview": MOCK_RAW,
        "parse_error": "bad json",
        "response_char_count": len(MOCK_RAW),
    }
    execution_summary = build_execution_summary(
        ConnectionExecutionAudit(
            provider_call_count=1,
            provider_success_count=1,
            parse_error_count=1,
            pack_count=1,
        ),
        [pack_summary],
        extra={
            "debug_single_pack": True,
            "planned_pack_count": 114,
            "executed_pack_count": 1,
            "skipped_debug_pack_count": 113,
        },
    )
    conn_step = LlmCompositeWorkflowStep(
        id=uuid.uuid4(),
        workflow_run_id=workflow_run.id,
        step_order=1,
        step_key="extract_connections",
        status=CompositeStepStatus.failed.value,
        response_json=composite_svc._connection_step_response_json(
            ConnectionExtractionResult(execution_summary=execution_summary)
        ),
    )
    finalized = asyncio.run(
        composite_svc.finalize_workflow_run(
            AsyncMock(),
            workflow_run,
            [conn_step],
            warnings=[],
            errors=[],
        )
    )
    summary = finalized.result_summary_json
    assert summary.get("provider_audit", {}).get("pack_summaries")
    assert summary["provider_audit"]["pack_summaries"][0]["raw_response_preview"]


def test_run_read_exposes_top_level_provider_audit_pack_summaries():
    workflow_run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status="failed",
        dry_run=False,
        candidate_count=10,
        pair_count=45,
        result_summary_json=composite_svc.build_result_summary(
            LlmCompositeWorkflowRun(
                id=uuid.uuid4(),
                workflow_type="connection_with_function",
                status="failed",
                dry_run=False,
                candidate_count=10,
                pair_count=45,
            ),
            [],
        ),
    )
    pack_summary = {
        "pack_id": 0,
        "raw_response_preview": MOCK_RAW,
        "parse_error": "bad json",
        "parse_error_type": "json_decode_error",
    }
    conn_step = LlmCompositeWorkflowStep(
        id=uuid.uuid4(),
        workflow_run_id=workflow_run.id,
        step_order=1,
        step_key="extract_connections",
        status=CompositeStepStatus.failed.value,
        response_json={
            "execution_summary": {
                "provider_call_count": 1,
                "provider_success_count": 1,
                "parse_error_count": 1,
                "pack_summaries": [pack_summary],
                "provider_audit": merge_provider_audit({"pack_summaries": [pack_summary], "parse_error_count": 1}),
            },
            "pack_summaries": [pack_summary],
        },
    )
    read = composite_svc._run_read(workflow_run, [conn_step])
    assert read.provider_audit.get("pack_summaries")
    assert read.provider_audit["pack_summaries"][0]["raw_response_preview"]


def test_connection_extraction_debug_single_pack_single_provider_call():
    candidates = [_candidate(), _candidate(batch_id=_candidate().batch_id)]
    candidates[1].batch_id = candidates[0].batch_id
    candidates[1].resource_id = candidates[0].resource_id
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=_text_result(MOCK_RAW))
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
    summary = result.execution_summary or {}
    assert mock_provider.complete_text.await_count == 1
    assert summary["provider_call_count"] == 1
    assert summary["provider_success_count"] == 1
    assert summary["parse_error_count"] == 1
    assert summary["executed_pack_count"] == 1
    assert summary["provider_audit"]["pack_summaries"]
    assert MOCK_RAW in str(summary["provider_audit"]["pack_summaries"][0]["raw_response_preview"])


def test_safe_append_workflow_event_swallows_failure():
    from app.services.llm_workflow_event_log import append_workflow_event, safe_append_workflow_event

    session = AsyncMock()
    run_id = uuid.uuid4()
    with patch(
        "app.services.llm_workflow_event_log.append_workflow_event",
        new=AsyncMock(side_effect=RuntimeError("db unavailable")),
    ):
        result = asyncio.run(
            safe_append_workflow_event(
                session,
                run_id,
                event="test_event",
                message="should not raise",
            )
        )
    assert result is None


def test_connection_extraction_log_event_does_not_name_error():
    """_log_event must call safe_append_workflow_event (no bare append_workflow_event NameError)."""
    import inspect

    from app.services import llm_connection_extraction_service as conn_svc

    source = inspect.getsource(conn_svc.run_same_granularity_connection_extraction)
    assert "safe_append_workflow_event" in source
    assert "await append_workflow_event(" not in source
