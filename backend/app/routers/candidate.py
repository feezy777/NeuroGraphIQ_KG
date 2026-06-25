from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.candidate import (
    CandidateBrainRegionListResponse,
    CandidateBrainRegionRead,
    CandidateGenerationRunRead,
    CandidateGenStatus,
    CandidateOptionsResponse,
    CandidateStatus,
    CandidateStatusCount,
    CandidateStatusSummary,
    GenerateCandidatesResponse,
    GenerateMacro96CandidatesResponse,
)
from app.schemas.raw_parsing import Laterality
from app.services import candidate_service, import_batch_service, macro96_candidate_service

router = APIRouter()
batch_router = APIRouter()
gen_run_router = APIRouter()


@router.get("/options", response_model=CandidateOptionsResponse)
async def get_candidate_options():
    return CandidateOptionsResponse(
        candidate_status=[e.value for e in CandidateStatus],
        generation_run_status=[e.value for e in CandidateGenStatus],
        laterality=[e.value for e in Laterality],
    )


@batch_router.post("/{batch_id}/generate-candidates", response_model=GenerateCandidatesResponse)
async def generate_candidates(
    batch_id: uuid.UUID,
    parse_run_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    try:
        run = await candidate_service.generate_candidates_for_batch(
            session, batch_id, parse_run_id=parse_run_id
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except candidate_service.WrongCandidateGeneratorForMacro96Error as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WRONG_CANDIDATE_GENERATOR_FOR_MACRO96",
                "message": (
                    "This batch uses macro96_xlsx parser. "
                    "Use /generate-macro96-candidates instead of the AAL3 candidate generator."
                ),
                "batch_id": str(exc.batch_id),
                "parser_key": exc.parser_key,
                "suggestion": "Click Generate Macro96 Candidates in Import Pipeline.",
            },
        ) from exc
    except candidate_service.BatchNotCandidateReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except candidate_service.ParseRunNotEligibleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except candidate_service.NoRawLabelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except candidate_service.DuplicateCandidateGenerationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "candidates already generated for this batch and parse run",
                "batch_id": str(exc.batch_id),
                "parse_run_id": str(exc.parse_run_id),
                "existing_generation_run_id": str(exc.existing_run_id),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    batch = await import_batch_service.get_batch(session, batch_id)
    return GenerateCandidatesResponse(
        generation_run=CandidateGenerationRunRead.model_validate(run),
        output_count=run.output_count,
        skipped_count=run.skipped_count,
        batch_status=batch.status,
    )


@batch_router.post(
    "/{batch_id}/generate-macro96-candidates",
    response_model=GenerateMacro96CandidatesResponse,
)
async def generate_macro96_candidates(
    batch_id: uuid.UUID,
    parse_run_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
):
    try:
        run = await macro96_candidate_service.generate_macro96_candidates_for_batch(
            session, batch_id, parse_run_id=parse_run_id
        )
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    except macro96_candidate_service.WrongParserKeyError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WRONG_PARSER_KEY_FOR_MACRO96_CANDIDATES",
                "message": str(exc),
                "batch_id": str(batch_id),
                "suggestion": "Use /generate-candidates for AAL3 batches only.",
            },
        ) from exc
    except macro96_candidate_service.BatchNotCandidateReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except macro96_candidate_service.ParseRunNotEligibleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except macro96_candidate_service.NoMacro96RawRowsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except macro96_candidate_service.DuplicateMacro96CandidateGenerationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Macro96 candidates already generated for this batch and parse run",
                "batch_id": str(exc.batch_id),
                "parse_run_id": str(exc.parse_run_id),
                "existing_generation_run_id": str(exc.existing_run_id),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    batch = await import_batch_service.get_batch(session, batch_id)
    return GenerateMacro96CandidatesResponse(
        generation_run_id=run.id,
        batch_id=batch_id,
        resource_id=run.resource_id,
        parse_run_id=run.parse_run_id,
        generator_key=run.generator_key,
        candidate_count=run.output_count,
        status=CandidateGenStatus(run.status),
        batch_status=batch.status,
    )


@batch_router.get("/{batch_id}/candidate-runs", response_model=list[CandidateGenerationRunRead])
async def list_batch_candidate_runs(
    batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        runs = await candidate_service.list_generation_runs_for_batch(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc
    return [CandidateGenerationRunRead.model_validate(r) for r in runs]


@gen_run_router.get("/{generation_run_id}", response_model=CandidateGenerationRunRead)
async def get_candidate_generation_run(
    generation_run_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        run = await candidate_service.get_generation_run(session, generation_run_id)
    except candidate_service.CandidateGenerationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="candidate generation run not found") from exc
    return CandidateGenerationRunRead.model_validate(run)


@router.get("/brain-regions", response_model=CandidateBrainRegionListResponse)
async def list_candidate_brain_regions(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    parse_run_id: uuid.UUID | None = None,
    candidate_status: CandidateStatus | None = None,
    laterality: Laterality | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await candidate_service.list_candidate_regions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        parse_run_id=parse_run_id,
        candidate_status=candidate_status.value if candidate_status else None,
        laterality=laterality.value if laterality else None,
        limit=limit,
        offset=offset,
    )
    return CandidateBrainRegionListResponse(
        items=[CandidateBrainRegionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/brain-regions/status-summary", response_model=CandidateStatusSummary)
async def get_candidate_status_summary(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db),
):
    total, by_status = await candidate_service.candidate_status_summary(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
    )
    return CandidateStatusSummary(
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        total=total,
        by_status=[
            CandidateStatusCount(candidate_status=CandidateStatus(s), count=c)
            for s, c in by_status
        ],
    )


@router.get("/brain-regions/{candidate_id}", response_model=CandidateBrainRegionRead)
async def get_candidate_brain_region(
    candidate_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    row = await candidate_service.get_candidate_region(session, candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="candidate brain region not found")
    return CandidateBrainRegionRead.model_validate(row)
