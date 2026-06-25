"""Mirror circuit_function list/read API tests (Step 10.6.2 — no formal/final/kg writes)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.mirror_macro_clinical import MirrorCircuitFunction
from app.services import mirror_macro_clinical_service as svc


def _sample_row(**overrides) -> MirrorCircuitFunction:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        llm_run_id=uuid.uuid4(),
        llm_item_id=uuid.uuid4(),
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        function_term_en="memory consolidation",
        function_term_cn="记忆巩固",
        function_domain="memory",
        function_role="associated_with",
        effect_type="modulatory",
        confidence_score=Decimal("0.875"),
        confidence=Decimal("0.91"),
        evidence_level="moderate",
        description="test description",
        remark=None,
        attributes={"formal_field_overlay": {"function_term_cn": "记忆巩固"}},
        source_db="AAL3",
        status="active",
        mirror_status="llm_suggested",
        review_status="pending",
        validation_status=None,
        promotion_status="not_promoted",
        evidence_text="evidence",
        provenance="llm_extraction",
        uncertainty_reason=None,
        raw_payload_json={},
        normalized_payload_json={},
        created_by=None,
        updated_by=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return MirrorCircuitFunction(**defaults)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_openapi_registers_circuit_functions_routes(client):
    spec = client.get("/api/openapi.json").json()
    paths = spec.get("paths", {})
    assert "/api/mirror-kg/circuit-functions" in paths
    assert "/api/mirror-kg/circuit-functions/{circuit_function_id}" in paths
    assert "get" in paths["/api/mirror-kg/circuit-functions"]
    assert "get" in paths["/api/mirror-kg/circuit-functions/{circuit_function_id}"]


def test_list_circuit_functions_returns_paginated_shape(monkeypatch, client):
    row = _sample_row()

    async def _list(*_args, **kwargs):
        assert kwargs["limit"] == 50
        assert kwargs["offset"] == 0
        return [row], 1

    monkeypatch.setattr(svc, "list_mirror_circuit_functions", _list)

    resp = client.get("/api/mirror-kg/circuit-functions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["function_term_en"] == "memory consolidation"
    assert body["warnings"] == []


def test_list_clamps_limit_to_5000(monkeypatch, client):
    captured: dict = {}

    async def _list(*_args, **kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr(svc, "list_mirror_circuit_functions", _list)

    resp = client.get("/api/mirror-kg/circuit-functions?limit=6000")
    assert resp.status_code == 422


def test_list_passes_filters(monkeypatch, client):
    circuit_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    captured: dict = {}

    async def _list(*_args, **kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr(svc, "list_mirror_circuit_functions", _list)

    resp = client.get(
        "/api/mirror-kg/circuit-functions",
        params={
            "circuit_id": str(circuit_id),
            "batch_id": str(batch_id),
            "resource_id": str(resource_id),
            "function_domain": "memory",
            "function_role": "associated_with",
            "q": "consolidation",
        },
    )
    assert resp.status_code == 200
    assert captured["circuit_id"] == circuit_id
    assert captured["batch_id"] == batch_id
    assert captured["resource_id"] == resource_id
    assert captured["function_domain"] == "memory"
    assert captured["function_role"] == "associated_with"
    assert captured["q"] == "consolidation"


def test_list_serializes_decimal_and_attributes(monkeypatch, client):
    row = _sample_row()

    async def _list(*_args, **_kwargs):
        return [row], 1

    monkeypatch.setattr(svc, "list_mirror_circuit_functions", _list)

    resp = client.get("/api/mirror-kg/circuit-functions")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    json.dumps(item)
    assert item["confidence_score"] == 0.875
    assert item["confidence"] == 0.91
    assert isinstance(item["attributes"], dict)
    assert item["attributes"]["formal_field_overlay"]["function_term_cn"] == "记忆巩固"


def test_get_circuit_function_returns_read_schema(monkeypatch, client):
    row = _sample_row()
    row_id = row.id

    async def _get(*_args, **_kwargs):
        return row

    monkeypatch.setattr(svc, "get_mirror_circuit_function", _get)

    resp = client.get(f"/api/mirror-kg/circuit-functions/{row_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(row_id)
    assert body["attributes"]["formal_field_overlay"]["function_term_cn"] == "记忆巩固"


def test_get_circuit_function_not_found(monkeypatch, client):
    async def _get(*_args, **_kwargs):
        raise svc.MirrorCircuitFunctionNotFoundError(str(uuid.uuid4()))

    monkeypatch.setattr(svc, "get_mirror_circuit_function", _get)

    resp = client.get(f"/api/mirror-kg/circuit-functions/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_list_not_initialized_returns_structured_503(monkeypatch, client):
    async def _list(*_args, **_kwargs):
        raise svc.MirrorCircuitFunctionsNotInitializedError()

    monkeypatch.setattr(svc, "list_mirror_circuit_functions", _list)

    resp = client.get("/api/mirror-kg/circuit-functions")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED"
    assert "033_mirror_circuit_functions.sql" in detail["migration"]


def test_get_not_initialized_returns_structured_503(monkeypatch, client):
    async def _get(*_args, **_kwargs):
        raise svc.MirrorCircuitFunctionsNotInitializedError()

    monkeypatch.setattr(svc, "get_mirror_circuit_function", _get)

    resp = client.get(f"/api/mirror-kg/circuit-functions/{uuid.uuid4()}")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED"


def test_service_limit_clamp():
    session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    async def _execute(stmt):
        if "count" in str(stmt).lower():
            return count_result
        return list_result

    session.execute = AsyncMock(side_effect=_execute)

    async def _run():
        _, _ = await svc.list_mirror_circuit_functions(session, limit=999, offset=-5)
        call_args = session.execute.await_args_list
        assert len(call_args) >= 2

    asyncio.run(_run())


def test_service_maps_missing_table_to_not_initialized():
    from sqlalchemy.exc import ProgrammingError

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=ProgrammingError(
            "SELECT",
            {},
            Exception('relation "mirror_circuit_functions" does not exist'),
        )
    )

    async def _run():
        with pytest.raises(svc.MirrorCircuitFunctionsNotInitializedError):
            await svc.list_mirror_circuit_functions(session)

    asyncio.run(_run())
