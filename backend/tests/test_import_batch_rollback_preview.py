"""Import batch rollback preview tests (read-only; no DB mutations)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.schemas.import_batch_rollback import RollbackRiskLevel
from app.services import import_batch_rollback_service as svc


def test_validate_target_must_be_earlier():
    with pytest.raises(svc.RollbackPreviewInvalidTargetError):
        svc.validate_rollback_preview_request("candidate_generated", "candidate_generated")
    with pytest.raises(svc.RollbackPreviewInvalidTargetError):
        svc.validate_rollback_preview_request("parsed", "parsed")
    svc.validate_rollback_preview_request("parsed", "running")


def test_validate_disallowed_targets():
    with pytest.raises(svc.RollbackPreviewInvalidTargetError):
        svc.validate_rollback_preview_request("parsed", "created")
    with pytest.raises(svc.RollbackPreviewInvalidTargetError):
        svc.validate_rollback_preview_request("parsed", "queued")


def test_validate_failed_cancelled_archived_409():
    with pytest.raises(svc.RollbackPreviewNotSupportedError):
        svc.validate_rollback_preview_request("failed", "parsed")
    with pytest.raises(svc.RollbackPreviewNotSupportedError):
        svc.validate_rollback_preview_request("cancelled", "parsed")
    with pytest.raises(svc.RollbackPreviewNotSupportedError):
        svc.validate_rollback_preview_request("archived", "parsed")


def test_candidate_generated_to_parsed_delete_plan():
    deps = {
        "raw_parse_runs": 1,
        "raw_aal3_region_labels": 0,
        "raw_macro96_region_rows": 96,
        "candidate_generation_runs": 1,
        "candidate_brain_regions": 96,
        "rule_validation_runs": 1,
        "candidate_rule_validation_results": 96,
        "candidate_review_records": 0,
        "promotion_records": 0,
        "final_brain_regions": 0,
    }
    delete_plan, keep_plan = svc.build_delete_keep_plans(deps, svc.TARGET_RANK["parsed"])
    assert delete_plan["candidate_generation_runs"] == 1
    assert delete_plan["candidate_brain_regions"] == 96
    assert delete_plan["rule_validation_runs"] == 1
    assert delete_plan["candidate_rule_validation_results"] == 96
    assert keep_plan["raw_macro96_region_rows"] == 96
    assert keep_plan["raw_parse_runs"] == 1
    assert delete_plan["raw_macro96_region_rows"] == 0


def test_parsed_to_running_deletes_raw():
    deps = {
        "raw_parse_runs": 1,
        "raw_aal3_region_labels": 166,
        "raw_macro96_region_rows": 0,
        "candidate_generation_runs": 0,
        "candidate_brain_regions": 0,
        "rule_validation_runs": 0,
        "candidate_rule_validation_results": 0,
        "candidate_review_records": 0,
        "promotion_records": 0,
        "final_brain_regions": 0,
    }
    delete_plan, keep_plan = svc.build_delete_keep_plans(deps, svc.TARGET_RANK["running"])
    assert delete_plan["raw_parse_runs"] == 1
    assert delete_plan["raw_aal3_region_labels"] == 166
    assert keep_plan["raw_parse_runs"] == 0


def test_validated_to_candidate_generated_deletes_validation_only():
    deps = {
        "raw_parse_runs": 1,
        "raw_macro96_region_rows": 96,
        "raw_aal3_region_labels": 0,
        "candidate_generation_runs": 1,
        "candidate_brain_regions": 96,
        "rule_validation_runs": 2,
        "candidate_rule_validation_results": 96,
        "candidate_review_records": 0,
        "promotion_records": 0,
        "final_brain_regions": 0,
    }
    delete_plan, keep_plan = svc.build_delete_keep_plans(
        deps, svc.TARGET_RANK["candidate_generated"]
    )
    assert delete_plan["rule_validation_runs"] == 2
    assert delete_plan["candidate_rule_validation_results"] == 96
    assert keep_plan["candidate_brain_regions"] == 96


def test_promoted_to_reviewed_deletes_final():
    deps = {
        "raw_parse_runs": 1,
        "raw_macro96_region_rows": 96,
        "raw_aal3_region_labels": 0,
        "candidate_generation_runs": 1,
        "candidate_brain_regions": 96,
        "rule_validation_runs": 1,
        "candidate_rule_validation_results": 96,
        "candidate_review_records": 3,
        "promotion_records": 3,
        "final_brain_regions": 3,
    }
    delete_plan, _ = svc.build_delete_keep_plans(deps, svc.TARGET_RANK["reviewed"])
    assert delete_plan["promotion_records"] == 3
    assert delete_plan["final_brain_regions"] == 3
    assert delete_plan["candidate_review_records"] == 0
    assert svc.compute_risk_level(delete_plan) == RollbackRiskLevel.critical


def test_risk_level_medium_for_candidates():
    delete_plan = {k: 0 for k in svc.PLAN_KEYS}
    delete_plan["candidate_brain_regions"] = 96
    assert svc.compute_risk_level(delete_plan) == RollbackRiskLevel.medium


def test_rollback_preview_api_batch_not_found():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    missing = uuid.uuid4()
    resp = client.get(
        f"/api/import-batches/{missing}/rollback-preview",
        params={"target_status": "parsed"},
    )
    assert resp.status_code == 404


def test_rollback_preview_api_invalid_target():
    from fastapi.testclient import TestClient

    from app.main import app

    batch_id = uuid.uuid4()

    async def fake_preview(session, bid, target_status):
        raise svc.RollbackPreviewInvalidTargetError("invalid target_status: 'created'")

    original = svc.get_import_batch_rollback_preview
    svc.get_import_batch_rollback_preview = fake_preview  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            f"/api/import-batches/{batch_id}/rollback-preview",
            params={"target_status": "created"},
        )
        assert resp.status_code == 400
    finally:
        svc.get_import_batch_rollback_preview = original  # type: ignore[assignment]


def test_rollback_preview_api_mocked_macro96():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.import_batch_rollback import RollbackPreviewResponse, RollbackRiskLevel

    batch_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async def fake_preview(session, bid, target_status):
        assert target_status == "parsed"
        return RollbackPreviewResponse(
            batch_id=bid,
            batch_code="macro96_test",
            resource_id=uuid.uuid4(),
            parser_key="macro96_xlsx",
            current_status="candidate_generated",
            target_status="parsed",
            required_confirmation="ROLLBACK macro96_test TO parsed",
            delete_plan={
                "candidate_generation_runs": 1,
                "candidate_brain_regions": 96,
                "raw_macro96_region_rows": 0,
            },
            keep_plan={"raw_macro96_region_rows": 96, "raw_parse_runs": 1},
            dependency_counts={"raw_macro96_region_rows": 96, "candidate_brain_regions": 96},
            risk_level=RollbackRiskLevel.medium,
            generated_at=now,
        )

    original = svc.get_import_batch_rollback_preview
    svc.get_import_batch_rollback_preview = fake_preview  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            f"/api/import-batches/{batch_id}/rollback-preview",
            params={"target_status": "parsed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["parser_key"] == "macro96_xlsx"
        assert body["keep_plan"]["raw_macro96_region_rows"] == 96
        assert body["delete_plan"]["candidate_brain_regions"] == 96
    finally:
        svc.get_import_batch_rollback_preview = original  # type: ignore[assignment]


def test_preview_does_not_mutate_batch_status():
    """Service module has no commit/flush — verify no write helpers are called."""
    import inspect

    source = inspect.getsource(svc.get_import_batch_rollback_preview)
    assert "commit" not in source
    assert "delete" not in source.lower() or "delete_plan" in source
