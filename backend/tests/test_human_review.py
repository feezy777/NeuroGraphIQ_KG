"""Human Review Module tests (no PostgreSQL required)."""

import uuid
from types import SimpleNamespace

import pytest

from app.schemas.candidate import (
    CandidateStatus,
    InvalidCandidateTransitionError,
    validate_candidate_transition,
)
from app.schemas.human_review import REVIEW_DECISION_ACTIONS, ReviewAction
from app.services import human_review_service as hrs


def _candidate(**overrides):
    base = dict(
        id=uuid.uuid4(),
        raw_name="Precentral_L",
        std_name="Precentral_L",
        en_name="Precentral_L",
        cn_name=None,
        laterality="left",
        region_base_name="Precentral",
        label_value=1,
        source_label_id="1",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_review_action_enum_values():
    assert {e.value for e in ReviewAction} == {
        "submit",
        "approve",
        "reject",
        "request_changes",
        "mark_uncertain",
    }


def test_submit_is_not_a_decision_action():
    assert ReviewAction.submit not in REVIEW_DECISION_ACTIONS
    assert ReviewAction.approve in REVIEW_DECISION_ACTIONS
    assert ReviewAction.reject in REVIEW_DECISION_ACTIONS
    assert ReviewAction.request_changes in REVIEW_DECISION_ACTIONS
    assert ReviewAction.mark_uncertain in REVIEW_DECISION_ACTIONS


def test_decision_target_mapping():
    assert hrs._DECISION_TARGET[ReviewAction.approve] == CandidateStatus.manual_approved
    assert hrs._DECISION_TARGET[ReviewAction.reject] == CandidateStatus.manual_rejected
    # request_changes / mark_uncertain keep the candidate pending (no status move).
    assert hrs._DECISION_TARGET[ReviewAction.request_changes] is None
    assert hrs._DECISION_TARGET[ReviewAction.mark_uncertain] is None


def test_snapshot_captures_key_fields():
    snap = hrs._snapshot(_candidate())
    assert snap["raw_name"] == "Precentral_L"
    assert snap["candidate_status"] == "rule_passed"
    assert snap["laterality"] == "left"
    assert snap["label_value"] == 1


def test_record_builder_preserves_lineage():
    cand = _candidate()
    rec = hrs._record(
        cand,
        action=ReviewAction.submit,
        from_status="rule_passed",
        to_status="manual_review_pending",
        reviewed_by="alice",
        reason="looks good",
    )
    assert rec.candidate_id == cand.id
    assert rec.batch_id == cand.batch_id
    assert rec.resource_id == cand.resource_id
    assert rec.generation_run_id == cand.generation_run_id
    assert rec.parse_run_id == cand.parse_run_id
    assert rec.action == "submit"
    assert rec.reviewed_by == "alice"


def test_rule_passed_can_be_submitted_to_review():
    validate_candidate_transition(
        CandidateStatus.rule_passed, CandidateStatus.manual_review_pending
    )


def test_pending_can_be_approved_or_rejected():
    validate_candidate_transition(
        CandidateStatus.manual_review_pending, CandidateStatus.manual_approved
    )
    validate_candidate_transition(
        CandidateStatus.manual_review_pending, CandidateStatus.manual_rejected
    )


def test_candidate_created_cannot_reach_review():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.candidate_created, CandidateStatus.manual_review_pending
        )


def test_rule_failed_cannot_directly_approve():
    # rule_failed must go through manual_review_pending; never straight to approved.
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.rule_failed, CandidateStatus.manual_approved
        )


def test_pending_cannot_skip_to_archived():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.manual_review_pending, CandidateStatus.archived
        )


def test_human_review_options_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/human-review/options")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["actions"]) == {
        "submit",
        "approve",
        "reject",
        "request_changes",
        "mark_uncertain",
    }
    assert "submit" not in body["decision_actions"]
    assert body["pending_status"] == "manual_review_pending"
    assert body["approved_status"] == "manual_approved"
    assert body["rejected_status"] == "manual_rejected"


def test_health_reports_human_review_module():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["modules"]["human_review"] == "active"
    assert "mvp" in body["version"]
    assert body["modules"].get("promotion") == "active"


def test_prior_options_endpoints_still_work():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/resources/options").status_code == 200
    assert client.get("/api/files/options").status_code == 200
    assert client.get("/api/import-batches/options").status_code == 200
    assert client.get("/api/raw-parsing/options").status_code == 200
    assert client.get("/api/candidates/options").status_code == 200
    assert client.get("/api/rule-validation/options").status_code == 200
