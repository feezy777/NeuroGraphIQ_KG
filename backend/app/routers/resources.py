from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.resource import (
    GranularityFamily,
    GranularityLevel,
    ResourceCreate,
    ResourceListResponse,
    ResourceOptionsResponse,
    ResourceRead,
    ResourceStatus,
    ResourceType,
    ResourceUpdate,
    Species,
    TemplateSpace,
)
from app.schemas.resource_delete import ResourceDeletePreview, ResourceDeleteRequest, ResourceDeleteResult
from app.services import resource_service
from app.services import resource_delete_service

router = APIRouter()


@router.get("/options", response_model=ResourceOptionsResponse)
async def get_resource_options():
    return ResourceOptionsResponse(
        resource_type=[e.value for e in ResourceType],
        species=[e.value for e in Species],
        granularity_level=[e.value for e in GranularityLevel],
        granularity_family=[e.value for e in GranularityFamily],
        template_space=[e.value for e in TemplateSpace],
        status=[e.value for e in ResourceStatus],
    )


@router.get("", response_model=ResourceListResponse)
async def list_resources(
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    source_atlas: str | None = None,
    granularity_level: GranularityLevel | None = None,
    granularity_family: GranularityFamily | None = None,
    status: str | None = Query(None, description="active | archived | inactive | all"),
    session: AsyncSession = Depends(get_db),
):
    items, total = await resource_service.list_resources(
        session,
        limit=limit,
        offset=offset,
        source_atlas=source_atlas,
        granularity_level=granularity_level.value if granularity_level else None,
        granularity_family=granularity_family.value if granularity_family else None,
        status=(status or "").strip().lower() or None,
    )
    return ResourceListResponse(
        items=[ResourceRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ResourceRead, status_code=201)
async def create_resource(payload: ResourceCreate, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_service.create_resource(session, payload)
    except resource_service.ResourceCodeConflictError as exc:
        existing = exc.existing
        if existing is None and exc.resource_code:
            existing = await resource_service.get_resource_by_code_any(session, exc.resource_code)
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_RESOURCE_CODE",
                    "message": "Resource code already exists.",
                    "resource_code": exc.resource_code,
                },
            ) from exc
        counts = await resource_service.count_resource_dependencies(session, existing.id)
        raise HTTPException(
            status_code=409,
            detail=resource_service.build_duplicate_resource_detail(existing, counts),
        ) from exc
    return ResourceRead.model_validate(row)


@router.get("/{resource_id}", response_model=ResourceRead)
async def get_resource(
    resource_id: uuid.UUID,
    include_archived: bool = Query(False),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await resource_service.get_resource(
            session, resource_id, include_archived=include_archived
        )
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    return ResourceRead.model_validate(row)


@router.patch("/{resource_id}", response_model=ResourceRead)
async def update_resource(
    resource_id: uuid.UUID,
    payload: ResourceUpdate,
    session: AsyncSession = Depends(get_db),
):
    if not payload.model_dump(exclude_unset=True):
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        row = await resource_service.update_resource(session, resource_id, payload)
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    return ResourceRead.model_validate(row)


@router.delete("/{resource_id}", response_model=ResourceRead)
async def delete_resource(resource_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_service.soft_delete_resource(session, resource_id)
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    return ResourceRead.model_validate(row)


@router.post("/{resource_id}/restore", response_model=ResourceRead)
async def restore_resource(resource_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        row = await resource_service.restore_resource(session, resource_id)
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    except resource_service.ResourceActiveCodeConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACTIVE_RESOURCE_CODE_EXISTS",
                "message": "Another active resource already uses this resource_code.",
                "resource_code": exc.resource_code,
                "existing_resource_id": str(exc.existing_id),
            },
        ) from exc
    return ResourceRead.model_validate(row)


@router.post("/{resource_id}/purge", status_code=204)
async def purge_resource(resource_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        await resource_service.purge_resource(session, resource_id)
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    except resource_service.ResourceHasDependenciesError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RESOURCE_HAS_DEPENDENCIES",
                "message": "This resource has downstream dependencies and cannot be permanently deleted.",
                "resource_id": str(exc.resource_id),
                "dependency_counts": exc.dependency_counts,
                "suggestion": (
                    "Restore and reuse this resource, or create a new version with a different resource_code."
                ),
            },
        ) from exc


@router.get("/{resource_id}/delete-preview", response_model=ResourceDeletePreview)
async def get_resource_delete_preview(
    resource_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await resource_delete_service.get_resource_delete_preview(session, resource_id)
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc


@router.post("/{resource_id}/destructive-delete", response_model=ResourceDeleteResult)
async def destructive_delete_resource(
    resource_id: uuid.UUID,
    payload: ResourceDeleteRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await resource_delete_service.destructive_delete_resource(
            session, resource_id, payload
        )
    except resource_service.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="resource not found") from exc
    except resource_delete_service.ResourceDeleteConfirmationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except resource_delete_service.ResourceDeleteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
