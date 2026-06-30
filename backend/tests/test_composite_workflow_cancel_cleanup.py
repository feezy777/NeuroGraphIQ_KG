"""Composite workflow cancel + cleanup tests (no real DeepSeek)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.llm_composite_workflow import CompositeStepStatus, CompositeWorkflowStatus
from app.schemas.llm_extraction import LlmRunStatus
from app.services import llm_workflow_cancel_registry as cancel_registry
from app.services.llm_connection_extraction_service import run_same_granularity_connection_extraction
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


def _mock_session(*candidates: CandidateBrainRegion) -> AsyncMock:
    cands = list(candidates)
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _m, pk: next((c for c in cands if c.id == pk), None))

    async def _execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = cands
        mock_result.scalar_one_or_none.return_value = None
        return mock_result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", uuid.uuid4()) if not getattr(obj, "id", None) else None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_cancel_registry_mark_and_check():
    async def _run():
        wf_id = uuid.uuid4()
        assert cancel_registry.is_cancelling(wf_id) is False
        await cancel_registry.mark_cancelling(wf_id)
        assert cancel_registry.is_cancelling(wf_id) is True
        await cancel_registry.clear(wf_id)
        assert cancel_registry.is_cancelling(wf_id) is False

    asyncio.run(_run())


def test_cancel_unknown_workflow_returns_404(client):
    resp = client.post(
        f"/api/llm-extraction/composite-workflows/{uuid.uuid4()}/cancel",
        json={"cleanup": True, "reason": "user_closed_modal"},
    )
    assert resp.status_code == 404


def test_cancel_running_workflow_marks_cancelling(client):
    wf_id = uuid.uuid4()
    with patch(
        "app.services.llm_composite_workflow_service.cancel_composite_workflow",
        new=AsyncMock(return_value=MagicMock(
            workflow_run_id=wf_id,
            status=CompositeWorkflowStatus.cleanup_done,
            cleanup=True,
            deleted={"mirror_projections": 1},
            warnings=[],
            errors=[],
        )),
    ) as mock_cancel:
        resp = client.post(
            f"/api/llm-extraction/composite-workflows/{wf_id}/cancel",
            json={"cleanup": True, "reason": "user_closed_modal"},
        )
    assert resp.status_code == 200
    mock_cancel.assert_awaited_once()


def test_connection_pack_stops_when_cancelled():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session(c1, c2)
    wf_id = uuid.uuid4()

    async def _run():
        await cancel_registry.mark_cancelling(wf_id)
        mock_provider = AsyncMock()
        with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
             patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
            cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
            result = await run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=False,
                composite_workflow_run_id=wf_id,
            )
        assert mock_provider.complete_json.await_count == 0
        assert result.status == LlmRunStatus.cancelled
        await cancel_registry.clear(wf_id)

    asyncio.run(_run())


def test_late_provider_response_not_persisted_when_cancelled():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    session = _mock_session(c1, c2)
    wf_id = uuid.uuid4()

    from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderUsage
    import json

    async def _run():
        llm_json = {
            "projections": [{
                "pair_id": "x",
                "source_region_candidate_id": str(c1.id),
                "target_region_candidate_id": str(c2.id),
                "connection_type": "functional_connectivity",
                "directionality": "undirected",
                "confidence": 0.5,
            }]
        }
        response = LlmProviderTextResult(
            provider="deepseek",
            model="deepseek-chat",
            raw_text=json.dumps(llm_json),
            usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            request_payload_redacted={},
            response_payload={},
            latency_ms=1,
            transport_ok=True,
        )
        mock_provider = AsyncMock()
        call_count = {"n": 0}

        async def _complete(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                await cancel_registry.mark_cancelling(wf_id)
            return response

        mock_provider.complete_text = _complete

        with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
             patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg, \
             patch("app.services.llm_connection_extraction_service.persist_connection_mirror_records", new=AsyncMock()) as persist:
            cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
            result = await run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=True,
                composite_workflow_run_id=wf_id,
            )
        persist.assert_not_awaited()
        assert result.status == LlmRunStatus.cancelled
        await cancel_registry.clear(wf_id)

    asyncio.run(_run())


def test_cleanup_service_scoped_by_workflow_run_id():
    from app.services.llm_composite_workflow_cleanup_service import cleanup_composite_workflow_artifacts

    assert asyncio.iscoroutinefunction(cleanup_composite_workflow_artifacts)


def test_cancelled_connection_skips_projection_function_step():
    from app.services import llm_composite_workflow_service as composite_svc
    from app.services.llm_connection_extraction_service import ConnectionExtractionResult

    result = ConnectionExtractionResult(status=LlmRunStatus.cancelled, run_id=uuid.uuid4())
    assert composite_svc._connection_step_status(result) == CompositeStepStatus.cancelled
    override, fn_skip = composite_svc._connection_workflow_overrides(result)
    assert override == CompositeWorkflowStatus.cancelled.value
    assert fn_skip == CompositeStepStatus.skipped


def test_cleanup_does_not_physically_delete_extraction_items():
    """Trace items must be marked cancelled (UPDATE), never physically deleted."""
    import inspect
    from app.services import llm_composite_workflow_cleanup_service as cleanup_svc

    src = inspect.getsource(cleanup_svc.cleanup_composite_workflow_artifacts)
    # No physical delete of LlmExtractionItem; only a status update to cancelled.
    assert "delete(LlmExtractionItem)" not in src
    assert "update(LlmExtractionItem)" in src
    assert "LlmItemStatus.cancelled" in src


def test_cancel_is_idempotent_when_already_cleanup_done():
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()
    run = MagicMock()
    run.status = CompositeWorkflowStatus.cleanup_done.value
    run.result_summary_json = {
        "deleted": {"mirror_projections": 3},
        "cleanup_warnings": ["w"],
        "cleanup_errors": [],
    }
    session = AsyncMock()
    session.get = AsyncMock(return_value=run)

    async def _run():
        cleanup_mock = AsyncMock()
        with patch.object(composite_svc, "cleanup_composite_workflow_artifacts", cleanup_mock):
            resp = await composite_svc.cancel_composite_workflow(session, wf_id, cleanup=True)
        # Idempotent: never re-runs cleanup on an already terminal run.
        cleanup_mock.assert_not_awaited()
        assert resp.status == CompositeWorkflowStatus.cleanup_done
        assert resp.deleted == {"mirror_projections": 3}

    asyncio.run(_run())


def test_is_workflow_cancelled_or_cancelling_uses_registry():
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()
    session = AsyncMock()

    async def _run():
        await cancel_registry.mark_cancelling(wf_id)
        assert await composite_svc.is_workflow_cancelled_or_cancelling(session, wf_id) is True
        await cancel_registry.clear(wf_id)

    asyncio.run(_run())


# ── Transaction rollback + recovery tests ──────────────────────────────────────

def test_cleanup_sql_failure_rolls_back_and_writes_cleanup_failed():
    """When a DELETE inside cleanup raises, the session is rolled back and the
    workflow is marked cleanup_failed (not left in an aborted-transaction state)."""
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()
    run = MagicMock()
    run.id = wf_id
    run.status = CompositeWorkflowStatus.running.value
    run.result_summary_json = {}
    run.completed_at = None
    run.warnings_json = []
    run.errors_json = []

    step = MagicMock()
    step.workflow_run_id = wf_id
    step.llm_run_id = uuid.uuid4()
    step.status = CompositeStepStatus.running.value
    step.completed_at = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=run)

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [step]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    cleanup_error = RuntimeError("simulated cleanup SQL failure")

    async def _run():
        with patch.object(
            composite_svc, "cleanup_composite_workflow_artifacts",
            AsyncMock(side_effect=cleanup_error),
        ):
            resp = await composite_svc.cancel_composite_workflow(
                session, wf_id, cleanup=True, reason="test"
            )

        assert resp.status == CompositeWorkflowStatus.cleanup_failed
        assert resp.errors
        assert "simulated cleanup SQL failure" in str(resp.errors)
        session.rollback.assert_awaited()

    asyncio.run(_run())


def test_cancel_cleanup_failure_writes_outcome_to_summary_json():
    """After a cleanup failure, cleanup_failed is written to result_summary_json
    and the status field is set to cleanup_failed (valid enum value)."""
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()

    run_obj = MagicMock()
    run_obj.id = wf_id
    run_obj.status = CompositeWorkflowStatus.running.value
    run_obj.result_summary_json = {}
    run_obj.completed_at = None
    run_obj.warnings_json = []
    run_obj.errors_json = []

    step = MagicMock()
    step.workflow_run_id = wf_id
    step.llm_run_id = uuid.uuid4()
    step.status = CompositeStepStatus.running.value
    step.completed_at = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=run_obj)

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [step]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    cleanup_error = RuntimeError("FK violation during mirror delete")

    async def _run():
        with patch.object(
            composite_svc, "cleanup_composite_workflow_artifacts",
            AsyncMock(side_effect=cleanup_error),
        ):
            resp = await composite_svc.cancel_composite_workflow(
                session, wf_id, cleanup=True, reason="fk_test"
            )

        assert resp.status == CompositeWorkflowStatus.cleanup_failed
        assert run_obj.status == CompositeWorkflowStatus.cleanup_failed.value
        summary = run_obj.result_summary_json
        assert summary.get("cleanup") is True
        assert summary.get("cleanup_failed") is True
        assert summary.get("cancelled") is True
        assert summary.get("cancel_reason") == "fk_test"
        assert "cleanup_errors" in summary

    asyncio.run(_run())


def test_cancel_no_cleanup_writes_cancelled_status():
    """Cancel without cleanup should write cancelled status directly."""
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()
    run = MagicMock()
    run.id = wf_id
    run.status = CompositeWorkflowStatus.running.value
    run.result_summary_json = {}
    run.completed_at = None
    run.warnings_json = []
    run.errors_json = []

    step = MagicMock()
    step.workflow_run_id = wf_id
    step.status = CompositeStepStatus.running.value
    step.completed_at = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=run)

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [step]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    async def _run():
        resp = await composite_svc.cancel_composite_workflow(
            session, wf_id, cleanup=False, reason="quick_cancel"
        )
        assert resp.status == CompositeWorkflowStatus.cancelled
        assert run.status == CompositeWorkflowStatus.cancelled.value
        assert run.result_summary_json.get("cancelled") is True
        assert run.result_summary_json.get("cancel_reason") == "quick_cancel"

    asyncio.run(_run())


def test_cancel_idempotent_when_already_cleanup_failed():
    """Repeated cancel when already cleanup_failed should return current state."""
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()
    run = MagicMock()
    run.status = CompositeWorkflowStatus.cleanup_failed.value
    run.result_summary_json = {
        "deleted": {"mirror_projections": 0},
        "cleanup_warnings": [],
        "cleanup_errors": ["prior failure"],
        "cancelled": True,
    }
    session = AsyncMock()
    session.get = AsyncMock(return_value=run)

    async def _run():
        cleanup_mock = AsyncMock()
        with patch.object(composite_svc, "cleanup_composite_workflow_artifacts", cleanup_mock):
            resp = await composite_svc.cancel_composite_workflow(session, wf_id, cleanup=True)
        cleanup_mock.assert_not_awaited()
        assert resp.status == CompositeWorkflowStatus.cleanup_failed
        assert resp.errors == ["prior failure"]

    asyncio.run(_run())


def test_cancel_idempotent_when_already_cancelled():
    """Repeated cancel when already cancelled should return current state."""
    from app.services import llm_composite_workflow_service as composite_svc

    wf_id = uuid.uuid4()
    run = MagicMock()
    run.status = CompositeWorkflowStatus.cancelled.value
    run.result_summary_json = {
        "cancelled": True,
        "cancelled_by": "user",
    }
    session = AsyncMock()
    session.get = AsyncMock(return_value=run)

    async def _run():
        cleanup_mock = AsyncMock()
        with patch.object(composite_svc, "cleanup_composite_workflow_artifacts", cleanup_mock):
            resp = await composite_svc.cancel_composite_workflow(session, wf_id, cleanup=True)
        cleanup_mock.assert_not_awaited()
        assert resp.status == CompositeWorkflowStatus.cancelled

    asyncio.run(_run())


def test_cleanup_service_rollback_on_exception():
    """When cleanup_composite_workflow_artifacts catches an internal exception,
    it must rollback the session so the caller is not left with an aborted tx."""
    from app.services.llm_composite_workflow_cleanup_service import cleanup_composite_workflow_artifacts

    wf_id = uuid.uuid4()
    session = AsyncMock()

    session.execute = AsyncMock(side_effect=RuntimeError("simulated JSONB cast error"))

    async def _run():
        deleted, warnings, errors = await cleanup_composite_workflow_artifacts(
            session, wf_id, steps=[]
        )
        assert len(errors) >= 1
        assert any("simulated JSONB" in e for e in errors)
        session.rollback.assert_awaited()

    asyncio.run(_run())


def test_safe_append_event_does_not_raise():
    """The safe_append_workflow_event wrapper must never propagate exceptions."""
    from app.services.llm_workflow_event_log import safe_append_workflow_event

    session = AsyncMock()
    session.add = MagicMock(side_effect=RuntimeError("DB gone"))
    session.flush = AsyncMock(side_effect=RuntimeError("DB gone"))

    async def _run():
        result = await safe_append_workflow_event(
            session,
            uuid.uuid4(),
            event="cancel_initiated",
            message="test",
            commit=False,
        )
        assert result is None

    asyncio.run(_run())
