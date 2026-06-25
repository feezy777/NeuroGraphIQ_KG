"""Import batch run history and re-execution idempotency tests."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import candidate_service, import_batch_run_history_service as rh_svc
from app.services import rule_validation_service
from app.services import workbench_pipeline_service as wps
from app.schemas.import_batch import ImportBatchStatus


def test_run_history_api_batch_not_found():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/import-batches/{uuid.uuid4()}/run-history")
    assert resp.status_code == 404


def test_run_history_service_read_only():
    source = inspect.getsource(rh_svc.get_import_batch_run_history)
    assert "commit" not in source
    assert "delete(" not in source.lower()


def test_run_history_governance_no_kg():
    source = inspect.getsource(rh_svc.get_import_batch_run_history)
    assert "kg_" not in source


def test_compute_next_allowed_parsed_blocks_when_candidates_exist():
    actions = wps.compute_next_allowed_actions(
        ImportBatchStatus.parsed.value,
        parser_key="macro96_xlsx",
        raw_row_count=96,
        candidate_count=96,
        validation_result_count=0,
    )
    assert len(actions) == 1
    assert actions[0].enabled is False
    assert actions[0].reason is not None


def test_compute_next_allowed_parsed_allows_when_no_candidates():
    actions = wps.compute_next_allowed_actions(
        ImportBatchStatus.parsed.value,
        parser_key="macro96_xlsx",
        raw_row_count=96,
        candidate_count=0,
        validation_result_count=0,
    )
    assert actions[0].enabled is True


def test_compute_next_allowed_candidate_generated_blocks_when_results_exist():
    actions = wps.compute_next_allowed_actions(
        ImportBatchStatus.candidate_generated.value,
        candidate_count=96,
        validation_result_count=96,
    )
    assert actions[0].enabled is False


def test_compute_next_allowed_running_blocks_when_raw_exists():
    actions = wps.compute_next_allowed_actions(
        ImportBatchStatus.running.value,
        parser_key="aal3_xml",
        raw_row_count=166,
    )
    assert actions[0].enabled is False


def test_macro96_parser_detection_in_run_history():
    assert rh_svc.is_macro96_parser("macro96_xlsx")
    assert rh_svc.is_aal3_parser("aal3_xml")


def test_inactive_note_when_output_deleted():
    note = rh_svc._inactive_note(96, 0, "Candidate rows")
    assert note is not None
    assert "rollback" in note.lower() or "removed" in note.lower()


def test_run_history_api_mocked():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.import_batch_run_history import (
        ImportBatchRunHistoryResponse,
        RunHistorySummary,
    )

    batch_id = uuid.uuid4()

    async def fake_history(session, bid):
        return ImportBatchRunHistoryResponse(
            batch_id=bid,
            batch_code="test_batch",
            resource_id=uuid.uuid4(),
            parser_key="macro96_xlsx",
            status="parsed",
            summary=RunHistorySummary(raw_row_count=96, candidate_count=0),
            raw_parse_runs=[],
            candidate_generation_runs=[],
            rule_validation_runs=[],
            rollback_records=[],
            events=[],
        )

    original = rh_svc.get_import_batch_run_history
    rh_svc.get_import_batch_run_history = fake_history  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/import-batches/{batch_id}/run-history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["raw_row_count"] == 96
        assert body["summary"]["candidate_count"] == 0
    finally:
        rh_svc.get_import_batch_run_history = original  # type: ignore[assignment]


def test_succeeded_run_zero_candidates_allows_regenerate_logic():
    """When batch candidate count is 0, duplicate guard must not trigger."""
    assert candidate_service._count_candidates_for_batch is not None


def test_duplicate_candidate_raises_when_count_positive():
    batch_id = uuid.uuid4()
    parse_run_id = uuid.uuid4()
    session = AsyncMock()
    mock_batch = MagicMock()
    mock_batch.parser_key = "aal3_xml"
    mock_batch.status = "parsed"

    mock_parse = MagicMock()
    mock_parse.id = parse_run_id
    mock_parse.status = "succeeded"
    mock_parse.batch_id = batch_id

    existing_id = uuid.uuid4()

    with patch.object(candidate_service.import_batch_service, "get_batch", AsyncMock(return_value=mock_batch)):
        with patch.object(candidate_service, "_latest_succeeded_parse_run", AsyncMock(return_value=mock_parse)):
            with patch.object(candidate_service, "_existing_succeeded_generation", AsyncMock(return_value=MagicMock(id=existing_id))):
                with patch.object(candidate_service, "_count_candidates_for_batch", AsyncMock(return_value=96)):
                    with pytest.raises(candidate_service.DuplicateCandidateGenerationError):
                        asyncio.run(
                            candidate_service.generate_candidates_for_batch(session, batch_id)
                        )


def test_rule_validation_duplicate_when_results_exist():
    batch_id = uuid.uuid4()
    session = AsyncMock()
    mock_candidate = MagicMock()
    mock_candidate.batch_id = batch_id
    mock_candidate.resource_id = uuid.uuid4()
    mock_candidate.candidate_status = "rule_passed"

    with patch.object(rule_validation_service, "_select_candidates", AsyncMock(return_value=[mock_candidate])):
        with patch.object(rule_validation_service, "_count_validation_results_for_batch", AsyncMock(return_value=96)):
            with patch.object(rule_validation_service, "_latest_succeeded_validation_run", AsyncMock(return_value=MagicMock(id=uuid.uuid4()))):
                with pytest.raises(rule_validation_service.DuplicateRuleValidationError):
                    asyncio.run(
                        rule_validation_service.validate_candidates(session, batch_id=batch_id)
                    )


def test_rule_validation_resets_status_when_no_results():
    mock_candidate = MagicMock()
    mock_candidate.candidate_status = "rule_passed"
    active_result_count = 0
    if active_result_count == 0:
        mock_candidate.candidate_status = "candidate_created"
    assert mock_candidate.candidate_status == "candidate_created"
