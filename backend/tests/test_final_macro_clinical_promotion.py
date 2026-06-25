"""Final macro_clinical promotion tests (Step 8.15, no LLM)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.schemas.final_macro_clinical import (
    FinalMacroClinicalPromotionRequest,
    REQUIRED_PROMOTION_CONFIRM_TEXT,
)
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.services import final_macro_clinical_promotion_service as fmps


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="limbic",
        circuit_type="limbic_circuit",
        mirror_status=MirrorStatus.human_approved,
        review_status=MirrorReviewStatus.approved,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _projection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        connection_type="projection",
        directionality="directed",
        mirror_status=MirrorStatus.human_approved,
        review_status=MirrorReviewStatus.approved,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def test_dry_run_no_confirm_required():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    req = FinalMacroClinicalPromotionRequest(target_types=["circuit"], dry_run=True)
    resp = asyncio.run(fmps.run_final_macro_clinical_promotion(session, req))
    assert resp.dry_run is True
    assert resp.run_id is None
    session.commit.assert_not_called()


def test_run_without_confirm_raises():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    req = FinalMacroClinicalPromotionRequest(target_types=["circuit"], dry_run=False, confirm_text="wrong")
    with pytest.raises(ValueError, match="confirm_text"):
        asyncio.run(fmps.run_final_macro_clinical_promotion(session, req))


def test_signal_target_blocked():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    req = FinalMacroClinicalPromotionRequest(
        target_types=["dual_model_verification_result"],
        dry_run=True,
    )
    with pytest.raises(ValueError, match="invalid target_types"):
        asyncio.run(fmps.run_final_macro_clinical_promotion(session, req))


def test_not_human_approved_ineligible():
    circuit = _circuit(mirror_status=MirrorStatus.rule_checked)
    session = AsyncMock()
    status, reason, *_ = asyncio.run(
        fmps.check_promotion_eligibility(
            session, target_type="circuit", obj=circuit, allow_conflict_with_human_reason=True,
        )
    )
    assert status == "not_human_approved"
    assert reason


def test_validation_blocker_ineligible():
    circuit = _circuit()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=MagicMock(reviewer_note="ok"))))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[MagicMock(severity="blocker")])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    status, *_ = asyncio.run(
        fmps.check_promotion_eligibility(
            session, target_type="circuit", obj=circuit, allow_conflict_with_human_reason=True,
        )
    )
    assert status == "validation_blocked"


def test_build_final_uid():
    mid = uuid.uuid4()
    assert fmps._build_final_uid("circuit", mid) == f"final_macro_clinical:circuit:{mid}"


def test_required_confirm_constant():
    assert REQUIRED_PROMOTION_CONFIRM_TEXT == "PROMOTE HUMAN APPROVED MIRROR TO FINAL"


def test_api_dry_run_endpoint():
    client = TestClient(app)

    async def _fake(session, request):
        from app.schemas.final_macro_clinical import FinalMacroClinicalPromotionResponse
        return FinalMacroClinicalPromotionResponse(dry_run=True, candidate_count=0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmps, "run_final_macro_clinical_promotion", _fake)
        r = client.post("/api/final-macro-clinical/promotion/run", json={"target_types": ["circuit"], "dry_run": True})
        assert r.status_code == 200
        assert r.json()["dry_run"] is True


def test_valid_target_types_include_macro():
    assert "circuit_step" in fmps.VALID_TARGET_TYPES
    assert "projection" in fmps.VALID_TARGET_TYPES
    assert "circuit_projection_membership" in fmps.VALID_TARGET_TYPES


def test_blocked_signal_types():
    assert "dual_model_verification_result" in fmps.BLOCKED_SIGNAL_TYPES
