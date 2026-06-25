"""Workbench Pipeline aggregation router — read-only.

GET /api/workbench/import-batches/{batch_id}/overview
Returns a complete pipeline overview for one import batch.
This endpoint NEVER writes to any table.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.workbench_pipeline import ImportBatchPipelineOverview
from app.services import import_batch_service, workbench_pipeline_service

router = APIRouter()


@router.get(
    "/import-batches/{batch_id}/overview",
    response_model=ImportBatchPipelineOverview,
    tags=["Workbench Pipeline"],
)
async def get_import_batch_pipeline_overview(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """Read-only aggregation of the full import pipeline for one batch.

    Does NOT write to any table, change any status, or call LLM.
    """
    try:
        return await workbench_pipeline_service.get_batch_pipeline_overview(
            session, batch_id
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
