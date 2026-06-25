"""Final KG export API (Step 8.17, read-only DB, local files only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.final_kg_export import (
    FinalKgExportManifest,
    FinalKgExportManifestListResponse,
    FinalKgExportFileListResponse,
    FinalKgExportPreviewResponse,
    FinalKgExportRequest,
    FinalKgExportRunResponse,
)
from app.services import final_kg_export_service as fkes

router = APIRouter()


@router.post("/export/run", response_model=FinalKgExportRunResponse | FinalKgExportPreviewResponse)
async def run_export(
    body: FinalKgExportRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await fkes.run_final_kg_export(
            session,
            body,
            app_version="4.6.0-mvp2-final-kg-export",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/export/list", response_model=FinalKgExportManifestListResponse)
async def list_exports():
    return fkes.list_exports()


@router.get("/export/{export_id}/manifest", response_model=FinalKgExportManifest)
async def get_manifest(export_id: str):
    try:
        fkes.sanitize_export_id(export_id)
        return fkes.get_export_manifest(export_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/export/{export_id}/files", response_model=FinalKgExportFileListResponse)
async def list_files(export_id: str):
    try:
        fkes.sanitize_export_id(export_id)
        return fkes.list_export_files(export_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/export/{export_id}/files/{filename}")
async def download_file(export_id: str, filename: str):
    try:
        path = fkes.get_export_file_path(export_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
