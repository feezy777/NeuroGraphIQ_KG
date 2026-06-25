"""Import Batch module tests (no PostgreSQL required)."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.import_batch import (
    ALLOWED_TRANSITIONS,
    BatchType,
    FileRoleInBatch,
    ImportBatchCreate,
    ImportBatchStatus,
    ImportBatchStatusUpdate,
    InvalidBatchTransitionError,
    TERMINAL_STATUSES,
    validate_import_batch_transition,
)


def test_batch_type_enum_valid():
    assert BatchType.atlas_import.value == "atlas_import"
    assert BatchType.metadata_import.value == "metadata_import"


def test_status_enum_valid():
    assert ImportBatchStatus.created.value == "created"
    assert ImportBatchStatus.validation_dispatched.value == "validation_dispatched"


def test_file_role_in_batch_enum_valid():
    assert FileRoleInBatch.label_dictionary.value == "label_dictionary"
    assert FileRoleInBatch.macro_region_pool_source.value == "macro_region_pool_source"


def test_transition_created_to_queued():
    validate_import_batch_transition(ImportBatchStatus.created, ImportBatchStatus.queued)


def test_transition_queued_to_running():
    validate_import_batch_transition(ImportBatchStatus.queued, ImportBatchStatus.running)


def test_transition_running_to_completed():
    validate_import_batch_transition(ImportBatchStatus.running, ImportBatchStatus.completed)


def test_transition_running_to_parsed():
    validate_import_batch_transition(ImportBatchStatus.running, ImportBatchStatus.parsed)


def test_transition_parsed_to_candidate_generated():
    validate_import_batch_transition(
        ImportBatchStatus.parsed, ImportBatchStatus.candidate_generated
    )


def test_transition_invalid_created_to_running():
    with pytest.raises(InvalidBatchTransitionError):
        validate_import_batch_transition(ImportBatchStatus.created, ImportBatchStatus.running)


def test_transition_invalid_completed_to_running():
    with pytest.raises(InvalidBatchTransitionError):
        validate_import_batch_transition(ImportBatchStatus.completed, ImportBatchStatus.running)


def test_transition_invalid_cancelled_to_queued():
    with pytest.raises(InvalidBatchTransitionError):
        validate_import_batch_transition(ImportBatchStatus.cancelled, ImportBatchStatus.queued)


def test_terminal_statuses_frozen():
    assert "completed" in TERMINAL_STATUSES
    assert "cancelled" in TERMINAL_STATUSES
    for terminal in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[ImportBatchStatus(terminal)] == frozenset()


def test_rejects_candidate_status_in_batch_schema():
    with pytest.raises(ValidationError):
        ImportBatchStatusUpdate(status="candidate_created")  # type: ignore[arg-type]


def test_rejects_promotion_status_in_batch_schema():
    with pytest.raises(ValidationError):
        ImportBatchStatusUpdate(status="promoted_to_final")  # type: ignore[arg-type]


def test_rejects_rule_passed_status():
    with pytest.raises(ValidationError):
        ImportBatchStatusUpdate(status="rule_passed")  # type: ignore[arg-type]


def test_create_schema_requires_resource_id():
    with pytest.raises(ValidationError):
        ImportBatchCreate(batch_type="atlas_import")  # type: ignore[call-arg]


def test_create_schema_rejects_illegal_batch_type():
    with pytest.raises(ValidationError):
        ImportBatchCreate(
            resource_id=uuid.uuid4(),
            batch_type="raw_parsing",  # type: ignore[arg-type]
        )


def test_create_schema_rejects_illegal_file_role():
    with pytest.raises(ValidationError):
        ImportBatchCreate(
            resource_id=uuid.uuid4(),
            batch_type=BatchType.atlas_import,
            files=[{"file_id": uuid.uuid4(), "file_role_in_batch": "manual_approved"}],  # type: ignore[list-item]
        )


def test_create_schema_accepts_macro_region_pool_source():
    payload = ImportBatchCreate(
        resource_id=uuid.uuid4(),
        batch_type=BatchType.atlas_import,
        parser_key="macro96_xlsx",
        files=[{"file_id": uuid.uuid4(), "file_role_in_batch": "macro_region_pool_source"}],
    )
    assert payload.files[0].file_role_in_batch == FileRoleInBatch.macro_region_pool_source


def test_create_schema_accepts_aal3_label_dictionary():
    payload = ImportBatchCreate(
        resource_id=uuid.uuid4(),
        batch_type=BatchType.atlas_import,
        parser_key="aal3_xml",
        files=[{"file_id": uuid.uuid4(), "file_role_in_batch": "label_dictionary"}],
    )
    assert payload.files[0].file_role_in_batch == FileRoleInBatch.label_dictionary


def test_api_options_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/import-batches/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "atlas_import" in body["batch_type"]
    assert "created" in body["status"]
    assert "label_dictionary" in body["file_role_in_batch"]
    assert "macro_region_pool_source" in body["file_role_in_batch"]


def test_create_macro96_batch_api_integration():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resource_id = "5a5220d8-eba3-4c8e-b24e-0585f623d4d8"
    file_id = "75f7dc57-6e2e-47d1-bd34-1b7d0f4bd9a4"
    resp = client.post(
        "/api/import-batches",
        json={
            "resource_id": resource_id,
            "batch_type": "atlas_import",
            "parser_key": "macro96_xlsx",
            "files": [
                {
                    "file_id": file_id,
                    "file_role_in_batch": "macro_region_pool_source",
                    "sort_order": 0,
                }
            ],
        },
    )
    if resp.status_code >= 500:
        pytest.skip("database unavailable")
    if resp.status_code == 400 and "not active" in resp.text.lower():
        pytest.skip("fixture resource/file not active in database")
    if resp.status_code == 409:
        pytest.skip("batch already exists for fixture file")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["parser_key"] == "macro96_xlsx"
    assert body["files"][0]["file_role_in_batch"] == "macro_region_pool_source"


def test_health_and_prior_options_still_work():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/resources/options").status_code == 200
    assert client.get("/api/files/options").status_code == 200


def test_import_batch_update_schema():
    from app.schemas.import_batch import ImportBatchUpdate, ImportBatchFilesUpdate

    u = ImportBatchUpdate(description="updated", batch_type=BatchType.atlas_import)
    assert u.description == "updated"
    fu = ImportBatchFilesUpdate(
        files=[{"file_id": uuid.uuid4(), "file_role_in_batch": "label_dictionary"}]
    )
    assert len(fu.files) == 1


def test_compute_batch_next_actions():
    from app.services.import_batch_service import compute_batch_next_actions

    assert "queue" in compute_batch_next_actions("created")
    assert "cancel" in compute_batch_next_actions("created")
    assert "start" in compute_batch_next_actions("queued")
    assert "go_pipeline" in compute_batch_next_actions("running")
    assert compute_batch_next_actions("cancelled") == []


def test_import_batch_file_enriched_read_schema():
    from datetime import datetime, timezone

    from app.schemas.import_batch import ImportBatchFileEnrichedRead, FileRoleInBatch

    now = datetime.now(tz=timezone.utc)
    row = ImportBatchFileEnrichedRead(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        file_role_in_batch=FileRoleInBatch.label_dictionary,
        sort_order=0,
        created_at=now,
        original_filename="AAL3.xml",
        file_type="label_table",
        file_role="label_dictionary",
        file_status="active",
        sha256="abc",
        file_size=1024,
        intermediate_status="ready",
        is_active=True,
        can_parse=True,
    )
    assert row.file_status == "active"
    assert row.can_parse is True


def test_patch_running_batch_rejected_via_service_error():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import import_batch_service

    batch_id = uuid.uuid4()

    async def fake_update(*_args, **_kwargs):
        raise import_batch_service.BatchEditNotAllowedError(
            "batch status running does not allow metadata edit"
        )

    original = import_batch_service.update_batch
    import_batch_service.update_batch = fake_update  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(
            f"/api/import-batches/{batch_id}",
            json={"description": "x"},
        )
        assert resp.status_code == 409
        assert "running" in resp.json()["detail"]
    finally:
        import_batch_service.update_batch = original  # type: ignore[assignment]


def test_patch_files_running_rejected():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import import_batch_service

    batch_id = uuid.uuid4()
    file_id = uuid.uuid4()

    async def fake_replace(*_args, **_kwargs):
        raise import_batch_service.BatchEditNotAllowedError(
            "files can only be updated when batch status is created or queued"
        )

    original = import_batch_service.replace_batch_files
    import_batch_service.replace_batch_files = fake_replace  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(
            f"/api/import-batches/{batch_id}/files",
            json={"files": [{"file_id": str(file_id), "file_role_in_batch": "label_dictionary"}]},
        )
        assert resp.status_code == 409
        assert "created or queued" in resp.json()["detail"]
    finally:
        import_batch_service.replace_batch_files = original  # type: ignore[assignment]


def test_workspace_file_binding_error_message():
    from app.services.import_batch_service import FileBindingError

    err = FileBindingError(
        "workspace file cannot be bound directly; attach to resource first: abc"
    )
    assert "workspace file" in str(err)


def test_inactive_file_binding_error_message():
    from app.services.import_batch_service import FileBindingError

    err = FileBindingError("file is not active: abc (status=archived)")
    assert "archived" in str(err)


def test_import_batch_detail_has_warnings_and_actions():
    from datetime import datetime, timezone

    from app.schemas.import_batch import ImportBatchDetail, ImportBatchRead, BatchType, ImportBatchStatus

    now = datetime.now(tz=timezone.utc)
    detail = ImportBatchDetail(
        id=uuid.uuid4(),
        batch_code="test_batch",
        resource_id=uuid.uuid4(),
        batch_type=BatchType.atlas_import,
        parser_key="aal3_xml",
        status=ImportBatchStatus.created,
        description=None,
        remark=None,
        created_at=now,
        updated_at=now,
        started_at=None,
        finished_at=None,
        failed_at=None,
        cancelled_at=None,
        error_message=None,
        files=[],
        recent_events=[],
        warnings=["file x has no intermediate artifact"],
        next_allowed_actions=["queue", "cancel"],
    )
    assert detail.warnings[0].startswith("file")
    assert "queue" in detail.next_allowed_actions
