"""Composite workflow circuit_to_functions integration tests (mock provider, no real LLM)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_circuit_extraction_service import CircuitExtractionResult
from app.services.llm_circuit_function_extraction_service import (
    CircuitToFunctionsResult,
    MirrorCircuitFunctionsTableMissingError,
)
from app.services.llm_composite_workflow_service import aggregate_workflow_created_targets


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


def _circuit_fn_result(**kwargs) -> CircuitToFunctionsResult:
    defaults = dict(
        status="preview",
        circuit_count=1,
        created_count=0,
        updated_count=0,
        skipped_count=0,
        failed_count=0,
        dry_run=True,
        warnings=[],
        prompt_preview={"seed_count": 1},
    )
    defaults.update(kwargs)
    return CircuitToFunctionsResult(**defaults)


def _run_payload(**kwargs):
    base = {
        "workflow_type": "circuit_with_function_steps",
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


def test_composite_dry_run_calls_circuit_to_functions_without_provider_write(client):
    circuit_id = uuid.uuid4()
    fn_id = uuid.uuid4()
    mock_fn = AsyncMock(
        return_value=_circuit_fn_result(
            status="preview",
            created_count=0,
            created_ids=[],
            dry_run=True,
        )
    )
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[circuit_id]),
    ), patch(
        "app.services.llm_composite_workflow_service.circuit_step_svc.run_circuit_to_steps_extraction",
        new=AsyncMock(return_value=type("R", (), {"mirror_step_created_count": 1, "warnings": []})()),
    ), patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_to_functions_extraction",
        new=mock_fn,
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(dry_run=True),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuit_functions"]["status"] == "succeeded"
    mock_fn.assert_awaited_once()
    body = mock_fn.await_args.args[1]
    assert body.dry_run is True
    assert circuit_id in body.circuit_ids
    assert data["result_summary"]["created_counts"].get("circuit_functions", 0) == 0
    assert not any(t.get("target_type") == "circuit_function" for t in data.get("created_targets", []))


def test_composite_execute_aggregates_circuit_function_created_targets(client):
    circuit_id = uuid.uuid4()
    fn_id = uuid.uuid4()
    fn_result = _circuit_fn_result(
        status="completed",
        created_count=1,
        created_ids=[fn_id],
        dry_run=False,
        created_targets=[
            {
                "target_type": "circuit_function",
                "target_table": "mirror_circuit_functions",
                "ids": [str(fn_id)],
                "count": 1,
            }
        ],
    )
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result(dry_run=False)),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[circuit_id]),
    ), patch(
        "app.services.llm_composite_workflow_service.circuit_step_svc.run_circuit_to_steps_extraction",
        new=AsyncMock(return_value=type("R", (), {"mirror_step_created_count": 2, "warnings": []})()),
    ), patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_to_functions_extraction",
        new=AsyncMock(return_value=fn_result),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(dry_run=False),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    fn_targets = [
        t for t in data.get("created_targets", [])
        if t.get("target_type") == "circuit_function"
    ]
    assert fn_targets
    assert fn_targets[0]["count"] == 1
    assert str(fn_id) in fn_targets[0]["ids"]
    assert data["result_summary"]["created_counts"].get("circuit_functions") == 1


def test_composite_migration_missing_step_failed_not_500(client):
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result()),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[uuid.uuid4()]),
    ), patch(
        "app.services.llm_composite_workflow_service.circuit_step_svc.run_circuit_to_steps_extraction",
        new=AsyncMock(return_value=type("R", (), {"mirror_step_created_count": 0, "warnings": []})()),
    ), patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_to_functions_extraction",
        new=AsyncMock(
            side_effect=MirrorCircuitFunctionsTableMissingError(
                "backend/migrations/033_mirror_circuit_functions.sql"
            )
        ),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(dry_run=False),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuits"]["status"] == "succeeded"
    assert steps["extract_circuit_functions"]["status"] == "failed"
    assert any("MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED" in e for e in data.get("errors", []))


def test_composite_fn_failure_preserves_circuit_step_targets(client):
    circuit_id = uuid.uuid4()
    with patch(
        "app.services.llm_composite_workflow_service.circuit_svc.run_same_granularity_circuit_extraction",
        new=AsyncMock(return_value=_circuit_result(dry_run=False)),
    ), patch(
        "app.services.llm_composite_workflow_service._resolve_circuit_ids",
        new=AsyncMock(return_value=[circuit_id]),
    ), patch(
        "app.services.llm_composite_workflow_service.circuit_step_svc.run_circuit_to_steps_extraction",
        new=AsyncMock(return_value=type("R", (), {"mirror_step_created_count": 3, "warnings": []})()),
    ), patch(
        "app.services.llm_composite_workflow_service.invoke_circuit_to_functions_extraction",
        new=AsyncMock(side_effect=RuntimeError("provider failed")),
    ):
        resp = client.post(
            "/api/llm-extraction/composite-workflows/run",
            json=_run_payload(dry_run=False),
        )
    _skip_if_no_tables(resp)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuits"]["status"] == "succeeded"
    assert steps["extract_circuit_steps"]["status"] == "succeeded"
    assert steps["extract_circuit_functions"]["status"] == "failed"
    circuit_targets = [
        t for t in data.get("created_targets", [])
        if t.get("target_type") == "circuit"
    ]
    assert circuit_targets
    assert str(circuit_id) in circuit_targets[0]["ids"]


def test_composite_no_circuit_ids_skips_circuit_functions(client):
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
            json=_run_payload(),
        )
    _skip_if_no_tables(resp)
    data = resp.json()
    steps = {s["step_key"]: s for s in data["steps"]}
    assert steps["extract_circuit_functions"]["status"] == "skipped"
    mock_fn.assert_not_awaited()
    assert any("No circuit ids" in w for w in data.get("warnings", []))


def test_aggregate_workflow_created_targets_dedupes():
    from app.models.llm_composite_workflow import LlmCompositeWorkflowStep

    step = LlmCompositeWorkflowStep(
        id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        step_order=3,
        step_key="extract_circuit_functions",
        status="succeeded",
        response_json={
            "created_targets": [
                {
                    "target_type": "circuit_function",
                    "target_table": "mirror_circuit_functions",
                    "ids": ["a", "b", "a"],
                    "count": 3,
                    "step_key": "circuit_to_functions",
                }
            ]
        },
    )
    targets = aggregate_workflow_created_targets([step])
    assert len(targets) == 1
    assert targets[0]["count"] == 2
    assert set(targets[0]["ids"]) == {"a", "b"}
