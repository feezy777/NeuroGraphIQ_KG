"""Composite workflow step status update tests (commit_progress duplicate guard)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.llm_composite_workflow import CompositeStepStatus, CompositeWorkflowStatus
from app.schemas.llm_extraction import LlmRunStatus
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_connection_extraction_service import ConnectionExtractionResult
from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit


def _mock_step() -> MagicMock:
    step = MagicMock()
    step.status = CompositeStepStatus.pending.value
    step.started_at = None
    step.completed_at = None
    step.llm_run_id = None
    step.llm_item_id = None
    step.request_json = {}
    step.response_json = {}
    step.created_counts_json = {}
    step.warnings_json = []
    step.errors_json = []
    return step


def test_sanitize_step_update_kwargs_removes_commit_progress():
    cleaned = composite_svc._sanitize_step_update_kwargs({
        "status": CompositeStepStatus.running,
        "commit_progress": True,
    })
    assert "commit_progress" not in cleaned
    assert cleaned["status"] == CompositeStepStatus.running


def test_update_workflow_step_status_explicit_commit_progress():
    async def _run():
        session = AsyncMock()
        session.is_active = True
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        step = _mock_step()
        updated = await composite_svc.update_workflow_step_status(
            session,
            step,
            status=CompositeStepStatus.running,
            commit_progress=True,
        )
        assert updated is step
        session.commit.assert_awaited_once()

    asyncio.run(_run())


def test_update_workflow_step_status_via_us_with_duplicate_commit_progress():
    async def _run():
        session = AsyncMock()
        session.is_active = True
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        step = _mock_step()

        async def _us(**kwargs):
            return await composite_svc.update_workflow_step_status(
                session,
                step,
                commit_progress=True,
                **composite_svc._sanitize_step_update_kwargs(kwargs),
            )

        await _us(
            status=CompositeStepStatus.running,
            commit_progress=True,
            response_json={"provider_call_count": 1},
        )
        assert step.response_json["provider_call_count"] == 1
        session.commit.assert_awaited_once()

    asyncio.run(_run())


def test_connection_progress_callback_does_not_typeerror():
    async def _run():
        session = AsyncMock()
        session.is_active = True
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        conn_step = _mock_step()
        conn_step.step_key = "extract_connections"

        async def _us(step, **kwargs):
            return await composite_svc.update_workflow_step_status(
                session,
                step,
                commit_progress=True,
                **composite_svc._sanitize_step_update_kwargs(kwargs),
            )

        audit = ConnectionExecutionAudit(
            pair_count=10,
            pack_count=1,
            provider_call_count=1,
        )
        llm_run = MagicMock()
        llm_run.id = uuid.uuid4()

        await _us(
            conn_step,
            status=CompositeStepStatus.running,
            llm_run_id=llm_run.id,
            response_json={
                "execution_summary": audit.to_dict(),
                "provider_call_count": 1,
                "pack_count": 1,
                "status": "running",
            },
            commit_progress=True,
        )
        assert conn_step.response_json["provider_call_count"] == 1
        assert "commit_progress" not in conn_step.response_json

    asyncio.run(_run())


def test_connection_with_function_projection_failure_skips_fn_step():
    result = ConnectionExtractionResult(
        run_id=uuid.uuid4(),
        status=LlmRunStatus.failed_provider_not_called,
        provider_call_count=0,
        pair_count=10,
    )
    assert composite_svc._connection_step_status(result) == CompositeStepStatus.failed
    override, fn_skip = composite_svc._connection_workflow_overrides(result)
    assert override == CompositeWorkflowStatus.failed.value
    assert fn_skip == CompositeStepStatus.skipped_dependency_failed


def test_provider_audit_payload_has_no_commit_progress():
    audit = ConnectionExecutionAudit(
        pair_count=4950,
        pack_count=124,
        provider_call_count=1,
    )
    payload = audit.to_dict()
    assert "commit_progress" not in payload
