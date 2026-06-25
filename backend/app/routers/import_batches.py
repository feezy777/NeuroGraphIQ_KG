from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.import_batch import (
    BatchType,
    FileRoleInBatch,
    ImportBatchCreate,
    ImportBatchDetail,
    ImportBatchEventListResponse,
    ImportBatchEventRead,
    ImportBatchFileAttach,
    ImportBatchFileListResponse,
    ImportBatchFilePatch,
    ImportBatchFilesUpdate,
    ImportBatchListResponse,
    ImportBatchOptionsResponse,
    ImportBatchRead,
    ImportBatchStatus,
    ImportBatchStatusUpdate,
    ImportBatchUpdate,
)
from app.schemas.import_batch_run_history import ImportBatchRunHistoryResponse
from app.schemas.import_batch_rollback import (
    RollbackExecuteRequest,
    RollbackExecuteResponse,
    RollbackPreviewResponse,
)
from app.services import import_batch_run_history_service
from app.services import import_batch_service
from app.services import import_batch_rollback_service

router = APIRouter()


@router.get("/options", response_model=ImportBatchOptionsResponse)
async def get_import_batch_options():
    return ImportBatchOptionsResponse(
        batch_type=[e.value for e in BatchType],
        status=[e.value for e in ImportBatchStatus],
        file_role_in_batch=[e.value for e in FileRoleInBatch],
    )


@router.post("", response_model=ImportBatchDetail, status_code=201)
async def create_import_batch(
    payload: ImportBatchCreate, session: AsyncSession = Depends(get_db)
):
    try:
        batch = await import_batch_service.create_batch(session, payload)
        batch, files, events = await import_batch_service.get_batch_detail(session, batch.id)
    except import_batch_service.ResourceNotEligibleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except import_batch_service.FileBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except import_batch_service.BatchCodeConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "batch_code already exists", "batch_code": str(exc)},
        ) from exc

    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    return await _build_detail(session, batch, files, events, file_map)


@router.get("", response_model=ImportBatchListResponse)
async def list_import_batches(
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    resource_id: uuid.UUID | None = None,
    batch_type: BatchType | None = None,
    status: ImportBatchStatus | None = None,
    parser_key: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    items, total = await import_batch_service.list_batches(
        session,
        limit=limit,
        offset=offset,
        resource_id=resource_id,
        batch_type=batch_type.value if batch_type else None,
        status=status.value if status else None,
        parser_key=parser_key,
    )
    return ImportBatchListResponse(
        items=[ImportBatchRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_id}", response_model=ImportBatchDetail)
async def get_import_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        batch, files, events = await import_batch_service.get_batch_detail(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    return await _build_detail(session, batch, files, events, file_map)


@router.get("/{batch_id}/files", response_model=ImportBatchFileListResponse)
async def list_import_batch_files(
    batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        files = await import_batch_service.list_batch_files(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    enriched, warnings = await import_batch_service.build_enriched_file_reads(
        session, files, file_map
    )
    return ImportBatchFileListResponse(items=enriched, total=len(enriched), warnings=warnings)


@router.get("/{batch_id}/events", response_model=ImportBatchEventListResponse)
async def list_import_batch_events(
    batch_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        events, total = await import_batch_service.list_batch_events(
            session, batch_id, limit=limit, offset=offset
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    return ImportBatchEventListResponse(
        items=[ImportBatchEventRead.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_id}/rollback-preview", response_model=RollbackPreviewResponse)
async def get_import_batch_rollback_preview(
    batch_id: uuid.UUID,
    target_status: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await import_batch_rollback_service.get_import_batch_rollback_preview(
            session, batch_id, target_status
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_rollback_service.RollbackPreviewInvalidTargetError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except import_batch_rollback_service.RollbackPreviewNotSupportedError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc


@router.post("/{batch_id}/rollback", response_model=RollbackExecuteResponse)
async def execute_import_batch_rollback(
    batch_id: uuid.UUID,
    payload: RollbackExecuteRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await import_batch_rollback_service.execute_import_batch_rollback(
            session, batch_id, payload
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_rollback_service.RollbackExecuteConfirmationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except import_batch_rollback_service.RollbackPreviewInvalidTargetError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except import_batch_rollback_service.RollbackPreviewNotSupportedError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except import_batch_rollback_service.RollbackExecuteStalePreviewError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except import_batch_rollback_service.RollbackExecuteUnsafeScopeError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{batch_id}/run-history", response_model=ImportBatchRunHistoryResponse)
async def get_import_batch_run_history(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await import_batch_run_history_service.get_import_batch_run_history(
            session, batch_id
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc


@router.patch("/{batch_id}", response_model=ImportBatchDetail)
async def patch_import_batch(
    batch_id: uuid.UUID,
    payload: ImportBatchUpdate,
    session: AsyncSession = Depends(get_db),
):
    try:
        await import_batch_service.update_batch(session, batch_id, payload)
        batch, files, events = await import_batch_service.get_batch_detail(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.BatchEditNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except import_batch_service.BatchCodeConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "batch_code already exists", "batch_code": str(exc)},
        ) from exc
    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    return await _build_detail(session, batch, files, events, file_map)


@router.patch("/{batch_id}/files", response_model=ImportBatchFileListResponse)
async def patch_import_batch_files(
    batch_id: uuid.UUID,
    payload: ImportBatchFilesUpdate,
    session: AsyncSession = Depends(get_db),
):
    try:
        files, warnings = await import_batch_service.replace_batch_files(
            session, batch_id, payload.files
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.BatchEditNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except import_batch_service.FileBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    enriched, extra_warnings = await import_batch_service.build_enriched_file_reads(
        session, files, file_map
    )
    all_warnings = warnings + extra_warnings
    return ImportBatchFileListResponse(
        items=enriched, total=len(enriched), warnings=all_warnings
    )


@router.post("/{batch_id}/files", response_model=ImportBatchFileListResponse, status_code=201)
async def attach_import_batch_file(
    batch_id: uuid.UUID,
    payload: ImportBatchFileAttach,
    session: AsyncSession = Depends(get_db),
):
    from app.schemas.import_batch import ImportBatchFileBinding

    binding = ImportBatchFileBinding(
        file_id=payload.file_id,
        file_role_in_batch=payload.file_role_in_batch,
        sort_order=payload.sort_order,
    )
    try:
        files = await import_batch_service.attach_batch_file(session, batch_id, binding)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.BatchEditNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except import_batch_service.FileBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    enriched, warnings = await import_batch_service.build_enriched_file_reads(
        session, files, file_map
    )
    return ImportBatchFileListResponse(items=enriched, total=len(enriched), warnings=warnings)


@router.patch("/{batch_id}/files/{file_id}", response_model=ImportBatchFileListResponse)
async def patch_import_batch_file_binding(
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: ImportBatchFilePatch,
    session: AsyncSession = Depends(get_db),
):
    patch = payload.model_dump(exclude_unset=True)
    try:
        files = await import_batch_service.update_batch_file_binding(
            session,
            batch_id,
            file_id,
            file_role_in_batch=patch.get("file_role_in_batch"),
            sort_order=patch.get("sort_order"),
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.BatchEditNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except import_batch_service.FileBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    enriched, warnings = await import_batch_service.build_enriched_file_reads(
        session, files, file_map
    )
    return ImportBatchFileListResponse(items=enriched, total=len(enriched), warnings=warnings)


@router.delete("/{batch_id}/files/{file_id}", response_model=ImportBatchFileListResponse)
async def detach_import_batch_file(
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        files = await import_batch_service.detach_batch_file(session, batch_id, file_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.BatchEditNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except import_batch_service.FileBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    enriched, warnings = await import_batch_service.build_enriched_file_reads(
        session, files, file_map
    )
    return ImportBatchFileListResponse(items=enriched, total=len(enriched), warnings=warnings)


@router.post("/{batch_id}/clone", response_model=ImportBatchDetail, status_code=201)
async def clone_import_batch(
    batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        batch = await import_batch_service.clone_batch(session, batch_id)
        batch, files, events = await import_batch_service.get_batch_detail(session, batch.id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.ResourceNotEligibleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except import_batch_service.FileBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except import_batch_service.BatchCodeConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "batch_code already exists", "batch_code": str(exc)},
        ) from exc

    file_map = await import_batch_service.load_resource_files_for_bindings(session, files)
    return await _build_detail(session, batch, files, events, file_map)


@router.post("/{batch_id}/cancel", response_model=ImportBatchRead)
async def cancel_import_batch(
    batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        batch = await import_batch_service.cancel_batch(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "invalid status transition",
                "from_status": exc.from_status,
                "to_status": exc.to_status,
                "reason": exc.reason,
            },
        ) from exc
    return ImportBatchRead.model_validate(batch)


@router.post("/{batch_id}/queue", response_model=ImportBatchRead)
async def queue_import_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    return await _transition_endpoint(session, batch_id, import_batch_service.queue_batch)


@router.post("/{batch_id}/start", response_model=ImportBatchRead)
async def start_import_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    return await _transition_endpoint(session, batch_id, import_batch_service.start_batch)


@router.post("/{batch_id}/complete", response_model=ImportBatchRead)
async def complete_import_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    return await _transition_endpoint(session, batch_id, import_batch_service.complete_batch)


@router.post("/{batch_id}/fail", response_model=ImportBatchRead)
async def fail_import_batch(
    batch_id: uuid.UUID,
    error_message: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    try:
        batch = await import_batch_service.fail_batch(
            session, batch_id, error_message=error_message
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "invalid status transition",
                "from_status": exc.from_status,
                "to_status": exc.to_status,
                "reason": exc.reason,
            },
        ) from exc
    return ImportBatchRead.model_validate(batch)


@router.post("/{batch_id}/status", response_model=ImportBatchRead)
async def update_import_batch_status(
    batch_id: uuid.UUID,
    payload: ImportBatchStatusUpdate,
    session: AsyncSession = Depends(get_db),
):
    try:
        batch = await import_batch_service.update_batch_status(
            session,
            batch_id,
            payload.status,
            message=payload.message,
            error_message=payload.error_message,
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "invalid status transition",
                "from_status": exc.from_status,
                "to_status": exc.to_status,
                "reason": exc.reason,
            },
        ) from exc
    return ImportBatchRead.model_validate(batch)


async def _transition_endpoint(session, batch_id, fn):
    try:
        batch = await fn(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except import_batch_service.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "invalid status transition",
                "from_status": exc.from_status,
                "to_status": exc.to_status,
                "reason": exc.reason,
            },
        ) from exc
    return ImportBatchRead.model_validate(batch)


async def _build_detail(session, batch, files, events, file_map) -> ImportBatchDetail:
    enriched, warnings = await import_batch_service.build_enriched_file_reads(
        session, files, file_map
    )
    return ImportBatchDetail(
        **ImportBatchRead.model_validate(batch).model_dump(),
        files=enriched,
        recent_events=[ImportBatchEventRead.model_validate(e) for e in events],
        warnings=warnings,
        next_allowed_actions=import_batch_service.compute_batch_next_actions(batch.status),
    )
