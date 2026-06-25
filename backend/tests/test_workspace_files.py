"""Unit tests for workspace_file_service pure/helper logic.

Tests pure helpers without DB dependency.
Does NOT test raw_aal3_region_labels, candidate_brain_regions, final_*, kg_*.
"""

from __future__ import annotations

import ast
import pathlib
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ─── _workspace_storage_path ──────────────────────────────────────────────────

def test_workspace_storage_path():
    from app.services.workspace_file_service import _workspace_storage_path
    path = _workspace_storage_path("abc123_filename.xml")
    assert path.startswith("workspace/")
    assert "abc123_filename.xml" in path


# ─── upload produces correct fields ──────────────────────────────────────────

import pytest


@pytest.mark.anyio
async def test_upload_workspace_file_creates_record(tmp_path):
    """Upload should write workspace/ subdir and record correct metadata."""
    from io import BytesIO
    from fastapi import UploadFile
    from app.services import workspace_file_service

    content = b"label1,label2\n1,2\n"
    upload = UploadFile(filename="test.csv", file=BytesIO(content))

    # Patch get_upload_root to use tmp_path
    with patch.object(workspace_file_service.resource_file_service, "get_upload_root", return_value=tmp_path):
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock(side_effect=lambda row: None)

        row = await workspace_file_service.upload_workspace_file(
            session,
            upload,
            file_type="label_table",
            file_role="label_dictionary",
        )
        assert row.original_filename == "test.csv"
        assert row.file_type == "label_table"
        assert row.file_role == "label_dictionary"
        assert row.sha256 is not None and len(row.sha256) == 64
        assert row.storage_path.startswith("workspace/")
        # Physical file should exist
        ws_path = tmp_path / Path(*row.storage_path.split("/"))
        assert ws_path.is_file()


def test_workspace_file_no_resource_id_required():
    """WorkspaceFile model should not have resource_id attribute."""
    from app.models.workspace_file import WorkspaceFile
    assert not hasattr(WorkspaceFile, "resource_id"), (
        "WorkspaceFile must not have resource_id; it is a staging table"
    )


# ─── Archive (soft-delete) ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_archive_workspace_file():
    from app.services import workspace_file_service
    from app.models.workspace_file import WorkspaceFile

    wf = WorkspaceFile()
    wf.id = uuid.uuid4()
    wf.status = "active"
    wf.archived_at = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=wf)
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda row: None)

    result = await workspace_file_service.archive_workspace_file(session, wf.id)
    assert result.status == "archived"
    assert result.archived_at is not None


@pytest.mark.anyio
async def test_get_deleted_workspace_file_raises():
    from app.services import workspace_file_service
    from app.models.workspace_file import WorkspaceFile
    from app.services.workspace_file_service import WorkspaceFileNotFoundError

    wf = WorkspaceFile()
    wf.id = uuid.uuid4()
    wf.status = "deleted"

    session = AsyncMock()
    session.get = AsyncMock(return_value=wf)

    with pytest.raises(WorkspaceFileNotFoundError):
        await workspace_file_service.get_workspace_file(session, wf.id)


# ─── Attach to resource ───────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_attach_to_resource_creates_resource_file(tmp_path):
    """attach_to_resource should copy file and create ResourceFile with source_workspace_file_id."""
    from app.services import workspace_file_service
    from app.models.workspace_file import WorkspaceFile
    from app.models.resource_file import ResourceFile
    from app.schemas.workspace_file import AttachToResourceRequest

    wf = WorkspaceFile()
    wf.id = uuid.uuid4()
    wf.status = "active"
    wf.original_filename = "labels.xml"
    wf.sha256 = "a" * 64
    wf.file_type = "label_table"
    wf.file_role = "label_dictionary"
    wf.file_ext = ".xml"
    wf.mime_type = "application/xml"
    wf.file_size_bytes = 42
    wf.description = None
    wf.remark = None

    # Create fake physical file in workspace dir
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    stored = f"{wf.id}_{wf.sha256[:12]}_{wf.original_filename}"
    wf.stored_filename = stored
    wf.storage_path = f"workspace/{stored}"
    src = ws_dir / stored
    src.write_bytes(b"<data/>")

    resource_id = uuid.uuid4()
    req = AttachToResourceRequest(resource_id=resource_id)

    # Mock resource + session
    fake_resource = MagicMock()
    fake_resource.id = resource_id

    session = AsyncMock()
    session.get = AsyncMock(return_value=wf)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda row: None)

    with (
        patch.object(workspace_file_service.resource_service, "get_resource", AsyncMock(return_value=fake_resource)),
        patch.object(workspace_file_service.resource_file_service, "get_upload_root", return_value=tmp_path),
        patch.object(workspace_file_service.resource_file_service, "_find_active_duplicate", AsyncMock(return_value=None)),
        patch.object(workspace_file_service.file_normalization_service, "auto_normalize_after_upload", AsyncMock(return_value={"intermediate_status": "ready"})),
    ):
        rf = await workspace_file_service.attach_to_resource(session, wf.id, req)

    assert isinstance(rf, ResourceFile)
    assert rf.resource_id == resource_id
    assert rf.source_workspace_file_id == wf.id
    assert rf.sha256 == wf.sha256
    # Copied file should exist in resource dir
    resource_dir = tmp_path / str(resource_id)
    assert resource_dir.is_dir()
    dest_files = list(resource_dir.iterdir())
    assert len(dest_files) == 1


@pytest.mark.anyio
async def test_attach_archived_file_raises():
    from app.services import workspace_file_service
    from app.models.workspace_file import WorkspaceFile
    from app.schemas.workspace_file import AttachToResourceRequest
    from app.services.workspace_file_service import WorkspaceFileArchivedError

    wf = WorkspaceFile()
    wf.id = uuid.uuid4()
    wf.status = "archived"

    session = AsyncMock()
    session.get = AsyncMock(return_value=wf)

    with pytest.raises(WorkspaceFileArchivedError):
        await workspace_file_service.attach_to_resource(
            session, wf.id, AttachToResourceRequest(resource_id=uuid.uuid4())
        )


@pytest.mark.anyio
async def test_attach_duplicate_sha256_raises():
    from app.services import workspace_file_service
    from app.models.workspace_file import WorkspaceFile
    from app.models.resource_file import ResourceFile
    from app.schemas.workspace_file import AttachToResourceRequest
    from app.services.resource_file_service import DuplicateFileError

    wf = WorkspaceFile()
    wf.id = uuid.uuid4()
    wf.status = "active"
    wf.sha256 = "b" * 64

    existing_rf = ResourceFile()
    existing_rf.id = uuid.uuid4()

    resource_id = uuid.uuid4()
    fake_resource = MagicMock()
    session = AsyncMock()
    session.get = AsyncMock(return_value=wf)

    with (
        patch.object(workspace_file_service.resource_service, "get_resource", AsyncMock(return_value=fake_resource)),
        patch.object(workspace_file_service.resource_file_service, "get_upload_root", return_value=Path("/tmp")),
        patch.object(workspace_file_service.resource_file_service, "_find_active_duplicate", AsyncMock(return_value=existing_rf)),
    ):
        with pytest.raises(DuplicateFileError):
            await workspace_file_service.attach_to_resource(
                session, wf.id, AttachToResourceRequest(resource_id=resource_id)
            )


# ─── Architecture boundary: no final_*/kg_* imports ──────────────────────────

def test_service_does_not_import_forbidden_models():
    """workspace_file_service must not import raw_aal3_region_labels, candidate_brain_regions,
    final_*, kg_*, or LLM modules."""
    service_path = pathlib.Path(__file__).parent.parent / "app" / "services" / "workspace_file_service.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden = [
        "raw_aal3_region_labels",
        "candidate_brain_regions",
        "final_brain_regions",
        "kg_",
        "deepseek",
        "llm",
        "import_batch_files",
    ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            node_str = ast.unparse(node)
            for pattern in forbidden:
                assert pattern not in node_str.lower(), (
                    f"workspace_file_service must not reference '{pattern}': found '{node_str}'"
                )


def test_router_does_not_include_batch_endpoint():
    """workspace_files router must not import or call raw_aal3/candidate/final/kg modules."""
    router_path = pathlib.Path(__file__).parent.parent / "app" / "routers" / "workspace_files.py"
    source = router_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = ["raw_pars", "candidate", "final_brain", "kg_", "promotion"]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            node_str = ast.unparse(node)
            for pat in forbidden_imports:
                assert pat not in node_str.lower(), (
                    f"workspace_files router must not import '{pat}': found '{node_str}'"
                )


# ─── storage_path in workspace dir ───────────────────────────────────────────

def test_workspace_storage_path_prefix():
    from app.services.workspace_file_service import _workspace_storage_path
    p = _workspace_storage_path("myfile.txt")
    assert p.startswith("workspace/")
    # Must not escape workspace dir
    assert ".." not in p
