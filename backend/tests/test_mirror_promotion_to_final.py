"""Mirror KG Promotion to Final KG tests (no LLM, no network)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_review import MirrorHumanReviewRecord
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_promotion import MirrorPromotionRequest, MirrorPromotionResponse, MirrorPromotionScope
from app.schemas.mirror_review import MirrorReviewAction
from app.services import mirror_promotion_service as mps


def _connection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        connection_type="functional_connectivity",
        directionality="undirected",
        confidence=0.8,
        evidence_text="evidence",
        mirror_status=MirrorStatus.human_approved,
        review_status=MirrorReviewStatus.approved,
        promotion_status=MirrorPromotionStatus.not_promoted,
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def _function(**kwargs) -> MirrorRegionFunction:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        region_candidate_id=uuid.uuid4(),
        function_term="Motor control",
        function_category="motor",
        relation_type="associated_with",
        confidence=0.7,
        evidence_text="evidence",
        mirror_status=MirrorStatus.human_approved,
        review_status=MirrorReviewStatus.approved,
        promotion_status=MirrorPromotionStatus.not_promoted,
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionFunction(**defaults)


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="Default Mode",
        circuit_type="functional",
        confidence=0.75,
        evidence_text="evidence",
        mirror_status=MirrorStatus.human_approved,
        review_status=MirrorReviewStatus.approved,
        promotion_status=MirrorPromotionStatus.not_promoted,
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _triple(**kwargs) -> MirrorKgTriple:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        subject_type="region",
        subject_id=uuid.uuid4(),
        subject_label="RegionA",
        predicate="connects_to",
        object_type="region",
        object_id=uuid.uuid4(),
        object_label="RegionB",
        triple_scope="same_granularity",
        confidence=0.6,
        evidence_text="evidence",
        mirror_status=MirrorStatus.human_approved,
        review_status=MirrorReviewStatus.approved,
        promotion_status=MirrorPromotionStatus.not_promoted,
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorKgTriple(**defaults)


def _approve_record(target_type: str, target_id: uuid.UUID) -> MirrorHumanReviewRecord:
    return MirrorHumanReviewRecord(
        id=uuid.uuid4(),
        target_type=target_type,
        target_id=target_id,
        action=MirrorReviewAction.approve,
        reviewer="reviewer1",
    )


def test_build_required_confirmation():
    text = mps.build_required_confirmation(["connection", "triple"], 42)
    assert text == "PROMOTE MIRROR KG TO FINAL: connection,triple COUNT 42"


def test_empty_target_types_raises():
    with pytest.raises(mps.EmptyTargetTypesError):
        asyncio.run(mps.build_promotion_preview(AsyncMock(), MirrorPromotionRequest(target_types=[])))


def test_not_human_approved_ineligible():
    conn = _connection(mirror_status=MirrorStatus.rule_checked)
    session = AsyncMock()
    eligible, reason, _, _ = asyncio.run(mps.validate_promotion_eligibility(session, "connection", conn))
    assert not eligible
    assert reason == "NOT_HUMAN_APPROVED"


def test_review_not_approved_ineligible():
    conn = _connection(review_status=MirrorReviewStatus.pending)
    session = AsyncMock()
    eligible, reason, _, _ = asyncio.run(mps.validate_promotion_eligibility(session, "connection", conn))
    assert not eligible
    assert reason == "REVIEW_STATUS_NOT_APPROVED"


def test_promotion_blocked_ineligible():
    conn = _connection(promotion_status=MirrorPromotionStatus.blocked)
    session = AsyncMock()
    eligible, reason, _, _ = asyncio.run(mps.validate_promotion_eligibility(session, "connection", conn))
    assert not eligible
    assert reason == "PROMOTION_BLOCKED"


def test_no_approve_record_ineligible():
    conn = _connection()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
    with patch.object(mps, "get_latest_validation_summary", AsyncMock(return_value={"has_blocker": False, "has_error": False})):
        eligible, reason, _, _ = asyncio.run(mps.validate_promotion_eligibility(session, "connection", conn))
    assert not eligible
    assert reason == "NO_APPROVE_REVIEW_RECORD"


def test_validation_blocker_ineligible():
    conn = _connection()
    session = AsyncMock()
    approve = _approve_record("connection", conn.id)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=approve)))),
        ]
    )
    with patch.object(
        mps,
        "get_latest_validation_summary",
        AsyncMock(return_value={"has_blocker": True, "has_error": False}),
    ):
        eligible, reason, _, _ = asyncio.run(mps.validate_promotion_eligibility(session, "connection", conn))
    assert not eligible
    assert reason == "HAS_VALIDATION_BLOCKER"


def test_warning_does_not_block():
    conn = _connection()
    session = AsyncMock()
    approve = _approve_record("connection", conn.id)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=approve)))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    with patch.object(
        mps,
        "get_latest_validation_summary",
        AsyncMock(return_value={"has_blocker": False, "has_error": False, "has_warning": True}),
    ):
        with patch.object(mps, "detect_final_duplicate", AsyncMock(return_value=False)):
            eligible, reason, review_id, val = asyncio.run(
                mps.validate_promotion_eligibility(session, "connection", conn)
            )
    assert eligible
    assert reason is None
    assert review_id == approve.id
    assert val.get("has_warning")


def test_run_missing_operator():
    session = AsyncMock()
    req = MirrorPromotionRequest(
        target_types=["connection"],
        dry_run=False,
        operator=None,
        reason="test",
        confirmation_text="PROMOTE MIRROR KG TO FINAL: connection COUNT 1",
    )
    with patch.object(mps, "build_promotion_preview", AsyncMock(return_value=MagicMock(required_confirmation=req.confirmation_text, object_count=1, eligible_count=1, warnings=[], preview_items=[]))):
        with pytest.raises(mps.MissingOperatorError):
            asyncio.run(mps.run_mirror_promotion(session, req))


def test_run_missing_reason():
    session = AsyncMock()
    req = MirrorPromotionRequest(
        target_types=["connection"],
        dry_run=False,
        operator="op1",
        reason=None,
        confirmation_text="PROMOTE MIRROR KG TO FINAL: connection COUNT 1",
    )
    with patch.object(mps, "build_promotion_preview", AsyncMock(return_value=MagicMock(required_confirmation=req.confirmation_text, object_count=1, eligible_count=1, warnings=[], preview_items=[]))):
        with pytest.raises(mps.MissingReasonError):
            asyncio.run(mps.run_mirror_promotion(session, req))


def test_run_confirmation_mismatch():
    session = AsyncMock()
    req = MirrorPromotionRequest(
        target_types=["connection"],
        dry_run=False,
        operator="op1",
        reason="reason",
        confirmation_text="WRONG",
    )
    with patch.object(mps, "build_promotion_preview", AsyncMock(return_value=MagicMock(required_confirmation="PROMOTE MIRROR KG TO FINAL: connection COUNT 1", object_count=1, eligible_count=1, warnings=[], preview_items=[]))):
        with pytest.raises(mps.ConfirmationMismatchError):
            asyncio.run(mps.run_mirror_promotion(session, req))


def test_update_mirror_source_after_promotion():
    conn = _connection()
    mps.update_mirror_source_after_promotion(conn)
    assert conn.promotion_status == MirrorPromotionStatus.promoted
    assert conn.mirror_status == MirrorStatus.promoted_to_final
    assert conn.review_status == MirrorReviewStatus.approved


def test_api_preview_empty_target_types_400():
    client = TestClient(app)
    with patch("app.routers.mirror_promotion.get_db") as mock_db:
        mock_db.return_value = AsyncMock()
        resp = client.post("/api/mirror-kg/promotion/preview", json={"target_types": []})
    assert resp.status_code == 400


def test_api_preview_returns_required_confirmation():
    client = TestClient(app)
    preview = MirrorPromotionResponse(
        dry_run=True,
        required_confirmation="PROMOTE MIRROR KG TO FINAL: connection COUNT 1",
        object_count=1,
        eligible_count=1,
    )
    with patch("app.routers.mirror_promotion.mps.build_promotion_preview", AsyncMock(return_value=preview)):
        with patch("app.database.get_db") as mock_get_db:
            mock_get_db.return_value = AsyncMock()
            resp = client.post(
                "/api/mirror-kg/promotion/preview",
                json={"target_types": ["connection"]},
            )
    assert resp.status_code == 200
    assert "required_confirmation" in resp.json()


def test_api_run_missing_operator_400():
    client = TestClient(app)
    with patch("app.routers.mirror_promotion.mps.run_mirror_promotion", AsyncMock(side_effect=mps.MissingOperatorError("operator required"))):
        with patch("app.database.get_db") as mock_get_db:
            mock_get_db.return_value = AsyncMock()
            resp = client.post(
                "/api/mirror-kg/promotion/run",
                json={"target_types": ["connection"], "confirmation_text": "x"},
            )
    assert resp.status_code == 400


def test_dry_run_does_not_commit():
    session = AsyncMock()
    req = MirrorPromotionRequest(target_types=["connection"], dry_run=True)
    with patch.object(mps, "collect_promotion_targets", AsyncMock(return_value=[])):
        result = asyncio.run(mps.build_promotion_preview(session, req))
    assert result.dry_run is True
    session.commit.assert_not_called()


def test_promote_connection_writes_final():
    conn = _connection()
    run = mps.create_promotion_run(
        target_types=["connection"],
        scope_json={},
        scope=mps.PromotionScope(),
        dry_run=False,
        required_confirmation="x",
        operator="op",
        reason="reason",
        confirmation_text="x",
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    with patch.object(mps, "promote_evidence_for_target", AsyncMock(return_value=1)):
        rec, final = asyncio.run(
            mps.promote_connection(session, obj=conn, run=run, review_record_id=uuid.uuid4(), warnings=[])
        )
    assert rec.status == "promoted"
    assert final.source_mirror_connection_id == conn.id
    assert conn.promotion_status == MirrorPromotionStatus.promoted


def test_promote_function_writes_final():
    fn = _function()
    run = mps.create_promotion_run(
        target_types=["function"],
        scope_json={},
        scope=mps.PromotionScope(),
        dry_run=False,
        required_confirmation="x",
        operator="op",
        reason="reason",
        confirmation_text="x",
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    with patch.object(mps, "promote_evidence_for_target", AsyncMock(return_value=1)):
        rec, final = asyncio.run(
            mps.promote_function(session, obj=fn, run=run, review_record_id=uuid.uuid4(), warnings=[])
        )
    assert rec.status == "promoted"
    assert final.source_mirror_function_id == fn.id


def test_promote_circuit_writes_final_and_regions():
    circ = _circuit()
    run = mps.create_promotion_run(
        target_types=["circuit"],
        scope_json={},
        scope=mps.PromotionScope(),
        dry_run=False,
        required_confirmation="x",
        operator="op",
        reason="reason",
        confirmation_text="x",
    )
    mr = MirrorCircuitRegion(
        id=uuid.uuid4(),
        circuit_id=circ.id,
        region_candidate_id=uuid.uuid4(),
        role="participant",
        sort_order=0,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mr]))))
    )
    with patch.object(mps, "promote_evidence_for_target", AsyncMock(return_value=1)):
        rec, final = asyncio.run(
            mps.promote_circuit(session, obj=circ, run=run, review_record_id=uuid.uuid4(), warnings=[])
        )
    assert rec.status == "promoted"
    assert final.source_mirror_circuit_id == circ.id
    assert session.add.call_count >= 2


def test_promote_triple_writes_final():
    t = _triple()
    run = mps.create_promotion_run(
        target_types=["triple"],
        scope_json={},
        scope=mps.PromotionScope(),
        dry_run=False,
        required_confirmation="x",
        operator="op",
        reason="reason",
        confirmation_text="x",
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
    with patch.object(mps, "promote_evidence_for_target", AsyncMock(return_value=1)):
        rec, final = asyncio.run(
            mps.promote_triple(session, obj=t, run=run, review_record_id=uuid.uuid4(), warnings=[])
        )
    assert rec.status == "promoted"
    assert final.source_mirror_triple_id == t.id


def test_promote_evidence_from_mirror_records():
    conn = _connection()
    mev = MirrorEvidenceRecord(
        id=uuid.uuid4(),
        evidence_target_type="mirror_connection",
        evidence_target_id=conn.id,
        evidence_text="mirror evidence",
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mev])))),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    )
    session.add = MagicMock()
    count = asyncio.run(
        mps.promote_evidence_for_target(
            session,
            target_type="connection",
            mirror_obj=conn,
            final_obj_id=uuid.uuid4(),
            review_record_id=uuid.uuid4(),
            promotion_record_id=uuid.uuid4(),
            warnings=[],
        )
    )
    assert count == 1
    session.add.assert_called()


def test_no_llm_imports_in_promotion_service():
    import inspect
    import app.services.mirror_promotion_service as mod

    src = inspect.getsource(mod)
    assert "deepseek" not in src.lower()
    assert "kimi" not in src.lower()
    assert "openai" not in src.lower()
    assert "llm_extraction" not in src
    assert "FinalKgTriple" in src
    assert "FinalRegionConnection" in src


def test_final_kg_list_api():
    client = TestClient(app)
    with patch("app.routers.final_kg.fks.list_final_connections", AsyncMock(return_value=([], 0))):
        with patch("app.database.get_db") as mock_get_db:
            mock_get_db.return_value = AsyncMock()
            resp = client.get("/api/final-kg/connections")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
