"""Mirror KG Human Review Queue tests (no LLM, no network)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.mirror_kg import MirrorRegionConnection
from app.models.mirror_review import MirrorHumanReviewRecord
from app.models.mirror_validation import MirrorRuleValidationResult
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_review import MirrorReviewAction
from app.services import mirror_review_service as mrs


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
        mirror_status=MirrorStatus.rule_checked,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def _validation_result(target_id: uuid.UUID, *, severity: str = "warning", rule_code: str = "RULE_TEST") -> MirrorRuleValidationResult:
    return MirrorRuleValidationResult(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        target_type="connection",
        target_id=target_id,
        rule_code=rule_code,
        severity=severity,
        status="warning" if severity == "warning" else "blocked",
        message="test",
    )


def test_validate_eligibility_not_validated_raises():
    conn = _connection()
    with pytest.raises(mrs.MirrorObjectNotValidatedError):
        mrs.validate_review_eligibility(
            MirrorReviewAction.approve, "connection", conn, {"validated": False}, allow_with_warnings=True
        )


def test_validate_eligibility_blocker_raises():
    conn = _connection()
    with pytest.raises(mrs.MirrorObjectHasBlockersError):
        mrs.validate_review_eligibility(
            MirrorReviewAction.approve,
            "connection",
            conn,
            {"validated": True, "has_blocker": True, "has_error": False},
            allow_with_warnings=True,
        )


def test_validate_eligibility_warning_allowed():
    conn = _connection()
    warnings = mrs.validate_review_eligibility(
        MirrorReviewAction.approve,
        "connection",
        conn,
        {"validated": True, "has_blocker": False, "has_error": False, "has_warning": True},
        allow_with_warnings=True,
        reviewer_note="acknowledged",
    )
    assert warnings


def test_edit_whitelist_only():
    conn = _connection()
    mrs.apply_safe_edit_patch("connection", conn, {"confidence": 0.9})
    assert float(conn.confidence) == 0.9


def test_edit_forbidden_provenance():
    conn = _connection()
    with pytest.raises(mrs.ForbiddenEditFieldError):
        mrs.apply_safe_edit_patch("connection", conn, {"resource_id": uuid.uuid4()})


def test_approve_updates_status():
    conn = _connection()
    target_id = conn.id
    val_result = _validation_result(target_id, severity="info", rule_code="RULE_INFO")

    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[val_result])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    record, updated, _ = asyncio.run(
        mrs.perform_mirror_review_action(
            session,
            target_type="connection",
            target_id=target_id,
            action=MirrorReviewAction.approve,
            reviewer="reviewer1",
        )
    )
    assert conn.mirror_status == MirrorStatus.human_approved
    assert conn.review_status == MirrorReviewStatus.approved
    assert conn.promotion_status == MirrorPromotionStatus.not_promoted
    assert updated["mirror_status"] == MirrorStatus.human_approved
    session.commit.assert_called_once()
    assert isinstance(record, MirrorHumanReviewRecord)


def test_approve_not_promoted():
    conn = _connection()
    val_result = _validation_result(conn.id, severity="info")
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[val_result])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    asyncio.run(
        mrs.perform_mirror_review_action(
            session,
            target_type="connection",
            target_id=conn.id,
            action=MirrorReviewAction.approve,
            reviewer="r1",
        )
    )
    assert conn.promotion_status != MirrorPromotionStatus.promoted


def test_reject_requires_note():
    conn = _connection()
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    with pytest.raises(mrs.ReviewerNoteRequiredError):
        asyncio.run(
            mrs.perform_mirror_review_action(
                session,
                target_type="connection",
                target_id=conn.id,
                action=MirrorReviewAction.reject,
                reviewer="r1",
            )
        )


def test_reject_sets_blocked():
    conn = _connection()
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    asyncio.run(
        mrs.perform_mirror_review_action(
            session,
            target_type="connection",
            target_id=conn.id,
            action=MirrorReviewAction.reject,
            reviewer="r1",
            reviewer_note="bad connection",
        )
    )
    assert conn.mirror_status == MirrorStatus.human_rejected
    assert conn.review_status == MirrorReviewStatus.rejected
    assert conn.promotion_status == MirrorPromotionStatus.blocked


def test_needs_revision_requires_note():
    conn = _connection()
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    with pytest.raises(mrs.ReviewerNoteRequiredError):
        asyncio.run(
            mrs.perform_mirror_review_action(
                session,
                target_type="connection",
                target_id=conn.id,
                action=MirrorReviewAction.needs_revision,
                reviewer="r1",
            )
        )


def test_needs_revision_updates_status():
    conn = _connection()
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    asyncio.run(
        mrs.perform_mirror_review_action(
            session,
            target_type="connection",
            target_id=conn.id,
            action=MirrorReviewAction.needs_revision,
            reviewer="r1",
            reviewer_note="fix evidence",
        )
    )
    assert conn.review_status == MirrorReviewStatus.needs_revision
    assert conn.mirror_status == MirrorStatus.human_review_pending


def test_edit_sets_needs_revision():
    conn = _connection()
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    _, _, warnings = asyncio.run(
        mrs.perform_mirror_review_action(
            session,
            target_type="connection",
            target_id=conn.id,
            action=MirrorReviewAction.edit,
            reviewer="r1",
            edit_patch_json={"confidence": 0.95},
        )
    )
    assert conn.review_status == MirrorReviewStatus.needs_revision
    assert any("re-validation" in w for w in warnings)


def test_comment_no_status_change():
    conn = _connection()
    orig_ms = conn.mirror_status
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    asyncio.run(
        mrs.perform_mirror_review_action(
            session,
            target_type="connection",
            target_id=conn.id,
            action=MirrorReviewAction.comment,
            reviewer="r1",
            reviewer_note="looks ok",
        )
    )
    assert conn.mirror_status == orig_ms


def test_promoted_cannot_review():
    conn = _connection(promotion_status=MirrorPromotionStatus.promoted)
    with pytest.raises(mrs.TargetAlreadyPromotedError):
        mrs.validate_review_eligibility(
            MirrorReviewAction.approve,
            "connection",
            conn,
            {"validated": True, "has_blocker": False, "has_error": False},
        )


def test_api_approve_not_validated_409():
    from app.main import app

    conn = _connection()
    client = TestClient(app)
    with patch("app.services.mirror_review_service.get_target", new_callable=AsyncMock, return_value=conn):
        with patch(
            "app.services.mirror_review_service.get_latest_validation_summary",
            new_callable=AsyncMock,
            return_value={"validated": False, "has_blocker": False, "has_error": False},
        ):
            with patch(
                "app.services.mirror_review_service.get_evidence_summary",
                new_callable=AsyncMock,
                return_value={"count": 0, "records": []},
            ):
                resp = client.post(
                    "/api/mirror-kg/review/action",
                    json={
                        "target_type": "connection",
                        "target_id": str(conn.id),
                        "action": "approve",
                        "reviewer": "r1",
                    },
                )
    assert resp.status_code == 409


def test_no_llm_called():
    with patch("app.services.mirror_review_service.perform_mirror_review_action", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = (MagicMock(id=uuid.uuid4()), {}, [])
        asyncio.run(mock_fn(AsyncMock(), target_type="connection", target_id=uuid.uuid4(), action="comment", reviewer="r"))
        mock_fn.assert_called_once()


def test_api_reject_no_note_400():
    from app.main import app

    client = TestClient(app)
    with patch(
        "app.routers.mirror_review.mrs.perform_mirror_review_action",
        new_callable=AsyncMock,
        side_effect=mrs.ReviewerNoteRequiredError(),
    ):
        resp = client.post(
            "/api/mirror-kg/review/action",
            json={
                "target_type": "connection",
                "target_id": str(uuid.uuid4()),
                "action": "reject",
                "reviewer": "r1",
            },
        )
    assert resp.status_code == 400


def test_api_invalid_target_type_400():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/mirror-kg/review/action",
        json={
            "target_type": "invalid",
            "target_id": str(uuid.uuid4()),
            "action": "comment",
            "reviewer": "r1",
            "reviewer_note": "x",
        },
    )
    assert resp.status_code == 400
