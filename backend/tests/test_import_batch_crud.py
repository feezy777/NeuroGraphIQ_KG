"""Import batch CRUD and parser compatibility tests."""

import uuid

import pytest

from app.utils.import_batch_parser_compat import ParserFileBindingError, validate_parser_file_binding


class _FakeFile:
    def __init__(
        self,
        *,
        file_type: str = "other",
        file_ext: str = "",
        original_filename: str = "file",
    ):
        self.file_type = file_type
        self.file_ext = file_ext
        self.original_filename = original_filename


def test_macro96_requires_spreadsheet_and_role():
    f = _FakeFile(file_type="spreadsheet", file_ext=".xlsx", original_filename="Brain volume list.xlsx")
    validate_parser_file_binding("macro96_xlsx", "macro_region_pool_source", f)


def test_macro96_rejects_label_dictionary_role():
    f = _FakeFile(file_type="spreadsheet", file_ext=".xlsx", original_filename="Brain volume list.xlsx")
    with pytest.raises(ParserFileBindingError):
        validate_parser_file_binding("macro96_xlsx", "label_dictionary", f)


def test_aal3_requires_xml_label_dictionary():
    f = _FakeFile(file_type="label_table", file_ext=".xml", original_filename="AAL3.xml")
    validate_parser_file_binding("aal3_xml", "label_dictionary", f)


def test_aal3_rejects_xlsx():
    f = _FakeFile(file_type="spreadsheet", file_ext=".xlsx", original_filename="Brain volume list.xlsx")
    with pytest.raises(ParserFileBindingError):
        validate_parser_file_binding("aal3_xml", "label_dictionary", f)


def test_clone_endpoint_mocked():
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.import_batch import BatchType, ImportBatchStatus
    from app.services import import_batch_service

    source_id = uuid.uuid4()
    cloned_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    class FakeBatch:
        id = cloned_id
        batch_code = "cloned_batch"
        resource_id = uuid.uuid4()
        batch_type = BatchType.atlas_import.value
        parser_key = "macro96_xlsx"
        status = ImportBatchStatus.created.value
        description = "copy"
        remark = None
        created_at = now
        updated_at = now
        started_at = None
        finished_at = None
        failed_at = None
        cancelled_at = None
        error_message = None

    fake_batch = FakeBatch()

    async def fake_clone(session, batch_id):
        assert batch_id == source_id
        return fake_batch

    async def fake_detail(session, batch_id, **kwargs):
        return fake_batch, [], []

    original_clone = import_batch_service.clone_batch
    original_detail = import_batch_service.get_batch_detail
    import_batch_service.clone_batch = fake_clone  # type: ignore[assignment]
    import_batch_service.get_batch_detail = fake_detail  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/api/import-batches/{source_id}/clone")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "created"
        assert body["parser_key"] == "macro96_xlsx"
    finally:
        import_batch_service.clone_batch = original_clone  # type: ignore[assignment]
        import_batch_service.get_batch_detail = original_detail  # type: ignore[assignment]


def test_attach_file_running_rejected():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import import_batch_service

    batch_id = uuid.uuid4()
    file_id = uuid.uuid4()

    async def fake_attach(*_args, **_kwargs):
        raise import_batch_service.BatchEditNotAllowedError(
            "files can only be updated when batch status is created or queued"
        )

    original = import_batch_service.attach_batch_file
    import_batch_service.attach_batch_file = fake_attach  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/import-batches/{batch_id}/files",
            json={"file_id": str(file_id), "file_role_in_batch": "macro_region_pool_source"},
        )
        assert resp.status_code == 409
        assert "created or queued" in resp.json()["detail"]
    finally:
        import_batch_service.attach_batch_file = original  # type: ignore[assignment]
