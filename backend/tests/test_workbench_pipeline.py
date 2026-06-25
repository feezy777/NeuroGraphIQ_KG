"""Workbench Pipeline overview tests (no PostgreSQL required).

Covers:
- next_allowed_actions pure function for all batch statuses
- PipelineAction schema
- ImportBatchPipelineOverview field presence
- Confirms no final_* / kg_* writes (structural check only)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.schemas.import_batch import ImportBatchStatus
from app.schemas.workbench_pipeline import (
    BoundFilePipelineRead,
    ImportBatchPipelineOverview,
    LatestValidationSummary,
    PipelineAction,
)
from app.services.workbench_pipeline_service import compute_next_allowed_actions


# ── compute_next_allowed_actions pure function ─────────────────────────────────

def test_created_allows_queue_batch():
    actions = compute_next_allowed_actions(ImportBatchStatus.created.value)
    assert len(actions) == 1
    assert actions[0].action == "queue_batch"
    assert actions[0].enabled is True


def test_queued_allows_start_batch():
    actions = compute_next_allowed_actions(ImportBatchStatus.queued.value)
    assert len(actions) == 1
    assert actions[0].action == "start_batch"
    assert actions[0].enabled is True


def test_running_allows_parse_aal3():
    actions = compute_next_allowed_actions(ImportBatchStatus.running.value)
    assert len(actions) == 1
    assert actions[0].action == "parse_aal3"
    assert actions[0].enabled is True


def test_running_parse_aal3_disabled_when_bound_file_inactive():
    file_id = uuid.uuid4()
    reason = f"Bound label file is not active: {file_id} (status=archived)"
    actions = compute_next_allowed_actions(
        ImportBatchStatus.running.value,
        parse_enabled=False,
        parse_disable_reason=reason,
    )
    assert len(actions) == 1
    assert actions[0].action == "parse_aal3"
    assert actions[0].enabled is False
    assert str(file_id) in (actions[0].reason or "")


def test_parsed_allows_generate_candidates():
    actions = compute_next_allowed_actions(
        ImportBatchStatus.parsed.value,
        raw_row_count=166,
        candidate_count=0,
    )
    assert len(actions) == 1
    assert actions[0].action == "generate_candidates"
    assert actions[0].enabled is True


def test_candidate_generated_allows_validate_batch():
    actions = compute_next_allowed_actions(
        ImportBatchStatus.candidate_generated.value,
        candidate_count=96,
        validation_result_count=0,
    )
    assert len(actions) == 1
    assert actions[0].action == "validate_batch"
    assert actions[0].enabled is True


def test_validation_dispatched_no_main_actions():
    actions = compute_next_allowed_actions(ImportBatchStatus.validation_dispatched.value)
    assert actions == []


def test_completed_no_actions():
    actions = compute_next_allowed_actions(ImportBatchStatus.completed.value)
    assert actions == []


def test_failed_no_actions():
    actions = compute_next_allowed_actions(ImportBatchStatus.failed.value)
    assert actions == []


def test_cancelled_no_actions():
    actions = compute_next_allowed_actions(ImportBatchStatus.cancelled.value)
    assert actions == []


def test_unknown_status_no_actions():
    actions = compute_next_allowed_actions("some_unknown_status")
    assert actions == []


# ── next_allowed_actions never includes forbidden actions ─────────────────────

FORBIDDEN_ACTIONS = {"submit_review", "approve", "promote", "llm_extract"}


@pytest.mark.parametrize("status", [s.value for s in ImportBatchStatus])
def test_no_forbidden_actions_for_any_status(status):
    actions = compute_next_allowed_actions(status)
    action_names = {a.action for a in actions}
    assert action_names.isdisjoint(FORBIDDEN_ACTIONS), (
        f"Status {status!r} returned forbidden action(s): "
        f"{action_names & FORBIDDEN_ACTIONS}"
    )


# ── PipelineAction schema ──────────────────────────────────────────────────────

def test_pipeline_action_schema():
    a = PipelineAction(action="queue_batch", label="Queue Batch", enabled=True, reason=None)
    assert a.action == "queue_batch"
    assert a.enabled is True
    assert a.reason is None


def test_pipeline_action_disabled_with_reason():
    a = PipelineAction(
        action="parse_aal3",
        label="Parse AAL3",
        enabled=False,
        reason="batch is not in running status",
    )
    assert a.enabled is False
    assert a.reason is not None


# ── LatestValidationSummary schema ────────────────────────────────────────────

def test_latest_validation_summary_schema():
    s = LatestValidationSummary(passed_count=166, failed_count=0, warning_count=2)
    assert s.passed_count == 166
    assert s.failed_count == 0
    assert s.warning_count == 2


# ── ImportBatchPipelineOverview field presence ────────────────────────────────

def _make_batch_read() -> dict:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "batch_code": "test_batch_001",
        "resource_id": str(uuid.uuid4()),
        "batch_type": "atlas_import",
        "parser_key": "aal3_xml",
        "status": "created",
        "description": None,
        "remark": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "failed_at": None,
        "cancelled_at": None,
        "error_message": None,
    }


def test_overview_has_required_fields():
    batch_data = _make_batch_read()
    overview = ImportBatchPipelineOverview(
        batch=batch_data,
        bound_files=[],
        events=[],
        parse_runs=[],
        raw_label_count=0,
        raw_labels_preview=[],
        generation_runs=[],
        candidate_count=0,
        candidate_status_counts={},
        candidates_preview=[],
        validation_runs=[],
        latest_validation_summary=None,
        next_allowed_actions=[
            PipelineAction(action="queue_batch", label="Queue Batch", enabled=True)
        ],
    )
    assert overview.raw_label_count == 0
    assert overview.candidate_count == 0
    assert overview.latest_validation_summary is None
    assert len(overview.next_allowed_actions) == 1


def test_overview_raw_labels_preview_field_exists():
    batch_data = _make_batch_read()
    overview = ImportBatchPipelineOverview(
        batch=batch_data,
        bound_files=[],
        events=[],
        parse_runs=[],
        raw_label_count=166,
        raw_labels_preview=[],
        generation_runs=[],
        candidate_count=166,
        candidate_status_counts={"rule_passed": 166},
        candidates_preview=[],
        validation_runs=[],
        latest_validation_summary=LatestValidationSummary(
            passed_count=166, failed_count=0, warning_count=2
        ),
        next_allowed_actions=[],
    )
    assert overview.raw_label_count == 166
    assert overview.candidate_count == 166
    assert overview.latest_validation_summary is not None
    assert overview.latest_validation_summary.passed_count == 166


def test_overview_candidate_status_counts_field():
    batch_data = _make_batch_read()
    overview = ImportBatchPipelineOverview(
        batch=batch_data,
        bound_files=[],
        events=[],
        parse_runs=[],
        raw_label_count=10,
        raw_labels_preview=[],
        generation_runs=[],
        candidate_count=10,
        candidate_status_counts={"candidate_created": 5, "rule_passed": 5},
        candidates_preview=[],
        validation_runs=[],
        latest_validation_summary=None,
        next_allowed_actions=[],
    )
    assert overview.candidate_status_counts["candidate_created"] == 5
    assert overview.candidate_status_counts["rule_passed"] == 5


def test_bound_file_pipeline_read_schema():
    file_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    row = BoundFilePipelineRead(
        id=uuid.uuid4(),
        file_id=file_id,
        file_role_in_batch="label_dictionary",
        sort_order=0,
        created_at=now,
        original_filename="AAL3v1_1mm.xml",
        file_type="label_table",
        file_role="label_dictionary",
        file_status="archived",
        is_active=False,
        can_parse=False,
        inactive_reason="file is archived",
        intermediate_status="ready",
        latest_intermediate_artifact_id=None,
        latest_intermediate_kind="label_table",
        latest_intermediate_schema="label_table_v1",
        parser_compatible_for_aal3_xml=False,
        parser_incompatible_reason="file is archived",
        warning="Bound file is not active",
    )
    assert row.file_status == "archived"
    assert row.can_parse is False
    assert row.parser_compatible_for_aal3_xml is False


def test_running_parse_aal3_disabled_for_xlsx_binding():
    from app.services.raw_parsing_service import evaluate_batch_parse_readiness

    file_id = uuid.uuid4()
    xlsx = type("RF", (), {
        "id": file_id,
        "original_filename": "Brain volume list.xlsx",
        "file_type": "spreadsheet",
        "file_role": "macro_region_pool_source",
        "file_ext": ".xlsx",
        "status": "active",
        "deleted_at": None,
    })()
    binding = type("B", (), {"file_id": file_id, "file_role_in_batch": "label_dictionary"})()
    can_parse, reason = evaluate_batch_parse_readiness([binding], {file_id: xlsx})
    actions = compute_next_allowed_actions(
        ImportBatchStatus.running.value,
        parse_enabled=can_parse,
        parse_disable_reason=reason,
    )
    assert actions[0].action == "parse_aal3"
    assert actions[0].enabled is False
    assert reason is not None


def test_running_parse_aal3_enabled_for_xml_binding():
    from app.services.raw_parsing_service import evaluate_batch_parse_readiness

    file_id = uuid.uuid4()
    xml = type("RF", (), {
        "id": file_id,
        "original_filename": "AAL3v1_1mm.xml",
        "file_type": "label_table",
        "file_role": "label_dictionary",
        "file_ext": ".xml",
        "status": "active",
        "deleted_at": None,
    })()
    binding = type("B", (), {"file_id": file_id, "file_role_in_batch": "label_dictionary"})()
    can_parse, reason = evaluate_batch_parse_readiness([binding], {file_id: xml})
    actions = compute_next_allowed_actions(
        ImportBatchStatus.running.value,
        parse_enabled=can_parse,
        parse_disable_reason=reason,
    )
    assert actions[0].enabled is True
    assert reason is None
