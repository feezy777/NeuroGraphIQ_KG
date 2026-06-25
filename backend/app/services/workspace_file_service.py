"""Workspace Public File service.

Workspace files are staging files without resource_id binding.
Architectural constraints (strictly enforced):
- Does NOT write import_batch_files, raw_aal3_region_labels, candidate_brain_regions.
- Does NOT write final_*, kg_*.
- Does NOT call any LLM.
- Does NOT trigger Raw Parsing, Candidate Generation, or Batch creation.
- attach_to_resource copies the physical file to the resource directory and creates
  a resource_files row; it records source_workspace_file_id for provenance.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource_file import ResourceFile
from app.models.workspace_file import WorkspaceFile
from app.schemas.resource_file import FilePreviewResponse, FileRole, FileType
from app.schemas.workspace_file import AttachToResourceRequest, WorkspaceFileUpdate
from app.services import file_normalization_service, resource_file_service, resource_service
from app.utils.file_meta import (
    build_stored_filename,
    guess_mime_type,
    infer_file_type,
    normalize_extension,
    relative_storage_path,
    resolve_under_root,
    safe_filename,
)

logger = logging.getLogger(__name__)

_WORKSPACE_DIR = "workspace"


class WorkspaceFileNotFoundError(Exception):
    pass


class WorkspaceFileArchivedError(Exception):
    pass


class DuplicateWorkspaceFileError(Exception):
    def __init__(self, sha256: str, existing_id: uuid.UUID | None = None):
        self.sha256 = sha256
        self.existing_id = existing_id
        super().__init__(sha256)


class WorkspaceFileStorageError(Exception):
    pass


def _get_workspace_dir() -> Path:
    root = resource_file_service.get_upload_root()
    ws_dir = root / _WORKSPACE_DIR
    ws_dir.mkdir(parents=True, exist_ok=True)
    return ws_dir


def _workspace_storage_path(stored_filename: str) -> str:
    """POSIX-style relative path for workspace files."""
    from pathlib import PurePosixPath
    return str(PurePosixPath(_WORKSPACE_DIR) / stored_filename)


def _log(action: str, result: str, *, file_id: uuid.UUID | None = None, error: str | None = None) -> None:
    logger.info("event_type=workspace_file action=%s result=%s file_id=%s error=%s",
                action, result, file_id, error)


async def _find_active_workspace_duplicate(session: AsyncSession, sha256: str) -> WorkspaceFile | None:
    """No global deduplication; workspace files allow same sha256 from different uploads."""
    return None  # Allow duplicates in workspace; dedup only happens at resource level.


async def upload_workspace_file(
    session: AsyncSession,
    upload: UploadFile,
    *,
    file_type: str | None = None,
    file_role: str | None = None,
    description: str | None = None,
    remark: str | None = None,
) -> WorkspaceFile:
    """Upload a file to workspace storage without requiring resource_id."""
    original = upload.filename or "upload"
    safe_name = safe_filename(original)
    ft_enum = infer_file_type(original, FileType(file_type) if file_type else None)
    file_ext = normalize_extension(original)
    ws_dir = _get_workspace_dir()
    upload_root = resource_file_service.get_upload_root()

    file_id = uuid.uuid4()
    temp_path: Path | None = None
    final_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(dir=ws_dir, delete=False, prefix=".tmp_ws_") as tmp:
            temp_path = Path(tmp.name)
            h = hashlib.sha256()
            size = 0
            while chunk := await upload.read(65536):
                h.update(chunk)
                tmp.write(chunk)
                size += len(chunk)
            digest = h.hexdigest()

        stored_filename = build_stored_filename(str(file_id), digest, original)
        rel_path = _workspace_storage_path(stored_filename)
        final_path = resolve_under_root(upload_root, rel_path)
        os.replace(temp_path, final_path)
        temp_path = None

        mime = guess_mime_type(original, upload.content_type)
        row = WorkspaceFile(
            id=file_id,
            original_filename=original,
            safe_filename=safe_name,
            stored_filename=stored_filename,
            storage_path=rel_path,
            file_ext=file_ext,
            mime_type=mime,
            file_type=ft_enum.value,
            file_role=(FileRole(file_role).value if file_role else FileRole.unknown.value),
            file_size_bytes=size,
            sha256=digest,
            status="active",
            description=description,
            remark=remark,
            source="workspace_upload",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        _log("upload", "success", file_id=file_id)
        return row

    except Exception as exc:
        _log("upload", "error", file_id=file_id, error=str(exc))
        if temp_path and temp_path.is_file():
            temp_path.unlink(missing_ok=True)
        if final_path and final_path.is_file():
            final_path.unlink(missing_ok=True)
        raise WorkspaceFileStorageError(str(exc)) from exc
    finally:
        await upload.close()


async def list_workspace_files(
    session: AsyncSession,
    *,
    status: str | None = None,
    file_type: str | None = None,
    file_role: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
) -> tuple[list[WorkspaceFile], int]:
    base = select(WorkspaceFile)
    count_q = select(func.count()).select_from(WorkspaceFile)

    if not include_archived:
        base = base.where(WorkspaceFile.status == "active")
        count_q = count_q.where(WorkspaceFile.status == "active")
    elif status:
        base = base.where(WorkspaceFile.status == status)
        count_q = count_q.where(WorkspaceFile.status == status)

    if file_type:
        base = base.where(WorkspaceFile.file_type == file_type)
        count_q = count_q.where(WorkspaceFile.file_type == file_type)
    if file_role:
        base = base.where(WorkspaceFile.file_role == file_role)
        count_q = count_q.where(WorkspaceFile.file_role == file_role)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(WorkspaceFile.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_workspace_file(session: AsyncSession, file_id: uuid.UUID) -> WorkspaceFile:
    row = await session.get(WorkspaceFile, file_id)
    if row is None or row.status == "deleted":
        raise WorkspaceFileNotFoundError(str(file_id))
    return row


async def update_workspace_file(
    session: AsyncSession, file_id: uuid.UUID, payload: WorkspaceFileUpdate
) -> WorkspaceFile:
    row = await get_workspace_file(session, file_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    _log("update", "success", file_id=file_id)
    return row


async def archive_workspace_file(session: AsyncSession, file_id: uuid.UUID) -> WorkspaceFile:
    """Soft-delete: sets status=archived, records archived_at.
    Does NOT delete physical file.
    Does NOT touch already-attached resource_files rows.
    """
    row = await get_workspace_file(session, file_id)
    if row.status == "archived":
        return row
    row.status = "archived"
    row.archived_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    _log("archive", "success", file_id=file_id)
    return row


def build_workspace_file_preview(row: WorkspaceFile) -> FilePreviewResponse:
    """Reuse resource_file preview logic by building a temporary duck-typed view."""
    if row.status != "active":
        raise WorkspaceFileNotFoundError(str(row.id))

    upload_root = resource_file_service.get_upload_root()
    path = resolve_under_root(upload_root, row.storage_path)

    # Use the existing resource_file_service preview internals via a shim.
    shim = _WorkspaceFileShim(row)
    return resource_file_service.build_file_preview(shim, upload_root=upload_root)  # type: ignore[arg-type]


def resolve_workspace_download_path(row: WorkspaceFile) -> Path:
    if row.status != "active":
        raise WorkspaceFileNotFoundError(str(row.id))
    upload_root = resource_file_service.get_upload_root()
    path = resolve_under_root(upload_root, row.storage_path)
    if not path.is_file():
        raise WorkspaceFileNotFoundError(str(row.id))
    return path


class _WorkspaceFileShim:
    """Minimal duck-type shim to pass a WorkspaceFile into build_file_preview."""

    def __init__(self, row: WorkspaceFile) -> None:
        self.id = row.id
        self.original_filename = row.original_filename
        self.stored_filename = row.stored_filename
        self.storage_path = row.storage_path
        self.file_ext = row.file_ext
        self.mime_type = row.mime_type
        self.file_type = row.file_type
        self.file_role = row.file_role
        self.file_size = row.file_size_bytes
        self.sha256 = row.sha256
        self.status = row.status
        self.deleted_at = None  # always treated as alive


async def attach_to_resource(
    session: AsyncSession,
    workspace_file_id: uuid.UUID,
    req: AttachToResourceRequest,
) -> ResourceFile:
    """Copy workspace file to resource directory and create a resource_files row.

    Strategy A: copies physical file → fully compatible with existing parsers.
    Records source_workspace_file_id for provenance.

    Constraints:
    - Does NOT create import batch.
    - Does NOT call parse / candidate / final.
    - Does NOT write kg_*.
    """
    ws_row = await get_workspace_file(session, workspace_file_id)
    if ws_row.status != "active":
        raise WorkspaceFileArchivedError(f"workspace_file {workspace_file_id} is not active")

    resource = await resource_service.get_resource(session, req.resource_id)

    # Check resource-level sha256 deduplication.
    existing = await resource_file_service._find_active_duplicate(
        session, req.resource_id, ws_row.sha256
    )
    if existing is not None:
        from app.services.resource_file_service import DuplicateFileError
        raise DuplicateFileError(
            ws_row.sha256,
            resource_id=req.resource_id,
            existing=existing,
            inactive=False,
        )

    # Copy physical file to resource directory.
    upload_root = resource_file_service.get_upload_root()
    src_path = resolve_under_root(upload_root, ws_row.storage_path)
    if not src_path.is_file():
        raise WorkspaceFileNotFoundError(f"physical file missing for workspace_file {workspace_file_id}")

    new_file_id = uuid.uuid4()
    resource_dir = upload_root / str(req.resource_id)
    resource_dir.mkdir(parents=True, exist_ok=True)

    stored_name = build_stored_filename(str(new_file_id), ws_row.sha256, ws_row.original_filename)
    rel_path = relative_storage_path(str(req.resource_id), stored_name)
    dest_path = resolve_under_root(upload_root, rel_path)
    shutil.copy2(str(src_path), str(dest_path))

    ft_value = req.file_type or ws_row.file_type
    fr_value = req.file_role or ws_row.file_role

    rf_row = ResourceFile(
        id=new_file_id,
        resource_id=req.resource_id,
        original_filename=ws_row.original_filename,
        stored_filename=stored_name,
        storage_path=rel_path,
        file_ext=ws_row.file_ext,
        mime_type=ws_row.mime_type,
        file_size=ws_row.file_size_bytes,
        sha256=ws_row.sha256,
        file_type=ft_value,
        file_role=fr_value,
        status="active",
        description=req.description or ws_row.description,
        remark=req.remark or ws_row.remark,
        source_workspace_file_id=workspace_file_id,
    )
    session.add(rf_row)
    await session.commit()
    await session.refresh(rf_row)

    await file_normalization_service.auto_normalize_after_upload(session, rf_row.id)

    _log("attach_to_resource", "success", file_id=new_file_id)
    return rf_row
