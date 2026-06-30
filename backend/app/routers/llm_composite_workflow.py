"""Composite LLM extraction workflow API routes."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_composite_workflow import LlmCompositeWorkflowRun
from app.schemas.llm_composite_workflow import (
    CompositeWorkflowCancelRequest,
    CompositeWorkflowCancelResponse,
    CompositeWorkflowRunListResponse,
    CompositeWorkflowRunRequest,
    CompositeWorkflowRunResponse,
    CompositeWorkflowRunRead,
    CompositeWorkflowRawResponsesDebugResponse,
    CompositeWorkflowStartResponse,
    CompositeWorkflowStepListResponse,
)
from app.services import llm_composite_workflow_service as composite_svc
from app.services.llm_composite_workflow_service import CompositeWorkflowHandledError

logger = logging.getLogger(__name__)

router = APIRouter()


def _start_response_from_run(response: CompositeWorkflowRunResponse) -> CompositeWorkflowStartResponse:
    return CompositeWorkflowStartResponse(
        workflow_run_id=response.workflow_run_id,
        workflow_type=response.workflow_type,
        status=response.status,
        dry_run=response.dry_run,
        candidate_count=response.candidate_count,
        pair_count=response.pair_count,
        steps=response.steps,
        progress_percent=response.progress_percent,
        warnings=response.warnings,
    )


@router.post("/composite-workflows/run", response_model=CompositeWorkflowRunResponse)
async def run_composite_workflow(
    request: CompositeWorkflowRunRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await composite_svc.run_composite_workflow(session, request)
    except CompositeWorkflowHandledError as exc:
        return exc.response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[llm-composite-workflow][run][unhandled]")
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "COMPOSITE_WORKFLOW_INTERNAL_ERROR",
                "message": "Composite workflow failed before workflow_run could be created.",
                "hint": "Check backend logs for traceback.",
                "error": str(exc)[:500],
            },
        ) from exc


@router.post(
    "/composite-workflows/start",
    response_model=CompositeWorkflowStartResponse,
    status_code=202,
)
async def start_composite_workflow(
    request: CompositeWorkflowRunRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    try:
        normalized = composite_svc.normalize_composite_request(request)
        normalized = await composite_svc.resolve_composite_request_candidates(session, normalized)
        logger.info(
            "[llm-composite-workflow][start] workflow_type=%s dry_run=%s debug_single_pack=%s debug_max_packs=%s candidate_count=%s",
            normalized.workflow_type.value,
            normalized.dry_run,
            normalized.debug_single_pack,
            normalized.debug_max_packs,
            len(normalized.candidate_ids),
        )
        pending = await composite_svc.start_composite_workflow(session, normalized)
        background_tasks.add_task(
            composite_svc.execute_composite_workflow_background,
            pending.workflow_run_id,
            normalized.model_dump(mode="json"),
        )
        return _start_response_from_run(pending)
    except HTTPException:
        raise
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[llm-composite-workflow][start][unhandled]")
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "COMPOSITE_WORKFLOW_START_ERROR",
                "message": "Failed to start composite workflow.",
                "hint": "Check backend logs for traceback.",
                "error": str(exc)[:500],
            },
        ) from exc


@router.get("/composite-workflows/runs", response_model=CompositeWorkflowRunListResponse)
async def list_composite_workflow_runs(
    workflow_type: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await composite_svc.list_composite_workflow_runs(
        session,
        workflow_type=workflow_type,
        status=status,
        provider=provider,
        batch_id=batch_id,
        resource_id=resource_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return CompositeWorkflowRunListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/composite-workflows/runs/{workflow_run_id}", response_model=CompositeWorkflowRunRead)
async def get_composite_workflow_run(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await composite_svc.get_composite_workflow_run(session, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Composite workflow run not found")
    return run


@router.get(
    "/composite-workflows/runs/{workflow_run_id}/steps",
    response_model=CompositeWorkflowStepListResponse,
)
async def list_composite_workflow_steps(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Composite workflow run not found")
    steps = await composite_svc.list_composite_workflow_steps(session, workflow_run_id)
    return CompositeWorkflowStepListResponse(items=steps, total=len(steps))


@router.get(
    "/composite-workflows/{workflow_run_id}/debug/raw-responses",
    response_model=CompositeWorkflowRawResponsesDebugResponse,
    summary="Debug: pack raw_response_preview from workflow step/run JSONB",
)
async def debug_composite_workflow_raw_responses(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    payload = await composite_svc.get_composite_workflow_raw_responses_debug(session, workflow_run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Composite workflow run not found")
    return payload


@router.post(
    "/composite-workflows/{workflow_run_id}/cancel",
    response_model=CompositeWorkflowCancelResponse,
)
async def cancel_composite_workflow(
    workflow_run_id: uuid.UUID,
    request: CompositeWorkflowCancelRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await composite_svc.cancel_composite_workflow(
            session,
            workflow_run_id,
            cleanup=request.cleanup,
            reason=request.reason,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Composite workflow run not found") from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[llm-composite-workflow][cancel] unhandled workflow_run_id=%s", workflow_run_id)
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "COMPOSITE_WORKFLOW_CANCEL_ERROR",
                "message": "Failed to cancel composite workflow.",
                "error": str(exc)[:500],
            },
        ) from exc


@router.post(
    "/composite-workflows/{workflow_run_id}/pause",
    response_model=CompositeWorkflowCancelResponse,
)
async def pause_composite_workflow(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await composite_svc.pause_composite_workflow(
            session,
            workflow_run_id,
            reason="user_paused",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Composite workflow run not found") from None
    except Exception as exc:
        logger.exception("[llm-composite-workflow][pause] unhandled")
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "COMPOSITE_WORKFLOW_PAUSE_ERROR",
                "message": "Failed to pause composite workflow.",
                "error": str(exc)[:500],
            },
        ) from exc


@router.post(
    "/composite-workflows/{workflow_run_id}/resume",
    response_model=CompositeWorkflowCancelResponse,
)
async def resume_composite_workflow(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await composite_svc.resume_composite_workflow(
            session,
            workflow_run_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Composite workflow run not found") from None
    except Exception as exc:
        logger.exception("[llm-composite-workflow][resume] unhandled")
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "COMPOSITE_WORKFLOW_RESUME_ERROR",
                "message": "Failed to resume composite workflow.",
                "error": str(exc)[:500],
            },
        ) from exc
