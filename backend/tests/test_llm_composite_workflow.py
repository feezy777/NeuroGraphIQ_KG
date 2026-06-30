"""Composite LLM extraction workflow tests (mock services, no real LLM)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.llm_composite_workflow import (
    CompositeStepStatus,
    CompositeWorkflowStatus,
    CompositeWorkflowType,
)
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_circuit_extraction_service import CircuitExtractionResult
from app.services.llm_circuit_function_extraction_service import CircuitToFunctionsResult
from app.services.llm_connection_extraction_service import ConnectionExtractionResult
from app.services.llm_projection_function_extraction_service import ProjectionToFunctionsResult


def _conn_result(**kwargs) -> ConnectionExtractionResult:
    defaults = dict(
        run_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        candidate_count=2,
        pair_count=1,
        connection_count=1,
        mirror_connection_created_count=1,
        dry_run=True,
        warnings=[],
    )
    defaults.update(kwargs)
    return ConnectionExtractionResult(**defaults)


def _circuit_result(**kwargs) -> CircuitExtractionResult:
    defaults = dict(
        run_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        candidate_count=2,
        mirror_circuit_created_count=1,
        dry_run=True,
        warnings=[],
    )
    defaults.update(kwargs)
    return CircuitExtractionResult(**defaults)


def _projection_fn_result(**kwargs) -> ProjectionToFunctionsResult:
    defaults = dict(
        run_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        mirror_projection_function_created_count=2,
        dry_run=True,
        warnings=[],
    )
    defaults.update(kwargs)
    return ProjectionToFunctionsResult(**defaults)


def _run_payload(**kwargs):
    base = {
        "workflow_type": "connection_with_function",
        "provider": "deepseek",
        "dry_run": True,
        "candidate_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
    }
    base.update(kwargs)
    return base


def _skip_if_no_tables(resp):
    if resp.status_code == 500 and "llm_composite_workflow" in resp.text:
        pytest.skip("Composite workflow tables not migrated")


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_compute_pair_count_30_candidates_not_blocking():
    ids = [uuid.uuid4() for _ in range(30)]
    assert composite_svc.compute_pair_count(ids) == 435


def test_connection_with_function_dry_run_creates_workflow_run(client):
    with patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(return_value=_conn_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_projection_ids",
        new=AsyncMock(return_value=[uuid.uuid4()]),
    ), patch(
        "app.services.llm_composite_workflow_service.proj_fn_svc.run_projection_to_functions_extraction",
        new=AsyncMock(return_value=_projection_fn_result()),
    ):
        resp = client.post("/api/llm-extraction/composite-workflows/run", json=_run_payload())
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["workflow_run_id"]
    assert data["workflow_type"] == "connection_with_function"
    assert data["status"] in {"dry_run", "succeeded", "partially_succeeded"}
    assert len(data["steps"]) == 2


def test_connection_with_function_one_candidate_failed(client):
    resp = client.post(
        "/api/llm-extraction/composite-workflows/run",
        json=_run_payload(candidate_ids=[str(uuid.uuid4())]),
    )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "failed"
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_connections"]["status"] == "failed"
    assert steps["extract_projection_functions"]["status"] == "skipped"


def test_connection_with_function_30_candidates_not_blocked(client):
    ids = [str(uuid.uuid4()) for _ in range(30)]
    with patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(return_value=_conn_result(candidate_count=30, pair_count=435)),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_projection_ids",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(candidate_ids=ids),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pair_count"] == 435
    assert any("435" in w or "pair_count" in w for w in data.get("warnings", []))


def test_connection_step1_failed_skips_step2(client):
    with patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(side_effect=RuntimeError("connection failed")),
    ):
        resp = client.post("/api/llm-extraction/composite-workflows/run", json=_run_payload())
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "failed"
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_connections"]["status"] == "failed"
    assert steps["extract_projection_functions"]["status"] == "skipped_dependency_failed"


def test_projection_to_functions_not_implemented_skipped(client):
    with patch.object(composite_svc, "PROJECTION_TO_FUNCTIONS_ENABLED", False), patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(return_value=_conn_result()),
    ):
        resp = client.post("/api/llm-extraction/composite-workflows/run", json=_run_payload())
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_projection_functions"]["status"] == "skipped"
    assert any("projection_to_functions" in w for w in data["warnings"])


def test_circuit_with_function_steps_dry_run(client):
    step_result = type("R", (), {"mirror_step_created_count": 1, "warnings": []})()
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[uuid.uuid4()]),
    ), patch(
        "app.services.llm_composite_workflow_service.circuit_step_svc.run_circuit_to_steps_extraction",
        new=AsyncMock(return_value=step_result),
    ), patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_to_functions_extraction",
        new=AsyncMock(return_value=CircuitToFunctionsResult(status="preview", dry_run=True)),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(
                workflow_type="circuit_with_function_steps",
                candidate_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
            ),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["workflow_type"] == "circuit_with_function_steps"
    assert len(data["steps"]) == 3
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuit_functions"]["status"] == "succeeded"


def test_circuit_one_candidate_failed(client):
    resp = client.post(
        "/api/llm-extraction/composite-workflows/run",
        json=_run_payload(
            workflow_type="circuit_with_function_steps",
            candidate_ids=[str(uuid.uuid4())],
        ),
    )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "failed"
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuits"]["status"] == "failed"
    assert steps["extract_circuit_steps"]["status"] == "skipped"
    assert steps["extract_circuit_functions"]["status"] == "skipped"


def test_circuit_step1_failed_skips_dependents(client):
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(side_effect=RuntimeError("circuit failed")),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(
                workflow_type="circuit_with_function_steps",
                candidate_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
            ),
        )
    _skip_if_no_tables(resp)
    steps = {s["step_key"]: s for s in resp.json()["steps"]}
    assert steps["extract_circuits"]["status"] == "failed"
    assert steps["extract_circuit_steps"]["status"] == "skipped"
    assert steps["extract_circuit_functions"]["status"] == "skipped"


def test_circuit_to_functions_skipped_with_warning(client):
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_to_functions_extraction",
        new=AsyncMock(),
    ) as mock_fn:
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(
                workflow_type="circuit_with_function_steps",
                candidate_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
            ),
        )
    _skip_if_no_tables(resp)
    data = resp.json()
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuit_functions"]["status"] == "skipped"
    mock_fn.assert_not_awaited()
    assert any("No circuit ids" in w for w in data["warnings"])


def test_triple_generation_no_mirror_objects_failed(client):
    with patch(
        "app.services.llm_composite_workflow_service._count_mirror_objects_in_scope",
        new=AsyncMock(return_value={"connections": 0, "region_functions": 0, "circuits": 0}),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json={"workflow_type": "triple_generation", "provider": "deepseek", "dry_run": True},
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "failed"
    assert any("No Mirror objects" in e for e in data["errors"])


def test_list_composite_workflow_runs(client):
    resp = client.get("/api/llm-extraction/composite-workflows/runs?limit=10")
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data
    assert "total" in data


def test_workflow_run_detail_returns_steps(client):
    with patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(return_value=_conn_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_projection_ids",
        new=AsyncMock(return_value=[]),
    ):
        create = client.post("/api/llm-extraction/composite-workflows/run", json=_run_payload())
    _skip_if_no_tables(create)
    assert create.status_code == 200, create.text
    run_id = create.json()["workflow_run_id"]
    detail = client.get(f"/api/llm-extraction/composite-workflows/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == run_id
    assert len(body["steps"]) >= 1
    steps = client.get(f"/api/llm-extraction/composite-workflows/runs/{run_id}/steps")
    assert steps.status_code == 200
    assert steps.json()["total"] >= 1


def test_finalize_status_rules():
    from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep

    run = LlmCompositeWorkflowRun(
        id=uuid.uuid4(),
        workflow_type=CompositeWorkflowType.connection_with_function.value,
        status=CompositeWorkflowStatus.running.value,
        dry_run=True,
        candidate_count=2,
        pair_count=1,
    )
    steps = [
        LlmCompositeWorkflowStep(
            id=uuid.uuid4(),
            workflow_run_id=run.id,
            step_order=1,
            step_key="extract_connections",
            status=CompositeStepStatus.succeeded.value,
        ),
        LlmCompositeWorkflowStep(
            id=uuid.uuid4(),
            workflow_run_id=run.id,
            step_order=2,
            step_key="extract_projection_functions",
            status=CompositeStepStatus.skipped.value,
        ),
    ]
    summary = composite_svc.build_result_summary(run, steps)
    assert summary["step_statuses"]["extract_connections"] == "succeeded"


def test_invoke_circuit_extraction_does_not_pass_scope_keyword():
    from app.schemas.llm_composite_workflow import CompositeWorkflowRunRequest

    ids = [uuid.uuid4() for _ in range(96)]
    composite_req = CompositeWorkflowRunRequest(
        workflow_type=CompositeWorkflowType.circuit_with_function_steps,
        provider="deepseek",
        candidate_ids=ids,
        dry_run=True,
    )
    body = composite_svc.build_circuit_extraction_request(composite_req)
    assert len(body.candidate_ids) == 96

    session = AsyncMock()
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result(candidate_count=96)),
    ) as mock_run:
        asyncio.run(composite_svc.invoke_circuit_extraction(session, body))

    assert "scope" not in mock_run.call_args.kwargs
    assert mock_run.call_args.kwargs["scope_resource_id"] is None
    assert mock_run.call_args.kwargs["scope_batch_id"] is None
    assert len(mock_run.call_args.kwargs["candidate_ids"]) == 96


def test_invoke_connection_extraction_does_not_pass_scope_keyword():
    from app.schemas.llm_composite_workflow import CompositeWorkflowRunRequest

    composite_req = CompositeWorkflowRunRequest(
        workflow_type=CompositeWorkflowType.connection_with_function,
        provider="deepseek",
        candidate_ids=[uuid.uuid4(), uuid.uuid4()],
        dry_run=True,
        resource_id=uuid.uuid4(),
    )
    body = composite_svc.build_connection_extraction_request(composite_req)

    session = AsyncMock()
    with patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(return_value=_conn_result()),
    ) as mock_run:
        asyncio.run(composite_svc.invoke_connection_extraction(session, body))

    assert "scope" not in mock_run.call_args.kwargs
    assert mock_run.call_args.kwargs["scope_resource_id"] == composite_req.resource_id


def test_circuit_workflow_96_candidates_no_scope_typeerror(client):
    ids = [str(uuid.uuid4()) for _ in range(96)]
    with patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result(candidate_count=96)),
    ) as mock_invoke, patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(
                workflow_type="circuit_with_function_steps",
                candidate_ids=ids,
            ),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "unexpected keyword argument 'scope'" not in " ".join(data.get("errors", [])).lower()
    assert mock_invoke.await_count >= 1
    all_candidate_ids: list[uuid.UUID] = []
    for call in mock_invoke.await_args_list:
        req_body = call.args[1]
        all_candidate_ids.extend(req_body.candidate_ids)
        assert "scope" not in call.kwargs
    assert len(set(str(cid) for cid in all_candidate_ids)) == 96
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuits"]["status"] == "succeeded"


def test_none_if_blank_normalizes_empty_scope():
    from app.schemas.llm_composite_workflow import CompositeWorkflowRunRequest

    req = CompositeWorkflowRunRequest(
        workflow_type="circuit_with_function_steps",
        provider="deepseek",
        candidate_ids=[uuid.uuid4(), uuid.uuid4()],
        source_atlas="",
        granularity_level="  ",
        batch_id=None,
    )
    normalized = composite_svc.normalize_composite_request(req)
    assert normalized.source_atlas is None
    assert normalized.granularity_level is None


def test_compute_progress_percent():
    from app.models.llm_composite_workflow import LlmCompositeWorkflowStep

    run_id = uuid.uuid4()
    steps = [
        LlmCompositeWorkflowStep(
            id=uuid.uuid4(), workflow_run_id=run_id, step_order=1, step_key="a",
            status=CompositeStepStatus.succeeded.value,
        ),
        LlmCompositeWorkflowStep(
            id=uuid.uuid4(), workflow_run_id=run_id, step_order=2, step_key="b",
            status=CompositeStepStatus.running.value,
        ),
        LlmCompositeWorkflowStep(
            id=uuid.uuid4(), workflow_run_id=run_id, step_order=3, step_key="c",
            status=CompositeStepStatus.pending.value,
        ),
    ]
    assert composite_svc.compute_progress_percent(steps) == 50.0


def test_composite_workflow_start_returns_run_id(client):
    with patch(
        "app.services.llm_composite_workflow_service.execute_composite_workflow_background",
        new=lambda *args, **kwargs: None,
    ), patch(
        "app.services.llm_composite_workflow_service.conn_svc.run_same_granularity_connection_extraction",
        new=AsyncMock(return_value=_conn_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_projection_ids",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post("/api/llm-extraction/composite-workflows/start", json=_run_payload())
    _skip_if_no_tables(resp)
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["workflow_run_id"]
    assert data["status"] == "pending"
    assert len(data["steps"]) >= 1


def test_start_then_get_detail_pending_or_running(client):
    with patch(
        "app.services.llm_composite_workflow_service.execute_composite_workflow_background",
        new=lambda *args, **kwargs: None,
    ):
        start = client.post("/api/llm-extraction/composite-workflows/start", json=_run_payload())
    _skip_if_no_tables(start)
    assert start.status_code == 202, start.text
    run_id = start.json()["workflow_run_id"]
    detail = client.get(f"/api/llm-extraction/composite-workflows/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == run_id
    assert "progress_percent" in body
    assert body["status"] in {"pending", "running", "succeeded", "failed", "dry_run", "partially_succeeded"}


def test_run_service_exception_returns_structured_not_bare_500(client):
    with patch(
        "app.services.llm_composite_workflow_service._dispatch_workflow_execution",
        new=AsyncMock(side_effect=RuntimeError("boom after run created")),
    ):
        resp = client.post("/api/llm-extraction/composite-workflows/run", json=_run_payload())
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["workflow_run_id"]
    assert data["status"] == "failed"
    assert data["errors"]


def test_background_failure_marks_workflow_failed(client):
    async def _fail_bg(run_id, payload):
        from app.database import AsyncSessionLocal
        from app.services.llm_composite_workflow_service import _recover_unhandled_workflow_failure

        async with AsyncSessionLocal() as session:
            await _recover_unhandled_workflow_failure(
                session, run_id, TypeError("adapter bug"), commit=True
            )

    with patch(
        "app.routers.llm_composite_workflow.composite_svc.execute_composite_workflow_background",
        side_effect=_fail_bg,
    ):
        start = client.post("/api/llm-extraction/composite-workflows/start", json=_run_payload())
    _skip_if_no_tables(start)
    assert start.status_code == 202, start.text
    run_id = start.json()["workflow_run_id"]
    detail = client.get(f"/api/llm-extraction/composite-workflows/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"
