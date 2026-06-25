"""Rule Validation Module tests (no PostgreSQL required)."""

import uuid
from types import SimpleNamespace

import pytest

from app.schemas.candidate import CandidateStatus, validate_candidate_transition
from app.schemas.rule_validation import (
    RULE_CATALOGUE,
    CandidateRuleStatus,
    RuleSeverity,
    RuleValidationRunStatus,
    ValidationScope,
)
from app.services import rule_validation_service as rvs


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
        candidate_status="candidate_created",
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        row_index=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_clean_candidate_passes_no_warnings():
    checks = rvs.evaluate_candidate(_candidate())
    overall, errors, warnings, info = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.passed.value
    assert errors == 0
    assert warnings == 0


def test_empty_raw_name_is_error_and_fails():
    checks = rvs.evaluate_candidate(_candidate(raw_name="  "))
    overall, errors, _, _ = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.failed.value
    assert errors >= 1
    empty = next(c for c in checks if c["rule_id"] == "raw_name_not_empty")
    assert empty["passed"] is False
    assert empty["severity"] == RuleSeverity.error.value


def test_invalid_laterality_is_error():
    checks = rvs.evaluate_candidate(_candidate(laterality="sideways"))
    overall, errors, _, _ = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.failed.value
    assert errors >= 1


def test_missing_granularity_is_error():
    checks = rvs.evaluate_candidate(_candidate(granularity_level="", granularity_family=""))
    overall, errors, _, _ = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.failed.value
    assert errors >= 1


def test_unknown_laterality_is_warning_not_failure():
    checks = rvs.evaluate_candidate(_candidate(laterality="unknown"))
    overall, errors, warnings, _ = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.passed.value
    assert errors == 0
    assert warnings >= 1


def test_missing_std_name_is_warning():
    checks = rvs.evaluate_candidate(_candidate(std_name=None))
    overall, errors, warnings, _ = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.passed.value
    assert warnings >= 1


def test_missing_source_id_is_warning():
    checks = rvs.evaluate_candidate(_candidate(source_label_id=None, label_value=None))
    overall, _, warnings, _ = rvs.summarize_checks(checks)
    assert overall == CandidateRuleStatus.passed.value
    assert warnings >= 1


def test_duplicate_label_value_flagged_as_warning_not_merged():
    c = _candidate(label_value=5)
    checks = rvs.evaluate_candidate(c, duplicate_label_values=frozenset({5}))
    dup = next(c for c in checks if c["rule_id"] == "unique_label_value_in_run")
    assert dup["passed"] is False
    assert dup["severity"] == RuleSeverity.warning.value


def test_duplicates_helper_detects_repeats():
    cands = [
        _candidate(label_value=1, region_base_name="Precentral", laterality="left"),
        _candidate(label_value=1, region_base_name="Precentral", laterality="left"),
        _candidate(label_value=2, region_base_name="Frontal", laterality="right"),
    ]
    dup_labels, dup_names = rvs._duplicates(cands)
    assert 1 in dup_labels
    assert 2 not in dup_labels
    assert ("precentral", "left") in dup_names


def test_resolve_scope_requires_exactly_one():
    with pytest.raises(rvs.ValidationScopeError):
        rvs._resolve_scope(
            candidate_id=None, generation_run_id=None, batch_id=None, parse_run_id=None
        )
    with pytest.raises(rvs.ValidationScopeError):
        rvs._resolve_scope(
            candidate_id=uuid.uuid4(),
            generation_run_id=uuid.uuid4(),
            batch_id=None,
            parse_run_id=None,
        )


def test_resolve_scope_single_value():
    assert (
        rvs._resolve_scope(
            candidate_id=None,
            generation_run_id=None,
            batch_id=uuid.uuid4(),
            parse_run_id=None,
        )
        == ValidationScope.batch
    )


def test_candidate_transition_rule_validating_to_passed():
    validate_candidate_transition(
        CandidateStatus.candidate_created, CandidateStatus.rule_validating
    )
    validate_candidate_transition(
        CandidateStatus.rule_validating, CandidateStatus.rule_passed
    )
    validate_candidate_transition(
        CandidateStatus.rule_validating, CandidateStatus.rule_failed
    )


def test_rule_catalogue_non_empty_and_unique_ids():
    ids = [r.rule_id for r in RULE_CATALOGUE]
    assert len(ids) == len(set(ids))
    assert "raw_name_not_empty" in ids


def test_run_status_enum():
    assert {e.value for e in RuleValidationRunStatus} == {
        "created",
        "running",
        "succeeded",
        "failed",
    }


def test_rule_validation_options_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/rule-validation/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "batch" in body["scope"]
    assert "error" in body["severity"]
    assert "passed" in body["candidate_rule_status"]
    assert any(r["rule_id"] == "raw_name_not_empty" for r in body["rules"])


def test_health_reports_rule_validation_module():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["modules"]["rule_validation"] == "active"
    assert "mvp" in body["version"]


def test_prior_options_endpoints_still_work():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/resources/options").status_code == 200
    assert client.get("/api/files/options").status_code == 200
    assert client.get("/api/import-batches/options").status_code == 200
    assert client.get("/api/raw-parsing/options").status_code == 200
    assert client.get("/api/candidates/options").status_code == 200
