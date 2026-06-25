"""Server-side composite LLM extraction workflow orchestration."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError

logger = logging.getLogger(__name__)

from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep
from app.models.llm_extraction import LlmExtractionRun
from app.models.mirror_kg import (
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorProjectionFunction,
)
from app.schemas.llm_composite_workflow import (
    CompositeStepStatus,
    CompositeWorkflowCancelResponse,
    CompositeWorkflowRunRequest,
    CompositeWorkflowRunResponse,
    CompositeWorkflowRunRead,
    CompositeWorkflowStatus,
    CompositeWorkflowStepRead,
    CompositeWorkflowType,
)
from app.schemas.llm_extraction import (
    CircuitExtractionScope,
    CircuitToFunctionsExtractionRequest,
    CircuitToStepsExtractionRequest,
    ConnectionExtractionScope,
    LlmRunStatus,
    ProjectionToFunctionsExtractionRequest,
    SameGranularityCircuitExtractionRequest,
    SameGranularityConnectionExtractionRequest,
)
from app.services import llm_circuit_extraction_service as circuit_svc
from app.services import llm_circuit_function_extraction_service as circuit_fn_svc
from app.services import llm_circuit_step_extraction_service as circuit_step_svc
from app.services import llm_connection_extraction_service as conn_svc
from app.services import llm_projection_function_extraction_service as proj_fn_svc
from app.services import mirror_kg_service
from app.services.llm_extraction_prompt_engineering import CONNECTION_FAILURE_STATUSES
from app.services.llm_status_utils import is_semantic_failure, is_semantic_no_edges
from app.services.llm_workflow_cancel_registry import is_cancelling, mark_cancelling, cancel_tasks, clear as clear_cancel_registry
from app.services.llm_workflow_event_log import get_recent_events, safe_append_workflow_event
from app.services.llm_composite_workflow_cleanup_service import (
    cleanup_composite_workflow_artifacts,
    mark_workflow_cleanup_summary,
)
from app.services.triple_consolidation_service import ConsolidationScope, consolidate_mirror_triples


class CompositeWorkflowHandledError(Exception):
    """Structured composite workflow failure — carries a client-safe response."""

    def __init__(self, response: CompositeWorkflowRunResponse):
        self.response = response
        super().__init__("Composite workflow completed with handled failure")

# Test hooks — patch to simulate unimplemented optional steps.
PROJECTION_TO_FUNCTIONS_ENABLED = True
CIRCUIT_TO_FUNCTIONS_ENABLED = True

LARGE_PAIR_COUNT_WARNING_THRESHOLD = 200
LARGE_CANDIDATE_WARNING_THRESHOLD = 50

WORKFLOW_STEP_DEFS: dict[str, list[dict[str, Any]]] = {
    CompositeWorkflowType.connection_with_function: [
        {
            "step_key": "extract_connections",
            "step_label": "Extract Connections",
            "step_order": 1,
            "dependency_step_key": None,
            "required": True,
        },
        {
            "step_key": "extract_projection_functions",
            "step_label": "Extract Projection Functions",
            "step_order": 2,
            "dependency_step_key": "extract_connections",
            "required": False,
        },
    ],
    CompositeWorkflowType.circuit_with_function_steps: [
        {
            "step_key": "extract_circuits",
            "step_label": "Extract Circuits",
            "step_order": 1,
            "dependency_step_key": None,
            "required": True,
        },
        {
            "step_key": "extract_circuit_steps",
            "step_label": "Extract Circuit Steps",
            "step_order": 2,
            "dependency_step_key": "extract_circuits",
            "required": False,
        },
        {
            "step_key": "extract_circuit_functions",
            "step_label": "Extract Circuit Functions",
            "step_order": 3,
            "dependency_step_key": "extract_circuits",
            "required": False,
        },
    ],
    CompositeWorkflowType.triple_generation: [
        {
            "step_key": "generate_triples",
            "step_label": "Generate Triples",
            "step_order": 1,
            "dependency_step_key": None,
            "required": True,
        },
    ],
}


def compute_pair_count(candidate_ids: list[uuid.UUID]) -> int:
    n = len(candidate_ids)
    if n < 2:
        return 0
    return n * (n - 1) // 2


def none_if_blank(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


PROVIDER_AUDIT_SUMMARY_KEYS: tuple[str, ...] = (
    "provider_call_count",
    "provider_success_count",
    "provider_error_count",
    "provider_transport_error_count",
    "provider_empty_response_count",
    "prompt_sent_count",
    "prompt_built_count",
    "parse_error_count",
    "schema_error_count",
    "failed_pack_count",
    "pack_count",
    "processed_pack_count",
    "processed_pair_count",
    "parsed_projection_count",
    "parsed_no_connection_count",
    "created_projection_count",
    "no_connection_count",
    "unprocessed_pair_count",
    "rejected_item_count",
    "response_received_count",
    "fail_fast_triggered",
    "remaining_pack_count_skipped",
    "fail_fast_reason",
    "debug_mode",
    "debug_single_pack",
    "debug_max_packs",
    "planned_pack_count",
    "executed_pack_count",
    "skipped_debug_pack_count",
    "planned_model_call_count",
    "pack_summaries",
    "provider_audit",
    "errors",
)


def apply_debug_flags_to_request(
    request: CompositeWorkflowRunRequest,
) -> CompositeWorkflowRunRequest:
    data = request.model_dump()
    if data.get("debug_single_pack"):
        data["debug_max_packs"] = 1
    return CompositeWorkflowRunRequest.model_validate(data)


def normalize_composite_request(request: CompositeWorkflowRunRequest) -> CompositeWorkflowRunRequest:
    data = request.model_dump()
    for key in (
        "resource_id",
        "batch_id",
        "source_atlas",
        "source_version",
        "granularity_level",
        "granularity_family",
        "batch_strategy",
        "notes",
        "model_name",
    ):
        if key in data:
            data[key] = none_if_blank(data[key])
    normalized = CompositeWorkflowRunRequest.model_validate(data)
    return apply_debug_flags_to_request(normalized)


def compute_progress_percent(steps: list[LlmCompositeWorkflowStep]) -> float:
    if not steps:
        return 0.0
    total = len(steps)
    completed = 0.0
    for step in steps:
        if step.status in {
            CompositeStepStatus.succeeded.value,
            CompositeStepStatus.skipped.value,
            CompositeStepStatus.failed.value,
        }:
            completed += 1.0
        elif step.status == CompositeStepStatus.running.value:
            completed += 0.5
    return round((completed / total) * 100.0, 1)


def normalize_step_error(error: BaseException | str) -> str:
    if isinstance(error, str):
        return error
    msg = str(error) or error.__class__.__name__
    if isinstance(error, TypeError) and "unexpected keyword argument" in msg:
        return f"Composite workflow service invocation failed: {msg}"
    return msg


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _scope_from_request(request: CompositeWorkflowRunRequest) -> ConnectionExtractionScope:
    return ConnectionExtractionScope(
        resource_id=request.resource_id,
        batch_id=request.batch_id,
        source_atlas=request.source_atlas,
        granularity_level=request.granularity_level,
        granularity_family=request.granularity_family,
    )


def _circuit_scope_from_composite(
    request: CompositeWorkflowRunRequest,
) -> CircuitExtractionScope | None:
    if not any(
        (
            request.resource_id,
            request.batch_id,
            request.source_atlas,
            request.granularity_level,
            request.granularity_family,
        )
    ):
        return None
    return CircuitExtractionScope(
        resource_id=request.resource_id,
        batch_id=request.batch_id,
        source_atlas=request.source_atlas,
        granularity_level=request.granularity_level,
        granularity_family=request.granularity_family,
    )


def _connection_scope_from_composite(
    request: CompositeWorkflowRunRequest,
) -> ConnectionExtractionScope | None:
    scope = _scope_from_request(request)
    if not any(
        (
            scope.resource_id,
            scope.batch_id,
            scope.source_atlas,
            scope.granularity_level,
            scope.granularity_family,
        )
    ):
        return None
    return scope


def build_circuit_extraction_request(
    request: CompositeWorkflowRunRequest,
) -> SameGranularityCircuitExtractionRequest:
    """Map composite workflow input to the same-granularity circuit request schema."""
    return SameGranularityCircuitExtractionRequest(
        provider=request.provider,
        model_name=request.model_name,
        candidate_ids=list(request.candidate_ids),
        scope=_circuit_scope_from_composite(request),
        dry_run=request.dry_run,
        create_mirror_records=request.create_mirror_records,
        create_triples=request.create_triples,
        create_evidence=request.create_evidence,
    )


def build_connection_extraction_request(
    request: CompositeWorkflowRunRequest,
) -> SameGranularityConnectionExtractionRequest:
    """Map composite workflow input to the same-granularity connection request schema."""
    debug_max_packs = 1 if request.debug_single_pack else request.debug_max_packs
    return SameGranularityConnectionExtractionRequest(
        provider=request.provider,
        model_name=request.model_name,
        candidate_ids=list(request.candidate_ids),
        scope=_connection_scope_from_composite(request),
        dry_run=request.dry_run,
        create_mirror_records=request.create_mirror_records,
        create_triples=request.create_triples,
        create_evidence=request.create_evidence,
        debug_max_packs=debug_max_packs,
        debug_single_pack=request.debug_single_pack,
        parse_error_fail_fast_enabled=request.parse_error_fail_fast_enabled,
        parse_error_fail_fast_threshold=request.parse_error_fail_fast_threshold,
    )


def build_projection_to_functions_request(
    request: CompositeWorkflowRunRequest,
    projection_ids: list[uuid.UUID],
) -> ProjectionToFunctionsExtractionRequest:
    return ProjectionToFunctionsExtractionRequest(
        provider=request.provider,
        model_name=request.model_name,
        projection_ids=projection_ids,
        dry_run=request.dry_run,
        include_circuit_context=True,
        include_region_context=request.include_region_context,
        create_mirror_records=request.create_mirror_records,
        create_triples=request.create_triples,
        create_evidence=request.create_evidence,
    )


def build_circuit_to_steps_request(
    request: CompositeWorkflowRunRequest,
    circuit_id: uuid.UUID,
) -> CircuitToStepsExtractionRequest:
    return CircuitToStepsExtractionRequest(
        provider=request.provider,
        model_name=request.model_name,
        circuit_id=circuit_id,
        dry_run=request.dry_run,
        create_mirror_records=request.create_mirror_records,
        include_circuit_regions=True,
    )


def build_circuit_to_functions_request(
    request: CompositeWorkflowRunRequest,
    circuit_ids: list[uuid.UUID],
) -> CircuitToFunctionsExtractionRequest:
    return CircuitToFunctionsExtractionRequest(
        provider=request.provider,
        model_name=request.model_name,
        circuit_ids=_dedupe_uuid_list(circuit_ids),
        batch_id=request.batch_id,
        resource_id=request.resource_id,
        dry_run=request.dry_run,
        include_related_steps=True,
        include_provenance=True,
    )


async def invoke_circuit_extraction(
    session: AsyncSession,
    body: SameGranularityCircuitExtractionRequest,
) -> circuit_svc.CircuitExtractionResult:
    """Invoke circuit extraction using the same kwargs as llm_extraction router."""
    scope = body.scope
    return await circuit_svc.run_same_granularity_circuit_extraction(
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


async def invoke_connection_extraction(
    session: AsyncSession,
    body: SameGranularityConnectionExtractionRequest,
    *,
    composite_workflow_run_id: uuid.UUID | None = None,
    workflow_step_key: str | None = None,
    on_progress: conn_svc.ConnectionProgressCallback | None = None,
    commit_progress: bool = False,
) -> conn_svc.ConnectionExtractionResult:
    """Invoke connection extraction using the same kwargs as llm_extraction router."""
    scope = body.scope
    return await conn_svc.run_same_granularity_connection_extraction(
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
        composite_workflow_run_id=composite_workflow_run_id,
        workflow_step_key=workflow_step_key,
        on_progress=on_progress,
        commit_progress=commit_progress,
        debug_max_packs=body.debug_max_packs,
        debug_single_pack=body.debug_single_pack,
        parse_error_fail_fast_enabled=body.parse_error_fail_fast_enabled,
        parse_error_fail_fast_threshold=body.parse_error_fail_fast_threshold,
    )


async def invoke_projection_to_functions_extraction(
    session: AsyncSession,
    body: ProjectionToFunctionsExtractionRequest,
    *,
    composite_workflow_run_id: uuid.UUID | None = None,
    workflow_step_key: str | None = None,
) -> proj_fn_svc.ProjectionToFunctionsResult:
    return await proj_fn_svc.run_projection_to_functions_extraction(
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
        composite_workflow_run_id=composite_workflow_run_id,
        workflow_step_key=workflow_step_key,
    )


async def invoke_circuit_to_steps_extraction(
    session: AsyncSession,
    body: CircuitToStepsExtractionRequest,
) -> circuit_step_svc.CircuitToStepsResult:
    return await circuit_step_svc.run_circuit_to_steps_extraction(
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


async def invoke_circuit_to_functions_extraction(
    session: AsyncSession,
    body: CircuitToFunctionsExtractionRequest,
) -> circuit_fn_svc.CircuitToFunctionsResult:
    return await circuit_fn_svc.run_circuit_to_functions_extraction(
        session,
        circuit_ids=body.circuit_ids,
        batch_id=body.batch_id,
        resource_id=body.resource_id,
        provider_name=body.provider,
        model_name=body.model_name,
        dry_run=body.dry_run,
        include_related_steps=body.include_related_steps,
        include_provenance=body.include_provenance,
        prompt_template_key=body.prompt_template_key,
        prompt_overrides=body.prompt_overrides or None,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        limit=body.limit,
    )


def _consolidation_scope_from_request(request: CompositeWorkflowRunRequest) -> ConsolidationScope:
    return ConsolidationScope(
        resource_id=request.resource_id,
        batch_id=request.batch_id,
        source_atlas=request.source_atlas,
        granularity_level=request.granularity_level,
        granularity_family=request.granularity_family,
    )


def _input_scope_json(request: CompositeWorkflowRunRequest) -> dict[str, Any]:
    return {
        "resource_id": str(request.resource_id) if request.resource_id else None,
        "batch_id": str(request.batch_id) if request.batch_id else None,
        "source_atlas": request.source_atlas,
        "source_version": request.source_version,
        "granularity_level": request.granularity_level,
        "granularity_family": request.granularity_family,
    }


def collect_step_counts(response: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if response is None:
        return counts
    if isinstance(response, circuit_fn_svc.CircuitToFunctionsResult):
        if response.created_count:
            counts["circuit_functions"] = int(response.created_count)
        return counts
    mapping = {
        "mirror_connection_created_count": "connections",
        "mirror_circuit_created_count": "circuits",
        "mirror_step_created_count": "circuit_steps",
        "mirror_projection_function_created_count": "projection_functions",
        "triple_created_count": "triples",
        "evidence_created_count": "evidence",
        "created_triple_count": "triples",
    }
    for attr, key in mapping.items():
        val = getattr(response, attr, None)
        if val:
            counts[key] = counts.get(key, 0) + int(val)
    return counts


def _connection_extraction_failed(status: str | None) -> bool:
    return is_semantic_failure(status)


def _connection_semantic_outcome(result: conn_svc.ConnectionExtractionResult) -> str | None:
    return result.outcome or result.display_status or result.status


def _step_response_semantic_outcome(response_json: dict[str, Any] | None) -> str | None:
    if not response_json:
        return None
    return (
        response_json.get("outcome")
        or response_json.get("display_status")
        or response_json.get("semantic_status")
        or response_json.get("status")
    )


def _connection_step_status(result: conn_svc.ConnectionExtractionResult) -> CompositeStepStatus:
    status = _connection_semantic_outcome(result) or ""
    if status == LlmRunStatus.cancelled:
        return CompositeStepStatus.cancelled
    if _connection_extraction_failed(status):
        return CompositeStepStatus.failed
    if is_semantic_no_edges(status):
        return CompositeStepStatus.succeeded
    if status == LlmRunStatus.partially_succeeded:
        return CompositeStepStatus.failed
    return CompositeStepStatus.succeeded


def _connection_workflow_overrides(
    result: conn_svc.ConnectionExtractionResult,
) -> tuple[str | None, CompositeStepStatus | None]:
    """Return optional workflow status override and projection_function skip status."""
    status = _connection_semantic_outcome(result) or ""
    if status == LlmRunStatus.cancelled:
        return CompositeWorkflowStatus.cancelled.value, CompositeStepStatus.skipped
    if _connection_extraction_failed(status):
        return CompositeWorkflowStatus.failed.value, CompositeStepStatus.skipped_dependency_failed
    if is_semantic_no_edges(status):
        return CompositeWorkflowStatus.succeeded.value, CompositeStepStatus.skipped_no_projection
    return None, None


def _response_to_json(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if is_dataclass(response):
        data = asdict(response)
    elif isinstance(response, dict):
        data = response
    else:
        return {"value": str(response)}
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, list) and v and isinstance(v[0], uuid.UUID):
            out[k] = [str(x) for x in v]
        else:
            out[k] = v
    return out


def _connection_step_response_json(result: Any) -> dict[str, Any]:
    """Normalize connection extraction result for workflow step JSONB + progress API."""
    from app.services.llm_connection_parse_diagnostics import (
        merge_provider_audit,
        validate_connection_progress_invariants,
    )

    base = _response_to_json(result)
    execution_summary = dict(getattr(result, "execution_summary", None) or base.get("execution_summary") or {})
    provider_audit = merge_provider_audit(execution_summary)
    pack_summaries = provider_audit.get("pack_summaries") or execution_summary.get("pack_summaries") or []
    execution_summary["provider_audit"] = provider_audit
    execution_summary["pack_summaries"] = pack_summaries
    diagnostics = list(execution_summary.get("diagnostics") or [])
    diagnostics.extend(validate_connection_progress_invariants(execution_summary))
    if diagnostics:
        execution_summary["diagnostics"] = diagnostics
    return {
        **base,
        "execution_summary": execution_summary,
        "provider_audit": provider_audit,
        "pack_summaries": pack_summaries,
    }


def _merge_connection_provider_audit_into_summary(
    summary: dict[str, Any],
    *,
    existing_summary: dict[str, Any] | None = None,
    conn_step: LlmCompositeWorkflowStep | None = None,
) -> dict[str, Any]:
    from app.services.llm_connection_parse_diagnostics import (
        INVARIANT_PACK_SUMMARIES_MISSING,
        merge_provider_audit,
        validate_connection_progress_invariants,
    )

    merged = dict(summary)
    if existing_summary:
        for key in PROVIDER_AUDIT_SUMMARY_KEYS:
            val = existing_summary.get(key)
            if val not in (None, {}, []):
                merged[key] = val

    if conn_step is None:
        return merged

    conn_resp = dict(conn_step.response_json or {})
    execution_summary = dict(conn_resp.get("execution_summary") or {})
    if not execution_summary and conn_resp.get("execution_summary") is None:
        execution_summary = {
            key: conn_resp[key]
            for key in PROVIDER_AUDIT_SUMMARY_KEYS
            if conn_resp.get(key) is not None
        }
    provider_audit = conn_resp.get("provider_audit")
    if not isinstance(provider_audit, dict):
        provider_audit = execution_summary.get("provider_audit")
    if not isinstance(provider_audit, dict):
        provider_audit = merge_provider_audit(execution_summary)
    pack_summaries = (
        provider_audit.get("pack_summaries")
        or execution_summary.get("pack_summaries")
        or conn_resp.get("pack_summaries")
        or []
    )
    provider_audit = dict(provider_audit)
    provider_audit["pack_summaries"] = pack_summaries
    execution_summary["provider_audit"] = provider_audit
    execution_summary["pack_summaries"] = pack_summaries

    for key in PROVIDER_AUDIT_SUMMARY_KEYS:
        if execution_summary.get(key) is not None:
            merged[key] = execution_summary[key]
    merged["provider_audit"] = provider_audit
    merged["pack_summaries"] = pack_summaries

    diagnostics = list(merged.get("diagnostics") or [])
    diagnostics.extend(validate_connection_progress_invariants(merged))
    parse_error_count = int(merged.get("parse_error_count") or 0)
    if parse_error_count > 0 and not pack_summaries:
        diagnostics.append({
            "code": INVARIANT_PACK_SUMMARIES_MISSING,
            "level": "error",
            "message": "parse_error_count > 0 but provider_audit.pack_summaries is empty",
        })
    if diagnostics:
        merged["diagnostics"] = diagnostics
    return merged


def build_result_summary(
    run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
) -> dict[str, Any]:
    totals: dict[str, int] = {}
    llm_run_ids: list[str] = []
    for step in steps:
        for key, val in (step.created_counts_json or {}).items():
            if isinstance(val, (int, float)):
                totals[key] = totals.get(key, 0) + int(val)
        if step.llm_run_id:
            llm_run_ids.append(str(step.llm_run_id))
    return {
        "workflow_type": run.workflow_type,
        "dry_run": run.dry_run,
        "candidate_count": run.candidate_count,
        "pair_count": run.pair_count,
        "created_counts": totals,
        "created_targets": aggregate_workflow_created_targets(steps),
        "llm_run_ids": llm_run_ids,
        "step_statuses": {s.step_key: s.status for s in steps},
    }


def _dedupe_uuid_list(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for tid in ids:
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
    return out


def _dedupe_str_list(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tid in ids:
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
    return out


def aggregate_workflow_created_targets(
    steps: list[LlmCompositeWorkflowStep],
) -> list[dict[str, Any]]:
    """Merge per-step created_targets for workflow response (dedupe ids per group)."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for step in steps:
        if step.status not in {
            CompositeStepStatus.succeeded.value,
        }:
            continue
        resp = step.response_json or {}
        targets = resp.get("created_targets")
        if not isinstance(targets, list):
            continue
        for raw in targets:
            if not isinstance(raw, dict):
                continue
            target_type = str(raw.get("target_type") or "")
            step_key = str(raw.get("step_key") or step.step_key)
            if not target_type:
                continue
            ids = _dedupe_str_list([str(i) for i in (raw.get("ids") or []) if i])
            if not ids and not raw.get("count"):
                continue
            key = (target_type, step_key)
            bucket = grouped.get(key)
            if bucket is None:
                bucket = {
                    "target_type": target_type,
                    "target_table": raw.get("target_table"),
                    "ids": [],
                    "count": 0,
                    "step_key": step_key,
                }
                grouped[key] = bucket
            bucket["ids"] = _dedupe_str_list(list(bucket["ids"]) + ids)
            bucket["count"] = len(bucket["ids"])
    return list(grouped.values())


def _attach_circuit_ids_to_step_response(
    step: LlmCompositeWorkflowStep,
    circuit_ids: list[uuid.UUID],
) -> dict[str, Any]:
    merged = dict(step.response_json or {})
    id_strs = [str(i) for i in _dedupe_uuid_list(circuit_ids)]
    merged["source_circuit_ids"] = id_strs
    if id_strs:
        targets = list(merged.get("created_targets") or [])
        targets.append({
            "target_type": "circuit",
            "target_table": "mirror_region_circuits",
            "ids": id_strs,
            "count": len(id_strs),
            "step_key": "extract_circuits",
        })
        merged["created_targets"] = targets
    step.response_json = merged
    return merged


def build_circuit_to_functions_step_response(
    fn_result: circuit_fn_svc.CircuitToFunctionsResult,
    *,
    circuit_ids: list[uuid.UUID],
    dry_run: bool,
) -> dict[str, Any]:
    created_targets = []
    for raw in fn_result.created_targets:
        entry = dict(raw)
        entry["step_key"] = "circuit_to_functions"
        created_targets.append(entry)
    status = fn_result.status
    if dry_run:
        status = "dry_run"
    return {
        "step_key": "circuit_to_functions",
        "step_label": "Extract Circuit Functions",
        "status": status,
        "target_type": "circuit_function",
        "target_table": "mirror_circuit_functions",
        "source_target_type": "circuit",
        "source_count": len(_dedupe_uuid_list(circuit_ids)),
        "created_count": fn_result.created_count,
        "updated_count": fn_result.updated_count,
        "skipped_count": fn_result.skipped_count,
        "failed_count": fn_result.failed_count,
        "created_ids": [str(i) for i in fn_result.created_ids],
        "updated_ids": [str(i) for i in fn_result.updated_ids],
        "created_targets": created_targets,
        "warnings": list(fn_result.warnings),
        "errors": list(fn_result.errors),
        "prompt_preview": fn_result.prompt_preview or {},
    }


async def create_workflow_run(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
) -> LlmCompositeWorkflowRun:
    candidate_ids = list(request.candidate_ids)
    pair_count = compute_pair_count(candidate_ids)
    run = LlmCompositeWorkflowRun(
        workflow_type=request.workflow_type.value,
        status=CompositeWorkflowStatus.pending.value,
        provider=request.provider,
        model_name=request.model_name,
        dry_run=request.dry_run,
        resource_id=request.resource_id,
        batch_id=request.batch_id,
        source_atlas=request.source_atlas,
        source_version=request.source_version,
        granularity_level=request.granularity_level,
        granularity_family=request.granularity_family,
        candidate_ids_json=[str(cid) for cid in candidate_ids],
        candidate_count=len(candidate_ids),
        pair_count=pair_count,
        input_scope_json=_input_scope_json(request),
        request_json=request.model_dump(mode="json"),
        started_at=_utcnow(),
    )
    session.add(run)
    await session.flush()
    return run


async def create_workflow_step(
    session: AsyncSession,
    *,
    workflow_run_id: uuid.UUID,
    step_order: int,
    step_key: str,
    step_label: str | None,
    dependency_step_key: str | None,
) -> LlmCompositeWorkflowStep:
    step = LlmCompositeWorkflowStep(
        workflow_run_id=workflow_run_id,
        step_order=step_order,
        step_key=step_key,
        step_label=step_label,
        status=CompositeStepStatus.pending.value,
        dependency_step_key=dependency_step_key,
    )
    session.add(step)
    await session.flush()
    return step


def _sanitize_step_update_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove control kwargs accidentally passed via **kwargs to update_workflow_step_status."""
    if "commit_progress" not in kwargs:
        return kwargs
    logger.warning(
        "[composite-workflow] duplicate commit_progress removed from step update payload"
    )
    cleaned = dict(kwargs)
    cleaned.pop("commit_progress", None)
    return cleaned


async def update_workflow_step_status(
    session: AsyncSession,
    step: LlmCompositeWorkflowStep,
    *,
    status: CompositeStepStatus,
    llm_run_id: uuid.UUID | None = None,
    llm_item_id: uuid.UUID | None = None,
    request_json: dict[str, Any] | None = None,
    response_json: dict[str, Any] | None = None,
    created_counts: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    mark_started: bool = False,
    mark_completed: bool = False,
    commit_progress: bool = False,
) -> LlmCompositeWorkflowStep:
    if not session.is_active:
        await session.rollback()
    step.status = status.value
    if llm_run_id is not None:
        step.llm_run_id = llm_run_id
    if llm_item_id is not None:
        step.llm_item_id = llm_item_id
    if request_json is not None:
        step.request_json = request_json
    if response_json is not None:
        step.response_json = response_json
        flag_modified(step, "response_json")
    if created_counts is not None:
        step.created_counts_json = created_counts
        flag_modified(step, "created_counts_json")
    if warnings is not None:
        step.warnings_json = warnings
        flag_modified(step, "warnings_json")
    if errors is not None:
        step.errors_json = errors
        flag_modified(step, "errors_json")
    if mark_started and step.started_at is None:
        step.started_at = _utcnow()
    if mark_completed:
        step.completed_at = _utcnow()
    try:
        await session.flush()
        if commit_progress:
            await session.commit()
    except StaleDataError:
        # A concurrent cancel/cleanup may have changed rows underneath us. If the
        # workflow is being cancelled this is an expected late update and must be
        # ignored rather than surfaced to the user. Otherwise it is a genuine
        # consistency error and should propagate.
        if is_cancelling(step.workflow_run_id):
            logger.warning(
                "[composite] late step update ignored after cancellation step=%s workflow_run_id=%s",
                step.step_key,
                step.workflow_run_id,
            )
            await session.rollback()
            return step
        raise
    return step


_CANCELLED_RUN_STATUSES = {
    CompositeWorkflowStatus.cancelling.value,
    CompositeWorkflowStatus.cancelled.value,
    CompositeWorkflowStatus.cleanup_in_progress.value,
    CompositeWorkflowStatus.cleanup_done.value,
    CompositeWorkflowStatus.cleanup_failed.value,
}


async def is_workflow_cancelled_or_cancelling(
    session: AsyncSession,
    workflow_run_id: uuid.UUID | None,
) -> bool:
    """Cancel-aware guard: true if the in-process registry flagged the run OR the
    persisted run status indicates the workflow is being / has been cancelled."""
    if workflow_run_id is None:
        return False
    if is_cancelling(workflow_run_id):
        return True
    status = (
        await session.execute(
            select(LlmCompositeWorkflowRun.status).where(
                LlmCompositeWorkflowRun.id == workflow_run_id
            )
        )
    ).scalar_one_or_none()
    return status in _CANCELLED_RUN_STATUSES


async def finalize_workflow_run(
    session: AsyncSession,
    run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
    *,
    warnings: list[str],
    errors: list[str],
) -> LlmCompositeWorkflowRun:
    run.warnings_json = warnings
    run.errors_json = errors
    existing_summary = dict(run.result_summary_json or {})
    summary = build_result_summary(run, steps)
    if existing_summary.get("events"):
        summary["events"] = existing_summary["events"]
    conn_step = next((s for s in steps if s.step_key == "extract_connections"), None)
    summary = _merge_connection_provider_audit_into_summary(
        summary,
        existing_summary=existing_summary,
        conn_step=conn_step,
    )
    run.completed_at = _utcnow()

    step_map = {s.step_key: s for s in steps}
    defs = WORKFLOW_STEP_DEFS.get(run.workflow_type, [])
    required_keys = [d["step_key"] for d in defs if d.get("required")]
    optional_keys = [d["step_key"] for d in defs if not d.get("required")]

    any_required_failed = any(
        step_map.get(k) and step_map[k].status == CompositeStepStatus.failed.value for k in required_keys
    )
    all_required_succeeded = all(
        step_map.get(k) and step_map[k].status == CompositeStepStatus.succeeded.value for k in required_keys
    )
    any_optional_skipped_or_failed = any(
        step_map.get(k)
        and step_map[k].status in {
            CompositeStepStatus.skipped.value,
            CompositeStepStatus.skipped_no_projection.value,
            CompositeStepStatus.skipped_dependency_failed.value,
            CompositeStepStatus.failed.value,
        }
        for k in optional_keys
    )
    any_core_succeeded = any(
        step_map.get(k) and step_map[k].status == CompositeStepStatus.succeeded.value for k in required_keys
    )

    if any_required_failed:
        run.status = CompositeWorkflowStatus.failed.value
    elif run.dry_run and all(
        step_map.get(d["step_key"])
        and step_map[d["step_key"]].status
        in {
            CompositeStepStatus.succeeded.value,
            CompositeStepStatus.skipped.value,
            CompositeStepStatus.skipped_no_projection.value,
        }
        for d in defs
    ):
        run.status = CompositeWorkflowStatus.dry_run.value
    elif not any_required_failed and any(
        _step_response_semantic_outcome((step_map.get(k).response_json or {})) == LlmRunStatus.succeeded_no_edges  # type: ignore[union-attr]
        for k in required_keys
        if step_map.get(k)
    ):
        run.status = CompositeWorkflowStatus.succeeded.value
        summary["outcome"] = LlmRunStatus.succeeded_no_edges
        summary["semantic_status"] = LlmRunStatus.succeeded_no_edges
        summary["display_status"] = LlmRunStatus.succeeded_no_edges
        summary["has_projection"] = False
        summary["projection_function_skipped_reason"] = "no_projection"
    elif all_required_succeeded and not any_optional_skipped_or_failed:
        run.status = CompositeWorkflowStatus.succeeded.value
    elif any_core_succeeded:
        run.status = CompositeWorkflowStatus.partially_succeeded.value
    else:
        run.status = CompositeWorkflowStatus.failed.value

    if summary.get("outcome"):
        summary.setdefault("display_status", summary["outcome"])
        summary.setdefault("semantic_status", summary["outcome"])

    run.result_summary_json = summary
    flag_modified(run, "result_summary_json")
    await session.flush()
    return run


def _step_read(step: LlmCompositeWorkflowStep) -> CompositeWorkflowStepRead:
    from app.services.llm_connection_parse_diagnostics import merge_provider_audit

    response_json = step.response_json or {}
    execution_summary = dict(response_json.get("execution_summary") or {})
    top_level_packs = response_json.get("pack_summaries")
    if top_level_packs and not execution_summary.get("pack_summaries"):
        execution_summary["pack_summaries"] = top_level_packs
    provider_audit = response_json.get("provider_audit")
    if isinstance(provider_audit, dict):
        if provider_audit.get("pack_summaries") and not execution_summary.get("pack_summaries"):
            execution_summary["pack_summaries"] = provider_audit.get("pack_summaries")
        for key, val in provider_audit.items():
            if key == "errors":
                continue
            if val is not None and execution_summary.get(key) in (None, 0, [], {}):
                execution_summary[key] = val
    if not execution_summary.get("provider_audit"):
        execution_summary["provider_audit"] = merge_provider_audit(execution_summary)
    if not execution_summary and response_json:
        execution_summary = {
            key: response_json[key]
            for key in (
                "provider_call_count",
                "provider_success_count",
                "provider_error_count",
                "provider_empty_response_count",
                "provider_transport_error_count",
                "parse_error_count",
                "schema_error_count",
                "failed_pack_count",
                "pack_summaries",
                "pack_count",
                "processed_pair_count",
                "unprocessed_pair_count",
                "created_projection_count",
                "no_connection_count",
                "status",
            )
            if key in response_json
        }
    return CompositeWorkflowStepRead(
        id=step.id,
        workflow_run_id=step.workflow_run_id,
        step_order=step.step_order,
        step_key=step.step_key,
        step_label=step.step_label,
        status=CompositeStepStatus(step.status),
        llm_run_id=step.llm_run_id,
        llm_item_id=step.llm_item_id,
        created_counts=step.created_counts_json or {},
        warnings=list(step.warnings_json or []),
        errors=list(step.errors_json or []),
        execution_summary=execution_summary,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def _workflow_semantic_fields(summary: dict[str, Any]) -> dict[str, str | None]:
    outcome = summary.get("outcome") or summary.get("semantic_status")
    display = summary.get("display_status") or outcome
    return {
        "outcome": outcome,
        "display_status": display,
        "semantic_status": summary.get("semantic_status") or outcome,
    }


def _run_response(
    run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
) -> CompositeWorkflowRunResponse:
    step_reads = [_step_read(s) for s in sorted(steps, key=lambda s: s.step_order)]
    summary = run.result_summary_json or build_result_summary(run, steps)
    semantic = _workflow_semantic_fields(summary)
    return CompositeWorkflowRunResponse(
        workflow_run_id=run.id,
        workflow_type=CompositeWorkflowType(run.workflow_type),
        status=CompositeWorkflowStatus(run.status),
        dry_run=run.dry_run,
        candidate_count=run.candidate_count,
        pair_count=run.pair_count,
        steps=step_reads,
        progress_percent=compute_progress_percent(steps),
        result_summary=summary,
        outcome=semantic["outcome"],
        display_status=semantic["display_status"],
        semantic_status=semantic["semantic_status"],
        recent_events=get_recent_events(summary),
        created_targets=list(summary.get("created_targets") or []),
        warnings=list(run.warnings_json or []),
        errors=list(run.errors_json or []),
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def _collect_preflight_warnings(request: CompositeWorkflowRunRequest) -> list[str]:
    warnings: list[str] = []
    n = len(request.candidate_ids)
    pair_count = compute_pair_count(request.candidate_ids)
    if n > LARGE_CANDIDATE_WARNING_THRESHOLD:
        warnings.append(
            f"Selected {n} candidates; model input, cost, and runtime may increase significantly. "
            "No automatic truncation or batching is applied."
        )
    if pair_count > LARGE_PAIR_COUNT_WARNING_THRESHOLD:
        warnings.append(
            f"pair_count ({pair_count}) is large; prompt size or runtime may increase. "
            "No truncation or automatic batching is applied."
        )
    if request.explicit_batching_enabled:
        warnings.append(
            "explicit_batching_enabled is set but automatic batching is not implemented in this release."
        )
    return warnings


async def _count_mirror_objects_in_scope(
    session: AsyncSession,
    scope: ConsolidationScope,
) -> dict[str, int]:
    counts: dict[str, int] = {}

    async def _count(model, key: str) -> None:
        q = select(func.count()).select_from(model)
        if scope.resource_id:
            q = q.where(model.resource_id == scope.resource_id)
        if scope.batch_id:
            q = q.where(model.batch_id == scope.batch_id)
        if scope.source_atlas:
            q = q.where(model.source_atlas == scope.source_atlas)
        if scope.granularity_level:
            q = q.where(model.granularity_level == scope.granularity_level)
        if scope.granularity_family:
            q = q.where(model.granularity_family == scope.granularity_family)
        result = await session.execute(q)
        counts[key] = int(result.scalar_one() or 0)

    await _count(MirrorRegionConnection, "connections")
    await _count(MirrorRegionFunction, "region_functions")
    await _count(MirrorRegionCircuit, "circuits")
    await _count(MirrorCircuitStep, "circuit_steps")
    await _count(MirrorProjectionFunction, "projection_functions")
    await _count(MirrorCircuitProjectionMembership, "memberships")
    return counts


async def _resolve_projection_ids(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    step1_response: Any,
    llm_run_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    if step1_response is not None:
        created_ids = getattr(step1_response, "created_connection_ids", None)
        if created_ids:
            return list(created_ids)

    scope = _scope_from_request(request)
    items, _ = await mirror_kg_service.list_mirror_connections(
        session,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        llm_run_id=llm_run_id,
        limit=10000,
        offset=0,
    )
    if items:
        return [c.id for c in items]

    items, _ = await mirror_kg_service.list_mirror_connections(
        session,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        limit=10000,
        offset=0,
    )
    return [c.id for c in items]


async def _resolve_circuit_ids(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    step1_response: Any,
    llm_run_id: uuid.UUID | None,
    *,
    strict: bool = False,
) -> list[uuid.UUID]:
    if step1_response is not None:
        created_ids = getattr(step1_response, "created_circuit_ids", None)
        if created_ids:
            return _dedupe_uuid_list(list(created_ids))
        resp_json = getattr(step1_response, "__dict__", {})
        if isinstance(step1_response, dict):
            resp_json = step1_response
        for key in ("created_ids",):
            raw_ids = resp_json.get(key) if isinstance(resp_json, dict) else None
            if raw_ids:
                return _dedupe_uuid_list([uuid.UUID(str(i)) for i in raw_ids])
        created_targets = resp_json.get("created_targets") if isinstance(resp_json, dict) else None
        if isinstance(created_targets, list):
            circuit_ids: list[uuid.UUID] = []
            for group in created_targets:
                if isinstance(group, dict) and group.get("target_type") == "circuit":
                    circuit_ids.extend(uuid.UUID(str(i)) for i in (group.get("ids") or []) if i)
            if circuit_ids:
                return _dedupe_uuid_list(circuit_ids)

    if llm_run_id:
        scope = _scope_from_request(request)
        items, _ = await mirror_kg_service.list_mirror_circuits(
            session,
            resource_id=scope.resource_id,
            batch_id=scope.batch_id,
            source_atlas=scope.source_atlas,
            granularity_level=scope.granularity_level,
            granularity_family=scope.granularity_family,
            llm_run_id=llm_run_id,
            limit=10000,
            offset=0,
        )
        if items:
            return _dedupe_uuid_list([c.id for c in items])

    if strict:
        return []

    scope = _scope_from_request(request)
    items, _ = await mirror_kg_service.list_mirror_circuits(
        session,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        limit=10000,
        offset=0,
    )
    if items:
        return _dedupe_uuid_list([c.id for c in items])

    items, _ = await mirror_kg_service.list_mirror_circuits(
        session,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        limit=10000,
        offset=0,
    )
    return _dedupe_uuid_list([c.id for c in items])


async def _load_workflow_run_with_steps(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
) -> tuple[LlmCompositeWorkflowRun | None, list[LlmCompositeWorkflowStep]]:
    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        return None, []
    steps_q = (
        select(LlmCompositeWorkflowStep)
        .where(LlmCompositeWorkflowStep.workflow_run_id == run.id)
        .order_by(LlmCompositeWorkflowStep.step_order)
    )
    steps = list((await session.execute(steps_q)).scalars().all())
    return run, steps


async def _recover_unhandled_workflow_failure(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    exc: BaseException,
    *,
    commit: bool = True,
) -> CompositeWorkflowRunResponse:
    run, steps = await _load_workflow_run_with_steps(session, workflow_run_id)
    if run is None:
        logger.error(
            "[llm-composite-workflow][recover] run not found: %s",
            workflow_run_id,
        )
        return CompositeWorkflowRunResponse(
            workflow_run_id=workflow_run_id,
            workflow_type=CompositeWorkflowType.connection_with_function,
            status=CompositeWorkflowStatus.failed,
            dry_run=False,
            candidate_count=0,
            pair_count=0,
            steps=[],
            progress_percent=0.0,
            result_summary={},
            warnings=[],
            errors=[normalize_step_error(exc)],
        )

    msg = normalize_step_error(exc)
    run_errors = list(run.errors_json or [])
    if msg not in run_errors:
        run_errors.append(msg)
    run.errors_json = run_errors

    for step in steps:
        if step.status == CompositeStepStatus.running.value:
            step.status = CompositeStepStatus.failed.value
            step_errors = list(step.errors_json or [])
            if msg not in step_errors:
                step_errors.append(msg)
            step.errors_json = step_errors
            step.completed_at = _utcnow()
        elif step.status == CompositeStepStatus.pending.value:
            step.status = CompositeStepStatus.skipped.value
            skip_msg = "Workflow failed before this step could run."
            step.errors_json = list(step.errors_json or []) + [skip_msg]
            step.completed_at = _utcnow()

    run.status = CompositeWorkflowStatus.failed.value
    run.completed_at = _utcnow()
    run.result_summary_json = build_result_summary(run, steps)
    await session.flush()
    if commit:
        await session.commit()
        await session.refresh(run)
        for step in steps:
            await session.refresh(step)
    return _run_response(run, steps)


async def _dispatch_workflow_execution(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
    warnings: list[str],
    errors: list[str],
    *,
    commit_progress: bool = False,
) -> tuple[list[LlmCompositeWorkflowStep], list[str], list[str]]:
    if request.workflow_type == CompositeWorkflowType.connection_with_function:
        return await run_connection_with_function_workflow(
            session, request, run, steps, warnings, errors, commit_progress=commit_progress
        )
    if request.workflow_type == CompositeWorkflowType.circuit_with_function_steps:
        return await run_circuit_with_function_steps_workflow(
            session, request, run, steps, warnings, errors, commit_progress=commit_progress
        )
    if request.workflow_type == CompositeWorkflowType.triple_generation:
        return await run_triple_generation_workflow(
            session, request, run, steps, warnings, errors, commit_progress=commit_progress
        )
    errors.append(f"Unknown workflow type: {request.workflow_type}")
    run.status = CompositeWorkflowStatus.failed.value
    return steps, warnings, errors


async def prepare_composite_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
) -> tuple[LlmCompositeWorkflowRun, list[LlmCompositeWorkflowStep], list[str]]:
    """Create workflow run and pending steps (does not execute)."""
    request = normalize_composite_request(request)
    warnings = _collect_preflight_warnings(request)
    run = await create_workflow_run(session, request)
    step_defs = WORKFLOW_STEP_DEFS[request.workflow_type.value]
    steps: list[LlmCompositeWorkflowStep] = []
    for sd in step_defs:
        step = await create_workflow_step(
            session,
            workflow_run_id=run.id,
            step_order=sd["step_order"],
            step_key=sd["step_key"],
            step_label=sd["step_label"],
            dependency_step_key=sd.get("dependency_step_key"),
        )
        steps.append(step)
    return run, steps, warnings


async def run_connection_with_function_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    workflow_run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
    warnings: list[str],
    errors: list[str],
    *,
    commit_progress: bool = False,
) -> tuple[list[LlmCompositeWorkflowStep], list[str], list[str]]:
    async def _us(step: LlmCompositeWorkflowStep, **kwargs: Any) -> LlmCompositeWorkflowStep:
        return await update_workflow_step_status(
            session,
            step,
            commit_progress=commit_progress,
            **_sanitize_step_update_kwargs(kwargs),
        )

    step_map = {s.step_key: s for s in steps}
    conn_step = step_map["extract_connections"]
    fn_step = step_map["extract_projection_functions"]

    if len(request.candidate_ids) < 2:
        msg = f"Connection extraction requires at least 2 candidates; got {len(request.candidate_ids)}."
        errors.append(msg)
        await _us(
            conn_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_started=True,
            mark_completed=True,
        )
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped,
            errors=["Step 1 failed — skipping projection function extraction."],
            mark_completed=True,
        )
        return steps, warnings, errors

    conn_step = await _us(conn_step, status=CompositeStepStatus.running, mark_started=True)

    if is_cancelling(workflow_run.id):
        await _us(conn_step, status=CompositeStepStatus.cancelled, mark_completed=True)
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped,
            errors=["Workflow cancelled before connection extraction."],
            mark_completed=True,
        )
        return steps, warnings, errors

    async def _connection_progress(
        llm_run: LlmExtractionRun,
        audit: Any,
        progress_summary: dict[str, Any] | None = None,
    ) -> None:
        from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit
        from app.services.llm_connection_parse_diagnostics import (
            merge_provider_audit,
            validate_connection_progress_invariants,
        )

        summary = dict(
            progress_summary
            or (
                audit.to_dict() if isinstance(audit, ConnectionExecutionAudit) else dict(audit)
            )
        )
        provider_audit = merge_provider_audit(summary)
        summary["provider_audit"] = provider_audit
        summary["pack_summaries"] = provider_audit.get("pack_summaries") or summary.get("pack_summaries") or []
        invariant_errors = validate_connection_progress_invariants(summary)
        if invariant_errors:
            for err in invariant_errors:
                await safe_append_workflow_event(
                    session,
                    workflow_run.id,
                    step_key="extract_connections",
                    level="error",
                    event=err["code"],
                    message=err["message"],
                    data={"summary_keys": list(summary.keys())},
                    step=conn_step,
                    commit=commit_progress,
                )
            run_errors = list(workflow_run.errors_json or [])
            for err in invariant_errors:
                msg = f"{err['code']}: {err['message']}"
                if msg not in run_errors:
                    run_errors.append(msg)
            workflow_run.errors_json = run_errors
            flag_modified(workflow_run, "errors_json")

        resp = dict(conn_step.response_json or {})
        if conn_step.started_at:
            elapsed = (datetime.now(timezone.utc) - conn_step.started_at).total_seconds()
            if (
                elapsed >= 60
                and summary.get("pack_count", 0) > 0
                and summary.get("prompt_built_count", 0) == 0
                and summary.get("prompt_sent_count", 0) == 0
                and summary.get("provider_call_count", 0) == 0
                and not resp.get("scheduling_delayed_logged")
            ):
                await safe_append_workflow_event(
                    session,
                    workflow_run.id,
                    step_key="extract_connections",
                    level="warning",
                    event="provider_scheduling_delayed",
                    message=(
                        "Provider scheduling delayed: packs built but no prompts sent after 60s"
                    ),
                    data={
                        "elapsed_seconds": int(elapsed),
                        "pack_count": summary.get("pack_count", 0),
                        "prompt_built_count": summary.get("prompt_built_count", 0),
                        "provider_call_count": summary.get("provider_call_count", 0),
                    },
                    step=conn_step,
                    commit=commit_progress,
                )
                resp["scheduling_delayed_logged"] = True
        await _us(
            conn_step,
            status=CompositeStepStatus.running,
            llm_run_id=llm_run.id,
            response_json={
                **resp,
                "execution_summary": summary,
                "provider_audit": provider_audit,
                "pack_summaries": summary.get("pack_summaries", []),
                "provider_call_count": summary.get("provider_call_count", 0),
                "provider_success_count": summary.get("provider_success_count", 0),
                "parse_error_count": summary.get("parse_error_count", 0),
                "pack_count": summary.get("pack_count", 0),
                "status": "running",
            },
        )
        run_summary = dict(workflow_run.result_summary_json or {})
        run_summary.update({
            "provider_call_count": summary.get("provider_call_count", 0),
            "provider_success_count": summary.get("provider_success_count", 0),
            "provider_transport_error_count": summary.get("provider_transport_error_count", 0),
            "provider_empty_response_count": summary.get("provider_empty_response_count", 0),
            "parse_error_count": summary.get("parse_error_count", 0),
            "schema_error_count": summary.get("schema_error_count", 0),
            "failed_pack_count": summary.get("failed_pack_count", 0),
            "pack_count": summary.get("pack_count", 0),
            "processed_pack_count": summary.get("processed_pack_count", 0),
            "pack_summaries": summary.get("pack_summaries", []),
            "provider_audit": provider_audit,
            "fail_fast_triggered": summary.get("fail_fast_triggered"),
            "remaining_pack_count_skipped": summary.get("remaining_pack_count_skipped"),
            "fail_fast_reason": summary.get("fail_fast_reason"),
            "debug_mode": summary.get("debug_mode"),
            "debug_single_pack": summary.get("debug_single_pack"),
            "debug_max_packs": summary.get("debug_max_packs"),
            "planned_pack_count": summary.get("planned_pack_count"),
            "executed_pack_count": summary.get("executed_pack_count"),
            "skipped_debug_pack_count": summary.get("skipped_debug_pack_count"),
            "planned_model_call_count": summary.get("planned_model_call_count"),
        })
        run_summary = _merge_connection_provider_audit_into_summary(
            run_summary,
            conn_step=conn_step,
        )
        workflow_run.result_summary_json = run_summary
        flag_modified(workflow_run, "result_summary_json")
        if commit_progress:
            await session.commit()

    try:
        conn_body = build_connection_extraction_request(request)
        await safe_append_workflow_event(
            session,
            workflow_run.id,
            step_key="extract_connections",
            level="info",
            event="connection_extraction_debug_flags",
            message="Connection extraction debug flags",
            data={
                "debug_single_pack": conn_body.debug_single_pack,
                "debug_max_packs": conn_body.debug_max_packs,
            },
            step=conn_step,
            commit=commit_progress,
        )
        result = await invoke_connection_extraction(
            session,
            conn_body,
            composite_workflow_run_id=workflow_run.id,
            workflow_step_key="extract_connections",
            on_progress=_connection_progress,
            commit_progress=commit_progress,
        )
        if result.warnings:
            warnings.extend(result.warnings)
        conn_step_status = _connection_step_status(result)
        workflow_status_override, fn_skip_status = _connection_workflow_overrides(result)
        if result.unprocessed_pair_count > 0 and conn_step_status != CompositeStepStatus.failed:
            warnings.append(
                f"Connection extraction left {result.unprocessed_pair_count} pair(s) unprocessed."
            )
        step_errors: list[str] = []
        if conn_step_status == CompositeStepStatus.failed:
            step_errors = [
                w for w in (result.warnings or [])
                if "Provider was not called" in w or w.startswith("pack[")
            ] or [result.status or "Connection extraction failed"]
        await _us(
            conn_step,
            status=conn_step_status,
            llm_run_id=result.run_id,
            llm_item_id=result.item_id,
            response_json=_connection_step_response_json(result),
            created_counts=collect_step_counts(result),
            warnings=list(result.warnings or []),
            errors=step_errors,
            mark_completed=True,
        )
        step1_result = result
    except Exception as exc:
        logger.exception("[llm-composite-workflow][extract_connections] step failed")
        msg = normalize_step_error(exc)
        errors.append(msg)
        await _us(
            conn_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_completed=True,
        )
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped_dependency_failed,
            errors=["Step 1 (connection extraction) failed — skipping projection function extraction."],
            mark_completed=True,
        )
        return steps, warnings, errors

    if conn_step_status == CompositeStepStatus.failed:
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped_dependency_failed,
            errors=["Step 1 (connection extraction) failed — skipping projection function extraction."],
            mark_completed=True,
        )
        return steps, warnings, errors

    if conn_step_status == CompositeStepStatus.cancelled or is_cancelling(workflow_run.id):
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped,
            errors=["Workflow cancelled — skipping projection function extraction."],
            mark_completed=True,
        )
        if workflow_status_override:
            workflow_run.status = workflow_status_override
        return steps, warnings, errors

    fn_step = await _us(fn_step, status=CompositeStepStatus.running, mark_started=True)
    if not PROJECTION_TO_FUNCTIONS_ENABLED:
        warn = "projection_to_functions is not implemented; skipped."
        warnings.append(warn)
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped,
            warnings=[warn],
            mark_completed=True,
        )
        return steps, warnings, errors

    projection_ids = await _resolve_projection_ids(
        session, request, step1_result, step1_result.run_id
    )
    if not projection_ids:
        if fn_skip_status == CompositeStepStatus.skipped_no_projection:
            warn = (
                "Connection extraction completed with no projections; "
                "skipping projection function extraction."
            )
        else:
            warn = "No projection ids found after connection extraction."
        warnings.append(warn)
        await _us(
            fn_step,
            status=fn_skip_status or CompositeStepStatus.skipped_no_projection,
            warnings=[warn],
            response_json={
                "outcome": "skipped_no_projection",
                "display_status": "skipped_no_projection",
                "message": warn,
            },
            mark_completed=True,
        )
        if workflow_status_override:
            workflow_run.status = workflow_status_override
        return steps, warnings, errors

    try:
        proj_body = build_projection_to_functions_request(request, projection_ids)
        fn_result = await invoke_projection_to_functions_extraction(
            session,
            proj_body,
            composite_workflow_run_id=workflow_run.id,
            workflow_step_key="extract_projection_functions",
        )
        if fn_result.warnings:
            warnings.extend(fn_result.warnings)
        await _us(
            fn_step,
            status=CompositeStepStatus.succeeded,
            llm_run_id=fn_result.run_id,
            llm_item_id=fn_result.item_id,
            response_json=_response_to_json(fn_result),
            created_counts=collect_step_counts(fn_result),
            warnings=list(fn_result.warnings or []),
            mark_completed=True,
        )
    except Exception as exc:
        logger.exception("[llm-composite-workflow][extract_projection_functions] step failed")
        msg = normalize_step_error(exc)
        errors.append(msg)
        await _us(
            fn_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_completed=True,
        )

    return steps, warnings, errors


async def run_circuit_with_function_steps_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    workflow_run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
    warnings: list[str],
    errors: list[str],
    *,
    commit_progress: bool = False,
) -> tuple[list[LlmCompositeWorkflowStep], list[str], list[str]]:
    async def _us(step: LlmCompositeWorkflowStep, **kwargs: Any) -> LlmCompositeWorkflowStep:
        return await update_workflow_step_status(
            session,
            step,
            commit_progress=commit_progress,
            **_sanitize_step_update_kwargs(kwargs),
        )

    step_map = {s.step_key: s for s in steps}
    circuit_step = step_map["extract_circuits"]
    steps_step = step_map["extract_circuit_steps"]
    fn_step = step_map["extract_circuit_functions"]

    if len(request.candidate_ids) < 2:
        msg = f"Circuit extraction requires at least 2 candidates; got {len(request.candidate_ids)}."
        errors.append(msg)
        await _us(
            circuit_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_started=True,
            mark_completed=True,
        )
        for sk in ("extract_circuit_steps", "extract_circuit_functions"):
            await _us(
                step_map[sk],
                status=CompositeStepStatus.skipped,
                errors=["Step 1 failed — skipping dependent steps."],
                mark_completed=True,
            )
        return steps, warnings, errors

    circuit_step = await _us(
        circuit_step, status=CompositeStepStatus.running, mark_started=True
    )

    # ── Batch circuit extraction ─────────────────────────────────────────
    CIRCUIT_BATCH_SIZE = 20
    all_candidate_ids = list(request.candidate_ids)
    batches: list[list[uuid.UUID]] = []
    for i in range(0, len(all_candidate_ids), CIRCUIT_BATCH_SIZE):
        batches.append(all_candidate_ids[i:i + CIRCUIT_BATCH_SIZE])

    all_circuit_ids: list[uuid.UUID] = []
    batch_warnings: list[str] = []
    batch_errors: list[str] = []
    total_circuits_created = 0
    first_run_id: uuid.UUID | None = None
    first_item_id: uuid.UUID | None = None

    for bi, batch_ids in enumerate(batches):
        if batch_errors:
            break  # Stop on first failing batch (circuit extraction is critical)
        try:
            batch_max_tokens = max(5000, min(8192, len(batch_ids) * 200))
            batch_max_circuits = getattr(request, 'max_circuits', None) or 100
            batch_temperature = getattr(request, 'temperature', None) or 0.2
            batch_request = SameGranularityCircuitExtractionRequest(
                provider=request.provider,
                model_name=request.model_name,
                candidate_ids=batch_ids,
                scope=_circuit_scope_from_composite(request),
                dry_run=request.dry_run,
                create_mirror_records=request.create_mirror_records,
                create_triples=request.create_triples,
                create_evidence=request.create_evidence,
                max_circuits=batch_max_circuits,
                temperature=batch_temperature,
                max_tokens=batch_max_tokens,
            )
            batch_result = await invoke_circuit_extraction(session, batch_request)
            if batch_result.warnings:
                batch_warnings.extend(batch_result.warnings)
            if first_run_id is None:
                first_run_id = batch_result.run_id
                first_item_id = batch_result.item_id
            batch_cids = await _resolve_circuit_ids(
                session, request, batch_result, batch_result.run_id, strict=False
            )
            all_circuit_ids.extend(batch_cids)
            total_circuits_created += len(batch_cids)
            # Update step progress
            await _us(
                circuit_step,
                status=CompositeStepStatus.running,
                created_counts={"circuits": total_circuits_created, "batch": bi + 1, "total_batches": len(batches)},
                warnings=list(batch_warnings),
            )
        except Exception as exc:
            logger.exception("[llm-composite-workflow][extract_circuits] batch %s failed", bi)
            batch_errors.append(f"batch {bi}: {normalize_step_error(exc)}")

    # Deduplicate circuit IDs
    all_circuit_ids = list(dict.fromkeys(all_circuit_ids))

    if batch_errors and total_circuits_created == 0:
        errors.extend(batch_errors)
        await _us(circuit_step, status=CompositeStepStatus.failed, errors=batch_errors, mark_completed=True)
        for sk in ("extract_circuit_steps", "extract_circuit_functions"):
            await _us(step_map[sk], status=CompositeStepStatus.skipped,
                       errors=["Step 1 (circuit extraction) failed — skipping dependent steps."], mark_completed=True)
        return steps, warnings, errors

    warnings.extend(batch_warnings)
    if batch_errors:
        warnings.extend(batch_errors)
    await _us(
        circuit_step,
        status=CompositeStepStatus.succeeded,
        llm_run_id=first_run_id,
        llm_item_id=first_item_id,
        created_counts={"circuits": total_circuits_created, "batches_processed": len(batches)},
        warnings=batch_warnings,
        errors=batch_errors,
        mark_completed=True,
    )
    circuit_ids = all_circuit_ids
    _attach_circuit_ids_to_step_response(circuit_step, circuit_ids)
    steps_step = await _us(
        steps_step, status=CompositeStepStatus.running, mark_started=True
    )
    if not circuit_ids:
        warn = "No circuit ids found after circuit extraction."
        warnings.append(warn)
        await _us(
            steps_step,
            status=CompositeStepStatus.skipped,
            warnings=[warn],
            mark_completed=True,
        )
    else:
        total_steps_created = 0
        step_warnings: list[str] = []
        step_errors: list[str] = []
        for circuit_id in circuit_ids:
            try:
                cs_body = build_circuit_to_steps_request(request, circuit_id)
                cs_result = await invoke_circuit_to_steps_extraction(session, cs_body)
                total_steps_created += cs_result.mirror_step_created_count or 0
                if cs_result.warnings:
                    step_warnings.extend(cs_result.warnings)
            except Exception as exc:
                logger.exception(
                    "[llm-composite-workflow][extract_circuit_steps] circuit %s failed",
                    circuit_id,
                )
                step_errors.append(f"circuit {circuit_id}: {normalize_step_error(exc)}")

        if step_errors and total_steps_created == 0:
            errors.extend(step_errors)
            await _us(
                steps_step,
                status=CompositeStepStatus.failed,
                created_counts={"circuit_steps": 0},
                warnings=step_warnings,
                errors=step_errors,
                mark_completed=True,
            )
        else:
            if step_errors:
                warnings.extend(step_errors)
            warnings.extend(step_warnings)
            await _us(
                steps_step,
                status=CompositeStepStatus.succeeded,
                created_counts={"circuit_steps": total_steps_created},
                warnings=step_warnings,
                errors=step_errors,
                mark_completed=True,
            )

    fn_step = await _us(
        fn_step, status=CompositeStepStatus.running, mark_started=True
    )
    if not CIRCUIT_TO_FUNCTIONS_ENABLED:
        warn = "circuit_to_functions is not implemented; skipped."
        warnings.append(warn)
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped,
            warnings=[warn],
            mark_completed=True,
        )
        return steps, warnings, errors

    if not circuit_ids:
        warn = "No circuit ids found after circuit extraction — skipping circuit_to_functions."
        warnings.append(warn)
        await _us(
            fn_step,
            status=CompositeStepStatus.skipped,
            warnings=[warn],
            mark_completed=True,
        )
        return steps, warnings, errors

    try:
        fn_body = build_circuit_to_functions_request(request, circuit_ids)
        fn_result = await invoke_circuit_to_functions_extraction(session, fn_body)
        fn_warnings = list(fn_result.warnings or [])
        fn_errors: list[str] = []
        if request.dry_run:
            fn_warnings.append(
                "dry_run=true — circuit functions were not written to mirror_circuit_functions."
            )
        if fn_result.skipped_count and not fn_result.created_count and not fn_result.failed_count:
            fn_warnings.append("No function signal found for some or all circuits.")
        if fn_result.errors:
            for err in fn_result.errors:
                if isinstance(err, dict):
                    fn_errors.append(str(err.get("message") or err))
                else:
                    fn_errors.append(str(err))
        if fn_result.failed_count:
            warnings.extend(fn_errors or [f"circuit_to_functions failed for {fn_result.failed_count} circuit(s)."])

        step_response = build_circuit_to_functions_step_response(
            fn_result,
            circuit_ids=circuit_ids,
            dry_run=request.dry_run,
        )
        if fn_result.failed_count and not fn_result.created_count and not fn_result.updated_count:
            step_status = CompositeStepStatus.failed
            errors.extend(fn_errors or ["circuit_to_functions extraction failed."])
        elif fn_result.failed_count:
            step_status = CompositeStepStatus.succeeded
        elif fn_result.created_count or fn_result.updated_count or request.dry_run:
            step_status = CompositeStepStatus.succeeded
        elif fn_result.skipped_count:
            step_status = CompositeStepStatus.skipped
        else:
            step_status = CompositeStepStatus.skipped
            fn_warnings.append("No mirror_circuit_functions created.")

        warnings.extend(fn_warnings)
        await _us(
            fn_step,
            status=step_status,
            response_json=step_response,
            created_counts=collect_step_counts(fn_result),
            warnings=fn_warnings,
            errors=fn_errors,
            mark_completed=True,
        )
    except circuit_fn_svc.MirrorCircuitFunctionsTableMissingError as exc:
        logger.exception("[llm-composite-workflow][extract_circuit_functions] table missing")
        msg = (
            "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED: mirror_circuit_functions table is not "
            "initialized. Please run backend/migrations/033_mirror_circuit_functions.sql."
        )
        errors.append(msg)
        await _us(
            fn_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            warnings=[str(exc)],
            mark_completed=True,
        )
    except Exception as exc:
        logger.exception("[llm-composite-workflow][extract_circuit_functions] step failed")
        msg = normalize_step_error(exc)
        errors.append(msg)
        await _us(
            fn_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_completed=True,
        )

    return steps, warnings, errors


async def run_triple_generation_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    workflow_run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
    warnings: list[str],
    errors: list[str],
    *,
    commit_progress: bool = False,
) -> tuple[list[LlmCompositeWorkflowStep], list[str], list[str]]:
    async def _us(step: LlmCompositeWorkflowStep, **kwargs: Any) -> LlmCompositeWorkflowStep:
        return await update_workflow_step_status(
            session,
            step,
            commit_progress=commit_progress,
            **_sanitize_step_update_kwargs(kwargs),
        )

    triple_step = steps[0]
    scope = _consolidation_scope_from_request(request)
    mirror_counts = await _count_mirror_objects_in_scope(session, scope)
    if sum(mirror_counts.values()) == 0:
        msg = "No Mirror objects available for triple generation."
        errors.append(msg)
        await _us(
            triple_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_started=True,
            mark_completed=True,
        )
        return steps, warnings, errors

    triple_step = await _us(triple_step, status=CompositeStepStatus.running, mark_started=True)
    try:
        result = await consolidate_mirror_triples(
            session,
            source_types=["connection", "function", "circuit"],
            scope=scope,
            dry_run=request.dry_run,
            limit=10000,
        )
        if result.warnings:
            warnings.extend(result.warnings)
        await _us(
            triple_step,
            status=CompositeStepStatus.succeeded,
            response_json=_response_to_json(result),
            created_counts=collect_step_counts(result),
            warnings=list(result.warnings or []),
            mark_completed=True,
        )
    except Exception as exc:
        logger.exception("[llm-composite-workflow][generate_triples] step failed")
        msg = normalize_step_error(exc)
        errors.append(msg)
        await _us(
            triple_step,
            status=CompositeStepStatus.failed,
            errors=[msg],
            mark_completed=True,
        )

    return steps, warnings, errors


async def _execute_composite_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    run: LlmCompositeWorkflowRun,
    steps: list[LlmCompositeWorkflowStep],
    warnings: list[str],
    *,
    commit_progress: bool = False,
) -> CompositeWorkflowRunResponse:
    errors: list[str] = []
    run.status = CompositeWorkflowStatus.running.value
    await session.flush()
    await safe_append_workflow_event(
        session,
        run.id,
        step_key=None,
        level="info",
        event="workflow_started",
        message=f"Composite workflow started ({run.workflow_type})",
        data={
            "candidate_count": run.candidate_count,
            "pair_count": run.pair_count,
            "dry_run": run.dry_run,
            "provider": run.provider,
        },
        commit=False,
    )
    await safe_append_workflow_event(
        session,
        run.id,
        step_key=None,
        level="info",
        event="composite_workflow_request_received",
        message="Composite workflow request received",
        data={
            "debug_single_pack": bool(request.debug_single_pack),
            "debug_max_packs": request.debug_max_packs,
            "candidate_count": run.candidate_count,
            "workflow_type": run.workflow_type,
            "dry_run": run.dry_run,
        },
        commit=False,
    )
    if commit_progress:
        await session.commit()

    try:
        steps, warnings, errors = await _dispatch_workflow_execution(
            session,
            request,
            run,
            steps,
            warnings,
            errors,
            commit_progress=commit_progress,
        )
    except Exception as exc:
        logger.exception(
            "[llm-composite-workflow][execute] unhandled failure run_id=%s",
            run.id,
        )
        await session.rollback()
        return await _recover_unhandled_workflow_failure(session, run.id, exc, commit=True)

    await session.refresh(run)
    if run.status in {
        CompositeWorkflowStatus.cancelling.value,
        CompositeWorkflowStatus.cancelled.value,
        CompositeWorkflowStatus.cleanup_in_progress.value,
        CompositeWorkflowStatus.cleanup_done.value,
        CompositeWorkflowStatus.cleanup_failed.value,
    }:
        return _run_response(run, steps)

    await finalize_workflow_run(session, run, steps, warnings=warnings, errors=errors)
    await session.commit()
    await session.refresh(run)
    for step in steps:
        await session.refresh(step)
    return _run_response(run, steps)


async def run_composite_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
) -> CompositeWorkflowRunResponse:
    request = normalize_composite_request(request)
    run_id: uuid.UUID | None = None
    try:
        run, steps, warnings = await prepare_composite_workflow(session, request)
        run_id = run.id
        await session.commit()
        await session.refresh(run)
        for step in steps:
            await session.refresh(step)
        return await _execute_composite_workflow(
            session, request, run, steps, warnings, commit_progress=False
        )
    except Exception as exc:
        logger.exception("[llm-composite-workflow][run] unhandled failure run_id=%s", run_id)
        await session.rollback()
        if run_id is not None:
            return await _recover_unhandled_workflow_failure(session, run_id, exc, commit=True)
        raise CompositeWorkflowHandledError(
            CompositeWorkflowRunResponse(
                workflow_run_id=uuid.uuid4(),
                workflow_type=request.workflow_type,
                status=CompositeWorkflowStatus.failed,
                dry_run=request.dry_run,
                candidate_count=len(request.candidate_ids),
                pair_count=compute_pair_count(request.candidate_ids),
                steps=[],
                progress_percent=0.0,
                result_summary={},
                warnings=[],
                errors=[normalize_step_error(exc)],
            )
        ) from exc


async def start_composite_workflow(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
) -> CompositeWorkflowRunResponse:
    """Create workflow run + pending steps and return immediately (202 path)."""
    request = normalize_composite_request(request)
    run, steps, warnings = await prepare_composite_workflow(session, request)
    run.status = CompositeWorkflowStatus.pending.value
    run.warnings_json = warnings
    await session.commit()
    await session.refresh(run)
    for step in steps:
        await session.refresh(step)
    return _run_response(run, steps)


async def execute_composite_workflow_background(
    workflow_run_id: uuid.UUID,
    request_payload: dict[str, Any],
) -> None:
    """Background worker — uses a fresh DB session (not the request session)."""
    from app.database import AsyncSessionLocal

    if AsyncSessionLocal is None:
        logger.error("[llm-composite-workflow][background] AsyncSessionLocal unavailable")
        return

    request = normalize_composite_request(CompositeWorkflowRunRequest.model_validate(request_payload))
    async with AsyncSessionLocal() as session:
        try:
            run, steps = await _load_workflow_run_with_steps(session, workflow_run_id)
            if run is None:
                logger.error(
                    "[llm-composite-workflow][background] run not found: %s",
                    workflow_run_id,
                )
                return
            warnings = list(run.warnings_json or [])
            await _execute_composite_workflow(
                session,
                request,
                run,
                steps,
                warnings,
                commit_progress=True,
            )
        except Exception as exc:
            logger.exception(
                "[llm-composite-workflow][background] unhandled failure run_id=%s",
                workflow_run_id,
            )
            try:
                await session.rollback()
                await _recover_unhandled_workflow_failure(
                    session, workflow_run_id, exc, commit=True
                )
            except Exception:
                logger.exception(
                    "[llm-composite-workflow][background] recovery failed run_id=%s",
                    workflow_run_id,
                )


def _run_read(run: LlmCompositeWorkflowRun, steps: list[LlmCompositeWorkflowStep]) -> CompositeWorkflowRunRead:
    summary = dict(run.result_summary_json or {})
    conn_step = next((s for s in steps if s.step_key == "extract_connections"), None)
    summary = _merge_connection_provider_audit_into_summary(
        summary,
        existing_summary=summary,
        conn_step=conn_step,
    )
    semantic = _workflow_semantic_fields(summary)
    provider_audit = dict(summary.get("provider_audit") or {})
    diagnostics = list(summary.get("diagnostics") or [])
    return CompositeWorkflowRunRead(
        id=run.id,
        workflow_type=CompositeWorkflowType(run.workflow_type),
        status=CompositeWorkflowStatus(run.status),
        provider=run.provider,
        model_name=run.model_name,
        dry_run=run.dry_run,
        resource_id=run.resource_id,
        batch_id=run.batch_id,
        source_atlas=run.source_atlas,
        source_version=run.source_version,
        granularity_level=run.granularity_level,
        granularity_family=run.granularity_family,
        candidate_count=run.candidate_count,
        pair_count=run.pair_count,
        progress_percent=compute_progress_percent(steps),
        result_summary=summary,
        provider_audit=provider_audit,
        diagnostics=diagnostics,
        outcome=semantic["outcome"],
        display_status=semantic["display_status"],
        semantic_status=semantic["semantic_status"],
        recent_events=get_recent_events(summary),
        warnings=list(run.warnings_json or []),
        errors=list(run.errors_json or []),
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[_step_read(s) for s in sorted(steps, key=lambda s: s.step_order)],
    )


async def list_composite_workflow_runs(
    session: AsyncSession,
    *,
    workflow_type: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CompositeWorkflowRunRead], int]:
    base = select(LlmCompositeWorkflowRun)
    if workflow_type:
        base = base.where(LlmCompositeWorkflowRun.workflow_type == workflow_type)
    if status:
        base = base.where(LlmCompositeWorkflowRun.status == status)
    if provider:
        base = base.where(LlmCompositeWorkflowRun.provider == provider)
    if batch_id:
        base = base.where(LlmCompositeWorkflowRun.batch_id == batch_id)
    if resource_id:
        base = base.where(LlmCompositeWorkflowRun.resource_id == resource_id)
    if source_atlas:
        base = base.where(LlmCompositeWorkflowRun.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(LlmCompositeWorkflowRun.granularity_level == granularity_level)

    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = base.order_by(LlmCompositeWorkflowRun.created_at.desc()).limit(limit).offset(offset)
    runs = list((await session.execute(q)).scalars().all())

    items: list[CompositeWorkflowRunRead] = []
    for run in runs:
        steps_q = (
            select(LlmCompositeWorkflowStep)
            .where(LlmCompositeWorkflowStep.workflow_run_id == run.id)
            .order_by(LlmCompositeWorkflowStep.step_order)
        )
        steps = list((await session.execute(steps_q)).scalars().all())
        items.append(_run_read(run, steps))
    return items, total


async def get_composite_workflow_run(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
) -> CompositeWorkflowRunRead | None:
    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        return None
    steps_q = (
        select(LlmCompositeWorkflowStep)
        .where(LlmCompositeWorkflowStep.workflow_run_id == run.id)
        .order_by(LlmCompositeWorkflowStep.step_order)
    )
    steps = list((await session.execute(steps_q)).scalars().all())
    return _run_read(run, steps)


async def list_composite_workflow_steps(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
) -> list[CompositeWorkflowStepRead]:
    q = (
        select(LlmCompositeWorkflowStep)
        .where(LlmCompositeWorkflowStep.workflow_run_id == workflow_run_id)
        .order_by(LlmCompositeWorkflowStep.step_order)
    )
    steps = list((await session.execute(q)).scalars().all())
    return [_step_read(s) for s in steps]


def _collect_pack_summaries_from_sources(
    *,
    step_response: dict[str, Any] | None = None,
    run_summary: dict[str, Any] | None = None,
    llm_run_scope: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(items: Any) -> None:
        if not isinstance(items, list):
            return
        for pack in items:
            if not isinstance(pack, dict):
                continue
            key = str(pack.get("pack_id", id(pack)))
            if key in seen:
                continue
            seen.add(key)
            packs.append(pack)

    if step_response:
        _add(step_response.get("pack_summaries"))
        execution_summary = step_response.get("execution_summary") or {}
        _add(execution_summary.get("pack_summaries"))
        provider_audit = step_response.get("provider_audit") or execution_summary.get("provider_audit") or {}
        _add(provider_audit.get("pack_summaries"))
    if run_summary:
        _add(run_summary.get("pack_summaries"))
        provider_audit = run_summary.get("provider_audit") or {}
        _add(provider_audit.get("pack_summaries"))
    if llm_run_scope:
        execution_summary = llm_run_scope.get("execution_summary") or {}
        _add(execution_summary.get("pack_summaries"))
        provider_audit = execution_summary.get("provider_audit") or {}
        _add(provider_audit.get("pack_summaries"))
    return packs


async def get_composite_workflow_raw_responses_debug(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
):
    from app.models.llm_extraction import LlmExtractionRun
    from app.schemas.llm_composite_workflow import (
        CompositeWorkflowRawResponseItem,
        CompositeWorkflowRawResponsesDebugResponse,
    )
    from app.services.llm_connection_parse_diagnostics import INVARIANT_PACK_SUMMARIES_MISSING

    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        return None

    steps_q = (
        select(LlmCompositeWorkflowStep)
        .where(LlmCompositeWorkflowStep.workflow_run_id == workflow_run_id)
        .order_by(LlmCompositeWorkflowStep.step_order)
    )
    steps = list((await session.execute(steps_q)).scalars().all())
    run_summary = dict(run.result_summary_json or {})
    items: list[CompositeWorkflowRawResponseItem] = []
    parse_error_count = int(run_summary.get("parse_error_count") or 0)

    for step in steps:
        if step.step_key != "extract_connections":
            continue
        resp = dict(step.response_json or {})
        llm_scope: dict[str, Any] = {}
        if step.llm_run_id:
            llm_run = await session.get(LlmExtractionRun, step.llm_run_id)
            if llm_run and llm_run.scope_json:
                llm_scope = dict(llm_run.scope_json)
        execution_summary = resp.get("execution_summary") or {}
        parse_error_count = max(
            parse_error_count,
            int(resp.get("parse_error_count") or execution_summary.get("parse_error_count") or 0),
        )
        pack_summaries = _collect_pack_summaries_from_sources(
            step_response=resp,
            run_summary=run_summary,
            llm_run_scope=llm_scope,
        )
        for pack in pack_summaries:
            items.append(
                CompositeWorkflowRawResponseItem(
                    step_key=step.step_key,
                    pack_id=pack.get("pack_id"),
                    status=pack.get("status"),
                    response_char_count=int(pack.get("response_char_count") or 0),
                    raw_response_preview=pack.get("raw_response_preview"),
                    parse_error=pack.get("parse_error"),
                    parse_error_type=pack.get("parse_error_type"),
                )
            )

    diagnostic_error = None
    if parse_error_count > 0 and not items:
        diagnostic_error = INVARIANT_PACK_SUMMARIES_MISSING

    return CompositeWorkflowRawResponsesDebugResponse(
        workflow_run_id=workflow_run_id,
        items=items,
        diagnostic_error=diagnostic_error,
    )


async def cancel_composite_workflow(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    cleanup: bool = True,
    reason: str = "user_closed_modal",
) -> CompositeWorkflowCancelResponse:
    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        raise KeyError("Composite workflow run not found")

    # Idempotency: a workflow that already reached a terminal cleanup/cancel state
    # should not be cleaned up again. Return its current state so repeated cancel
    # calls (e.g. from polling + manual close) never raise or double-delete.
    already_done = {
        CompositeWorkflowStatus.cleanup_done.value,
        CompositeWorkflowStatus.cleanup_failed.value,
        CompositeWorkflowStatus.cancelled.value,
    }
    if run.status in already_done:
        summary = run.result_summary_json or {}
        await clear_cancel_registry(workflow_run_id)
        return CompositeWorkflowCancelResponse(
            workflow_run_id=workflow_run_id,
            status=CompositeWorkflowStatus(run.status),
            cleanup=cleanup,
            deleted=summary.get("deleted", {}),
            warnings=summary.get("cleanup_warnings", []),
            errors=summary.get("cleanup_errors", []),
        )

    steps = list(
        (
            await session.execute(
                select(LlmCompositeWorkflowStep).where(
                    LlmCompositeWorkflowStep.workflow_run_id == workflow_run_id
                )
            )
        )
        .scalars()
        .all()
    )

    await mark_cancelling(workflow_run_id)
    await cancel_tasks(workflow_run_id)

    terminal = {
        CompositeWorkflowStatus.cleanup_done.value,
        CompositeWorkflowStatus.cancelled.value,
    }
    if run.status not in terminal:
        run.status = CompositeWorkflowStatus.cancelling.value
        await session.flush()
        await session.commit()

    deleted: dict[str, int] = {}
    warnings: list[str] = []
    errors: list[str] = []
    final_status = CompositeWorkflowStatus.cancelled

    if cleanup:
        run.status = CompositeWorkflowStatus.cleanup_in_progress.value
        await session.flush()
        deleted, cleanup_warnings, cleanup_errors = await cleanup_composite_workflow_artifacts(
            session, workflow_run_id, steps=steps
        )
        warnings.extend(cleanup_warnings)
        errors.extend(cleanup_errors)
        cancel_meta = {
            "provider_calls_before_cancel": (run.result_summary_json or {}).get("provider_call_count", 0),
            "cancel_reason": reason,
        }
        if errors:
            final_status = CompositeWorkflowStatus.cleanup_failed
        else:
            final_status = CompositeWorkflowStatus.cleanup_done
        await mark_workflow_cleanup_summary(
            session,
            run,
            deleted=deleted,
            cancel_reason=reason,
            cancel_meta=cancel_meta,
            warnings=warnings,
            errors=errors,
            final_status=final_status,
        )
    else:
        run.status = CompositeWorkflowStatus.cancelled.value
        run.completed_at = _utcnow()
        summary = dict(run.result_summary_json or {})
        summary.update({
            "cancelled": True,
            "cancelled_at": _utcnow().isoformat(),
            "cancelled_by": "user",
            "cancel_reason": reason,
        })
        run.result_summary_json = summary
        for step in steps:
            if step.status in {CompositeStepStatus.running.value, CompositeStepStatus.pending.value}:
                step.status = CompositeStepStatus.cancelled.value
                step.completed_at = _utcnow()

    await session.commit()
    await clear_cancel_registry(workflow_run_id)

    return CompositeWorkflowCancelResponse(
        workflow_run_id=workflow_run_id,
        status=final_status,
        cleanup=cleanup,
        deleted=deleted,
        warnings=warnings,
        errors=errors,
    )

async def pause_composite_workflow(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    reason: str = "user_paused",
) -> CompositeWorkflowCancelResponse:
    """Pause a running composite workflow. Processing stops after the current pack."""
    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        raise KeyError("Composite workflow run not found")

    if run.status in (CompositeWorkflowStatus.succeeded.value, CompositeWorkflowStatus.failed.value,
                      CompositeWorkflowStatus.cancelled.value, CompositeWorkflowStatus.cleanup_done.value,
                      CompositeWorkflowStatus.paused.value):
        return CompositeWorkflowCancelResponse(
            workflow_run_id=workflow_run_id,
            status=CompositeWorkflowStatus(run.status),
            cleanup=False,
            deleted={},
            warnings=[f"Workflow already in state: {run.status}"],
            errors=[],
        )

    await mark_cancelling(workflow_run_id)
    run.status = CompositeWorkflowStatus.paused.value
    run.result_summary_json = {
        **(run.result_summary_json or {}),
        "pause_reason": reason,
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }
    await session.flush()
    await session.commit()
    return CompositeWorkflowCancelResponse(
        workflow_run_id=workflow_run_id,
        status=CompositeWorkflowStatus.paused,
        cleanup=False,
        deleted={},
        warnings=[],
        errors=[],
    )


