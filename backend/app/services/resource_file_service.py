"""File Upload & File Management business logic.

Structured audit_log table is not implemented yet; actions are logged via Python logger.
Upload does NOT create candidates, parse content, or write final_* / kg_*.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.resource_file import ResourceFile
from app.schemas.resource_file import FilePreviewResponse, FileRole, FileType, ResourceFileUpdate
from app.schemas.resource_file import FileDeleteRequest, FileDeleteResult
from app.services import resource_service
from app.utils.file_meta import (
    build_stored_filename,
    guess_mime_type,
    infer_file_type,
    normalize_extension,
    relative_storage_path,
    resolve_under_root,
)

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
MAX_PREVIEW_BYTES = 64 * 1024
PREVIEW_SUPPORTED_TYPES = [
    ".xml",
    ".json",
    ".txt",
    ".csv",
    ".tsv",
    ".md",
    ".yaml",
    ".yml",
    ".rdf",
    ".owl",
    ".ttl",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
]
_TEXT_PREVIEW_EXTENSIONS = {
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".rdf",
    ".owl",
    ".ttl",
}
_XML_PREVIEW_EXTENSIONS = {".xml"}
_JSON_PREVIEW_EXTENSIONS = {".json"}
_CSV_PREVIEW_EXTENSIONS = {".csv", ".tsv"}
_IMAGE_PREVIEW_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_BINARY_UNSUPPORTED_EXTENSIONS = {
    ".nii",
    ".nii.gz",
    ".npz",
    ".npy",
    ".pkl",
    ".pickle",
    ".mat",
    ".zip",
    ".gz",
    ".tar.gz",
    ".pdf",
    ".xlsx",
    ".xls",
}


class FileNotFoundError(Exception):
    pass


class DuplicateFileError(Exception):
    def __init__(
        self,
        sha256: str,
        *,
        resource_id: uuid.UUID | None = None,
        existing: ResourceFile | None = None,
        inactive: bool = False,
    ):
        self.sha256 = sha256
        self.resource_id = resource_id
        self.existing = existing
        self.existing_id = existing.id if existing else None
        self.inactive = inactive
        # Backward-compatible alias used by older call sites.
        self.archived = inactive
        super().__init__(sha256)


def _is_file_active(row: ResourceFile) -> bool:
    return row.deleted_at is None and row.status == "active"


class FileStorageError(Exception):
    pass


class FileValidationError(Exception):
    """Upload metadata rejected by database constraints (not a duplicate)."""

    pass


class FileRestoreConflictError(Exception):
    def __init__(self, message: str, *, existing_file_id: uuid.UUID | None = None):
        super().__init__(message)
        self.existing_file_id = existing_file_id


class FileHasDependenciesError(Exception):
    def __init__(self, file_id: uuid.UUID, dependency_counts: dict[str, int]):
        super().__init__(str(file_id))
        self.file_id = file_id
        self.dependency_counts = dependency_counts


def get_upload_root() -> Path:
    settings = get_settings()
    root = Path(settings.upload_dir)
    if not root.is_absolute():
        root = _BACKEND_ROOT / root
    return root.resolve()


def _log_action(
    *,
    event_type: str,
    action: str,
    result: str,
    resource_id: uuid.UUID | None = None,
    file_id: uuid.UUID | None = None,
    original_filename: str | None = None,
    sha256: str | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=%s action=%s result=%s resource_id=%s file_id=%s "
        "original_filename=%s sha256=%s error=%s",
        event_type,
        action,
        result,
        resource_id,
        file_id,
        original_filename,
        sha256,
        error,
    )


async def _find_active_duplicate(
    session: AsyncSession, resource_id: uuid.UUID, sha256: str
) -> ResourceFile | None:
    q = select(ResourceFile).where(
        ResourceFile.resource_id == resource_id,
        ResourceFile.sha256 == sha256,
        ResourceFile.deleted_at.is_(None),
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _find_any_duplicate_by_sha(
    session: AsyncSession, resource_id: uuid.UUID, sha256: str
) -> ResourceFile | None:
    q = (
        select(ResourceFile)
        .where(
            ResourceFile.resource_id == resource_id,
            ResourceFile.sha256 == sha256,
        )
        .order_by(ResourceFile.created_at.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _find_blocking_duplicate(
    session: AsyncSession, resource_id: uuid.UUID, sha256: str
) -> tuple[ResourceFile | None, bool]:
    """Return (existing_row, is_inactive). Active duplicate takes precedence."""
    active = await _find_active_duplicate(session, resource_id, sha256)
    if active is not None:
        return active, False
    inactive = await _find_any_duplicate_by_sha(session, resource_id, sha256)
    if inactive is not None:
        return inactive, True
    return None, False


def _integrity_error_is_sha256_duplicate(exc: IntegrityError) -> bool:
    msg = str(exc.orig).lower()
    return "uq_resource_files_resource_sha256_active" in msg


def _existing_file_summary(existing: ResourceFile, summary: dict | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": str(existing.id),
        "resource_id": str(existing.resource_id),
        "original_filename": existing.original_filename,
        "file_type": existing.file_type,
        "file_role": existing.file_role,
        "status": existing.status,
        "file_size_bytes": existing.file_size,
        "sha256": existing.sha256,
        "created_at": existing.created_at.isoformat() if existing.created_at else None,
        "updated_at": existing.updated_at.isoformat() if existing.updated_at else None,
    }
    if summary:
        payload.update(
            {
                "intermediate_status": summary.get("intermediate_status"),
                "latest_intermediate_artifact_id": (
                    str(summary["latest_intermediate_artifact_id"])
                    if summary.get("latest_intermediate_artifact_id")
                    else None
                ),
                "latest_intermediate_kind": summary.get("latest_intermediate_kind"),
                "latest_intermediate_row_count": summary.get("latest_intermediate_row_count"),
            }
        )
    return payload


async def build_duplicate_upload_detail(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID,
    sha256: str,
    existing: ResourceFile,
    inactive: bool,
) -> dict[str, object]:
    """Structured 409 detail for duplicate upload under the same resource."""
    from app.services import file_normalization_service

    summary = await file_normalization_service.get_intermediate_summary_for_file(session, existing.id)
    existing_payload = _existing_file_summary(existing, summary)

    if inactive or not _is_file_active(existing):
        return {
            "code": "DUPLICATE_RESOURCE_FILE_INACTIVE",
            "message": "The same file already exists for this resource but is not active.",
            "resource_id": str(resource_id),
            "sha256": sha256,
            "existing_file": existing_payload,
            "suggestion": "Reactivate the existing file or upload a different file.",
        }

    return {
        "code": "DUPLICATE_RESOURCE_FILE",
        "message": "This file already exists for the selected resource.",
        "resource_id": str(resource_id),
        "sha256": sha256,
        "existing_file": existing_payload,
        "suggestion": "Use the existing file instead of uploading it again.",
    }


async def list_files_for_resource(
    session: AsyncSession,
    resource_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
    file_type: str | None = None,
    file_role: str | None = None,
    status: str | None = None,
) -> tuple[list[ResourceFile], int]:
    await resource_service.get_resource(session, resource_id)

    status_key = (status or "active").strip().lower()
    if status_key == "inactive":
        status_key = "archived"

    base = select(ResourceFile).where(ResourceFile.resource_id == resource_id)
    count_q = (
        select(func.count())
        .select_from(ResourceFile)
        .where(ResourceFile.resource_id == resource_id)
    )

    if status_key == "all":
        pass
    elif status_key == "archived":
        base = base.where(
            (ResourceFile.status == "archived") | (ResourceFile.deleted_at.is_not(None))
        )
        count_q = count_q.where(
            (ResourceFile.status == "archived") | (ResourceFile.deleted_at.is_not(None))
        )
    else:
        # Default and explicit active: non-deleted active files only.
        base = base.where(
            ResourceFile.deleted_at.is_(None),
            ResourceFile.status == "active",
        )
        count_q = count_q.where(
            ResourceFile.deleted_at.is_(None),
            ResourceFile.status == "active",
        )

    if file_type:
        base = base.where(ResourceFile.file_type == file_type)
        count_q = count_q.where(ResourceFile.file_type == file_type)
    if file_role:
        base = base.where(ResourceFile.file_role == file_role)
        count_q = count_q.where(ResourceFile.file_role == file_role)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(ResourceFile.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_file(
    session: AsyncSession,
    file_id: uuid.UUID,
    *,
    allow_archived: bool = False,
) -> ResourceFile:
    row = await session.get(ResourceFile, file_id)
    if row is None:
        raise FileNotFoundError(str(file_id))
    if not allow_archived and not _is_file_active(row):
        raise FileNotFoundError(str(file_id))
    return row


async def upload_file(
    session: AsyncSession,
    resource_id: uuid.UUID,
    upload: UploadFile,
    *,
    file_type: FileType | None = None,
    file_role: FileRole = FileRole.unknown,
    file_code: str | None = None,
    description: str | None = None,
    remark: str | None = None,
) -> ResourceFile:
    await resource_service.get_resource(session, resource_id)

    original = upload.filename or "upload"
    resolved_type = infer_file_type(original, file_type)
    file_ext = normalize_extension(original)
    upload_root = get_upload_root()
    resource_dir = upload_root / str(resource_id)
    resource_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4()
    temp_path: Path | None = None
    final_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=resource_dir, delete=False, prefix=".tmp_upload_"
        ) as tmp:
            temp_path = Path(tmp.name)
            h = hashlib.sha256()
            size = 0
            while chunk := await upload.read(65536):
                h.update(chunk)
                tmp.write(chunk)
                size += len(chunk)
            digest = h.hexdigest()

        dup, inactive = await _find_blocking_duplicate(session, resource_id, digest)
        if dup is not None:
            _log_action(
                event_type="resource_file",
                action="upload",
                result="duplicate_inactive" if inactive else "duplicate",
                resource_id=resource_id,
                file_id=dup.id,
                original_filename=original,
                sha256=digest,
            )
            raise DuplicateFileError(
                digest,
                resource_id=resource_id,
                existing=dup,
                inactive=inactive,
            )

        stored_filename = build_stored_filename(str(file_id), digest, original)
        rel_path = relative_storage_path(str(resource_id), stored_filename)
        final_path = resolve_under_root(upload_root, rel_path)
        os.replace(temp_path, final_path)
        temp_path = None

        mime = guess_mime_type(original, upload.content_type)
        row = ResourceFile(
            id=file_id,
            resource_id=resource_id,
            file_code=file_code,
            original_filename=original,
            stored_filename=stored_filename,
            storage_path=rel_path,
            file_ext=file_ext,
            mime_type=mime,
            file_size=size,
            sha256=digest,
            file_type=resolved_type.value,
            file_role=file_role.value,
            status="active",
            description=description,
            remark=remark,
        )
        session.add(row)
        try:
            await session.commit()
            await session.refresh(row)
        except IntegrityError as exc:
            await session.rollback()
            if final_path and final_path.is_file():
                final_path.unlink(missing_ok=True)
            _log_action(
                event_type="resource_file",
                action="upload",
                result="error",
                resource_id=resource_id,
                original_filename=original,
                sha256=digest,
                error=str(exc.orig),
            )
            if _integrity_error_is_sha256_duplicate(exc):
                dup, inactive = await _find_blocking_duplicate(session, resource_id, digest)
                if dup is not None:
                    raise DuplicateFileError(
                        digest,
                        resource_id=resource_id,
                        existing=dup,
                        inactive=inactive,
                    ) from exc
                raise DuplicateFileError(digest, resource_id=resource_id) from exc
            raise FileValidationError(
                f"file upload rejected by database constraint: {exc.orig}"
            ) from exc

        _log_action(
            event_type="resource_file",
            action="upload",
            result="success",
            resource_id=resource_id,
            file_id=row.id,
            original_filename=original,
            sha256=digest,
        )
        return row

    except DuplicateFileError:
        raise
    except Exception as exc:
        _log_action(
            event_type="resource_file",
            action="upload",
            result="error",
            resource_id=resource_id,
            original_filename=original,
            error=str(exc),
        )
        raise FileStorageError(str(exc)) from exc
    finally:
        if temp_path and temp_path.is_file():
            temp_path.unlink(missing_ok=True)
        await upload.close()


async def update_file_metadata(
    session: AsyncSession, file_id: uuid.UUID, payload: ResourceFileUpdate
) -> ResourceFile:
    row = await get_file(session, file_id, allow_archived=True)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value.value if hasattr(value, "value") else value)
    if row.status == "active":
        row.deleted_at = None

    await session.commit()
    await session.refresh(row)

    _log_action(
        event_type="resource_file",
        action="update",
        result="success",
        resource_id=row.resource_id,
        file_id=row.id,
        original_filename=row.original_filename,
        sha256=row.sha256,
    )
    return row


async def soft_delete_file(session: AsyncSession, file_id: uuid.UUID) -> ResourceFile:
    row = await get_file(session, file_id)
    now = datetime.now(timezone.utc)
    row.deleted_at = now
    row.status = "archived"
    await session.commit()
    await session.refresh(row)

    _log_action(
        event_type="resource_file",
        action="soft_delete",
        result="success",
        resource_id=row.resource_id,
        file_id=row.id,
        original_filename=row.original_filename,
        sha256=row.sha256,
    )
    return row


def _preview_kind(row: ResourceFile) -> str:
    ext = (row.file_ext or normalize_extension(row.original_filename)).lower()
    mime = (row.mime_type or "").lower()
    if ext in _BINARY_UNSUPPORTED_EXTENSIONS:
        return "unsupported"
    if (row.file_type or "").lower() == "spreadsheet" or "spreadsheet" in mime or "excel" in mime:
        return "unsupported"
    if ext in _XML_PREVIEW_EXTENSIONS or mime in ("application/xml", "text/xml"):
        return "xml"
    if ext in _JSON_PREVIEW_EXTENSIONS or "json" in mime:
        return "json"
    if ext in _CSV_PREVIEW_EXTENSIONS:
        return "csv"
    if ext in _IMAGE_PREVIEW_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if ext in _TEXT_PREVIEW_EXTENSIONS or mime.startswith("text/"):
        return "text"
    if ext in _BINARY_UNSUPPORTED_EXTENSIONS:
        return "unsupported"
    return "unsupported"


def _preview_metadata(row: ResourceFile) -> dict[str, str | int | None]:
    return {
        "sha256": row.sha256,
        "storage_path": row.storage_path,
        "file_ext": row.file_ext,
        "stored_filename": row.stored_filename,
        "line_count_estimated": None,
    }


def build_file_preview(
    row: ResourceFile,
    *,
    upload_root: Path | None = None,
    max_bytes: int = MAX_PREVIEW_BYTES,
) -> FilePreviewResponse:
    if row.status != "active" or row.deleted_at is not None:
        raise FileNotFoundError(str(row.id))

    root = upload_root.resolve() if upload_root else get_upload_root()
    path = resolve_under_root(root, row.storage_path)
    metadata = _preview_metadata(row)
    kind = _preview_kind(row)

    if not path.is_file():
        return FilePreviewResponse(
            file_id=row.id,
            filename=row.original_filename,
            file_type=row.file_type,
            mime_type=row.mime_type,
            preview_kind="missing",
            is_truncated=False,
            max_bytes=max_bytes,
            size_bytes=row.file_size,
            content=None,
            metadata=metadata,
            error_message="file missing on disk",
        )

    size = path.stat().st_size
    if kind == "image":
        return FilePreviewResponse(
            file_id=row.id,
            filename=row.original_filename,
            file_type=row.file_type,
            mime_type=row.mime_type,
            preview_kind="image",
            is_truncated=False,
            max_bytes=max_bytes,
            size_bytes=size,
            content=None,
            metadata=metadata,
        )

    if kind == "unsupported":
        return FilePreviewResponse(
            file_id=row.id,
            filename=row.original_filename,
            file_type=row.file_type,
            mime_type=row.mime_type,
            preview_kind="unsupported",
            is_truncated=False,
            max_bytes=max_bytes,
            size_bytes=size,
            content=None,
            metadata=metadata,
            error_message="inline preview is not supported for this file type",
        )

    raw = path.read_bytes()[: max_bytes + 1]
    is_truncated = len(raw) > max_bytes or size > max_bytes
    raw = raw[:max_bytes]
    text = raw.decode("utf-8", errors="replace")
    metadata["line_count_estimated"] = text.count("\n") + (1 if text else 0)

    return FilePreviewResponse(
        file_id=row.id,
        filename=row.original_filename,
        file_type=row.file_type,
        mime_type=row.mime_type,
        preview_kind=kind,
        is_truncated=is_truncated,
        max_bytes=max_bytes,
        size_bytes=size,
        encoding="utf-8",
        content=text,
        metadata=metadata,
    )


def resolve_download_path(row: ResourceFile) -> Path:
    if row.status != "active" or row.deleted_at is not None:
        raise FileNotFoundError(str(row.id))
    upload_root = get_upload_root()
    path = resolve_under_root(upload_root, row.storage_path)
    if not path.is_file():
        raise FileNotFoundError(str(row.id))
    return path


async def count_file_dependencies(session: AsyncSession, file_id: uuid.UUID) -> dict[str, int]:
    from app.models.candidate import CandidateBrainRegion
    from app.models.import_batch import ImportBatchFile
    from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun

    async def _count(model: type, column) -> int:
        q = select(func.count()).select_from(model).where(column == file_id)
        return int((await session.execute(q)).scalar_one())

    return {
        "import_batch_files": await _count(ImportBatchFile, ImportBatchFile.file_id),
        "raw_parse_runs": await _count(RawParseRun, RawParseRun.source_file_id),
        "raw_aal3_region_labels": await _count(RawAal3RegionLabel, RawAal3RegionLabel.source_file_id),
        "candidate_brain_regions": await _count(CandidateBrainRegion, CandidateBrainRegion.source_file_id),
    }


async def restore_file(session: AsyncSession, file_id: uuid.UUID) -> ResourceFile:
    row = await get_file(session, file_id, allow_archived=True)
    if _is_file_active(row):
        return row
    other_active = await _find_active_duplicate(session, row.resource_id, row.sha256)
    if other_active is not None and other_active.id != row.id:
        raise FileRestoreConflictError(
            "Another active file with the same sha256 exists for this resource.",
            existing_file_id=other_active.id,
        )
    row.status = "active"
    row.deleted_at = None
    await session.commit()
    await session.refresh(row)
    _log_action(
        event_type="resource_file",
        action="restore",
        result="success",
        resource_id=row.resource_id,
        file_id=row.id,
        sha256=row.sha256,
    )
    return row


class FileDeleteConfirmationError(Exception):
    pass


async def destructive_delete_file(
    session: AsyncSession,
    file_id: uuid.UUID,
    request: FileDeleteRequest,
) -> FileDeleteResult:
    row = await get_file(session, file_id, allow_archived=True)
    expected = f"DELETE FILE {file_id}"
    if request.confirmation_text.strip() != expected:
        raise FileDeleteConfirmationError(
            f"confirmation_text must exactly match: {expected}"
        )

    deps = await count_file_dependencies(session, file_id)
    if sum(deps.values()) > 0:
        raise FileHasDependenciesError(file_id, deps)

    storage_path = row.storage_path
    resource_id = row.resource_id
    deleted_counts: dict[str, int] = {}

    from app.models.file_normalization import FileIntermediateArtifact, FileNormalizationRun

    deleted_counts["file_intermediate_artifacts"] = int(
        (
            await session.execute(
                delete(FileIntermediateArtifact).where(FileIntermediateArtifact.file_id == file_id)
            )
        ).rowcount
        or 0
    )
    deleted_counts["file_normalization_runs"] = int(
        (
            await session.execute(
                delete(FileNormalizationRun).where(FileNormalizationRun.file_id == file_id)
            )
        ).rowcount
        or 0
    )
    deleted_counts["resource_files"] = int(
        (await session.execute(delete(ResourceFile).where(ResourceFile.id == file_id))).rowcount
        or 0
    )
    await session.commit()

    physical_ok = False
    physical_err: str | None = None
    if request.delete_physical_file:
        try:
            upload_root = get_upload_root()
            path = resolve_under_root(upload_root, storage_path)
            if path.is_file():
                path.unlink()
            physical_ok = True
        except Exception as exc:
            physical_err = str(exc)

    _log_action(
        event_type="resource_file",
        action="destructive_delete",
        result="success",
        resource_id=resource_id,
        file_id=file_id,
        sha256=row.sha256,
    )
    return FileDeleteResult(
        file_id=file_id,
        resource_id=resource_id,
        deleted_counts=deleted_counts,
        can_reupload_same_sha256=True,
        physical_file_deleted=physical_ok if request.delete_physical_file else False,
        physical_file_error=physical_err,
    )
