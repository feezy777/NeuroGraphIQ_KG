"""Pause/cancel control status must not be overwritten by worker progress commits."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models.llm_composite_workflow import LlmCompositeWorkflowRun
from app.schemas.llm_composite_workflow import CompositeWorkflowStatus
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_workflow_cancel_registry import mark_pause_requested


def test_sync_workflow_run_control_status_reads_pause_from_db():
    run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status=CompositeWorkflowStatus.running.value,
        dry_run=False,
        candidate_count=2,
        pair_count=1,
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=CompositeWorkflowStatus.pause_requested.value)
        )
    )
    status = asyncio.run(composite_svc.sync_workflow_run_control_status(session, run))
    assert status == CompositeWorkflowStatus.pause_requested.value
    assert run.status == CompositeWorkflowStatus.pause_requested.value


def test_finalize_workflow_run_preserves_pause_requested():
    run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type="connection_with_function",
        status=CompositeWorkflowStatus.running.value,
        dry_run=False,
        candidate_count=2,
        pair_count=1,
        result_summary_json={"pause_requested": True},
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=CompositeWorkflowStatus.pause_requested.value)
        )
    )
    session.flush = AsyncMock()
    finalized = asyncio.run(
        composite_svc.finalize_workflow_run(session, run, [], warnings=[], errors=[])
    )
    assert finalized.status == CompositeWorkflowStatus.pause_requested.value
    assert finalized.result_summary_json.get("pause_requested") is True


def test_pause_endpoint_marks_in_process_registry():
    wf_id = uuid.uuid4()
    asyncio.run(mark_pause_requested(wf_id))
    assert composite_svc.is_pause_requested(wf_id) is True
