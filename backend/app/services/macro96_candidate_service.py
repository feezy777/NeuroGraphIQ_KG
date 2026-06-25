"""Macro96 candidate generation — raw_macro96_region_rows → candidate_brain_regions.

Boundaries:
  - Reads raw_macro96_region_rows only (not raw_aal3_region_labels).
  - Writes candidate side ONLY. Does NOT write final_* / kg_*.
  - Does NOT call LLM, rule validation, human review, or promotion.
  - Does NOT auto-merge with AAL3 candidates or create mapping.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion, CandidateGenerationRun
from app.models.raw_macro96 import RawMacro96RegionRow
from app.models.raw_parsing import RawParseRun
from app.schemas.candidate import CandidateStatus
from app.schemas.import_batch import BatchEventType, ImportBatchStatus
from app.services import import_batch_service, resource_service
from app.utils.macro96_laterality import infer_macro96_laterality

logger = logging.getLogger(__name__)

GENERATOR_KEY = "macro96_candidate_v1"
GENERATOR_VERSION = "v1"
SOURCE_RAW_TABLE = "raw_macro96_region_rows"
_MACRO96_PARSER_KEYS = frozenset({"macro96_xlsx", "macro_96_excel"})


class WrongParserKeyError(Exception):
    pass


class BatchNotCandidateReadyError(Exception):
    pass


class ParseRunNotEligibleError(Exception):
    pass


class NoMacro96RawRowsError(Exception):
    pass


class DuplicateMacro96CandidateGenerationError(Exception):
    def __init__(self, batch_id: uuid.UUID, parse_run_id: uuid.UUID, existing_run_id: uuid.UUID):
        self.batch_id = batch_id
        self.parse_run_id = parse_run_id
        self.existing_run_id = existing_run_id
        super().__init__(str(existing_run_id))


def _log_action(
    *,
    action: str,
    result: str,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=macro96_candidate action=%s result=%s batch_id=%s generation_run_id=%s error=%s",
        action,
        result,
        batch_id,
        generation_run_id,
        error,
    )


async def _latest_succeeded_macro96_parse_run(
    session: AsyncSession, batch_id: uuid.UUID
) -> RawParseRun | None:
    q = (
        select(RawParseRun)
        .where(
            RawParseRun.batch_id == batch_id,
            RawParseRun.status == "succeeded",
            RawParseRun.parser_key.in_(_MACRO96_PARSER_KEYS),
        )
        .order_by(RawParseRun.finished_at.desc().nullslast(), RawParseRun.created_at.desc())
    )
    return (await session.execute(q)).scalars().first()


async def _count_candidates_for_batch(session: AsyncSession, batch_id: uuid.UUID) -> int:
    q = (
        select(func.count())
        .select_from(CandidateBrainRegion)
        .where(CandidateBrainRegion.batch_id == batch_id)
    )
    return int((await session.execute(q)).scalar_one())


async def _existing_succeeded_generation(
    session: AsyncSession, batch_id: uuid.UUID, parse_run_id: uuid.UUID
) -> CandidateGenerationRun | None:
    q = select(CandidateGenerationRun).where(
        CandidateGenerationRun.batch_id == batch_id,
        CandidateGenerationRun.parse_run_id == parse_run_id,
        CandidateGenerationRun.generator_key == GENERATOR_KEY,
        CandidateGenerationRun.status == "succeeded",
    )
    return (await session.execute(q)).scalar_one_or_none()


def _std_name(row: RawMacro96RegionRow) -> str:
    return row.en_name


async def generate_macro96_candidates_for_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    *,
    parse_run_id: uuid.UUID | None = None,
) -> CandidateGenerationRun:
    """Create candidate brain regions from Macro96 raw rows.

    Requires batch.parser_key == macro96_xlsx and batch.status == parsed.
    """
    batch = await import_batch_service.get_batch(session, batch_id)

    if (batch.parser_key or "").lower() not in _MACRO96_PARSER_KEYS:
        raise WrongParserKeyError(
            f"batch parser_key must be macro96_xlsx, got {batch.parser_key!r}"
        )

    if batch.status != ImportBatchStatus.parsed.value:
        raise BatchNotCandidateReadyError(
            f"batch status must be parsed, got {batch.status}"
        )

    if parse_run_id is None:
        parse_run = await _latest_succeeded_macro96_parse_run(session, batch_id)
        if parse_run is None:
            raise ParseRunNotEligibleError("no succeeded macro96 parse run found for batch")
    else:
        parse_run = await session.get(RawParseRun, parse_run_id)
        if parse_run is None or parse_run.batch_id != batch_id:
            raise ParseRunNotEligibleError("parse run not found for this batch")
        if parse_run.status != "succeeded":
            raise ParseRunNotEligibleError(
                f"parse run status must be succeeded, got {parse_run.status}"
            )
        if (parse_run.parser_key or "").lower() not in _MACRO96_PARSER_KEYS:
            raise ParseRunNotEligibleError(
                f"parse run parser_key must be macro96_xlsx, got {parse_run.parser_key!r}"
            )

    existing = await _existing_succeeded_generation(session, batch_id, parse_run.id)
    batch_cand_count = await _count_candidates_for_batch(session, batch_id)
    if batch_cand_count > 0:
        if existing is not None:
            existing_id = existing.id
        else:
            gen_q = (
                select(CandidateBrainRegion.generation_run_id)
                .where(CandidateBrainRegion.batch_id == batch_id)
                .limit(1)
            )
            existing_id = (await session.execute(gen_q)).scalar_one()
        _log_action(
            action="generate_macro96_candidates",
            result="duplicate_rejected",
            batch_id=batch_id,
            generation_run_id=existing_id,
        )
        raise DuplicateMacro96CandidateGenerationError(batch_id, parse_run.id, existing_id)

    raw_q = (
        select(RawMacro96RegionRow)
        .where(RawMacro96RegionRow.parse_run_id == parse_run.id)
        .order_by(RawMacro96RegionRow.row_index)
    )
    raw_rows = list((await session.execute(raw_q)).scalars().all())
    if not raw_rows:
        raise NoMacro96RawRowsError("no raw Macro96 rows found for parse run")

    resource = await resource_service.get_resource(session, batch.resource_id)

    now = datetime.now(timezone.utc)
    gen_run = CandidateGenerationRun(
        batch_id=batch_id,
        resource_id=batch.resource_id,
        parse_run_id=parse_run.id,
        generator_key=GENERATOR_KEY,
        generator_version=GENERATOR_VERSION,
        status="running",
        started_at=now,
    )
    session.add(gen_run)
    await session.flush()

    await import_batch_service.record_batch_event(
        session,
        batch_id,
        BatchEventType.candidate_generation_started.value,
        message="Macro96 candidate generation started",
        from_status=batch.status,
        payload_json={
            "generation_run_id": str(gen_run.id),
            "parse_run_id": str(parse_run.id),
            "generator_key": GENERATOR_KEY,
        },
    )
    _log_action(
        action="candidate_generation_started",
        result="success",
        batch_id=batch_id,
        generation_run_id=gen_run.id,
    )

    try:
        candidate_rows: list[CandidateBrainRegion] = []
        for row in raw_rows:
            laterality = infer_macro96_laterality(row.en_name, row.cn_name)
            candidate_rows.append(
                CandidateBrainRegion(
                    generation_run_id=gen_run.id,
                    batch_id=batch_id,
                    resource_id=batch.resource_id,
                    parse_run_id=parse_run.id,
                    source_raw_label_id=row.id,
                    source_raw_table=SOURCE_RAW_TABLE,
                    source_file_id=row.source_file_id,
                    source_atlas=resource.source_atlas,
                    source_version=resource.source_version,
                    source_label_id=f"macro96:{row.region_index}",
                    label_value=row.region_index,
                    raw_name=row.en_name,
                    std_name=_std_name(row),
                    en_name=row.en_name,
                    cn_name=row.cn_name,
                    laterality=laterality,
                    region_base_name=row.en_name,
                    granularity_level=resource.granularity_level,
                    granularity_family=resource.granularity_family,
                    candidate_status=CandidateStatus.candidate_created.value,
                    raw_payload={
                        "source_raw_table": SOURCE_RAW_TABLE,
                        "source_raw_label_id": str(row.id),
                        "parse_run_id": str(parse_run.id),
                        "region_index": row.region_index,
                        "row_index": row.row_index,
                        "en_name": row.en_name,
                        "cn_name": row.cn_name,
                        "source_sheet": row.source_sheet,
                        "parser_key": row.parser_key,
                        "macro96": True,
                        "raw_payload": row.raw_payload,
                    },
                    row_index=row.row_index,
                )
            )
        session.add_all(candidate_rows)

        finished = datetime.now(timezone.utc)
        gen_run.status = "succeeded"
        gen_run.output_count = len(candidate_rows)
        gen_run.skipped_count = 0
        gen_run.finished_at = finished

        await import_batch_service.record_batch_event(
            session,
            batch_id,
            BatchEventType.candidate_generation_succeeded.value,
            message=f"Macro96 candidate generation succeeded, output_count={len(candidate_rows)}",
            from_status=ImportBatchStatus.parsed.value,
            to_status=ImportBatchStatus.candidate_generated.value,
            payload_json={
                "generation_run_id": str(gen_run.id),
                "output_count": len(candidate_rows),
                "generator_key": GENERATOR_KEY,
            },
        )
        await import_batch_service.apply_batch_status_in_session(
            session,
            batch,
            ImportBatchStatus.candidate_generated,
            message="batch advanced to candidate_generated after Macro96 candidate generation",
            event_type=BatchEventType.status_changed.value,
        )

        await session.commit()
        await session.refresh(gen_run)
        _log_action(
            action="candidate_generation_succeeded",
            result="success",
            batch_id=batch_id,
            generation_run_id=gen_run.id,
        )
        return gen_run

    except Exception as exc:
        await session.rollback()
        _log_action(
            action="candidate_generation_failed",
            result="error",
            batch_id=batch_id,
            error=str(exc),
        )
        try:
            failed_run = CandidateGenerationRun(
                batch_id=batch_id,
                resource_id=batch.resource_id,
                parse_run_id=parse_run.id,
                generator_key=GENERATOR_KEY,
                generator_version=GENERATOR_VERSION,
                status="failed",
                error_message=str(exc),
                started_at=now,
                finished_at=datetime.now(timezone.utc),
            )
            session.add(failed_run)
            await session.flush()
            await import_batch_service.record_batch_event(
                session,
                batch_id,
                BatchEventType.candidate_generation_failed.value,
                message=f"Macro96 candidate generation failed: {exc}",
                from_status=ImportBatchStatus.parsed.value,
                payload_json={"error": str(exc), "generation_run_id": str(failed_run.id)},
            )
            await session.commit()
        except Exception as inner:
            await session.rollback()
            _log_action(
                action="candidate_generation_failure_record",
                result="error",
                batch_id=batch_id,
                error=str(inner),
            )
        raise
