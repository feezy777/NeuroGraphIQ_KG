"""Candidate DB Module tests (no PostgreSQL required)."""

import uuid

import pytest

from app.schemas.candidate import (
    CandidateGenStatus,
    CandidateStatus,
    InvalidCandidateTransitionError,
    validate_candidate_transition,
)
from app.schemas.import_batch import (
    ImportBatchStatus,
    validate_import_batch_transition,
)
from app.services.candidate_service import (
    DuplicateCandidateGenerationError,
    GENERATOR_KEY,
)


def test_candidate_status_enum_members():
    assert CandidateStatus.candidate_created.value == "candidate_created"
    assert CandidateStatus.manual_approved.value == "manual_approved"
    assert CandidateStatus.archived.value == "archived"


def test_candidate_status_distinct_from_approval():
    assert CandidateStatus.candidate_created != CandidateStatus.manual_approved
    assert CandidateStatus.candidate_created.value != "promoted_to_final"


def test_candidate_gen_status_enum():
    assert {e.value for e in CandidateGenStatus} == {
        "created",
        "running",
        "succeeded",
        "failed",
    }


def test_created_to_rule_validating_allowed():
    validate_candidate_transition(
        CandidateStatus.candidate_created, CandidateStatus.rule_validating
    )


def test_created_cannot_jump_to_manual_approved():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.candidate_created, CandidateStatus.manual_approved
        )


def test_review_pending_to_approved_allowed():
    validate_candidate_transition(
        CandidateStatus.manual_review_pending, CandidateStatus.manual_approved
    )


def test_terminal_rejected_blocked():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.manual_rejected, CandidateStatus.manual_review_pending
        )


def test_terminal_archived_blocked():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.archived, CandidateStatus.candidate_created
        )


def test_same_status_blocked():
    with pytest.raises(InvalidCandidateTransitionError):
        validate_candidate_transition(
            CandidateStatus.candidate_created, CandidateStatus.candidate_created
        )


def test_candidate_status_string_input_accepted():
    validate_candidate_transition("rule_validating", "rule_passed")


def test_parsed_to_candidate_generated_allowed():
    validate_import_batch_transition(
        ImportBatchStatus.parsed, ImportBatchStatus.candidate_generated
    )


def test_generator_key_constant():
    assert GENERATOR_KEY == "aal3_region_candidate"


def test_duplicate_candidate_generation_error_shape():
    bid = uuid.uuid4()
    prid = uuid.uuid4()
    rid = uuid.uuid4()
    err = DuplicateCandidateGenerationError(bid, prid, rid)
    assert err.batch_id == bid
    assert err.parse_run_id == prid
    assert err.existing_run_id == rid


def test_candidate_options_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/candidates/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "candidate_created" in body["candidate_status"]
    assert "succeeded" in body["generation_run_status"]
    assert "left" in body["laterality"]


def test_health_reports_candidate_module():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["modules"]["candidate_db"] == "active"
    assert "mvp" in body["version"]


def test_prior_options_endpoints_still_work():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/resources/options").status_code == 200
    assert client.get("/api/files/options").status_code == 200
    assert client.get("/api/import-batches/options").status_code == 200
    assert client.get("/api/raw-parsing/options").status_code == 200
