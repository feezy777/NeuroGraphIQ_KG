"""Prove active LLM extraction request schemas accept large candidate_ids lists."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.llm_composite_workflow import CompositeWorkflowRunRequest, CompositeWorkflowType
from app.schemas.llm_extraction import (
    BatchExtractRequest,
    RegionFieldCompletionRequest,
    SameGranularityCircuitExtractionRequest,
    SameGranularityConnectionExtractionRequest,
    SameGranularityFunctionExtractionRequest,
)


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def _assert_no_max_length_on_candidate_ids(schema_cls: type) -> None:
    props = schema_cls.model_json_schema()["properties"]["candidate_ids"]
    assert "maxItems" not in props, f"{schema_cls.__name__} must not cap candidate_ids"
    assert "maxLength" not in props


@pytest.mark.parametrize(
    "schema_cls,min_len",
    [
        (SameGranularityCircuitExtractionRequest, 2),
        (SameGranularityConnectionExtractionRequest, 2),
        (SameGranularityFunctionExtractionRequest, 1),
        (RegionFieldCompletionRequest, 1),
        (BatchExtractRequest, 1),
    ],
)
def test_schema_accepts_96_candidate_ids(schema_cls, min_len):
    _assert_no_max_length_on_candidate_ids(schema_cls)
    req = schema_cls(provider="deepseek", candidate_ids=_ids(96), dry_run=True)
    assert len(req.candidate_ids) == 96


@pytest.mark.parametrize(
    "schema_cls",
    [
        SameGranularityCircuitExtractionRequest,
        SameGranularityConnectionExtractionRequest,
    ],
)
def test_schema_rejects_one_candidate_id(schema_cls):
    with pytest.raises(ValidationError):
        schema_cls(provider="deepseek", candidate_ids=_ids(1), dry_run=True)


def test_composite_workflow_schema_accepts_96_candidate_ids():
    _assert_no_max_length_on_candidate_ids(CompositeWorkflowRunRequest)
    req = CompositeWorkflowRunRequest(
        workflow_type=CompositeWorkflowType.circuit_with_function_steps,
        provider="deepseek",
        candidate_ids=_ids(96),
        dry_run=True,
    )
    assert len(req.candidate_ids) == 96


def _assert_not_max_length_422(resp) -> None:
    if resp.status_code == 422:
        text = resp.text.lower()
        assert "max_length" not in text, resp.text
        assert "most 50 items" not in text, resp.text
        assert "at most 50" not in text, resp.text


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_api_circuit_route_96_not_max_length_422(client):
    ids = [str(uuid.uuid4()) for _ in range(96)]
    resp = client.post(
        "/api/llm-extraction/same-granularity-circuits",
        json={"provider": "deepseek", "candidate_ids": ids, "dry_run": True},
    )
    _assert_not_max_length_422(resp)
    assert resp.status_code != 422 or "min_length" in resp.text.lower()


def test_api_connection_route_96_not_max_length_422(client):
    ids = [str(uuid.uuid4()) for _ in range(96)]
    resp = client.post(
        "/api/llm-extraction/same-granularity-connections",
        json={"provider": "deepseek", "candidate_ids": ids, "dry_run": True},
    )
    _assert_not_max_length_422(resp)


def test_api_composite_workflow_route_96_not_max_length_422(client):
    ids = [str(uuid.uuid4()) for _ in range(96)]
    resp = client.post(
        "/api/llm-extraction/composite-workflows/run",
        json={
            "workflow_type": "circuit_with_function_steps",
            "provider": "deepseek",
            "candidate_ids": ids,
            "dry_run": True,
        },
    )
    _assert_not_max_length_422(resp)
