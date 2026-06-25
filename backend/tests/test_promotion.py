"""Promotion to final_* Module tests (no PostgreSQL required)."""

import uuid

import pytest

from app.schemas.candidate import (
    CandidateStatus,
    InvalidCandidateTransitionError,
    validate_candidate_transition,
)
from app.schemas.promotion import FinalRegionStatus, PromotionStatus
from app.services import promotion_service as ps


# ---------------------------------------------------------------------------
# Candidate state machine: promoted_to_final transitions
# ---------------------------------------------------------------------------

def test_manual_approved_can_transition_to_promoted_to_final():
    validate_candidate_transition(
        CandidateStatus.manual_approved, CandidateStatus.promoted_to_final
    )


def test_promoted_to_final_can_transition_to_archived():
    validate_candidate_transition(
        CandidateStatus.promoted_to_final, CandidateStatus.archived
    )


def test_manual_approved_is_in_candidate_status_enum():
    assert CandidateStatus.promoted_to_final.value == "promoted_to_final"


def test_rule_passed_cannot_promote_directly():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.rule_passed, CandidateStatus.promoted_to_final
        )


def test_manual_review_pending_cannot_promote():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.manual_review_pending, CandidateStatus.promoted_to_final
        )


def test_manual_rejected_cannot_promote():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.manual_rejected, CandidateStatus.promoted_to_final
        )


def test_candidate_created_cannot_promote():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.candidate_created, CandidateStatus.promoted_to_final
        )


def test_rule_failed_cannot_promote():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.rule_failed, CandidateStatus.promoted_to_final
        )


# ---------------------------------------------------------------------------
# Exception shapes
# ---------------------------------------------------------------------------

def test_candidate_not_promotable_error_carries_status():
    cid = uuid.uuid4()
    err = ps.CandidateNotPromotableError(cid, "rule_passed")
    assert err.candidate_id == cid
    assert err.current_status == "rule_passed"
    assert "only manual_approved" in str(err)


def test_already_promoted_error_carries_ids():
    cid, fid = uuid.uuid4(), uuid.uuid4()
    err = ps.AlreadyPromotedError(cid, fid)
    assert err.candidate_id == cid
    assert err.final_region_id == fid


# ---------------------------------------------------------------------------
# Schema enums
# ---------------------------------------------------------------------------

def test_promotion_status_enum():
    assert {e.value for e in PromotionStatus} == {"running", "succeeded", "failed"}


def test_final_region_status_enum():
    assert {e.value for e in FinalRegionStatus} == {"active", "archived"}


# ---------------------------------------------------------------------------
# API / health endpoints
# ---------------------------------------------------------------------------

def test_promotion_options_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/promotion/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "running" in body["promotion_status"]
    assert "succeeded" in body["promotion_status"]
    assert "active" in body["final_region_status"]
    assert body["promotable_candidate_status"] == "manual_approved"
    assert body["promoted_candidate_status"] == "promoted_to_final"


def test_health_reports_promotion_module():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["modules"]["promotion"] == "active"
    assert "mvp" in body["version"]
    assert body["modules"].get("final_db_query") == "active"


def test_all_prior_options_endpoints_still_work():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/resources/options").status_code == 200
    assert client.get("/api/files/options").status_code == 200
    assert client.get("/api/import-batches/options").status_code == 200
    assert client.get("/api/raw-parsing/options").status_code == 200
    assert client.get("/api/candidates/options").status_code == 200
    assert client.get("/api/rule-validation/options").status_code == 200
    assert client.get("/api/human-review/options").status_code == 200
