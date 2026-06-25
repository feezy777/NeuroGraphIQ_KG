from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.resource_file import (
    FileDeleteRequest,
    FileDeleteResult,
    FilePreviewResponse,
    FileOptionsResponse,
    FileRole,
    FileStatus,
    FileType,
    ResourceFileListResponse,
    ResourceFileRead,
    ResourceFileUpdate,
)
from app.services import resource_file_service, resource_service
from app.services import file_normalization_service

resource_router = APIRouter()
files_router = APIRouter()


async def _to_resource_file_read(
    session: AsyncSession,
    row,
    *,
    intermediate_summary: dict | None = None,
) -> ResourceFileRead:
    summary = intermediate_summary
    if summary is None:
        summary = await file_normalization_service.get_intermediate_summary_for_file(session, row.id)
    base = ResourceFileRead.model_validate(row)
    return base.model_copy(update=summary)


@files_router.get("/options", response_model=FileOptionsResponse)
async def get_file_options():
    return FileOptionsResponse(
        file_type=[e.value for e in FileType],
        file_role=[e.value for e in FileRole],
        status=[e.value for e in FileStatus],
        preview_supported_types=resource_file_service.PREVIEW_SUPPORTED_TYPES,
    )


@resource_router.post("/{resource_id}/files", response_model=ResourceFileRead, status_code=201)
async def upload_resource_file(
    resource_id: uuid.UUID,
    file: UploadFile = File(...),
    file_type: FileType | None = Form(default=None),
    file_role: FileRole = Form(default=FileRole.unknown),
    file_code: str | None = Form(default=None),
    description: str | None = Form(default=None),
    remark: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await resource_file_service.upload_file(
            session,
            resource_id,
            file,
            file_type=file_type,
            file_role=file_role,
            file_code=file_code,
            description=description,
            remark=remark,
        )
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    except resource_file_service.DuplicateFileError as exc:
        rid = exc.resource_id or resource_id
        existing = exc.existing
        inactive = exc.inactive
        if existing is None and rid is not None:
            existing, inactive = await resource_file_service._find_blocking_duplicate(
                session, rid, exc.sha256
            )
        if existing is not None and rid is not None:
            detail = await resource_file_service.build_duplicate_upload_detail(
                session,
                resource_id=rid,
                sha256=exc.sha256,
                existing=existing,
                inactive=inactive,
            )
        else:
            detail = {
                "code": "DUPLICATE_RESOURCE_FILE",
                "message": "duplicate file for this resource (same sha256)",
                "resource_id": str(rid),
                "sha256": exc.sha256,
                "suggestion": "Use the existing file instead of uploading it again.",
            }
        raise HTTPException(status_code=409, detail=detail) from exc
    except resource_file_service.FileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except resource_file_service.FileStorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    summary = await file_normalization_service.auto_normalize_after_upload(session, row.id)
    return await _to_resource_file_read(session, row, intermediate_summary=summary)


@resource_router.get("/{resource_id}/files", response_model=ResourceFileListResponse)
async def list_resource_files(
    resource_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    file_type: FileType | None = None,
    file_role: FileRole | None = None,
    status: str | None = Query(default="active", description="active | inactive | archived | all"),
    session: AsyncSession = Depends(get_db),
):
    status_key = (status or "active").strip().lower()
    if status_key not in {"active", "inactive", "archived", "all"}:
        raise HTTPException(
            status_code=400,
            detail="status must be active, inactive, archived, or all",
        )
    try:
        items, total = await resource_file_service.list_files_for_resource(
            session,
            resource_id,
            limit=limit,
            offset=offset,
            file_type=file_type.value if file_type else None,
            file_role=file_role.value if file_role else None,
            status=status_key,
        )
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    return ResourceFileListResponse(
        items=[await _to_resource_file_read(session, i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@files_router.get("/{file_id}", response_model=ResourceFileRead)
async def get_file_metadata(
    file_id: uuid.UUID,
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await resource_file_service.get_file(
            session, file_id, allow_archived=include_archived
        )
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    return await _to_resource_file_read(session, row)


@files_router.patch("/{file_id}", response_model=ResourceFileRead)
async def update_file_metadata(
    file_id: uuid.UUID,
    payload: ResourceFileUpdate,
    session: AsyncSession = Depends(get_db),
):
    if not payload.model_dump(exclude_unset=True):
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        row = await resource_file_service.update_file_metadata(session, file_id, payload)
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    return await _to_resource_file_read(session, row)


@files_router.post("/{file_id}/restore", response_model=ResourceFileRead)
async def restore_file(file_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_file_service.restore_file(session, file_id)
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except resource_file_service.FileRestoreConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FILE_RESTORE_SHA256_CONFLICT",
                "message": str(exc),
                "existing_file_id": str(exc.existing_file_id) if exc.existing_file_id else None,
            },
        ) from exc
    return await _to_resource_file_read(session, row)


@files_router.post("/{file_id}/destructive-delete", response_model=FileDeleteResult)
async def destructive_delete_file(
    file_id: uuid.UUID,
    payload: FileDeleteRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await resource_file_service.destructive_delete_file(session, file_id, payload)
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except resource_file_service.FileDeleteConfirmationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except resource_file_service.FileHasDependenciesError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FILE_HAS_DEPENDENCIES",
                "message": "This file is linked to import batches or downstream data and cannot be deleted alone.",
                "file_id": str(exc.file_id),
                "dependency_counts": exc.dependency_counts,
            },
        ) from exc


@files_router.delete("/{file_id}", response_model=ResourceFileRead)
async def delete_file(file_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_file_service.soft_delete_file(session, file_id)
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    return await _to_resource_file_read(session, row)


@files_router.get("/{file_id}/preview", response_model=FilePreviewResponse)
async def preview_file(file_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_file_service.get_file(session, file_id)
        return resource_file_service.build_file_preview(row)
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid storage path") from exc


@files_router.get("/{file_id}/download")
async def download_file(file_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_file_service.get_file(session, file_id)
        path = resource_file_service.resolve_download_path(row)
    except resource_file_service.FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid storage path") from exc

    return FileResponse(
        path=path,
        filename=row.original_filename,
        media_type=row.mime_type or "application/octet-stream",
    )
