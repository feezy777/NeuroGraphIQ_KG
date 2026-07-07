"""Universal field completion API routes (Step 10.3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.llm_field_completion import (
    FieldCompletionItemListResponse,
    FieldCompletionItemRead,
    FieldCompletionRelatedTargetsResponse,
    FieldCompletionPromptTemplateListResponse,
    FieldCompletionRunDetail,
    FieldCompletionRunListResponse,
    FieldCompletionRunRead,
    FieldCompletionStartResponse,
    TargetType,
    UniversalFieldCompletionRequest,
    UniversalFieldCompletionResponse,
)
from app.schemas.llm_field_completion import FieldScope
from app.services.field_completion_registry import (
    TargetTypeNotImplementedError,
    UnsupportedTargetTypeError,
    get_registry_entry,
    resolve_field_name,
)
from app.services import llm_field_completion_service as svc
from app.services.llm_field_completion_service import ProviderNotConfiguredServiceError
from app.services.llm_providers import UnknownProviderError

router = APIRouter()


@router.get("/related-targets", response_model=FieldCompletionRelatedTargetsResponse)
async def related_targets(
    target_type: TargetType,
    target_ids: str = Query(..., description="Comma-separated UUIDs"),
    include: str = Query("circuit_step,circuit_function"),
    session: AsyncSession = Depends(get_db),
):
    try:
        parsed_ids = [uuid.UUID(part.strip()) for part in target_ids.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TARGET_IDS", "message": "target_ids must be comma-separated UUIDs"},
        ) from exc
    if not parsed_ids:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_TARGET_IDS", "message": "target_ids must not be empty"},
        )
    include_list = [part.strip() for part in include.split(",") if part.strip()]
    try:
        return await svc.get_related_field_completion_targets(
            session,
            target_type=target_type,
            target_ids=parsed_ids,
            include=include_list,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_REQUEST", "message": str(exc)},
        ) from exc


@router.get("/prompt-templates", response_model=FieldCompletionPromptTemplateListResponse)
async def list_prompt_templates():
    from app.services.prompt_metadata import list_field_completion_prompt_template_items

    raw = list_field_completion_prompt_template_items()
    return FieldCompletionPromptTemplateListResponse(items=raw)


@router.post("/run")
async def run_field_completion(
    body: UniversalFieldCompletionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    # Step 10.4.2: validate selected_fields use real formal field names
    if body.field_scope == FieldScope.selected_fields and body.selected_fields:
        try:
            _entry = get_registry_entry(body.target_type)
            invalid_fields = [
                f for f in body.selected_fields
                if resolve_field_name(_entry, f) is None
            ]
            if invalid_fields:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_SELECTED_FIELDS",
                        "message": (
                            f"Invalid selected_fields for target_type={body.target_type.value}. "
                            f"Use formal field names from NeuroGraphIQ_KG_V3 "
                            f"(e.g. name_en, name_cn, circuit_class). "
                            f"Invalid: {invalid_fields}"
                        ),
                        "invalid_fields": invalid_fields,
                    },
                )
        except (UnsupportedTargetTypeError, TargetTypeNotImplementedError):
            pass  # Let the service return the proper error

    # ── Async path: non-dry-run runs in background ────────────────────────
    if not body.dry_run:
        try:
            start_response = await svc.start_field_completion_async(session, body)
        except TargetTypeNotImplementedError as exc:
            raise HTTPException(
                status_code=501,
                detail={"code": "TARGET_TYPE_NOT_IMPLEMENTED", "message": str(exc)},
            ) from exc
        except UnsupportedTargetTypeError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "UNSUPPORTED_TARGET_TYPE", "message": str(exc)},
            ) from exc
        except UnknownProviderError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "UNKNOWN_PROVIDER", "message": str(exc)},
            ) from exc
        except ProviderNotConfiguredServiceError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "PROVIDER_NOT_CONFIGURED", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_REQUEST", "message": str(exc)},
            ) from exc

        background_tasks.add_task(
            svc.execute_field_completion_background,
            start_response.run_id,
            body.model_dump(mode="json"),
        )
        return start_response

    # ── Sync path: dry_run returns immediately ────────────────────────────
    try:
        return await svc.run_universal_field_completion(session, body)
    except TargetTypeNotImplementedError as exc:
        raise HTTPException(
            status_code=501,
            detail={"code": "TARGET_TYPE_NOT_IMPLEMENTED", "message": str(exc)},
        ) from exc
    except UnsupportedTargetTypeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNSUPPORTED_TARGET_TYPE", "message": str(exc)},
        ) from exc
    except UnknownProviderError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNKNOWN_PROVIDER", "message": str(exc)},
        ) from exc
    except ProviderNotConfiguredServiceError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except svc.MirrorCircuitFunctionsNotInitializedForFieldCompletionError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": (
                    "mirror_circuit_functions table is not initialized. "
                    "Please run backend/migrations/033_mirror_circuit_functions.sql."
                ),
                "migration": exc.migration_path,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_REQUEST", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "FIELD_COMPLETION_FAILED", "message": str(exc)},
        ) from exc


@router.get("/runs", response_model=FieldCompletionRunListResponse)
async def list_runs(
    target_type: TargetType | None = None,
    status: str | None = None,
    provider: str | None = None,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    rows, total = await svc.list_field_completion_runs(
        session,
        target_type=target_type.value if target_type else None,
        status=status,
        provider=provider,
        limit=limit,
        offset=offset,
    )
    return FieldCompletionRunListResponse(
        items=[FieldCompletionRunRead.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=FieldCompletionRunDetail)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    detail = await svc.get_field_completion_run(session, run_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "RUN_NOT_FOUND", "message": f"run {run_id} not found"},
        )
    return detail


@router.post("/runs/{run_id}/cancel", response_model=FieldCompletionRunRead)
async def cancel_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await svc.cancel_field_completion_run(session, run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "RUN_NOT_FOUND", "message": f"run {run_id} not found"},
        )
    return FieldCompletionRunRead.model_validate(run)


@router.get("/items", response_model=FieldCompletionItemListResponse)
async def list_items(
    run_id: uuid.UUID | None = None,
    target_type: TargetType | None = None,
    target_id: uuid.UUID | None = None,
    field_name: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    rows, total = await svc.list_field_completion_items(
        session,
        run_id=run_id,
        target_type=target_type.value if target_type else None,
        target_id=target_id,
        field_name=field_name,
        status=status,
        limit=limit,
        offset=offset,
    )
    return FieldCompletionItemListResponse(
        items=[FieldCompletionItemRead.model_validate(r) for r in rows],
        total=total,
    )
