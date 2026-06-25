"""File Upload module tests (no PostgreSQL required)."""

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.resource_file import ResourceFile
from app.schemas.resource_file import FileRole, FileStatus, FileType, FileUploadFormMeta, ResourceFileUpdate
from app.services.resource_file_service import build_file_preview
from app.utils.file_meta import (
    build_stored_filename,
    infer_file_type,
    normalize_extension,
    resolve_under_root,
    safe_filename,
    sha256_bytes,
)


def test_normalize_extension_nii_gz():
    assert normalize_extension("AAL3v1_1mm.nii.gz") == ".nii.gz"
    assert normalize_extension("data.NII.GZ") == ".nii.gz"


def test_normalize_extension_simple():
    assert normalize_extension("labels.xml") == ".xml"
    assert normalize_extension("readme.txt") == ".txt"


def test_infer_file_type_nifti():
    assert infer_file_type("vol.nii.gz") == FileType.nifti
    assert infer_file_type("vol.nii") == FileType.nifti


def test_infer_file_type_user_override():
    assert infer_file_type("matrix.csv", FileType.connectivity_matrix) == FileType.connectivity_matrix


def test_infer_file_type_label_table_vs_text():
    assert infer_file_type("labels.xml") == FileType.label_table
    assert infer_file_type("notes.txt") == FileType.text


def test_infer_file_type_pdf_json():
    assert infer_file_type("guide.pdf") == FileType.pdf
    assert infer_file_type("meta.json") == FileType.json


def test_safe_filename_strips_path_traversal():
    name = safe_filename("../../etc/passwd")
    assert ".." not in name
    assert "/" not in name
    assert "\\" not in name


def test_build_stored_filename_no_traversal():
    fid = str(uuid.uuid4())
    digest = "a" * 64
    stored = build_stored_filename(fid, digest, "../../../evil.nii.gz")
    assert ".." not in stored
    assert stored.startswith(fid)


def test_sha256_bytes_stable():
    data = b"neurographiq-test-content"
    assert sha256_bytes(data) == sha256_bytes(data)
    assert len(sha256_bytes(data)) == 64


def test_resolve_under_root_rejects_escape(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "ok.txt").write_text("x", encoding="utf-8")
    ok = resolve_under_root(root, "ok.txt")
    assert ok.is_file()
    with pytest.raises(ValueError, match="traversal"):
        resolve_under_root(root, "../outside.txt")


def test_form_meta_rejects_illegal_file_type():
    with pytest.raises(ValidationError):
        FileUploadFormMeta(file_type="candidate_created")  # type: ignore[arg-type]


def test_form_meta_rejects_illegal_file_role():
    with pytest.raises(ValidationError):
        FileUploadFormMeta(file_role="manual_approved")  # type: ignore[arg-type]


def test_file_status_enum_values():
    assert FileStatus.active.value == "active"
    assert FileStatus.archived.value == "archived"


def test_duplicate_check_logic_mock():
    """Service-layer duplicate: same sha256 under same resource should conflict."""
    from app.services.resource_file_service import DuplicateFileError

    existing_id = uuid.uuid4()
    row = ResourceFile(
        id=existing_id,
        resource_id=uuid.uuid4(),
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256="abc" * 21 + "a",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="active",
        description=None,
        remark=None,
    )
    err = DuplicateFileError(
        row.sha256,
        resource_id=row.resource_id,
        existing=row,
        inactive=False,
    )
    assert len(err.sha256) == 64
    assert err.existing_id == existing_id
    assert err.existing is row
    assert err.inactive is False


@pytest.mark.anyio
async def test_build_duplicate_upload_detail_active():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    from app.services.resource_file_service import build_duplicate_upload_detail

    resource_id = uuid.uuid4()
    file_id = uuid.uuid4()
    row = ResourceFile(
        id=file_id,
        resource_id=resource_id,
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256="5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="active",
        description=None,
        remark=None,
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    summary = {
        "intermediate_status": "ready",
        "latest_intermediate_artifact_id": uuid.uuid4(),
        "latest_intermediate_kind": "macro_region_table",
        "latest_intermediate_row_count": 96,
        "latest_intermediate_error": None,
        "latest_normalization_run_id": uuid.uuid4(),
    }
    with patch(
        "app.services.file_normalization_service.get_intermediate_summary_for_file",
        new=AsyncMock(return_value=summary),
    ):
        detail = await build_duplicate_upload_detail(
            session,
            resource_id=resource_id,
            sha256=row.sha256,
            existing=row,
            inactive=False,
        )

    assert detail["code"] == "DUPLICATE_RESOURCE_FILE"
    assert detail["sha256"] == row.sha256
    assert detail["resource_id"] == str(resource_id)
    existing = detail["existing_file"]
    assert existing["id"] == str(file_id)
    assert existing["original_filename"] == "Brain volume list.xlsx"
    assert existing["status"] == "active"
    assert existing["intermediate_status"] == "ready"
    assert existing["latest_intermediate_kind"] == "macro_region_table"
    assert existing["latest_intermediate_row_count"] == 96


@pytest.mark.anyio
async def test_build_duplicate_upload_detail_inactive():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    from app.services.resource_file_service import build_duplicate_upload_detail

    resource_id = uuid.uuid4()
    file_id = uuid.uuid4()
    row = ResourceFile(
        id=file_id,
        resource_id=resource_id,
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256="5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="archived",
        description=None,
        remark=None,
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    with patch(
        "app.services.file_normalization_service.get_intermediate_summary_for_file",
        new=AsyncMock(return_value={"intermediate_status": "ready"}),
    ):
        detail = await build_duplicate_upload_detail(
            session,
            resource_id=resource_id,
            sha256=row.sha256,
            existing=row,
            inactive=True,
        )
    assert detail["code"] == "DUPLICATE_RESOURCE_FILE_INACTIVE"
    assert detail["existing_file"]["id"] == str(file_id)
    assert detail["existing_file"]["status"] == "archived"
    assert detail["existing_file"]["original_filename"] == "Brain volume list.xlsx"


@pytest.mark.anyio
async def test_upload_file_duplicate_does_not_add_row(tmp_path):
    from io import BytesIO
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import UploadFile
    from app.services.resource_file_service import DuplicateFileError, upload_file

    resource_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    digest = "5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d"
    existing = ResourceFile(
        id=existing_id,
        resource_id=resource_id,
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256=digest,
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="active",
        description=None,
        remark=None,
    )
    upload = UploadFile(filename="Brain volume list.xlsx", file=BytesIO(b"same-content"))
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch("app.services.resource_file_service.get_upload_root", return_value=tmp_path):
        with patch(
            "app.services.resource_file_service._find_blocking_duplicate",
            new=AsyncMock(return_value=(existing, False)),
        ):
            with patch(
                "app.services.resource_service.get_resource",
                new=AsyncMock(return_value=MagicMock()),
            ):
                with pytest.raises(DuplicateFileError) as exc:
                    await upload_file(session, resource_id, upload)
                assert exc.value.existing_id == existing_id
                session.add.assert_not_called()


def test_upload_duplicate_http_409_structured_detail():
    from datetime import datetime, timezone
    from io import BytesIO
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import resource_file_service
    from app.services.resource_file_service import DuplicateFileError

    resource_id = uuid.uuid4()
    file_id = uuid.uuid4()
    digest = "5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d"
    existing = ResourceFile(
        id=file_id,
        resource_id=resource_id,
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256=digest,
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="active",
        description=None,
        remark=None,
        created_at=datetime.now(timezone.utc),
    )
    detail = {
        "code": "DUPLICATE_RESOURCE_FILE",
        "message": "This file already exists for the selected resource.",
        "resource_id": str(resource_id),
        "sha256": digest,
        "existing_file": {
            "id": str(file_id),
            "original_filename": "Brain volume list.xlsx",
            "status": "active",
            "intermediate_status": "ready",
        },
        "suggestion": "Use the existing file instead of uploading it again.",
    }

    async def _raise_dup(*args, **kwargs):
        raise DuplicateFileError(
            digest,
            resource_id=resource_id,
            existing=existing,
            inactive=False,
        )

    client = TestClient(app)
    with patch.object(resource_file_service, "upload_file", side_effect=_raise_dup):
        with patch.object(
            resource_file_service,
            "build_duplicate_upload_detail",
            new=AsyncMock(return_value=detail),
        ):
            resp = client.post(
                f"/api/resources/{resource_id}/files",
                files={"file": ("Brain volume list.xlsx", BytesIO(b"x"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "DUPLICATE_RESOURCE_FILE"
    assert body["detail"]["sha256"] == digest
    assert body["detail"]["existing_file"]["id"] == str(file_id)
    assert body["detail"]["existing_file"]["original_filename"] == "Brain volume list.xlsx"
    assert body["detail"]["existing_file"]["status"] == "active"
    assert body["detail"]["existing_file"]["intermediate_status"] == "ready"


@pytest.mark.anyio
async def test_update_file_metadata_restores_active_clears_deleted_at():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    from app.schemas.resource_file import ResourceFileUpdate
    from app.services.resource_file_service import update_file_metadata

    file_id = uuid.uuid4()
    row = ResourceFile(
        id=file_id,
        resource_id=uuid.uuid4(),
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256="5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="archived",
        description=None,
        remark=None,
        deleted_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda r: r)

    updated = await update_file_metadata(session, file_id, ResourceFileUpdate(status="active"))

    assert updated.status == "active"
    assert updated.deleted_at is None


def test_list_resource_files_status_all_param():
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import resource_file_service

    resource_id = uuid.uuid4()
    client = TestClient(app)
    with patch.object(
        resource_file_service,
        "list_files_for_resource",
        new=AsyncMock(return_value=([], 0)),
    ) as list_mock:
        resp = client.get(f"/api/resources/{resource_id}/files", params={"status": "all"})
    assert resp.status_code == 200
    list_mock.assert_awaited_once()
    assert list_mock.await_args.kwargs["status"] == "all"


def test_api_options_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/files/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "nifti" in body["file_type"]
    assert "unknown" in body["file_role"]
    assert "active" in body["status"]
    assert ".xml" in body["preview_supported_types"]


def test_update_schema_allows_metadata_only():
    payload = ResourceFileUpdate(
        file_type="ontology",
        file_role="ontology_source",
        description="updated description",
        remark="updated remark",
        status="archived",
    )
    assert payload.file_type == FileType.ontology
    assert payload.file_role == FileRole.ontology_source
    assert payload.status == FileStatus.archived


def _preview_row(tmp_path: Path, storage_path: str, *, filename: str, file_type: str = "text") -> ResourceFile:
    return ResourceFile(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        file_code=None,
        original_filename=filename,
        stored_filename=Path(storage_path).name,
        storage_path=storage_path,
        file_ext=normalize_extension(filename),
        mime_type=None,
        file_size=0,
        sha256="a" * 64,
        file_type=file_type,
        file_role="label_dictionary",
        status="active",
        description=None,
        remark=None,
    )


def test_preview_xml_text_file_truncates(tmp_path):
    rel_path = "resource/labels.xml"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir()
    file_path.write_text("<atlas>\n<label>AAL3</label>\n</atlas>", encoding="utf-8")
    row = _preview_row(tmp_path, rel_path, filename="labels.xml", file_type="label_table")
    row.file_size = file_path.stat().st_size

    preview = build_file_preview(row, upload_root=tmp_path, max_bytes=16)

    assert preview.preview_kind == "xml"
    assert preview.is_truncated is True
    assert preview.content.startswith("<atlas>")
    assert preview.metadata["storage_path"] == rel_path
    assert str(tmp_path) not in preview.metadata["storage_path"]


def test_preview_xlsx_not_treated_as_xml(tmp_path):
    rel_path = "resource/brain_volume.xlsx"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir()
    file_path.write_bytes(b"PK\x03\x04fake-xlsx-content")
    row = _preview_row(tmp_path, rel_path, filename="Brain volume list.xlsx", file_type="spreadsheet")
    row.mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    row.file_size = file_path.stat().st_size

    preview = build_file_preview(row, upload_root=tmp_path, max_bytes=16)

    assert preview.preview_kind == "unsupported"
    assert preview.content is None


def test_preview_binary_unsupported_has_no_content(tmp_path):
    rel_path = "resource/brain.nii.gz"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir()
    file_path.write_bytes(b"\x00\x01\x02" * 10)
    row = _preview_row(tmp_path, rel_path, filename="brain.nii.gz", file_type="nifti")
    row.file_size = file_path.stat().st_size

    preview = build_file_preview(row, upload_root=tmp_path, max_bytes=16)

    assert preview.preview_kind == "unsupported"
    assert preview.content is None
    assert preview.error_message is not None


def test_preview_missing_file_returns_missing(tmp_path):
    row = _preview_row(tmp_path, "resource/missing.txt", filename="missing.txt")

    preview = build_file_preview(row, upload_root=tmp_path, max_bytes=16)

    assert preview.preview_kind == "missing"
    assert preview.content is None


def test_preview_rejects_path_traversal(tmp_path):
    row = _preview_row(tmp_path, "../evil.txt", filename="evil.txt")

    with pytest.raises(ValueError, match="traversal"):
        build_file_preview(row, upload_root=tmp_path, max_bytes=16)


def test_health_and_resource_options_still_work():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/resources/options").status_code == 200


@pytest.mark.anyio
async def test_restore_file_sets_active_and_clears_deleted_at():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    from app.services.resource_file_service import restore_file

    file_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    digest = "5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d"
    row = ResourceFile(
        id=file_id,
        resource_id=resource_id,
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256=digest,
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="archived",
        description=None,
        remark=None,
        deleted_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda r: r)

    restored = await restore_file(session, file_id)

    assert restored.status == "active"
    assert restored.deleted_at is None


def test_restore_file_http_endpoint():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import resource_file_service

    file_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    row = ResourceFile(
        id=file_id,
        resource_id=resource_id,
        file_code=None,
        original_filename="Brain volume list.xlsx",
        stored_filename="stored.xlsx",
        storage_path="resource/stored.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=12425,
        sha256="5e1b1037fd3a72cea6d294c5528486805ae4cea501751f2086ac282603edb92d",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="active",
        description=None,
        remark=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    client = TestClient(app)
    with patch.object(resource_file_service, "restore_file", new=AsyncMock(return_value=row)):
        resp = client.post(f"/api/files/{file_id}/restore")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(file_id)
    assert resp.json()["status"] == "active"


def test_destructive_delete_file_http_success():
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.resource_file import FileDeleteResult
    from app.services import resource_file_service

    file_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    result = FileDeleteResult(
        file_id=file_id,
        resource_id=resource_id,
        deleted_counts={"resource_files": 1, "file_intermediate_artifacts": 0, "file_normalization_runs": 0},
        can_reupload_same_sha256=True,
        physical_file_deleted=False,
        physical_file_error=None,
    )
    client = TestClient(app)
    with patch.object(
        resource_file_service,
        "destructive_delete_file",
        new=AsyncMock(return_value=result),
    ):
        resp = client.post(
            f"/api/files/{file_id}/destructive-delete",
            json={
                "confirmation_text": f"DELETE FILE {file_id}",
                "operator": "admin",
                "reason": "remove hidden duplicate",
                "delete_physical_file": False,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_reupload_same_sha256"] is True
    assert body["deleted_counts"]["resource_files"] == 1


@pytest.mark.anyio
async def test_list_files_for_resource_active_excludes_archived():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.resource_file_service import list_files_for_resource

    resource_id = uuid.uuid4()
    active = ResourceFile(
        id=uuid.uuid4(),
        resource_id=resource_id,
        file_code=None,
        original_filename="active.xlsx",
        stored_filename="a.xlsx",
        storage_path="r/a.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=100,
        sha256="a" * 64,
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="active",
        description=None,
        remark=None,
    )
    session = AsyncMock()

    async def _fake_execute(stmt):
        sql = str(stmt)
        if "count" in sql.lower():
            return MagicMock(scalar_one=lambda: 1)
        return MagicMock(scalars=lambda: MagicMock(all=lambda: [active]))

    session.execute = AsyncMock(side_effect=_fake_execute)

    with patch(
        "app.services.resource_file_service.resource_service.get_resource",
        new=AsyncMock(return_value=MagicMock()),
    ):
        rows, total = await list_files_for_resource(session, resource_id, limit=50, offset=0, status="active")

    assert total == 1
    assert len(rows) == 1
    assert rows[0].status == "active"


@pytest.mark.anyio
async def test_list_files_for_resource_all_includes_archived_filter():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.resource_file_service import list_files_for_resource

    resource_id = uuid.uuid4()
    archived = ResourceFile(
        id=uuid.uuid4(),
        resource_id=resource_id,
        file_code=None,
        original_filename="archived.xlsx",
        stored_filename="b.xlsx",
        storage_path="r/b.xlsx",
        file_ext=".xlsx",
        mime_type=None,
        file_size=100,
        sha256="b" * 64,
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
        status="archived",
        description=None,
        remark=None,
    )
    session = AsyncMock()

    async def _fake_execute(stmt):
        sql = str(stmt)
        if "count" in sql.lower():
            return MagicMock(scalar_one=lambda: 1)
        return MagicMock(scalars=lambda: MagicMock(all=lambda: [archived]))

    session.execute = AsyncMock(side_effect=_fake_execute)

    with patch(
        "app.services.resource_file_service.resource_service.get_resource",
        new=AsyncMock(return_value=MagicMock()),
    ):
        rows, total = await list_files_for_resource(session, resource_id, limit=50, offset=0, status="all")

    assert total == 1
    assert rows[0].status == "archived"


def test_integrity_error_non_duplicate_is_validation_not_409():
    from app.services.resource_file_service import FileValidationError, _integrity_error_is_sha256_duplicate

    class _Orig:
        def __str__(self):
            return 'new row for relation "resource_files" violates check constraint "chk_resource_files_file_role"'

    assert _integrity_error_is_sha256_duplicate(IntegrityError("", {}, _Orig())) is False

    with pytest.raises(FileValidationError):
        raise FileValidationError("file upload rejected by database constraint: chk_resource_files_file_role")
