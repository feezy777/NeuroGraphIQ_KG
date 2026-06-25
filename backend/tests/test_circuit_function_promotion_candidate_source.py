"""Circuit function promotion candidate source tests (Step 10.6.6)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.mirror_macro_clinical import MirrorCircuitFunction, MirrorProjectionFunction
from app.schemas.final_macro_clinical import FinalMacroClinicalPromotionRequest
from app.schemas.macro_clinical_promotion_candidate import (
    CircuitFunctionPromotionCandidateListResponse,
    CircuitFunctionPromotionPreviewResponse,
)
from app.services import final_macro_clinical_promotion_service as final_promo_svc
from app.services import macro_clinical_promotion_candidate_service as promo_svc
from app.services import mirror_macro_clinical_service as mirror_svc


def _circuit_function_row(**overrides) -> MirrorCircuitFunction:
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
        attributes={},
        source_db="AAL3",
        status="active",
        mirror_status="human_approved",
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


def test_registry_uses_mirror_circuit_functions_not_projection():
    info = promo_svc.PROMOTION_SOURCE_REGISTRY["circuit_function"]
    assert info.source_table == "mirror_circuit_functions"
    assert info.formal_table == "macro_clinical.circuit_function"
    assert info.model_name == "MirrorCircuitFunction"


def test_collect_candidates_uses_mirror_circuit_function():
    row = _circuit_function_row(review_status="approved", mirror_status="human_approved")
    session = AsyncMock()

    async def _execute(_stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        return result

    session.execute = _execute

    request = FinalMacroClinicalPromotionRequest(
        target_types=["circuit_function"],
        dry_run=True,
        limit=50,
    )
    candidates = asyncio.run(final_promo_svc.collect_promotion_candidates(session, request))
    assert len(candidates) == 1
    assert candidates[0].target_type == "circuit_function"
    assert isinstance(candidates[0].obj, MirrorCircuitFunction)
    assert not isinstance(candidates[0].obj, MirrorProjectionFunction)


def test_list_candidates_api_shape(monkeypatch, client):
    row = _circuit_function_row()

    async def _list(*_args, **_kwargs):
        return CircuitFunctionPromotionCandidateListResponse(
            source=promo_svc.CIRCUIT_FUNCTION_SOURCE,
            items=[promo_svc._to_candidate_item(row)],
            total=1,
            limit=50,
            offset=0,
        )

    monkeypatch.setattr(promo_svc, "list_circuit_function_promotion_candidates", _list)

    resp = client.get("/api/mirror-kg/promotion-candidates?target_type=circuit_function")
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_type"] == "circuit_function"
    assert body["source_table"] == "mirror_circuit_functions"
    assert body["formal_table"] == "macro_clinical.circuit_function"
    assert body["total"] == 1
    assert body["items"][0]["function_term_en"] == "memory consolidation"


def test_preview_returns_formal_payload(monkeypatch, client):
    row = _circuit_function_row(review_status="pending")

    async def _preview(_session, source_id):
        readiness, blocking, warnings = promo_svc.assess_circuit_function_readiness(row)
        return CircuitFunctionPromotionPreviewResponse(
            source_id=source_id,
            formal_payload_preview=promo_svc.build_formal_payload_preview(row),
            readiness=readiness,
            blocking_reasons=blocking,
            warnings=warnings,
            missing_required_fields=promo_svc._missing_required_fields(row),
            review_status=row.review_status,
            promotion_status=row.promotion_status,
            actual_promotion_allowed=False,
        )

    monkeypatch.setattr(promo_svc, "preview_circuit_function_promotion_candidate", _preview)

    resp = client.get(f"/api/mirror-kg/promotion-candidates/circuit_function/{row.id}/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_table"] == "mirror_circuit_functions"
    assert body["formal_table"] == "macro_clinical.circuit_function"
    assert body["formal_payload_preview"]["circuit_id"] == str(row.circuit_id)
    assert body["formal_payload_preview"]["function_term_en"] == "memory consolidation"
    assert body["readiness"] == "needs_review"


def test_missing_terms_blocked_readiness():
    row = _circuit_function_row(function_term_en=None, function_term_cn=None)
    readiness, blocking, _ = promo_svc.assess_circuit_function_readiness(row)
    assert readiness == "blocked"
    assert any("function_term" in b for b in blocking)


def test_pending_review_needs_review():
    row = _circuit_function_row(review_status="pending")
    readiness, _, warnings = promo_svc.assess_circuit_function_readiness(row)
    assert readiness == "needs_review"
    assert any("pending" in w for w in warnings)


def test_approved_complete_ready():
    row = _circuit_function_row(
        review_status="approved",
        mirror_status="human_approved",
        function_term_cn="记忆巩固",
        function_domain="memory",
        function_role="associated_with",
        evidence_level="moderate",
        confidence_score=Decimal("0.9"),
    )
    readiness, blocking, _ = promo_svc.assess_circuit_function_readiness(row)
    assert readiness == "ready"
    assert blocking == []


def test_attempt_promote_pending_rejected(monkeypatch, client):
    row = _circuit_function_row(review_status="pending")

    async def _attempt(_session, source_id):
        assert source_id == row.id
        raise promo_svc.ReviewRequiredForPromotionError()

    monkeypatch.setattr(promo_svc, "attempt_circuit_function_promotion", _attempt)

    resp = client.post(f"/api/mirror-kg/promotion-candidates/circuit_function/{row.id}/promote")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "REVIEW_REQUIRED"


def test_attempt_promote_formal_table_missing(monkeypatch, client):
    row = _circuit_function_row(review_status="approved")

    async def _attempt(_session, _source_id):
        raise promo_svc.FormalCircuitFunctionTableNotInitializedError()

    monkeypatch.setattr(promo_svc, "attempt_circuit_function_promotion", _attempt)

    resp = client.post(f"/api/mirror-kg/promotion-candidates/circuit_function/{row.id}/promote")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "FORMAL_CIRCUIT_FUNCTION_TABLE_NOT_INITIALIZED"


def test_attempt_promote_disabled_when_approved(monkeypatch, client):
    row = _circuit_function_row(review_status="approved")

    async def _attempt(_session, _source_id):
        raise promo_svc.CircuitFunctionActualPromotionDisabledError()

    monkeypatch.setattr(promo_svc, "attempt_circuit_function_promotion", _attempt)

    resp = client.post(f"/api/mirror-kg/promotion-candidates/circuit_function/{row.id}/promote")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "CIRCUIT_FUNCTION_PROMOTION_NOT_ENABLED"


def test_migration_033_missing_structured_error(monkeypatch, client):
    async def _list(*_args, **_kwargs):
        raise mirror_svc.MirrorCircuitFunctionsNotInitializedError()

    monkeypatch.setattr(promo_svc, "list_circuit_function_promotion_candidates", _list)

    resp = client.get("/api/mirror-kg/promotion-candidates?target_type=circuit_function")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED"


def test_promote_circuit_function_does_not_write():
    session = AsyncMock()
    ctx = final_promo_svc.PromotionContext(
        session=session,
        request=FinalMacroClinicalPromotionRequest(target_types=["circuit_function"], dry_run=False),
        dry_run=False,
        run=None,
        warnings=[],
        promoted_cache={},
    )
    row = _circuit_function_row(review_status="approved")
    result = asyncio.run(final_promo_svc.promote_circuit_function(ctx, row, review_record_id=None))
    assert result is None
    session.add.assert_not_called()


def test_build_formal_payload_preview_fields():
    row = _circuit_function_row()
    payload = promo_svc.build_formal_payload_preview(row)
    assert payload["function_term_en"] == "memory consolidation"
    assert payload["function_domain"] == "memory"
    assert payload["status"] == "active"
    assert "circuit_id" in payload
