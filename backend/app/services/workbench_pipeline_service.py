"""Workbench Pipeline aggregation service — strictly read-only.

Assembles a complete pipeline overview for one import batch by composing
existing service calls. No writes to any table; no state changes; no LLM.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_macro96 import RawMacro96RegionRow
from app.models.rule_validation import CandidateRuleValidationResult

from app.schemas.candidate import (
    CandidateBrainRegionRead,
    CandidateGenerationRunRead,
)
from app.schemas.import_batch import (
    ImportBatchEventRead,
    ImportBatchRead,
    ImportBatchStatus,
)
from app.schemas.raw_parsing import RawAal3RegionLabelRead, RawParseRunRead
from app.schemas.rule_validation import RuleValidationRunRead
from app.schemas.workbench_pipeline import (
    BoundFilePipelineRead,
    ImportBatchPipelineOverview,
    LatestValidationSummary,
    PipelineAction,
)
from app.services import (
    candidate_service,
    file_normalization_service,
    import_batch_service,
    raw_parsing_service,
    rule_validation_service,
)

_RAW_LABELS_PREVIEW_LIMIT = 20
_CANDIDATES_PREVIEW_LIMIT = 20
_VALIDATION_RUNS_LIMIT = 10
_EVENTS_LIMIT = 20


_MACRO96_PARSER_KEYS = frozenset({"macro96_xlsx", "macro_96_excel"})


def compute_next_allowed_actions(
    status: str,
    *,
    parser_key: str | None = None,
    parse_enabled: bool | None = None,
    parse_disable_reason: str | None = None,
    raw_row_count: int = 0,
    candidate_count: int = 0,
    validation_result_count: int = 0,
) -> list[PipelineAction]:
    """Return advisory next actions based on batch.status and bound-file readiness.

    This is a pure function — no DB access, no side effects.
    Prohibited: submit_review, approve, promote, llm_extract.
    """
    is_macro96 = (parser_key or "").lower() in _MACRO96_PARSER_KEYS

    if status == ImportBatchStatus.running.value:
        if raw_row_count > 0:
            parse_enabled_final = False
            parse_reason = "Active raw rows already exist for this batch"
        elif parse_enabled is False:
            parse_enabled_final = False
            parse_reason = parse_disable_reason
        else:
            parse_enabled_final = True
            parse_reason = None
        if is_macro96:
            parse_action = PipelineAction(
                action="parse_macro96",
                label="Parse Macro96",
                enabled=parse_enabled_final,
                reason=parse_reason,
            )
        else:
            parse_action = PipelineAction(
                action="parse_aal3",
                label="Parse AAL3",
                enabled=parse_enabled_final,
                reason=parse_reason,
            )
        return [parse_action]

    mapping: dict[str, PipelineAction] = {
        ImportBatchStatus.created.value: PipelineAction(
            action="queue_batch",
            label="Queue Batch",
            enabled=True,
            reason=None,
        ),
        ImportBatchStatus.queued.value: PipelineAction(
            action="start_batch",
            label="Start Batch",
            enabled=True,
            reason=None,
        ),
        ImportBatchStatus.parsed.value: PipelineAction(
            action="generate_macro96_candidates" if is_macro96 else "generate_candidates",
            label="Generate Macro96 Candidates" if is_macro96 else "Generate Candidates",
            enabled=candidate_count == 0 and raw_row_count > 0,
            reason=(
                "Active candidates already exist for this batch"
                if candidate_count > 0
                else ("No raw rows available; parse first" if raw_row_count == 0 else None)
            ),
        ),
        ImportBatchStatus.candidate_generated.value: PipelineAction(
            action="validate_batch",
            label="Validate Batch",
            enabled=validation_result_count == 0 and candidate_count > 0,
            reason=(
                "Active validation results already exist for this batch"
                if validation_result_count > 0
                else ("No candidates available" if candidate_count == 0 else None)
            ),
        ),
    }
    action = mapping.get(status)
    return [action] if action else []


async def get_batch_pipeline_overview(
    session: AsyncSession,
    batch_id: uuid.UUID,
) -> ImportBatchPipelineOverview:
    """Assemble a complete pipeline overview for one batch. Read-only."""
    batch = await import_batch_service.get_batch(session, batch_id)

    # Bound files
    raw_files = await import_batch_service.list_batch_files(session, batch_id)
    file_map = await import_batch_service.load_resource_files_for_bindings(
        session, raw_files
    )
    bound_files: list[BoundFilePipelineRead] = []
    intermediate_by_file_id: dict[uuid.UUID, object] = {}
    for binding in raw_files:
        resource_file = file_map.get(binding.file_id)
        intermediate_summary: dict = {}
        intermediate_artifact = None
        if resource_file is not None:
            intermediate_artifact = await file_normalization_service.get_latest_active_artifact(
                session, resource_file.id
            )
            intermediate_by_file_id[binding.file_id] = intermediate_artifact
            intermediate_summary = await file_normalization_service.get_intermediate_summary_for_file(
                session, resource_file.id
            )
        bound_files.append(
            _build_bound_file_pipeline_read(
                binding, resource_file, intermediate_summary, intermediate_artifact
            )
        )

    if (batch.parser_key or "").lower() in _MACRO96_PARSER_KEYS:
        parse_enabled, parse_disable_reason = raw_parsing_service.evaluate_macro96_parse_readiness(
            raw_files, file_map, intermediate_by_file_id=intermediate_by_file_id
        )
    else:
        parse_enabled, parse_disable_reason = raw_parsing_service.evaluate_batch_parse_readiness(
            raw_files, file_map, intermediate_by_file_id=intermediate_by_file_id
        )

    # Events (recent 20)
    raw_events, _ = await import_batch_service.list_batch_events(
        session, batch_id, limit=_EVENTS_LIMIT, offset=0
    )
    events = [ImportBatchEventRead.model_validate(e) for e in raw_events]

    # Parse runs
    raw_parse_runs = await raw_parsing_service.list_parse_runs_for_batch(
        session, batch_id
    )
    parse_runs = [
        RawParseRunRead.model_validate(
            raw_parsing_service.parse_run_to_read(r)
        )
        for r in raw_parse_runs
    ]

    # Raw labels — count + preview
    raw_labels_preview_rows, raw_label_count = await raw_parsing_service.list_aal3_labels(
        session,
        batch_id=batch_id,
        limit=_RAW_LABELS_PREVIEW_LIMIT,
        offset=0,
    )
    raw_labels_preview = [
        RawAal3RegionLabelRead.model_validate(r) for r in raw_labels_preview_rows
    ]

    # Candidate generation runs
    raw_gen_runs = await candidate_service.list_generation_runs_for_batch(
        session, batch_id
    )
    generation_runs = [CandidateGenerationRunRead.model_validate(r) for r in raw_gen_runs]

    # Candidates — count + preview + status breakdown
    candidate_preview_rows, candidate_count = await candidate_service.list_candidate_regions(
        session,
        batch_id=batch_id,
        limit=_CANDIDATES_PREVIEW_LIMIT,
        offset=0,
    )
    candidates_preview = [
        CandidateBrainRegionRead.model_validate(r) for r in candidate_preview_rows
    ]

    _, by_status_pairs = await candidate_service.candidate_status_summary(
        session, batch_id=batch_id
    )
    candidate_status_counts: dict[str, int] = {s: c for s, c in by_status_pairs}

    # Rule validation runs (recent 10)
    raw_val_runs, _ = await rule_validation_service.list_validation_runs(
        session,
        batch_id=batch_id,
        limit=_VALIDATION_RUNS_LIMIT,
        offset=0,
    )
    validation_runs = [RuleValidationRunRead.model_validate(r) for r in raw_val_runs]

    # Latest validation summary from most recent succeeded run
    latest_validation_summary: LatestValidationSummary | None = None
    for run in raw_val_runs:
        if run.status == "succeeded":
            latest_validation_summary = LatestValidationSummary(
                passed_count=run.passed_count,
                failed_count=run.failed_count,
                warning_count=run.warning_count,
            )
            break

    is_macro96_batch = (batch.parser_key or "").lower() in _MACRO96_PARSER_KEYS
    if is_macro96_batch:
        raw_row_count_q = (
            select(func.count())
            .select_from(RawMacro96RegionRow)
            .where(RawMacro96RegionRow.batch_id == batch_id)
        )
        raw_row_count = int((await session.execute(raw_row_count_q)).scalar_one())
    else:
        raw_row_count = raw_label_count

    validation_result_count_q = (
        select(func.count())
        .select_from(CandidateRuleValidationResult)
        .where(CandidateRuleValidationResult.batch_id == batch_id)
    )
    validation_result_count = int((await session.execute(validation_result_count_q)).scalar_one())

    next_allowed_actions = compute_next_allowed_actions(
        batch.status,
        parser_key=batch.parser_key,
        parse_enabled=parse_enabled if batch.status == ImportBatchStatus.running.value else None,
        parse_disable_reason=parse_disable_reason,
        raw_row_count=raw_row_count,
        candidate_count=candidate_count,
        validation_result_count=validation_result_count,
    )

    return ImportBatchPipelineOverview(
        batch=ImportBatchRead.model_validate(batch),
        bound_files=bound_files,
        events=events,
        parse_runs=parse_runs,
        raw_label_count=raw_label_count,
        raw_labels_preview=raw_labels_preview,
        generation_runs=generation_runs,
        candidate_count=candidate_count,
        candidate_status_counts=candidate_status_counts,
        candidates_preview=candidates_preview,
        validation_runs=validation_runs,
        latest_validation_summary=latest_validation_summary,
        next_allowed_actions=next_allowed_actions,
    )


def _build_bound_file_pipeline_read(
    binding,
    resource_file,
    intermediate_summary: dict,
    intermediate_artifact=None,
) -> BoundFilePipelineRead:
    parse_status = raw_parsing_service.assess_bound_file_parse_status(
        resource_file,
        binding.file_role_in_batch,
        intermediate_artifact=intermediate_artifact,
    )
    warning: str | None = None
    if resource_file is not None and not parse_status["is_active"]:
        warning = (
            f"Bound file {resource_file.id} is not active (status={parse_status.get('inactive_reason', 'unknown')}). "
            "Reactivate in File Center or create a new batch with an active AAL3 XML file."
        )
    elif resource_file is not None and not parse_status["can_parse"]:
        warning = parse_status.get("parser_incompatible_reason") or parse_status.get("inactive_reason")

    return BoundFilePipelineRead(
        id=binding.id,
        file_id=binding.file_id,
        file_role_in_batch=binding.file_role_in_batch,
        sort_order=binding.sort_order,
        created_at=binding.created_at,
        original_filename=resource_file.original_filename if resource_file else None,
        file_type=resource_file.file_type if resource_file else None,
        file_role=resource_file.file_role if resource_file else None,
        file_status=(
            "deleted"
            if resource_file is not None and resource_file.deleted_at is not None
            else (resource_file.status if resource_file else None)
        ),
        is_active=bool(parse_status["is_active"]),
        can_parse=bool(parse_status["can_parse"]),
        inactive_reason=parse_status.get("inactive_reason"),  # type: ignore[arg-type]
        intermediate_status=intermediate_summary.get("intermediate_status"),
        latest_intermediate_artifact_id=intermediate_summary.get("latest_intermediate_artifact_id"),
        latest_intermediate_kind=parse_status.get("latest_intermediate_kind") or intermediate_summary.get("latest_intermediate_kind"),
        latest_intermediate_schema=parse_status.get("latest_intermediate_schema"),  # type: ignore[arg-type]
        parser_compatible_for_aal3_xml=bool(parse_status.get("parser_compatible_for_aal3_xml")),
        parser_incompatible_reason=parse_status.get("parser_incompatible_reason"),  # type: ignore[arg-type]
        warning=warning,
    )
