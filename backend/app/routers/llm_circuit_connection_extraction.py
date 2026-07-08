"""Circuit -> Connection LLM extraction API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_circuit_connection_extraction import (
    LlmCircuitConnectionExtractionItem,
    LlmCircuitConnectionExtractionRun,
)
from app.schemas.llm_circuit_connection_extraction import (
    CircuitConnectionExtractionRequest,
    ExtractionItemRead,
    ExtractionRunDetail,
    ExtractionRunListResponse,
    ExtractionRunRead,
    ExtractionStartResponse,
)
from app.services import llm_circuit_connection_extraction_service as svc
from app.services.llm_field_completion_service import (
    _resolve_model,
    _check_cancelled,
)
from app.services.llm_providers import UnknownProviderError

router = APIRouter()


def _make_run(
    mode: str,
    circuit_count: int,
    dry_run: bool,
    create_mirror_updates: bool,
    overwrite_policy: str,
    provider: str,
    model_name: str | None,
) -> LlmCircuitConnectionExtractionRun:
    return LlmCircuitConnectionExtractionRun(
        id=uuid.uuid4(),
        mode=mode,
        circuit_count=circuit_count,
        dry_run=dry_run,
        create_mirror_updates=create_mirror_updates,
        overwrite_policy=overwrite_policy,
        provider=provider,
        model_name=model_name,
        status="pending",
    )


@router.post("/run")
async def run_extraction(
    body: CircuitConnectionExtractionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    if not body.dry_run:
        # Async path
        provider_key = body.provider.lower()
        resolved_model = _resolve_model(provider_key, body.model_name)

        run = _make_run(
            mode=body.mode,
            circuit_count=len(body.circuit_ids),
            dry_run=False,
            create_mirror_updates=body.create_mirror_updates,
            overwrite_policy=body.overwrite_policy,
            provider=provider_key,
            model_name=resolved_model,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        background_tasks.add_task(
            _execute_background,
            run.id,
            body.model_dump(mode="json"),
        )

        return ExtractionStartResponse(
            run_id=run.id,
            status="pending",
            provider=provider_key,
            model_name=resolved_model,
            mode=body.mode,
            circuit_count=len(body.circuit_ids),
            dry_run=False,
        )

    # Dry run: estimate only
    provider_key = body.provider.lower()
    resolved_model = _resolve_model(provider_key, body.model_name)

    run = _make_run(
        mode=body.mode,
        circuit_count=len(body.circuit_ids),
        dry_run=True,
        create_mirror_updates=False,
        overwrite_policy=body.overwrite_policy,
        provider=provider_key,
        model_name=resolved_model,
    )
    run.status = "dry_run"
    est_calls = len(body.circuit_ids)
    est_input = est_calls * 1500  # rough estimate per circuit context
    run.summary_json = {
        "total_circuits": len(body.circuit_ids),
        "estimated_model_calls": est_calls,
        "estimated_input_tokens": est_input,
        "estimated_output_tokens": est_calls * 300,
        "connections_created": 0,
        "connections_updated": 0,
    }
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return ExtractionRunRead.model_validate(run)


async def _execute_background(run_id: uuid.UUID, request_payload: dict) -> None:
    from app.database import AsyncSessionLocal

    if AsyncSessionLocal is None:
        return

    try:
        request = CircuitConnectionExtractionRequest.model_validate(request_payload)
    except Exception:
        return

    async with AsyncSessionLocal() as session:
        run = await session.get(LlmCircuitConnectionExtractionRun, run_id)
        if run is None:
            return

        provider_key = request.provider.lower()
        resolved_model = _resolve_model(provider_key, request.model_name)

        run.status = "running"
        run.started_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        await session.commit()

        try:
            items, created, updated = await svc.execute_circuit_connection_extraction(
                session,
                run,
                circuit_ids=request.circuit_ids,
                mode=request.mode,
                provider_key=provider_key,
                resolved_model=resolved_model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                overwrite_policy=request.overwrite_policy,
                create_mirror_updates=request.create_mirror_updates,
                check_cancelled=_check_cancelled,
            )
            run.summary_json = {
                **(run.summary_json or {}),
                "connections_created": created,
                "connections_updated": updated,
                "items_count": len(items),
            }
            if created > 0 and not (run.errors_json or []):
                run.status = "succeeded"
            elif created > 0:
                run.status = "partially_succeeded"
            else:
                run.status = "failed"
        except Exception as exc:
            run.status = "failed"
            run.errors_json = list(run.errors_json or []) + [str(exc)]
        finally:
            run.completed_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
            await session.commit()


@router.get("/runs", response_model=ExtractionRunListResponse)
async def list_runs(
    mode: str | None = None,
    limit: int = Query(default=20, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    q = select(LlmCircuitConnectionExtractionRun).order_by(
        LlmCircuitConnectionExtractionRun.created_at.desc()
    )
    count_q = select(func.count()).select_from(LlmCircuitConnectionExtractionRun)
    if mode:
        q = q.where(LlmCircuitConnectionExtractionRun.mode == mode)
        count_q = count_q.where(LlmCircuitConnectionExtractionRun.mode == mode)
    total = (await session.execute(count_q)).scalar_one()
    rows = (await session.execute(q.limit(limit).offset(offset))).scalars().all()
    return ExtractionRunListResponse(
        items=[ExtractionRunRead.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=ExtractionRunDetail)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await session.get(LlmCircuitConnectionExtractionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    item_q = (
        select(LlmCircuitConnectionExtractionItem)
        .where(LlmCircuitConnectionExtractionItem.run_id == run_id)
        .limit(500)
    )
    items = list((await session.execute(item_q)).scalars().all())
    return ExtractionRunDetail(
        **ExtractionRunRead.model_validate(run).model_dump(),
        items=[ExtractionItemRead.model_validate(i) for i in items],
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await session.get(LlmCircuitConnectionExtractionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("pending", "running"):
        run.status = "cancelled"
        run.completed_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        await session.commit()
    return ExtractionRunRead.model_validate(run)
