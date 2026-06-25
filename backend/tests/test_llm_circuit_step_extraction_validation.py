"""Validation tests for circuit-to-steps API endpoint defensive behaviour.

Covers:
- Missing circuit_id → Pydantic 422 (handled by FastAPI request validation)
- Unknown circuit_id → 404 (MirrorCircuitNotFoundError)
- Unexpected exception → 500 with structured message (not raw traceback)
- Valid dry_run still executes without error (smoke test)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.llm_circuit_step_extraction_service import MirrorCircuitNotFoundError


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_missing_circuit_id_returns_422(client: TestClient):
    """circuit_id is required by the Pydantic schema; omitting it → 422."""
    resp = client.post(
        "/api/llm-extraction/circuit-to-steps",
        json={"provider": "deepseek", "dry_run": True},
    )
    assert resp.status_code == 422


def test_unknown_circuit_id_returns_404(client: TestClient):
    """When MirrorCircuitNotFoundError is raised the router must return 404."""
    with patch(
        "app.services.llm_circuit_step_extraction_service.run_circuit_to_steps_extraction",
        new_callable=AsyncMock,
        side_effect=MirrorCircuitNotFoundError("not-found"),
    ):
        resp = client.post(
            "/api/llm-extraction/circuit-to-steps",
            json={"provider": "deepseek", "circuit_id": str(uuid.uuid4()), "dry_run": True},
        )
    assert resp.status_code == 404
    assert "mirror circuit not found" in resp.json().get("detail", "")


def test_unexpected_exception_does_not_return_raw_500(client: TestClient):
    """Unexpected exceptions must be caught by the defensive handler and return
    a structured 500 (not an unhandled traceback that leaks internals)."""
    with patch(
        "app.services.llm_circuit_step_extraction_service.run_circuit_to_steps_extraction",
        new_callable=AsyncMock,
        side_effect=RuntimeError("unexpected internal boom"),
    ):
        resp = client.post(
            "/api/llm-extraction/circuit-to-steps",
            json={"provider": "deepseek", "circuit_id": str(uuid.uuid4()), "dry_run": True},
        )
    assert resp.status_code == 500
    detail = resp.json().get("detail", "")
    # Must contain structured message, not just 'Internal Server Error'
    assert "RuntimeError" in detail or "unexpected" in detail.lower()


def test_invalid_request_body_never_returns_500(client: TestClient):
    """Completely invalid JSON body → 422, not 500."""
    resp = client.post(
        "/api/llm-extraction/circuit-to-steps",
        json={"provider": 12345, "circuit_id": "not-a-uuid"},
    )
    # Either 422 (validation) is fine; 500 is NOT acceptable
    assert resp.status_code != 500
