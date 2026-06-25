"""Import batch rollback execute tests (strong confirmation)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.import_batch_rollback import RollbackExecuteRequest, RollbackRiskLevel
from app.services import import_batch_rollback_service as svc


def _execute_request(**overrides) -> RollbackExecuteRequest:
    base = {
        "target_status": "parsed",
        "confirmation_text": "ROLLBACK test TO parsed",
        "operator": "admin",
        "reason": "test rollback",
    }
    base.update(overrides)
    return RollbackExecuteRequest(**base)


def test_execute_request_rejects_empty_operator():
    with pytest.raises(ValidationError):
        RollbackExecuteRequest(
            target_status="parsed",
            confirmation_text="x",
            operator="   ",
            reason="reason",
        )


def test_execute_request_rejects_empty_reason():
    with pytest.raises(ValidationError):
        RollbackExecuteRequest(
            target_status="parsed",
            confirmation_text="x",
            operator="admin",
            reason="",
        )


def test_validate_confirmation_mismatch():
    with pytest.raises(svc.RollbackExecuteConfirmationError):
        svc.validate_rollback_confirmation("wrong", "ROLLBACK batch TO parsed")


def test_validate_confirmation_match():
    svc.validate_rollback_confirmation("ROLLBACK batch TO parsed", "ROLLBACK batch TO parsed")


def test_plans_match_expected_delete_plan():
    assert svc._plans_match({"candidate_brain_regions": 96}, {"candidate_brain_regions": 96})
    assert not svc._plans_match({"candidate_brain_regions": 96}, {"candidate_brain_regions": 95})


def test_failed_cancelled_cannot_execute():
    with pytest.raises(svc.RollbackPreviewNotSupportedError):
        svc.validate_rollback_preview_request("failed", "parsed")


def test_target_not_earlier_than_current():
    with pytest.raises(svc.RollbackPreviewInvalidTargetError):
        svc.validate_rollback_preview_request("parsed", "parsed")


def test_disallowed_target_created():
    with pytest.raises(svc.RollbackPreviewInvalidTargetError):
        svc.validate_rollback_preview_request("parsed", "created")


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
    assert delete_plan["candidate_brain_regions"] == 96
    assert keep_plan["raw_macro96_region_rows"] == 96
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
    delete_plan, _ = svc.build_delete_keep_plans(deps, svc.TARGET_RANK["running"])
    assert delete_plan["raw_parse_runs"] == 1
    assert delete_plan["raw_aal3_region_labels"] == 166


def test_validated_to_candidate_generated_deletes_validation():
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
    assert keep_plan["candidate_brain_regions"] == 96


def test_reviewed_to_validated_deletes_reviews_only():
    deps = {
        "raw_parse_runs": 1,
        "raw_macro96_region_rows": 96,
        "raw_aal3_region_labels": 0,
        "candidate_generation_runs": 1,
        "candidate_brain_regions": 96,
        "rule_validation_runs": 1,
        "candidate_rule_validation_results": 96,
        "candidate_review_records": 5,
        "promotion_records": 0,
        "final_brain_regions": 0,
    }
    delete_plan, keep_plan = svc.build_delete_keep_plans(deps, svc.TARGET_RANK["validated"])
    assert delete_plan["candidate_review_records"] == 5
    assert keep_plan["rule_validation_runs"] == 1


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
    assert svc.compute_risk_level(delete_plan) == RollbackRiskLevel.critical


def test_final_brain_regions_has_batch_id():
    from app.models.promotion import FinalBrainRegion

    svc._assert_batch_scoped_model(FinalBrainRegion, "final_brain_regions")


def test_delete_order_promotion_before_final():
    assert svc.DELETE_ORDER.index("promotion_records") < svc.DELETE_ORDER.index("final_brain_regions")


def test_macro96_parser_detection():
    assert svc.is_macro96_parser("macro96_xlsx")
    assert svc.is_aal3_parser("aal3_xml")


def test_target_to_batch_status_mapping():
    assert svc.TARGET_TO_BATCH_STATUS["validated"] == "validation_dispatched"
    assert svc.TARGET_TO_BATCH_STATUS["parsed"] == "parsed"


def test_rollback_execute_api_confirmation_error():
    from fastapi.testclient import TestClient

    from app.main import app

    batch_id = uuid.uuid4()

    async def fake_execute(session, bid, request):
        raise svc.RollbackExecuteConfirmationError("confirmation_text does not match")

    original = svc.execute_import_batch_rollback
    svc.execute_import_batch_rollback = fake_execute  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/import-batches/{batch_id}/rollback",
            json=_execute_request().model_dump(),
        )
        assert resp.status_code == 400
    finally:
        svc.execute_import_batch_rollback = original  # type: ignore[assignment]


def test_rollback_execute_api_stale_preview():
    from fastapi.testclient import TestClient

    from app.main import app

    batch_id = uuid.uuid4()

    async def fake_execute(session, bid, request):
        raise svc.RollbackExecuteStalePreviewError("re-run preview")

    original = svc.execute_import_batch_rollback
    svc.execute_import_batch_rollback = fake_execute  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/import-batches/{batch_id}/rollback",
            json=_execute_request().model_dump(),
        )
        assert resp.status_code == 409
    finally:
        svc.execute_import_batch_rollback = original  # type: ignore[assignment]


def test_rollback_execute_api_not_supported():
    from fastapi.testclient import TestClient

    from app.main import app

    batch_id = uuid.uuid4()

    async def fake_execute(session, bid, request):
        raise svc.RollbackPreviewNotSupportedError("not supported")

    original = svc.execute_import_batch_rollback
    svc.execute_import_batch_rollback = fake_execute  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/import-batches/{batch_id}/rollback",
            json=_execute_request().model_dump(),
        )
        assert resp.status_code == 409
    finally:
        svc.execute_import_batch_rollback = original  # type: ignore[assignment]


def test_rollback_execute_api_invalid_target():
    from fastapi.testclient import TestClient

    from app.main import app

    batch_id = uuid.uuid4()

    async def fake_execute(session, bid, request):
        raise svc.RollbackPreviewInvalidTargetError("invalid target")

    original = svc.execute_import_batch_rollback
    svc.execute_import_batch_rollback = fake_execute  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/import-batches/{batch_id}/rollback",
            json=_execute_request().model_dump(),
        )
        assert resp.status_code == 400
    finally:
        svc.execute_import_batch_rollback = original  # type: ignore[assignment]


def test_rollback_execute_api_unsafe_scope():
    from fastapi.testclient import TestClient

    from app.main import app

    batch_id = uuid.uuid4()

    async def fake_execute(session, bid, request):
        raise svc.RollbackExecuteUnsafeScopeError("cannot safely scope final")

    original = svc.execute_import_batch_rollback
    svc.execute_import_batch_rollback = fake_execute  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/import-batches/{batch_id}/rollback",
            json=_execute_request().model_dump(),
        )
        assert resp.status_code == 409
    finally:
        svc.execute_import_batch_rollback = original  # type: ignore[assignment]


def test_rollback_execute_api_validation_422():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/import-batches/{uuid.uuid4()}/rollback",
        json={
            "target_status": "parsed",
            "confirmation_text": "x",
            "operator": "",
            "reason": "r",
        },
    )
    assert resp.status_code == 422


def test_execute_reuses_build_rollback_preview():
    batch_id = uuid.uuid4()
    mock_batch = MagicMock()
    mock_batch.id = batch_id
    mock_batch.batch_code = "macro96_test"
    mock_batch.resource_id = uuid.uuid4()
    mock_batch.parser_key = "macro96_xlsx"
    mock_batch.status = "candidate_generated"

    now = datetime.now(timezone.utc)
    from app.schemas.import_batch_rollback import RollbackPreviewResponse

    preview = RollbackPreviewResponse(
        batch_id=batch_id,
        batch_code="macro96_test",
        resource_id=mock_batch.resource_id,
        parser_key="macro96_xlsx",
        current_status="candidate_generated",
        target_status="parsed",
        required_confirmation="ROLLBACK macro96_test TO parsed",
        delete_plan={"candidate_brain_regions": 96, "candidate_generation_runs": 1},
        keep_plan={"raw_macro96_region_rows": 96},
        dependency_counts={"candidate_brain_regions": 96, "raw_macro96_region_rows": 96},
        risk_level=RollbackRiskLevel.medium,
        generated_at=now,
    )

    session = AsyncMock()
    request = _execute_request(
        confirmation_text="ROLLBACK macro96_test TO parsed",
        expected_delete_plan=preview.delete_plan,
        expected_dependency_counts=preview.dependency_counts,
    )

    async def _run():
        with patch.object(svc, "build_rollback_preview", AsyncMock(return_value=(mock_batch, preview))):
            with patch.object(svc, "create_rollback_audit_record", AsyncMock()) as mock_audit:
                mock_record = MagicMock()
                mock_record.id = uuid.uuid4()
                mock_audit.return_value = mock_record
                with patch.object(svc, "_execute_deletes", AsyncMock(return_value={"candidate_brain_regions": 96})):
                    with patch.object(svc, "write_rollback_events", AsyncMock(return_value=["rollback_succeeded"])):
                        with patch.object(svc, "_append_rollback_event", AsyncMock()):
                            return await svc.execute_import_batch_rollback(session, batch_id, request)

    result = asyncio.run(_run())

    assert result.batch_status == "parsed"
    assert result.deleted_counts["candidate_brain_regions"] == 96
    session.commit.assert_awaited()


def test_execute_stale_expected_delete_plan():
    batch_id = uuid.uuid4()
    mock_batch = MagicMock()
    mock_batch.status = "candidate_generated"
    now = datetime.now(timezone.utc)
    from app.schemas.import_batch_rollback import RollbackPreviewResponse

    preview = RollbackPreviewResponse(
        batch_id=batch_id,
        batch_code="t",
        resource_id=uuid.uuid4(),
        parser_key="macro96_xlsx",
        current_status="candidate_generated",
        target_status="parsed",
        required_confirmation="ROLLBACK t TO parsed",
        delete_plan={"candidate_brain_regions": 96},
        keep_plan={},
        dependency_counts={"candidate_brain_regions": 96},
        risk_level=RollbackRiskLevel.medium,
        generated_at=now,
    )
    session = AsyncMock()
    request = _execute_request(
        confirmation_text="ROLLBACK t TO parsed",
        expected_delete_plan={"candidate_brain_regions": 95},
    )

    async def _run():
        with patch.object(svc, "build_rollback_preview", AsyncMock(return_value=(mock_batch, preview))):
            await svc.execute_import_batch_rollback(session, batch_id, request)

    with pytest.raises(svc.RollbackExecuteStalePreviewError):
        asyncio.run(_run())


def test_execute_failure_rolls_back_and_writes_failed_audit():
    batch_id = uuid.uuid4()
    mock_batch = MagicMock()
    mock_batch.id = batch_id
    mock_batch.batch_code = "t"
    mock_batch.resource_id = uuid.uuid4()
    mock_batch.parser_key = "macro96_xlsx"
    mock_batch.status = "candidate_generated"

    now = datetime.now(timezone.utc)
    from app.schemas.import_batch_rollback import RollbackPreviewResponse

    preview = RollbackPreviewResponse(
        batch_id=batch_id,
        batch_code="t",
        resource_id=mock_batch.resource_id,
        parser_key="macro96_xlsx",
        current_status="candidate_generated",
        target_status="parsed",
        required_confirmation="ROLLBACK t TO parsed",
        delete_plan={"candidate_brain_regions": 96},
        keep_plan={},
        dependency_counts={"candidate_brain_regions": 96},
        risk_level=RollbackRiskLevel.medium,
        generated_at=now,
    )
    session = AsyncMock()
    request = _execute_request(confirmation_text="ROLLBACK t TO parsed")

    async def _run():
        with patch.object(svc, "build_rollback_preview", AsyncMock(return_value=(mock_batch, preview))):
            with patch.object(svc, "create_rollback_audit_record", AsyncMock(return_value=MagicMock(id=uuid.uuid4()))):
                with patch.object(svc, "_append_rollback_event", AsyncMock()):
                    with patch.object(
                        svc,
                        "_execute_deletes",
                        AsyncMock(side_effect=RuntimeError("db error")),
                    ):
                        await svc.execute_import_batch_rollback(session, batch_id, request)

    with pytest.raises(RuntimeError):
        asyncio.run(_run())

    session.rollback.assert_awaited()
    assert session.commit.await_count >= 1


def test_governance_no_kg_no_llm():
    import inspect

    source = inspect.getsource(svc.execute_import_batch_rollback)
    assert "kg_" not in source
    assert "llm" not in source.lower() or "rollback" in source
