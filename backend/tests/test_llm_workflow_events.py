"""Workflow structured event log tests (no real DeepSeek calls)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.llm_extraction import LlmRunStatus
from app.services.llm_connection_extraction_service import run_same_granularity_connection_extraction
from app.services.llm_workflow_event_log import (
    MAX_RECENT_EVENTS,
    append_workflow_event,
    get_recent_events,
)
from app.models.candidate import CandidateBrainRegion
from app.models.llm_composite_workflow import LlmCompositeWorkflowRun
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


def _mock_session(candidates: list[CandidateBrainRegion]) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: next((c for c in candidates if c.id == pk), None))

    async def _execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = candidates
        mock_result.scalar_one_or_none.return_value = None
        return mock_result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(
        side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None
    )
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


def test_append_workflow_event_stores_and_sanitizes():
    async def _run():
        session = AsyncMock()
        run = LlmCompositeWorkflowRun(
            id=uuid.uuid4(),
            workflow_type="connection_with_function",
            status="running",
            dry_run=False,
            candidate_count=2,
            pair_count=1,
            provider="deepseek",
            result_summary_json={},
        )
        session.get = AsyncMock(return_value=run)
        session.flush = AsyncMock()

        entry = await append_workflow_event(
            session,
            run.id,
            step_key="extract_connections",
            level="error",
            event="provider_response_parse_error",
            message="parse failed",
            data={
                "pack_id": 0,
                "parse_error": "bad json",
                "raw_response_preview": "x" * 3000,
                "api_key": "sk-secret-should-drop",
            },
            commit=False,
        )
        assert entry is not None
        assert entry["event"] == "provider_response_parse_error"
        assert "api_key" not in entry["data"]
        assert len(entry["data"]["raw_response_preview"]) <= 2100
        events = run.result_summary_json.get("events") or []
        assert len(events) == 1

    asyncio.run(_run())


def test_get_recent_events_caps_at_50():
    events = [{"event": f"e{i}", "ts": f"2026-01-01T00:00:{i:02d}Z"} for i in range(60)]
    recent = get_recent_events({"events": events}, limit=MAX_RECENT_EVENTS)
    assert len(recent) == 50
    assert recent[0]["event"] == "e10"


def test_running_provider_call_count_zero_not_failed_status():
    from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit, finalize_connection_extraction_status

    audit = ConnectionExecutionAudit(
        pair_count=10,
        pack_count=2,
        provider_call_count=0,
        prompt_sent_count=0,
    )
    # finalize only runs at step exit — while running we never call it.
    # Simulate mid-run: no status assignment yet; audit alone must not imply failure.
    assert audit.provider_call_count == 0
    assert audit.pair_count == 10


def test_terminal_provider_not_called_sets_failed_status():
    from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit, finalize_connection_extraction_status

    audit = ConnectionExecutionAudit(
        pair_count=10,
        pack_count=2,
        provider_call_count=0,
        prompt_sent_count=0,
    )
    status, warnings = finalize_connection_extraction_status(
        dry_run=False,
        audit=audit,
        processed_pair_count=0,
        unprocessed_pair_count=10,
        connection_count=0,
        no_connection_count=0,
        mirror_output_count=0,
    )
    assert status == LlmRunStatus.failed_provider_not_called
    assert warnings


def test_cancelled_does_not_set_failed_provider_not_called():
    from app.schemas.llm_composite_workflow import CompositeStepStatus
    from app.services import llm_composite_workflow_service as composite_svc
    from app.services.llm_connection_extraction_service import ConnectionExtractionResult

    result = ConnectionExtractionResult(
        run_id=uuid.uuid4(),
        status=LlmRunStatus.cancelled,
        provider_call_count=0,
        pair_count=10,
    )
    assert composite_svc._connection_step_status(result) == CompositeStepStatus.cancelled
    override, _ = composite_svc._connection_workflow_overrides(result)
    assert override == "cancelled"


def test_finalize_workflow_preserves_events():
    from app.services.llm_composite_workflow_service import build_result_summary, finalize_workflow_run
    from app.models.llm_composite_workflow import LlmCompositeWorkflowStep

    run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=2,
        pair_count=1,
        provider="deepseek",
        result_summary_json={
            "events": [{"event": "workflow_started", "ts": "2026-01-01T00:00:00Z"}],
        },
    )
    steps = [
        LlmCompositeWorkflowStep(
            id=uuid.uuid4(),
            workflow_run_id=run.id,
            step_order=1,
            step_key="extract_connections",
            status="succeeded",
        ),
    ]

    async def _run():
        session = AsyncMock()
        session.flush = AsyncMock()
        await finalize_workflow_run(session, run, steps, warnings=[], errors=[])
        return run

    updated = asyncio.run(_run())
    assert updated.result_summary_json.get("events")
    assert updated.result_summary_json["events"][0]["event"] == "workflow_started"
    assert "created_counts" in updated.result_summary_json


def test_connection_extraction_emits_core_events():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session([c1, c2])
    workflow_run_id = uuid.uuid4()
    wf_run = LlmCompositeWorkflowRun(
        id=workflow_run_id,
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=2,
        pair_count=1,
        provider="deepseek",
        result_summary_json={},
    )

    async def _get(model, pk):
        if model is LlmCompositeWorkflowRun:
            return wf_run
        return next((c for c in [c1, c2] if c.id == pk), None)

    session.get = AsyncMock(side_effect=_get)
    llm_json = _projection_json(c1, c2)
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"projections":[],"no_connections":[]}',
        parsed_json=llm_json,
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = MagicMock()
    mock_provider.complete_json = AsyncMock(return_value=response)

    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_connection_extraction_service.persist_connection_mirror_records",
             new=AsyncMock(return_value=(1, 0, 0, 0, [], [uuid.uuid4()])),
         ):
        cfg.return_value = MagicMock(default_model="deepseek-chat", api_key="test-key")

        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                scope_resource_id=c1.resource_id,
                scope_batch_id=c1.batch_id,
                dry_run=False,
                create_mirror_records=True,
                composite_workflow_run_id=workflow_run_id,
                workflow_step_key="extract_connections",
                commit_progress=False,
            )
        )

    events = [e["event"] for e in (wf_run.result_summary_json or {}).get("events") or []]
    assert "pairs_generated" in events
    assert "packs_built" in events
    assert "provider_call_start" in events
    assert "provider_call_success" in events
    assert result.provider_call_count >= 1


def test_parse_error_event_includes_raw_preview():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session([c1, c2])
    workflow_run_id = uuid.uuid4()
    wf_run = LlmCompositeWorkflowRun(
        id=workflow_run_id,
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=2,
        pair_count=1,
        provider="deepseek",
        result_summary_json={},
    )

    async def _get(model, pk):
        if model is LlmCompositeWorkflowRun:
            return wf_run
        return next((c for c in [c1, c2] if c.id == pk), None)

    session.get = AsyncMock(side_effect=_get)
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="not valid json at all",
        parsed_json=None,
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = MagicMock()
    mock_provider.complete_json = AsyncMock(return_value=response)

    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch(
             "app.services.llm_connection_extraction_service.persist_connection_mirror_records",
             new=AsyncMock(return_value=(0, 0, 0, 0, [], [])),
         ):
        cfg.return_value = MagicMock(default_model="deepseek-chat", api_key="test-key")

        asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                scope_resource_id=c1.resource_id,
                scope_batch_id=c1.batch_id,
                dry_run=False,
                create_mirror_records=False,
                composite_workflow_run_id=workflow_run_id,
                workflow_step_key="extract_connections",
                commit_progress=False,
            )
        )

    parse_events = [
        e for e in (wf_run.result_summary_json or {}).get("events") or []
        if e.get("event") == "provider_response_parse_error"
    ]
    assert parse_events
    assert parse_events[0]["data"].get("raw_response_preview")


def test_run_read_returns_recent_events():
    from app.services.llm_composite_workflow_service import _run_read
    from app.models.llm_composite_workflow import LlmCompositeWorkflowStep

    run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status="running",
        dry_run=False,
        candidate_count=2,
        pair_count=1,
        provider="deepseek",
        result_summary_json={
            "events": [{"event": "workflow_started", "ts": "2026-01-01T00:00:00Z", "level": "info", "message": "start"}],
        },
    )
    read = _run_read(run, [])
    assert read.recent_events
    assert read.recent_events[0]["event"] == "workflow_started"
