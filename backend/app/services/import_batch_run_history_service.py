"""Import batch run history — read-only aggregation by batch_id."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion, CandidateGenerationRun
from app.models.human_review import CandidateReviewRecord
from app.models.import_batch import ImportBatchEvent
from app.models.import_batch_rollback import ImportBatchRollbackRecord
from app.models.promotion import FinalBrainRegion, PromotionRecord
from app.models.raw_macro96 import RawMacro96RegionRow
from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun
from app.models.rule_validation import CandidateRuleValidationResult, RuleValidationRun
from app.schemas.import_batch_run_history import (
    CandidateGenerationRunHistoryItem,
    ImportBatchRunHistoryResponse,
    RawParseRunHistoryItem,
    RollbackRecordHistoryItem,
    RuleValidationRunHistoryItem,
    RunHistoryCurrentActive,
    RunHistoryEventItem,
    RunHistorySummary,
)
from app.services.import_batch_service import get_batch
from app.services.import_batch_rollback_service import is_aal3_parser, is_macro96_parser

_MACRO96_PARSER_KEYS = frozenset({"macro96_xlsx", "macro_96_excel"})
_EVENTS_LIMIT = 50


async def _count_by_batch(session: AsyncSession, model, batch_id: uuid.UUID) -> int:
    q = select(func.count()).select_from(model).where(model.batch_id == batch_id)
    return int((await session.execute(q)).scalar_one())


async def _count_raw_rows_for_parse_run(
    session: AsyncSession, parse_run_id: uuid.UUID, parser_key: str | None
) -> int:
    if is_macro96_parser(parser_key):
        q = (
            select(func.count())
            .select_from(RawMacro96RegionRow)
            .where(RawMacro96RegionRow.parse_run_id == parse_run_id)
        )
    elif is_aal3_parser(parser_key):
        q = (
            select(func.count())
            .select_from(RawAal3RegionLabel)
            .where(RawAal3RegionLabel.parse_run_id == parse_run_id)
        )
    else:
        aal3_q = (
            select(func.count())
            .select_from(RawAal3RegionLabel)
            .where(RawAal3RegionLabel.parse_run_id == parse_run_id)
        )
        macro_q = (
            select(func.count())
            .select_from(RawMacro96RegionRow)
            .where(RawMacro96RegionRow.parse_run_id == parse_run_id)
        )
        return int((await session.execute(aal3_q)).scalar_one()) + int(
            (await session.execute(macro_q)).scalar_one()
        )
    return int((await session.execute(q)).scalar_one())


async def _count_candidates_for_generation_run(
    session: AsyncSession, generation_run_id: uuid.UUID
) -> int:
    q = (
        select(func.count())
        .select_from(CandidateBrainRegion)
        .where(CandidateBrainRegion.generation_run_id == generation_run_id)
    )
    return int((await session.execute(q)).scalar_one())


async def _count_results_for_validation_run(
    session: AsyncSession, validation_run_id: uuid.UUID
) -> int:
    q = (
        select(func.count())
        .select_from(CandidateRuleValidationResult)
        .where(CandidateRuleValidationResult.validation_run_id == validation_run_id)
    )
    return int((await session.execute(q)).scalar_one())


def _inactive_note(output_count: int, current_count: int, product: str) -> str | None:
    if output_count > 0 and current_count == 0:
        return f"{product} were removed by rollback or manual cleanup"
    return None


async def get_import_batch_run_history(
    session: AsyncSession,
    batch_id: uuid.UUID,
) -> ImportBatchRunHistoryResponse:
    batch = await get_batch(session, batch_id)
    parser_key = batch.parser_key
    warnings: list[str] = []

    if not is_macro96_parser(parser_key) and not is_aal3_parser(parser_key):
        warnings.append(f"parser_key={parser_key!r} is unknown; raw counts include both AAL3 and Macro96")

    raw_row_count = 0
    if is_macro96_parser(parser_key):
        raw_row_count = await _count_by_batch(session, RawMacro96RegionRow, batch_id)
    elif is_aal3_parser(parser_key):
        raw_row_count = await _count_by_batch(session, RawAal3RegionLabel, batch_id)
    else:
        raw_row_count = await _count_by_batch(session, RawAal3RegionLabel, batch_id) + await _count_by_batch(
            session, RawMacro96RegionRow, batch_id
        )

    candidate_count = await _count_by_batch(session, CandidateBrainRegion, batch_id)
    validation_result_count = await _count_by_batch(
        session, CandidateRuleValidationResult, batch_id
    )
    review_count = await _count_by_batch(session, CandidateReviewRecord, batch_id)
    promotion_count = await _count_by_batch(session, PromotionRecord, batch_id)

    final_count = 0
    if hasattr(FinalBrainRegion, "batch_id"):
        final_count = await _count_by_batch(session, FinalBrainRegion, batch_id)
    else:
        warnings.append("final_brain_regions cannot be safely scoped to this batch with current schema")

    parse_runs_q = (
        select(RawParseRun)
        .where(RawParseRun.batch_id == batch_id)
        .order_by(RawParseRun.created_at.desc())
    )
    parse_runs = list((await session.execute(parse_runs_q)).scalars().all())

    raw_history: list[RawParseRunHistoryItem] = []
    active_raw_id: uuid.UUID | None = None
    for run in parse_runs:
        row_count = await _count_raw_rows_for_parse_run(session, run.id, run.parser_key or parser_key)
        active = row_count > 0
        if active and active_raw_id is None:
            active_raw_id = run.id
        raw_history.append(
            RawParseRunHistoryItem(
                id=run.id,
                parser_key=run.parser_key,
                status=run.status,
                input_count=len(run.input_file_ids or []),
                output_count=run.output_count,
                raw_row_count=row_count,
                active=active,
                created_at=run.created_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
                note=_inactive_note(run.output_count, row_count, "Raw rows"),
            )
        )

    gen_runs_q = (
        select(CandidateGenerationRun)
        .where(CandidateGenerationRun.batch_id == batch_id)
        .order_by(CandidateGenerationRun.created_at.desc())
    )
    gen_runs = list((await session.execute(gen_runs_q)).scalars().all())

    gen_history: list[CandidateGenerationRunHistoryItem] = []
    active_gen_id: uuid.UUID | None = None
    for run in gen_runs:
        cand_count = await _count_candidates_for_generation_run(session, run.id)
        active = cand_count > 0
        if active and active_gen_id is None:
            active_gen_id = run.id
        gen_history.append(
            CandidateGenerationRunHistoryItem(
                id=run.id,
                generator_key=run.generator_key,
                status=run.status,
                input_count=run.output_count,
                output_count=run.output_count,
                candidate_count=cand_count,
                active=active,
                created_at=run.created_at,
                finished_at=run.finished_at,
                note=_inactive_note(run.output_count, cand_count, "Candidate rows"),
            )
        )

    val_runs_q = (
        select(RuleValidationRun)
        .where(RuleValidationRun.batch_id == batch_id)
        .order_by(RuleValidationRun.created_at.desc())
    )
    val_runs = list((await session.execute(val_runs_q)).scalars().all())

    val_history: list[RuleValidationRunHistoryItem] = []
    active_val_id: uuid.UUID | None = None
    for run in val_runs:
        result_count = await _count_results_for_validation_run(session, run.id)
        active = result_count > 0
        if active and active_val_id is None:
            active_val_id = run.id
        val_history.append(
            RuleValidationRunHistoryItem(
                id=run.id,
                status=run.status,
                passed_count=run.passed_count,
                warning_count=run.warning_count,
                failed_count=run.failed_count,
                result_count=result_count,
                active=active,
                created_at=run.created_at,
                finished_at=run.finished_at,
                note=_inactive_note(run.candidate_count, result_count, "Validation results"),
            )
        )

    rollback_q = (
        select(ImportBatchRollbackRecord)
        .where(ImportBatchRollbackRecord.batch_id == batch_id)
        .order_by(ImportBatchRollbackRecord.created_at.desc())
    )
    rollback_rows = list((await session.execute(rollback_q)).scalars().all())

    rollback_history: list[RollbackRecordHistoryItem] = []
    active_rollback_id: uuid.UUID | None = None
    for rec in rollback_rows:
        if rec.status == "succeeded" and active_rollback_id is None:
            active_rollback_id = rec.id
        deleted = rec.deleted_counts_json or {}
        if isinstance(deleted, dict):
            deleted_counts = {str(k): int(v) for k, v in deleted.items() if v}
        else:
            deleted_counts = {}
        rollback_history.append(
            RollbackRecordHistoryItem(
                id=rec.id,
                from_status=rec.from_status,
                target_status=rec.target_status,
                operator=rec.operator,
                reason=rec.reason,
                deleted_counts=deleted_counts,
                status=rec.status,
                created_at=rec.created_at,
                finished_at=rec.finished_at,
            )
        )

    events_q = (
        select(ImportBatchEvent)
        .where(ImportBatchEvent.batch_id == batch_id)
        .order_by(ImportBatchEvent.created_at.desc())
        .limit(_EVENTS_LIMIT)
    )
    event_rows = list((await session.execute(events_q)).scalars().all())
    events = [
        RunHistoryEventItem(
            id=e.id,
            event_type=e.event_type,
            from_status=e.from_status,
            to_status=e.to_status,
            message=e.message,
            created_at=e.created_at,
        )
        for e in event_rows
    ]

    return ImportBatchRunHistoryResponse(
        batch_id=batch.id,
        batch_code=batch.batch_code,
        resource_id=batch.resource_id,
        parser_key=parser_key,
        status=batch.status,
        summary=RunHistorySummary(
            raw_row_count=raw_row_count,
            candidate_count=candidate_count,
            validation_result_count=validation_result_count,
            review_record_count=review_count,
            promotion_record_count=promotion_count,
            final_region_count=final_count,
        ),
        raw_parse_runs=raw_history,
        candidate_generation_runs=gen_history,
        rule_validation_runs=val_history,
        rollback_records=rollback_history,
        events=events,
        current_active=RunHistoryCurrentActive(
            raw_parse_run_id=active_raw_id,
            candidate_generation_run_id=active_gen_id,
            validation_run_id=active_val_id,
            rollback_record_id=active_rollback_id,
        ),
        warnings=warnings,
    )
