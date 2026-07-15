from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.rule_validation import (
    RULE_CATALOGUE,
    CandidateRuleResultListResponse,
    CandidateRuleStatus,
    CandidateRuleValidationResultRead,
    RuleSeverity,
    RuleValidationOptionsResponse,
    RuleValidationRunListResponse,
    RuleValidationRunRead,
    RuleValidationRunStatus,
    ValidateCandidatesResponse,
    ValidationScope,
)
from app.services import rule_validation_service

router = APIRouter()
candidate_router = APIRouter()


def _run_response(run) -> ValidateCandidatesResponse:
    return ValidateCandidatesResponse(
        validation_run=RuleValidationRunRead.model_validate(run),
        candidate_count=run.candidate_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        warning_count=run.warning_count,
        skipped_count=run.skipped_count,
    )


@router.get("/options", response_model=RuleValidationOptionsResponse)
async def get_rule_validation_options():
    return RuleValidationOptionsResponse(
        scope=[e.value for e in ValidationScope],
        run_status=[e.value for e in RuleValidationRunStatus],
        severity=[e.value for e in RuleSeverity],
        candidate_rule_status=[e.value for e in CandidateRuleStatus],
        rules=RULE_CATALOGUE,
    )


@router.post("/run", response_model=ValidateCandidatesResponse)
async def run_rule_validation(
    generation_run_id: uuid.UUID | None = Query(default=None),
    batch_id: uuid.UUID | None = Query(default=None),
    parse_run_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    try:
        run = await rule_validation_service.validate_candidates(
            session,
            generation_run_id=generation_run_id,
            batch_id=batch_id,
            parse_run_id=parse_run_id,
        )
    except rule_validation_service.ValidationScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except rule_validation_service.NoCandidateForValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except rule_validation_service.DuplicateRuleValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"rule validation already succeeded for batch {exc.batch_id} (run {exc.existing_run_id})",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _run_response(run)


@router.get("/runs", response_model=RuleValidationRunListResponse)
async def list_rule_validation_runs(
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    status: RuleValidationRunStatus | None = None,
    granularity_level: str | None = Query(None, description="Filter by granularity level"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await rule_validation_service.list_validation_runs(
        session,
        batch_id=batch_id,
        resource_id=resource_id,
        status=status.value if status else None,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return RuleValidationRunListResponse(
        items=[RuleValidationRunRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{validation_run_id}", response_model=RuleValidationRunRead)
async def get_rule_validation_run(
    validation_run_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        run = await rule_validation_service.get_validation_run(session, validation_run_id)
    except rule_validation_service.RuleValidationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="rule validation run not found") from exc
    return RuleValidationRunRead.model_validate(run)


@router.get(
    "/runs/{validation_run_id}/results", response_model=CandidateRuleResultListResponse
)
async def list_rule_validation_run_results(
    validation_run_id: uuid.UUID,
    overall_status: CandidateRuleStatus | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        await rule_validation_service.get_validation_run(session, validation_run_id)
    except rule_validation_service.RuleValidationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="rule validation run not found") from exc

    items, total = await rule_validation_service.list_run_results(
        session,
        validation_run_id,
        overall_status=overall_status.value if overall_status else None,
        limit=limit,
        offset=offset,
    )
    return CandidateRuleResultListResponse(
        items=[CandidateRuleValidationResultRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@candidate_router.post("/{candidate_id}/validate", response_model=ValidateCandidatesResponse)
async def validate_single_candidate(
    candidate_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        run = await rule_validation_service.validate_candidates(
            session, candidate_id=candidate_id
        )
    except rule_validation_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="candidate brain region not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _run_response(run)


@candidate_router.get(
    "/{candidate_id}/validation-results", response_model=CandidateRuleResultListResponse
)
async def list_candidate_validation_results(
    candidate_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await rule_validation_service.list_candidate_results(
        session, candidate_id, limit=limit, offset=offset
    )
    return CandidateRuleResultListResponse(
        items=[CandidateRuleValidationResultRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
