"""Workspace Public Files API router.

Workspace files are staging files without resource_id.
Workspace files CANNOT directly enter import_batch_files.
They must be attached via POST /{id}/attach-to-resource first.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.resource_file import ResourceFileRead
from app.schemas.workspace_file import (
    AttachToResourceRequest,
    WorkspaceFileListResponse,
    WorkspaceFileRead,
    WorkspaceFileUpdate,
)
from app.services import resource_service, workspace_file_service
from app.services.resource_file_service import DuplicateFileError
from app.services.workspace_file_service import (
    WorkspaceFileArchivedError,
    WorkspaceFileNotFoundError,
    WorkspaceFileStorageError,
)

router = APIRouter(prefix="/api/workspace-files", tags=["Workspace Files"])


@router.post("", response_model=WorkspaceFileRead, status_code=201)
async def upload_workspace_file(
    file: UploadFile = File(...),
    file_type: str | None = Form(default=None),
    file_role: str | None = Form(default=None),
    description: str | None = Form(default=None),
    remark: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
) -> WorkspaceFileRead:
    try:
        row = await workspace_file_service.upload_workspace_file(
            session,
            file,
            file_type=file_type,
            file_role=file_role,
            description=description,
            remark=remark,
        )
    except WorkspaceFileStorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return WorkspaceFileRead.model_validate(row)


@router.get("", response_model=WorkspaceFileListResponse)
async def list_workspace_files(
    status: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    file_role: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> WorkspaceFileListResponse:
    items, total = await workspace_file_service.list_workspace_files(
        session,
        status=status,
        file_type=file_type,
        file_role=file_role,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return WorkspaceFileListResponse(
        items=[WorkspaceFileRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{workspace_file_id}", response_model=WorkspaceFileRead)
async def get_workspace_file(
    workspace_file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceFileRead:
    try:
        row = await workspace_file_service.get_workspace_file(session, workspace_file_id)
    except WorkspaceFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace file not found") from exc
    return WorkspaceFileRead.model_validate(row)


@router.patch("/{workspace_file_id}", response_model=WorkspaceFileRead)
async def update_workspace_file(
    workspace_file_id: uuid.UUID,
    payload: WorkspaceFileUpdate,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceFileRead:
    if not payload.model_dump(exclude_unset=True):
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        row = await workspace_file_service.update_workspace_file(session, workspace_file_id, payload)
    except WorkspaceFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace file not found") from exc
    return WorkspaceFileRead.model_validate(row)


@router.delete("/{workspace_file_id}", response_model=WorkspaceFileRead)
async def archive_workspace_file(
    workspace_file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceFileRead:
    """Soft-delete (archive) a workspace file. Does not delete physical file or resource_files."""
    try:
        row = await workspace_file_service.archive_workspace_file(session, workspace_file_id)
    except WorkspaceFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace file not found") from exc
    return WorkspaceFileRead.model_validate(row)


@router.get("/{workspace_file_id}/preview")
async def preview_workspace_file(
    workspace_file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await workspace_file_service.get_workspace_file(session, workspace_file_id)
        return workspace_file_service.build_workspace_file_preview(row)
    except WorkspaceFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid storage path") from exc


@router.get("/{workspace_file_id}/download")
async def download_workspace_file(
    workspace_file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await workspace_file_service.get_workspace_file(session, workspace_file_id)
        path = workspace_file_service.resolve_workspace_download_path(row)
    except WorkspaceFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid storage path") from exc
    return FileResponse(
        path=path,
        filename=row.original_filename,
        media_type=row.mime_type or "application/octet-stream",
    )


@router.post("/{workspace_file_id}/attach-to-resource", response_model=ResourceFileRead)
async def attach_to_resource(
    workspace_file_id: uuid.UUID,
    req: AttachToResourceRequest,
    session: AsyncSession = Depends(get_db),
) -> ResourceFileRead:
    """Attach a workspace file to a resource → creates a resource_files record.

    This is the ONLY path from workspace files into the formal import pipeline.
    Does NOT create batch, parse, generate candidates, write final_*, or call LLM.
    """
    try:
        rf_row = await workspace_file_service.attach_to_resource(session, workspace_file_id, req)
    except WorkspaceFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace file not found") from exc
    except WorkspaceFileArchivedError as exc:
        raise HTTPException(status_code=422, detail="workspace file is not active") from exc
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    except DuplicateFileError as exc:
        detail = {
            "message": "file with same sha256 already exists in this resource",
            "sha256": exc.sha256,
        }
        if exc.existing_id:
            detail["existing_file_id"] = str(exc.existing_id)
        raise HTTPException(status_code=409, detail=detail) from exc
    return ResourceFileRead.model_validate(rf_row)
