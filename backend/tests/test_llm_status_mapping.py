"""Persistent DB status vs semantic outcome mapping tests."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.llm_extraction import LlmExtractionRun
from app.schemas.llm_composite_workflow import CompositeStepStatus, CompositeWorkflowStatus
from app.schemas.llm_extraction import LlmRunStatus
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_connection_extraction_service import (
    ConnectionExtractionResult,
    run_same_granularity_connection_extraction,
)
from app.services.llm_extraction_prompt_engineering import finalize_connection_extraction_status, ConnectionExecutionAudit
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage
from app.services.llm_status_utils import (
    PERSISTENT_RUN_STATUSES,
    apply_persistent_run_status,
    is_semantic_failure,
    is_semantic_no_edges,
    map_semantic_outcome_to_persistent_run_status,
)
from app.models.candidate import CandidateBrainRegion


def test_allowed_persistent_run_statuses():
    assert "succeeded" in PERSISTENT_RUN_STATUSES
    assert "failed" in PERSISTENT_RUN_STATUSES
    assert "succeeded_no_edges" not in PERSISTENT_RUN_STATUSES
    assert "failed_parse_error" not in PERSISTENT_RUN_STATUSES


def test_semantic_no_edges_maps_to_succeeded():
    assert map_semantic_outcome_to_persistent_run_status("succeeded_no_edges") == "succeeded"
    assert not is_semantic_failure("succeeded_no_edges")
    assert is_semantic_no_edges("succeeded_no_edges")


def test_semantic_failures_map_to_failed_persistent():
    for semantic in (
        "failed_provider_not_called",
        "failed_parse_error",
        "failed_no_output",
        "failed_provider_empty_response",
    ):
        assert map_semantic_outcome_to_persistent_run_status(semantic) == "failed"
        assert is_semantic_failure(semantic)


def test_apply_persistent_run_status_writes_scope_outcome():
    run = LlmExtractionRun(
        id=uuid.uuid4(),
        task_type="same_granularity_connection_completion",
        provider="deepseek",
        model_name="deepseek-chat",
        scope_type="manual_selection",
        status="running",
        scope_json={},
    )
    persistent, semantic = apply_persistent_run_status(
        run,
        LlmRunStatus.succeeded_no_edges,
        no_connection_count=1,
        created_projection_count=0,
    )
    assert persistent == LlmRunStatus.succeeded
    assert semantic == LlmRunStatus.succeeded_no_edges
    assert run.status == LlmRunStatus.succeeded
    assert run.scope_json["outcome"] == LlmRunStatus.succeeded_no_edges
    assert run.scope_json["display_status"] == LlmRunStatus.succeeded_no_edges
    assert run.scope_json["has_edges"] is False
    assert run.scope_json["no_connection_count"] == 1


def test_finalize_connection_no_edges_semantic():
    audit = ConnectionExecutionAudit(
        pair_count=1,
        pack_count=1,
        provider_call_count=1,
        prompt_sent_count=1,
        provider_success_count=1,
        parsed_no_connection_count=1,
    )
    status, _ = finalize_connection_extraction_status(
        dry_run=False,
        audit=audit,
        processed_pair_count=1,
        unprocessed_pair_count=0,
        connection_count=0,
        no_connection_count=1,
        mirror_output_count=0,
    )
    assert status == LlmRunStatus.succeeded_no_edges


def test_connection_step_not_failed_for_no_edges():
    result = ConnectionExtractionResult(
        status=LlmRunStatus.succeeded_no_edges,
        outcome=LlmRunStatus.succeeded_no_edges,
        display_status=LlmRunStatus.succeeded_no_edges,
        persistent_status=LlmRunStatus.succeeded,
    )
    assert composite_svc._connection_step_status(result) == CompositeStepStatus.succeeded
    override, fn_skip = composite_svc._connection_workflow_overrides(result)
    assert override == CompositeWorkflowStatus.succeeded.value
    assert fn_skip == CompositeStepStatus.skipped_no_projection


def test_connection_step_failed_for_provider_not_called():
    result = ConnectionExtractionResult(
        status=LlmRunStatus.failed_provider_not_called,
        outcome=LlmRunStatus.failed_provider_not_called,
        persistent_status=LlmRunStatus.failed,
    )
    assert composite_svc._connection_step_status(result) == CompositeStepStatus.failed
    override, fn_skip = composite_svc._connection_workflow_overrides(result)
    assert override == CompositeWorkflowStatus.failed.value
    assert fn_skip == CompositeStepStatus.skipped_dependency_failed


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
    captured_run: LlmExtractionRun | None = None

    def _add(obj):
        nonlocal captured_run
        if isinstance(obj, LlmExtractionRun):
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            captured_run = obj

    session.get = AsyncMock(side_effect=lambda _m, pk: next((c for c in candidates if c.id == pk), None))

    async def _execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = candidates
        mock_result.scalar_one_or_none.return_value = None
        return mock_result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session._captured_run = lambda: captured_run
    return session


def test_no_connections_run_persists_succeeded_with_outcome():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    pair_id = make_pair_id(c1.id, c2.id)
    llm_json = {
        "projections": [],
        "no_connections": [{"pair_id": pair_id, "reason": "none"}],
        "warnings": [],
    }
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=json.dumps(llm_json),
        parsed_json=llm_json,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
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
    run = session._captured_run()
    assert result.status == LlmRunStatus.succeeded_no_edges
    assert result.persistent_status == LlmRunStatus.succeeded
    assert run is not None
    assert run.status == LlmRunStatus.succeeded
    assert run.scope_json.get("outcome") == LlmRunStatus.succeeded_no_edges
    assert run.scope_json.get("has_edges") is False
