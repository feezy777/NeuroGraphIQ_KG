"""File normalization API endpoints.

POST /api/files/{file_id}/normalize       — trigger normalization
GET  /api/files/{file_id}/intermediate    — list runs + latest status
GET  /api/files/{file_id}/intermediate/preview — preview latest active artifact
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.file_normalization import FileIntermediateArtifact, FileNormalizationRun
from app.schemas.file_normalization import (
    FileIntermediateStatusResponse,
    FileNormalizeResponse,
    IntermediateArtifactRead,
    IntermediatePreviewResponse,
    NormalizationRunRead,
)
from app.services import file_normalization_service
from app.services.file_normalization_service import (
    FileArchivedForNormalization,
    FileNormalizationError,
    FileNotFoundForNormalization,
)

router = APIRouter(prefix="/api/files", tags=["file-normalization"])


@router.post(
    "/{file_id}/normalize",
    response_model=FileNormalizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger file normalization (generate intermediate artifact)",
)
async def normalize_file(
    file_id: uuid.UUID,
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> FileNormalizeResponse:
    try:
        run = await file_normalization_service.normalize_file(
            session, file_id, force=force
        )
    except FileNotFoundForNormalization as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileArchivedForNormalization as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FileNormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    art_q = select(FileIntermediateArtifact).where(FileIntermediateArtifact.run_id == run.id)
    artifacts = list((await session.execute(art_q)).scalars().all())

    return FileNormalizeResponse(
        run_id=run.id,
        run_code=run.run_code,
        status=run.status,
        artifact_count=run.artifact_count,
        warning_count=run.warning_count,
        error_message=run.error_message,
        artifacts=[IntermediateArtifactRead.model_validate(a) for a in artifacts],
    )


@router.get(
    "/{file_id}/intermediate",
    response_model=FileIntermediateStatusResponse,
    summary="Get intermediate state status for a file",
)
async def get_intermediate_status(
    file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> FileIntermediateStatusResponse:
    data = await file_normalization_service.get_file_intermediate_status(session, file_id)
    artifacts = data.get("artifacts") or []
    runs = data.get("runs") or []
    latest_art = artifacts[0] if artifacts else None
    return FileIntermediateStatusResponse(
        file_id=uuid.UUID(data["file_id"]),
        status=data.get("status", "missing"),
        has_active_intermediate=data["has_active_intermediate"],
        latest_run_id=data["latest_run_id"],
        latest_run_status=data["latest_run_status"],
        latest_artifact_kind=data["latest_artifact_kind"],
        latest_artifact=IntermediateArtifactRead.model_validate(latest_art) if latest_art else None,
        latest_run_created_at=data["latest_run_created_at"],
        latest_run_error=data.get("latest_run_error"),
        artifact_count=data["artifact_count"],
        artifacts=[IntermediateArtifactRead.model_validate(a) for a in artifacts],
        runs=[NormalizationRunRead.model_validate(r) for r in runs],
    )


@router.get(
    "/{file_id}/intermediate/runs",
    response_model=list[NormalizationRunRead],
    summary="List normalization runs for a file",
)
async def list_normalization_runs(
    file_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
) -> list[NormalizationRunRead]:
    runs = await file_normalization_service.list_normalization_runs(
        session, file_id, limit=limit, offset=offset
    )
    return [NormalizationRunRead.model_validate(r) for r in runs]


@router.get(
    "/{file_id}/intermediate/preview",
    response_model=IntermediatePreviewResponse,
    summary="Preview the latest active intermediate artifact",
)
async def preview_intermediate(
    file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> IntermediatePreviewResponse:
    artifact = await file_normalization_service.get_latest_active_artifact(session, file_id)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active intermediate artifact found for file_id={file_id}",
        )

    return IntermediatePreviewResponse(
        file_id=file_id,
        artifact_id=artifact.id,
        artifact_kind=artifact.artifact_kind,
        source_format=artifact.source_format,
        row_count=artifact.row_count,
        preview=artifact.preview_jsonb,
        metadata=artifact.metadata_jsonb,
    )
