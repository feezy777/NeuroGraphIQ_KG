"""LLM Extraction Workbench routes (MVP 2 Step 1 + Infrastructure Step 1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_deepseek_runtime_config
from app.database import get_db
from app.schemas.llm_extraction import (
    MAX_BATCH_SIZE,
    PROMPT_VERSION,
    LATERALITY_VALUES,
    BatchExtractRequest,
    BatchExtractResponse,
    LlmExtractionListResponse,
    LlmExtractionOptions,
    LlmExtractionRead,
    LlmExtractionRunDetail,
    LlmExtractionRunRead,
    LlmExtractionItemRead,
    LlmExtractionStatus,
    LlmItemListResponse,
    LlmProvidersResponse,
    LlmRunListResponse,
    LlmRunTaskRequest,
    LlmTaskType,
    LlmTaskTypesResponse,
    RegionFieldCompletionRequest,
    RegionFieldCompletionResponse,
    SameGranularityConnectionExtractionRequest,
    SameGranularityConnectionExtractionResponse,
    ConnectionParseReplayRequest,
    ConnectionParseReplayResponse,
    ProviderRawDebugRequest,
    ProviderRawDebugResponse,
    SameGranularityFunctionExtractionRequest,
    SameGranularityFunctionExtractionResponse,
    SameGranularityCircuitExtractionRequest,
    SameGranularityCircuitExtractionResponse,
    CircuitToStepsExtractionRequest,
    CircuitToStepsExtractionResponse,
    CircuitStepsToProjectionsExtractionRequest,
    CircuitStepsToProjectionsExtractionResponse,
    ProjectionToFunctionsExtractionRequest,
    ProjectionToFunctionsExtractionResponse,
    CircuitToFunctionsExtractionRequest,
    CircuitToFunctionsExtractionResponse,
    ProjectionsToCircuitsExtractionRequest,
    ProjectionsToCircuitsExtractionResponse,
    ExtractionPromptTemplateListResponse,
)
from app.services import llm_extraction_service
from app.services import llm_connection_extraction_service as conn_svc
from app.services import llm_function_extraction_service as func_svc
from app.services import llm_circuit_extraction_service as circuit_svc
from app.services import llm_circuit_step_extraction_service as circuit_step_svc
from app.services import llm_circuit_projection_extraction_service as circuit_proj_svc
from app.services import llm_projection_function_extraction_service as proj_fn_svc
from app.services import llm_circuit_function_extraction_service as circuit_fn_svc
from app.services import llm_projection_circuit_extraction_service as proj_circ_svc
from app.services.llm_providers import UnknownProviderError

router = APIRouter()
candidate_router = APIRouter()


@router.get("/options", response_model=LlmExtractionOptions)
async def get_llm_extraction_options():
    config = get_deepseek_runtime_config()
    return LlmExtractionOptions(
        provider="deepseek",
        model=config.default_model,
        prompt_version=PROMPT_VERSION,
        max_batch_size=min(config.max_batch_size, MAX_BATCH_SIZE),
        laterality_values=list(LATERALITY_VALUES),
        api_key_configured=bool((config.api_key or "").strip()),
    )


@router.get("/providers", response_model=LlmProvidersResponse)
async def get_llm_providers():
    return LlmProvidersResponse(providers=llm_extraction_service.list_llm_providers())


@router.get("/task-types", response_model=LlmTaskTypesResponse)
async def get_llm_task_types():
    return LlmTaskTypesResponse(task_types=llm_extraction_service.list_llm_task_types())


@router.get("/runs", response_model=LlmRunListResponse)
async def list_llm_extraction_runs(
    task_type: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await llm_extraction_service.list_extraction_runs(
        session,
        task_type=task_type,
        provider=provider,
        status=status,
        resource_id=resource_id,
        batch_id=batch_id,
        candidate_id=candidate_id,
        limit=limit,
        offset=offset,
    )
    return LlmRunListResponse(
        items=[LlmExtractionRunRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=LlmExtractionRunDetail)
async def get_llm_extraction_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run, items = await llm_extraction_service.get_extraction_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    detail = LlmExtractionRunRead.model_validate(run)
    return LlmExtractionRunDetail(
        **detail.model_dump(),
        items=[LlmExtractionItemRead.model_validate(i) for i in items],
    )


@router.get("/items", response_model=LlmItemListResponse)
async def list_llm_extraction_items(
    run_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    task_type: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await llm_extraction_service.list_extraction_items(
        session,
        run_id=run_id,
        candidate_id=candidate_id,
        task_type=task_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return LlmItemListResponse(
        items=[LlmExtractionItemRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/region-field-completion", response_model=RegionFieldCompletionResponse)
async def region_field_completion(
    body: RegionFieldCompletionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        run, items, legacy = await llm_extraction_service.run_region_field_completion(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
        )
    except llm_extraction_service.BatchTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm_extraction_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {exc}") from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    succeeded = sum(1 for i in items if i.status == "succeeded")
    failed = sum(1 for i in items if i.status == "failed")
    return RegionFieldCompletionResponse(
        run_id=run.id,
        requested=len(body.candidate_ids),
        succeeded=succeeded,
        failed=failed,
        dry_run=body.dry_run,
        items=[LlmExtractionItemRead.model_validate(i) for i in items],
        legacy_extractions=[LlmExtractionRead.model_validate(r) for r in legacy],
    )


@router.post(
    "/same-granularity-connections",
    response_model=SameGranularityConnectionExtractionResponse,
)
async def same_granularity_connections(
    body: SameGranularityConnectionExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    scope = body.scope
    try:
        result = await conn_svc.run_same_granularity_connection_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            scope_resource_id=scope.resource_id if scope else None,
            scope_batch_id=scope.batch_id if scope else None,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_candidate_pairs=body.max_candidate_pairs,
            pair_strategy=body.pair_strategy,
            center_candidate_id=body.center_candidate_id,
            allowed_connection_types=body.allowed_connection_types,
            create_mirror_records=body.create_mirror_records,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
            debug_max_packs=body.debug_max_packs,
            debug_single_pack=body.debug_single_pack,
            parse_error_fail_fast_enabled=body.parse_error_fail_fast_enabled,
            parse_error_fail_fast_threshold=body.parse_error_fail_fast_threshold,
        )
    except conn_svc.TooFewCandidatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except conn_svc.TooManyCandidatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except conn_svc.CrossAtlasError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CROSS_ATLAS_NOT_ALLOWED",
                "message": str(exc),
                "atlases": exc.atlases,
                "candidate_ids": exc.candidate_ids,
            },
        ) from exc
    except conn_svc.CrossGranularityError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CROSS_GRANULARITY_NOT_ALLOWED",
                "message": str(exc),
                "field": exc.field,
                "values": exc.values,
                "candidate_ids": exc.candidate_ids,
            },
        ) from exc
    except conn_svc.ScopeMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except conn_svc.TooManyCandidatePairsError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TOO_MANY_CANDIDATE_PAIRS",
                "message": "Too many candidate pairs for one LLM extraction run.",
                "pair_count": exc.pair_count,
                "max_candidate_pairs": exc.max_candidate_pairs,
                "suggestion": "Use region_centered strategy or select fewer candidates.",
            },
        ) from exc
    except conn_svc.CenterCandidateRequiredError as exc:
        raise HTTPException(status_code=400, detail="center_candidate_id required for region_centered") from exc
    except conn_svc.CenterCandidateNotInSelectionError as exc:
        raise HTTPException(status_code=400, detail="center_candidate_id must be in candidate_ids") from exc
    except conn_svc.InvalidPairStrategyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm_extraction_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {exc}") from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SameGranularityConnectionExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        candidate_count=result.candidate_count,
        pair_count=result.pair_count,
        connection_count=result.connection_count,
        mirror_connection_created_count=result.mirror_connection_created_count,
        mirror_connection_skipped_duplicate_count=result.mirror_connection_skipped_duplicate_count,
        triple_created_count=result.triple_created_count,
        evidence_created_count=result.evidence_created_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        prompt_preview=result.prompt_preview,
        pack_count=result.pack_count,
        processed_pair_count=result.processed_pair_count,
        unprocessed_pair_count=result.unprocessed_pair_count,
        no_connection_count=result.no_connection_count,
        created_connection_ids=result.created_connection_ids,
        execution_summary=result.execution_summary,
        provider_call_count=result.provider_call_count,
        provider_success_count=result.provider_success_count,
        provider_error_count=result.provider_error_count,
        provider_empty_response_count=result.provider_empty_response_count,
        warnings=result.warnings,
    )


@router.post(
    "/debug/parse-connection-response",
    response_model=ConnectionParseReplayResponse,
)
async def debug_parse_connection_response(body: ConnectionParseReplayRequest):
    from app.services.llm_connection_parse_diagnostics import replay_connection_parse_response

    payload = replay_connection_parse_response(
        body.raw_text,
        [p.model_dump(mode="json") for p in body.pack_pairs],
    )
    return ConnectionParseReplayResponse(**payload)


@router.post(
    "/debug/provider-raw",
    response_model=ProviderRawDebugResponse,
    summary="Isolated provider raw-text diagnostic (no DB, no JSON parse)",
)
async def debug_provider_raw(body: ProviderRawDebugRequest):
    """Call provider.complete_text once; return raw_text preview only."""
    from app.services.llm_provider_raw_debug_service import invoke_provider_raw_debug

    return await invoke_provider_raw_debug(body)


@router.post(
    "/same-granularity-functions",
    response_model=SameGranularityFunctionExtractionResponse,
)
async def same_granularity_functions(
    body: SameGranularityFunctionExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    scope = body.scope
    try:
        result = await func_svc.run_same_granularity_function_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            scope_resource_id=scope.resource_id if scope else None,
            scope_batch_id=scope.batch_id if scope else None,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_functions_per_region=body.max_functions_per_region,
            allowed_function_categories=body.allowed_function_categories,
            allowed_relation_types=body.allowed_relation_types,
            create_mirror_records=body.create_mirror_records,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
    except func_svc.EmptyCandidatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except func_svc.TooManyCandidatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except func_svc.CrossAtlasError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CROSS_ATLAS_NOT_ALLOWED",
                "message": str(exc),
                "atlases": exc.atlases,
                "candidate_ids": exc.candidate_ids,
            },
        ) from exc
    except func_svc.CrossGranularityError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CROSS_GRANULARITY_NOT_ALLOWED",
                "message": str(exc),
                "field": exc.field,
                "values": exc.values,
                "candidate_ids": exc.candidate_ids,
            },
        ) from exc
    except func_svc.ScopeMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm_extraction_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {exc}") from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SameGranularityFunctionExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        candidate_count=result.candidate_count,
        function_count=result.function_count,
        mirror_function_created_count=result.mirror_function_created_count,
        mirror_function_skipped_duplicate_count=result.mirror_function_skipped_duplicate_count,
        triple_created_count=result.triple_created_count,
        evidence_created_count=result.evidence_created_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        warnings=result.warnings,
    )


@router.post(
    "/same-granularity-circuits",
    response_model=SameGranularityCircuitExtractionResponse,
)
async def same_granularity_circuits(
    body: SameGranularityCircuitExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    scope = body.scope
    try:
        result = await circuit_svc.run_same_granularity_circuit_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            scope_resource_id=scope.resource_id if scope else None,
            scope_batch_id=scope.batch_id if scope else None,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_circuits=body.max_circuits,
            min_regions_per_circuit=body.min_regions_per_circuit,
            max_regions_per_circuit=body.max_regions_per_circuit,
            include_connection_context=body.include_connection_context,
            include_function_context=body.include_function_context,
            connection_ids=body.connection_ids,
            function_ids=body.function_ids,
            allowed_circuit_types=body.allowed_circuit_types,
            create_mirror_records=body.create_mirror_records,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
    except circuit_svc.TooFewCandidatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_svc.TooManyCandidatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_svc.CrossAtlasError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CROSS_ATLAS_NOT_ALLOWED",
                "message": str(exc),
                "atlases": exc.atlases,
                "candidate_ids": exc.candidate_ids,
            },
        ) from exc
    except circuit_svc.CrossGranularityError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CROSS_GRANULARITY_NOT_ALLOWED",
                "message": str(exc),
                "field": exc.field,
                "values": exc.values,
                "candidate_ids": exc.candidate_ids,
            },
        ) from exc
    except circuit_svc.ScopeMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_svc.InvalidConnectionContextError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_CONNECTION_CONTEXT",
                "message": str(exc),
                "connection_id": exc.connection_id,
            },
        ) from exc
    except circuit_svc.InvalidFunctionContextError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_FUNCTION_CONTEXT",
                "message": str(exc),
                "function_id": exc.function_id,
            },
        ) from exc
    except llm_extraction_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {exc}") from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SameGranularityCircuitExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        candidate_count=result.candidate_count,
        connection_context_count=result.connection_context_count,
        function_context_count=result.function_context_count,
        circuit_count=result.circuit_count,
        mirror_circuit_created_count=result.mirror_circuit_created_count,
        mirror_circuit_skipped_duplicate_count=result.mirror_circuit_skipped_duplicate_count,
        circuit_region_created_count=result.circuit_region_created_count,
        triple_created_count=result.triple_created_count,
        evidence_created_count=result.evidence_created_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        warnings=result.warnings,
    )


@router.post(
    "/circuit-to-steps",
    response_model=CircuitToStepsExtractionResponse,
)
async def circuit_to_steps(
    body: CircuitToStepsExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await circuit_step_svc.run_circuit_to_steps_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            circuit_id=body.circuit_id,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_steps=body.max_steps,
            include_circuit_regions=body.include_circuit_regions,
            create_mirror_records=body.create_mirror_records,
        )
    except circuit_step_svc.MirrorCircuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"mirror circuit not found: {exc}") from exc
    except circuit_step_svc.InvalidCircuitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_step_svc.CrossAtlasRegionError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_ATLAS_NOT_ALLOWED", "message": str(exc)}) from exc
    except circuit_step_svc.CrossGranularityRegionError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_GRANULARITY_NOT_ALLOWED", "message": str(exc)}) from exc
    except circuit_step_svc.MirrorStepsTableMissingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Defensive catch-all: surface unexpected errors as 500 with a structured message
        # rather than leaking raw tracebacks. MirrorStepsTableMissingError above handles
        # the known table-missing case; everything else is an unexpected internal error.
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error in circuit-to-steps extraction: {type(exc).__name__}: {exc}",
        ) from exc

    return CircuitToStepsExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        circuit_id=result.circuit_id or body.circuit_id,
        input_region_count=result.input_region_count,
        step_count=result.step_count,
        mirror_step_created_count=result.mirror_step_created_count,
        mirror_step_skipped_duplicate_count=result.mirror_step_skipped_duplicate_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        warnings=result.warnings,
    )


@router.post(
    "/circuit-steps-to-projections",
    response_model=CircuitStepsToProjectionsExtractionResponse,
)
async def circuit_steps_to_projections(
    body: CircuitStepsToProjectionsExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    if body.create_memberships and not body.create_mirror_records:
        raise HTTPException(
            status_code=400,
            detail="create_memberships=true requires create_mirror_records=true",
        )
    try:
        result = await circuit_proj_svc.run_circuit_steps_to_projections_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            circuit_id=body.circuit_id,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_projections=body.max_projections,
            step_ids=body.step_ids or None,
            include_existing_projections=body.include_existing_projections,
            create_mirror_records=body.create_mirror_records,
            create_memberships=body.create_memberships,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
    except circuit_proj_svc.MirrorCircuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"mirror circuit not found: {exc}") from exc
    except circuit_proj_svc.InvalidCircuitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_proj_svc.NoCircuitStepsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_proj_svc.InvalidStepIdsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_proj_svc.StepNotInCircuitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_proj_svc.CrossAtlasStepError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_ATLAS_NOT_ALLOWED", "message": str(exc)}) from exc
    except circuit_proj_svc.CrossGranularityStepError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_GRANULARITY_NOT_ALLOWED", "message": str(exc)}) from exc
    except circuit_proj_svc.InvalidMembershipConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_proj_svc.MirrorProjectionTableMissingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except circuit_proj_svc.MirrorPersistError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CircuitStepsToProjectionsExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        circuit_id=result.circuit_id or body.circuit_id,
        input_step_count=result.input_step_count,
        existing_projection_context_count=result.existing_projection_context_count,
        projection_count=result.projection_count,
        mirror_projection_created_count=result.mirror_projection_created_count,
        mirror_projection_skipped_duplicate_count=result.mirror_projection_skipped_duplicate_count,
        membership_created_count=result.membership_created_count,
        membership_skipped_duplicate_count=result.membership_skipped_duplicate_count,
        triple_created_count=result.triple_created_count,
        evidence_created_count=result.evidence_created_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        warnings=result.warnings,
    )


@router.post("/projection-to-functions", response_model=ProjectionToFunctionsExtractionResponse)
async def projection_to_functions(
    body: ProjectionToFunctionsExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await proj_fn_svc.run_projection_to_functions_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            projection_ids=body.projection_ids,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_functions_per_projection=body.max_functions_per_projection,
            include_circuit_context=body.include_circuit_context,
            include_region_context=body.include_region_context,
            create_mirror_records=body.create_mirror_records,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
    except proj_fn_svc.EmptyProjectionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_fn_svc.TooManyProjectionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_fn_svc.ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except proj_fn_svc.CrossAtlasProjectionError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_ATLAS_NOT_ALLOWED", "message": str(exc)}) from exc
    except proj_fn_svc.CrossGranularityProjectionError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_GRANULARITY_NOT_ALLOWED", "message": str(exc)}) from exc
    except proj_fn_svc.InvalidProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_fn_svc.MirrorPersistError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ProjectionToFunctionsExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        projection_count=result.projection_count,
        circuit_context_count=result.circuit_context_count,
        function_count=result.function_count,
        mirror_projection_function_created_count=result.mirror_projection_function_created_count,
        mirror_projection_function_skipped_duplicate_count=result.mirror_projection_function_skipped_duplicate_count,
        triple_created_count=result.triple_created_count,
        evidence_created_count=result.evidence_created_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        warnings=result.warnings,
    )


def _503_circuit_functions_not_initialized() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED",
            "message": (
                "mirror_circuit_functions table is not initialized. "
                "Please run backend/migrations/033_mirror_circuit_functions.sql."
            ),
            "migration": "backend/migrations/033_mirror_circuit_functions.sql",
        },
    )


@router.post("/circuit-to-functions", response_model=CircuitToFunctionsExtractionResponse)
async def circuit_to_functions(
    body: CircuitToFunctionsExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await circuit_fn_svc.run_circuit_to_functions_extraction(
            session,
            circuit_ids=body.circuit_ids,
            batch_id=body.batch_id,
            resource_id=body.resource_id,
            provider_name=body.provider,
            model_name=body.model_name,
            dry_run=body.dry_run,
            overwrite_policy=body.overwrite_policy,
            include_related_steps=body.include_related_steps,
            include_provenance=body.include_provenance,
            prompt_template_key=body.prompt_template_key,
            prompt_overrides=body.prompt_overrides,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            limit=body.limit,
        )
    except circuit_fn_svc.EmptyCircuitsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_fn_svc.CircuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except circuit_fn_svc.InvalidRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except circuit_fn_svc.MirrorCircuitFunctionsTableMissingError:
        raise _503_circuit_functions_not_initialized()
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error in circuit-to-functions extraction: {type(exc).__name__}: {exc}",
        ) from exc

    return CircuitToFunctionsExtractionResponse(
        status=result.status,
        target_type=result.target_type,
        source_target_type=result.source_target_type,
        circuit_count=result.circuit_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        created_ids=result.created_ids,
        updated_ids=result.updated_ids,
        skipped=result.skipped,
        errors=result.errors,
        warnings=result.warnings,
        prompt_preview=result.prompt_preview,
        estimated_model_calls=result.estimated_model_calls,
        estimated_input_tokens=result.estimated_input_tokens,
        dry_run=result.dry_run,
        created_targets=[
            {
                "target_type": t["target_type"],
                "target_table": t["target_table"],
                "ids": t["ids"],
                "count": t["count"],
            }
            for t in result.created_targets
        ],
    )


@router.post("/projections-to-circuits", response_model=ProjectionsToCircuitsExtractionResponse)
async def projections_to_circuits(
    body: ProjectionsToCircuitsExtractionRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await proj_circ_svc.run_projections_to_circuits_extraction(
            session,
            provider_name=body.provider,
            model_name=body.model_name,
            projection_ids=body.projection_ids,
            prompt_template_key=body.prompt_template_key,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_circuits=body.max_circuits,
            max_steps_per_circuit=body.max_steps_per_circuit,
            include_existing_circuits=body.include_existing_circuits,
            reuse_existing_circuits=body.reuse_existing_circuits,
            create_mirror_circuits=body.create_mirror_circuits,
            create_circuit_steps=body.create_circuit_steps,
            create_memberships=body.create_memberships,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
    except proj_circ_svc.EmptyProjectionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_circ_svc.TooFewProjectionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_circ_svc.TooManyProjectionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_circ_svc.ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except proj_circ_svc.CrossAtlasProjectionError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_ATLAS_NOT_ALLOWED", "message": str(exc)}) from exc
    except proj_circ_svc.CrossGranularityProjectionError as exc:
        raise HTTPException(status_code=400, detail={"code": "CROSS_GRANULARITY_NOT_ALLOWED", "message": str(exc)}) from exc
    except proj_circ_svc.InvalidProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_circ_svc.InvalidMembershipConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except proj_circ_svc.MirrorPersistError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except llm_extraction_service.ProviderNotConfiguredServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ProjectionsToCircuitsExtractionResponse(
        run_id=result.run_id,
        item_id=result.item_id,
        task_type=result.task_type,
        provider=result.provider,
        model_name=result.model_name,
        status=result.status,
        projection_count=result.projection_count,
        existing_circuit_context_count=result.existing_circuit_context_count,
        inferred_circuit_count=result.inferred_circuit_count,
        mirror_circuit_created_count=result.mirror_circuit_created_count,
        mirror_circuit_reused_count=result.mirror_circuit_reused_count,
        mirror_circuit_skipped_duplicate_count=result.mirror_circuit_skipped_duplicate_count,
        circuit_step_created_count=result.circuit_step_created_count,
        circuit_step_skipped_duplicate_count=result.circuit_step_skipped_duplicate_count,
        membership_created_count=result.membership_created_count,
        membership_skipped_duplicate_count=result.membership_skipped_duplicate_count,
        triple_created_count=result.triple_created_count,
        evidence_created_count=result.evidence_created_count,
        dry_run=result.dry_run,
        system_prompt=result.system_prompt,
        user_prompt=result.user_prompt,
        warnings=result.warnings,
    )


@router.post("/run-task")
async def run_llm_task(body: LlmRunTaskRequest, session: AsyncSession = Depends(get_db)):
    if body.task_type == LlmTaskType.same_granularity_connection_completion:
        if len(body.candidate_ids) < 2:
            raise HTTPException(status_code=400, detail="candidate_ids must have at least 2 items")
        req = SameGranularityConnectionExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            prompt_template_key=body.prompt_template_key or "same_granularity_connection_completion_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
        )
        return await same_granularity_connections(req, session)
    if body.task_type == LlmTaskType.same_granularity_function_completion:
        if not body.candidate_ids:
            raise HTTPException(status_code=400, detail="candidate_ids required")
        req = SameGranularityFunctionExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            prompt_template_key=body.prompt_template_key or "same_granularity_function_completion_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
        )
        return await same_granularity_functions(req, session)
    if body.task_type == LlmTaskType.same_granularity_circuit_completion:
        if len(body.candidate_ids) < 2:
            raise HTTPException(status_code=400, detail="candidate_ids must have at least 2 items")
        req = SameGranularityCircuitExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            candidate_ids=body.candidate_ids,
            prompt_template_key=body.prompt_template_key or "same_granularity_circuit_completion_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
        )
        return await same_granularity_circuits(req, session)
    if body.task_type == LlmTaskType.circuit_to_steps:
        if not body.circuit_id:
            raise HTTPException(status_code=400, detail="circuit_id required for circuit_to_steps")
        req = CircuitToStepsExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            circuit_id=body.circuit_id,
            prompt_template_key=body.prompt_template_key or "circuit_to_steps_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_steps=body.max_steps,
            include_circuit_regions=body.include_circuit_regions,
            create_mirror_records=body.create_mirror_records,
        )
        return await circuit_to_steps(req, session)
    if body.task_type == LlmTaskType.circuit_steps_to_projections:
        if not body.circuit_id:
            raise HTTPException(status_code=400, detail="circuit_id required for circuit_steps_to_projections")
        if body.create_memberships and not body.create_mirror_records:
            raise HTTPException(
                status_code=400,
                detail="create_memberships=true requires create_mirror_records=true",
            )
        req = CircuitStepsToProjectionsExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            circuit_id=body.circuit_id,
            prompt_template_key=body.prompt_template_key or "circuit_steps_to_projections_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_projections=body.max_projections,
            step_ids=body.step_ids,
            include_existing_projections=body.include_existing_projections,
            create_mirror_records=body.create_mirror_records,
            create_memberships=body.create_memberships,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
        return await circuit_steps_to_projections(req, session)
    if body.task_type == LlmTaskType.projection_to_functions:
        if not body.projection_ids:
            raise HTTPException(status_code=400, detail="projection_ids required for projection_to_functions")
        req = ProjectionToFunctionsExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            projection_ids=body.projection_ids,
            prompt_template_key=body.prompt_template_key or "projection_to_functions_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_functions_per_projection=body.max_functions_per_projection,
            include_circuit_context=body.include_circuit_context,
            include_region_context=body.include_region_context,
            create_mirror_records=body.create_mirror_records,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
        return await projection_to_functions(req, session)
    if body.task_type == LlmTaskType.circuit_to_functions:
        req = CircuitToFunctionsExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            circuit_ids=[body.circuit_id] if body.circuit_id else None,
            prompt_template_key=body.prompt_template_key or "circuit_to_functions_extraction_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
        )
        return await circuit_to_functions(req, session)
    if body.task_type == LlmTaskType.projections_to_circuits:
        if len(body.projection_ids) < 2:
            raise HTTPException(status_code=400, detail="projection_ids must have at least 2 items")
        if body.create_memberships and not body.create_mirror_circuits and not body.reuse_existing_circuits:
            raise HTTPException(
                status_code=400,
                detail="create_memberships=true requires create_mirror_circuits=true or reuse_existing_circuits=true",
            )
        req = ProjectionsToCircuitsExtractionRequest(
            provider=body.provider,
            model_name=body.model_name,
            projection_ids=body.projection_ids,
            prompt_template_key=body.prompt_template_key or "projections_to_circuits_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_circuits=body.max_circuits,
            max_steps_per_circuit=body.max_steps_per_circuit,
            include_existing_circuits=body.include_existing_circuits,
            reuse_existing_circuits=body.reuse_existing_circuits,
            create_mirror_circuits=body.create_mirror_circuits,
            create_circuit_steps=body.create_circuit_steps,
            create_memberships=body.create_memberships,
            create_triples=body.create_triples,
            create_evidence=body.create_evidence,
        )
        return await projections_to_circuits(req, session)
    if body.task_type == LlmTaskType.dual_model_verification:
        if not body.object_type:
            raise HTTPException(status_code=400, detail="object_type required for dual_model_verification")
        from app.schemas.mirror_dual_model_verification import DualModelVerificationRequest
        from app.routers.mirror_dual_model_verification import run_dual_model_verification as dm_run

        req = DualModelVerificationRequest(
            object_type=body.object_type,
            object_ids=body.object_ids or None,
            scope=None,
            model_a_provider=body.model_a_provider,
            model_a_name=body.model_a_name,
            model_b_provider=body.model_b_provider,
            model_b_name=body.model_b_name,
            prompt_template_key=body.prompt_template_key or "dual_model_verification_v1",
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            dry_run=body.dry_run,
            max_objects=body.max_objects,
            include_cross_validation_context=body.include_cross_validation_context,
            include_evidence_context=body.include_evidence_context,
            include_review_context=body.include_review_context,
            create_results=body.create_results,
        )
        return await dm_run(req, session)
    if body.task_type not in {LlmTaskType.region_field_completion} and body.task_type in {
        t for t in LlmTaskType.__dict__.values() if isinstance(t, str)
    }:
        from app.schemas.llm_extraction import PLANNED_MACRO_CLINICAL_TASK_TYPES
        if body.task_type in PLANNED_MACRO_CLINICAL_TASK_TYPES or body.task_type in {
            LlmTaskType.triple_candidate_generation,
            LlmTaskType.region_alias_completion,
            LlmTaskType.region_description_completion,
            LlmTaskType.translation,
            LlmTaskType.evidence_explanation,
            LlmTaskType.uncertainty_flagging,
        }:
            raise HTTPException(
                status_code=501,
                detail={
                    "code": "LLM_TASK_NOT_IMPLEMENTED",
                    "message": "This LLM task type is planned but not implemented.",
                },
            )
    if body.task_type not in {LlmTaskType.region_field_completion}:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "LLM_TASK_NOT_IMPLEMENTED",
                "message": "This LLM task type is planned but not implemented in Step 1.",
            },
        )
    if not body.candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids required")
    req = RegionFieldCompletionRequest(
        provider=body.provider,
        model_name=body.model_name,
        candidate_ids=body.candidate_ids,
        prompt_template_key=body.prompt_template_key or "region_field_completion_v1",
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        dry_run=body.dry_run,
    )
    return await region_field_completion(req, session)


@router.get("", response_model=LlmExtractionListResponse)
async def list_llm_extractions(
    candidate_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await llm_extraction_service.list_extractions(
        session,
        candidate_id=candidate_id,
        batch_id=batch_id,
        resource_id=resource_id,
        run_id=run_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return LlmExtractionListResponse(
        items=[LlmExtractionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/batch", response_model=BatchExtractResponse)
async def extract_batch(
    body: BatchExtractRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        run_id, rows = await llm_extraction_service.extract_batch(
            session, body.candidate_ids
        )
    except llm_extraction_service.BatchTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm_extraction_service.CandidateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"candidate not found: {exc}"
        ) from exc

    succeeded = sum(1 for r in rows if r.status == LlmExtractionStatus.succeeded)
    return BatchExtractResponse(
        run_id=run_id,
        requested=len(body.candidate_ids),
        succeeded=succeeded,
        failed=len(rows) - succeeded,
        items=[LlmExtractionRead.model_validate(r) for r in rows],
    )


@candidate_router.post("/{candidate_id}/llm-extract", response_model=LlmExtractionRead)
async def extract_single_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await llm_extraction_service.extract_one(session, candidate_id)
    except llm_extraction_service.CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    return LlmExtractionRead.model_validate(row)


@candidate_router.get(
    "/{candidate_id}/llm-extractions", response_model=LlmExtractionListResponse
)
async def list_candidate_llm_extractions(
    candidate_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await llm_extraction_service.list_extractions(
        session, candidate_id=candidate_id, limit=limit, offset=offset
    )
    return LlmExtractionListResponse(
        items=[LlmExtractionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/prompt-templates", response_model=ExtractionPromptTemplateListResponse)
async def list_extraction_prompt_templates(
    category: str = Query(default="extraction"),
):
    """Return LLM extraction prompt templates (not field completion prompts).
    
    category=extraction returns circuit_to_functions, circuit_to_steps, circuit extraction prompts.
    """
    from app.services.field_completion_prompt_engineering import list_extraction_prompt_template_items
    raw = list_extraction_prompt_template_items()
    if category and category != "extraction":
        raw = [r for r in raw if r.get("category") == category]
    return ExtractionPromptTemplateListResponse(items=raw)
