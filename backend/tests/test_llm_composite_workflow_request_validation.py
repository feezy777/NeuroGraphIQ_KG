"""Composite workflow request validation — optional UUID empty string handling."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.llm_composite_workflow import CompositeWorkflowRunRequest


def test_schema_resource_id_empty_string_becomes_none():
    req = CompositeWorkflowRunRequest(
        workflow_type="connection_with_function",
        provider="deepseek",
        resource_id="",
        candidate_ids=[uuid.uuid4()],
    )
    assert req.resource_id is None


def test_schema_batch_id_empty_string_becomes_none():
    req = CompositeWorkflowRunRequest(
        workflow_type="connection_with_function",
        provider="deepseek",
        batch_id="",
        candidate_ids=[uuid.uuid4()],
    )
    assert req.batch_id is None


def test_schema_candidate_ids_filters_empty_strings():
    valid = uuid.uuid4()
    req = CompositeWorkflowRunRequest(
        workflow_type="connection_with_function",
        provider="deepseek",
        candidate_ids=["", valid, "  "],
    )
    assert req.candidate_ids == [valid]


def test_schema_invalid_non_empty_uuid_still_raises():
    with pytest.raises(ValidationError):
        CompositeWorkflowRunRequest(
            workflow_type="connection_with_function",
            provider="deepseek",
            resource_id="abc",
            candidate_ids=[uuid.uuid4()],
        )


def test_schema_valid_batch_id_preserved():
    batch_id = uuid.uuid4()
    req = CompositeWorkflowRunRequest(
        workflow_type="connection_with_function",
        provider="deepseek",
        batch_id=str(batch_id),
        candidate_ids=[uuid.uuid4()],
    )
    assert req.batch_id == batch_id


def test_schema_source_atlas_empty_string_becomes_none():
    req = CompositeWorkflowRunRequest(
        workflow_type="connection_with_function",
        provider="deepseek",
        source_atlas="",
        granularity_level="  ",
        candidate_ids=[uuid.uuid4()],
    )
    assert req.source_atlas is None
    assert req.granularity_level is None


def test_api_start_accepts_empty_resource_id():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    batch_id = uuid.uuid4()
    candidate_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    with patch(
        "app.services.llm_composite_workflow_service.start_composite_workflow",
        new_callable=AsyncMock,
    ) as mock_start:
        from app.schemas.llm_composite_workflow import (
            CompositeWorkflowRunResponse,
            CompositeWorkflowStatus,
            CompositeWorkflowType,
        )

        mock_start.return_value = CompositeWorkflowRunResponse(
            workflow_run_id=uuid.uuid4(),
            workflow_type=CompositeWorkflowType.connection_with_function,
            status=CompositeWorkflowStatus.pending,
            dry_run=True,
            candidate_count=2,
            pair_count=1,
            steps=[],
        )
        resp = client.post(
            "/api/llm-extraction/composite-workflows/start",
            json={
                "workflow_type": "connection_with_function",
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "dry_run": True,
                "candidate_ids": candidate_ids,
                "resource_id": "",
                "batch_id": str(batch_id),
                "source_atlas": "",
                "granularity_level": "",
            },
        )

    assert resp.status_code == 202, resp.text
    called_request = mock_start.call_args[0][1]
    assert called_request.resource_id is None
    assert called_request.batch_id == batch_id
    assert len(called_request.candidate_ids) == 2


def test_api_start_rejects_invalid_resource_id():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/llm-extraction/composite-workflows/start",
        json={
            "workflow_type": "connection_with_function",
            "provider": "deepseek",
            "dry_run": True,
            "candidate_ids": [str(uuid.uuid4())],
            "resource_id": "abc",
        },
    )
    assert resp.status_code == 422
