"""Candidate DB business logic — generate candidate brain regions from raw AAL3 labels.

Boundaries (guide §18 / §25):
  - Reads raw_aal3_region_labels (raw side) and writes candidate side ONLY.
  - Does NOT write final_* / kg_*, run rule validation, call LLM, do human review,
    or perform promotion. Does NOT auto-merge same-name regions; laterality is preserved.
  - Advances import batch parsed -> candidate_generated via the Import Batch state machine.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion, CandidateGenerationRun
from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun
from app.schemas.candidate import CandidateStatus
from app.schemas.import_batch import BatchEventType, ImportBatchStatus
from app.services import import_batch_service, resource_service

logger = logging.getLogger(__name__)

GENERATOR_KEY = "aal3_region_candidate"
GENERATOR_VERSION = "v1"
_SOURCE_RAW_TABLE_AAL3 = "raw_aal3_region_labels"
_MACRO96_PARSER_KEYS = frozenset({"macro96_xlsx", "macro_96_excel"})


class WrongCandidateGeneratorForMacro96Error(Exception):
    def __init__(self, batch_id: uuid.UUID, parser_key: str):
        self.batch_id = batch_id
        self.parser_key = parser_key
        super().__init__(parser_key)


class BatchNotCandidateReadyError(Exception):
    pass


class ParseRunNotEligibleError(Exception):
    pass


class NoRawLabelError(Exception):
    pass


class DuplicateCandidateGenerationError(Exception):
    def __init__(self, batch_id: uuid.UUID, parse_run_id: uuid.UUID, existing_run_id: uuid.UUID):
        self.batch_id = batch_id
        self.parse_run_id = parse_run_id
        self.existing_run_id = existing_run_id
        super().__init__(str(existing_run_id))


class CandidateGenerationRunNotFoundError(Exception):
    pass


def _log_action(
    *,
    action: str,
    result: str,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=candidate_db action=%s result=%s batch_id=%s generation_run_id=%s error=%s",
        action,
        result,
        batch_id,
        generation_run_id,
        error,
    )


def _std_name(label: RawAal3RegionLabel) -> str | None:
    return label.en_name or label.region_base_name or label.raw_name


async def _latest_succeeded_parse_run(
    session: AsyncSession, batch_id: uuid.UUID
) -> RawParseRun | None:
    q = (
        select(RawParseRun)
        .where(RawParseRun.batch_id == batch_id, RawParseRun.status == "succeeded")
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


async def _count_candidates_for_generation_run(
    session: AsyncSession, generation_run_id: uuid.UUID
) -> int:
    q = (
        select(func.count())
        .select_from(CandidateBrainRegion)
        .where(CandidateBrainRegion.generation_run_id == generation_run_id)
    )
    return int((await session.execute(q)).scalar_one())


async def _existing_succeeded_generation(
    session: AsyncSession, batch_id: uuid.UUID, parse_run_id: uuid.UUID
) -> CandidateGenerationRun | None:
    q = select(CandidateGenerationRun).where(
        CandidateGenerationRun.batch_id == batch_id,
        CandidateGenerationRun.parse_run_id == parse_run_id,
        CandidateGenerationRun.status == "succeeded",
    )
    return (await session.execute(q)).scalar_one_or_none()


async def generate_candidates_for_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    *,
    parse_run_id: uuid.UUID | None = None,
) -> CandidateGenerationRun:
    """Create candidate brain regions from a batch's succeeded AAL3 parse run.

    Requires batch.status == parsed. On success advances batch to candidate_generated.
    """
    batch = await import_batch_service.get_batch(session, batch_id)

    if (batch.parser_key or "").lower() in _MACRO96_PARSER_KEYS:
        raise WrongCandidateGeneratorForMacro96Error(batch_id, batch.parser_key or "")

    if batch.status != ImportBatchStatus.parsed.value:
        raise BatchNotCandidateReadyError(
            f"batch status must be parsed, got {batch.status}"
        )

    if parse_run_id is None:
        parse_run = await _latest_succeeded_parse_run(session, batch_id)
        if parse_run is None:
            raise ParseRunNotEligibleError("no succeeded parse run found for batch")
    else:
        parse_run = await session.get(RawParseRun, parse_run_id)
        if parse_run is None or parse_run.batch_id != batch_id:
            raise ParseRunNotEligibleError("parse run not found for this batch")
        if parse_run.status != "succeeded":
            raise ParseRunNotEligibleError(
                f"parse run status must be succeeded, got {parse_run.status}"
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
            action="generate_candidates",
            result="duplicate_rejected",
            batch_id=batch_id,
            generation_run_id=existing_id,
        )
        raise DuplicateCandidateGenerationError(batch_id, parse_run.id, existing_id)

    labels_q = (
        select(RawAal3RegionLabel)
        .where(RawAal3RegionLabel.parse_run_id == parse_run.id)
        .order_by(RawAal3RegionLabel.row_index)
    )
    labels = list((await session.execute(labels_q)).scalars().all())
    if not labels:
        raise NoRawLabelError("no raw labels found for parse run")

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
        message="candidate generation started",
        from_status=batch.status,
        payload_json={
            "generation_run_id": str(gen_run.id),
            "parse_run_id": str(parse_run.id),
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
        for label in labels:
            candidate_rows.append(
                CandidateBrainRegion(
                    generation_run_id=gen_run.id,
                    batch_id=batch_id,
                    resource_id=batch.resource_id,
                    parse_run_id=parse_run.id,
                    source_raw_label_id=label.id,
                    source_raw_table=_SOURCE_RAW_TABLE_AAL3,
                    source_file_id=label.source_file_id,
                    source_atlas=label.source_atlas,
                    source_version=label.source_version,
                    source_label_id=label.source_label_id,
                    label_value=label.label_value,
                    raw_name=label.raw_name,
                    std_name=_std_name(label),
                    en_name=label.en_name,
                    cn_name=label.cn_name,
                    laterality=label.laterality,
                    region_base_name=label.region_base_name,
                    granularity_level=resource.granularity_level,
                    granularity_family=resource.granularity_family,
                    candidate_status=CandidateStatus.candidate_created.value,
                    raw_payload={
                        "source_raw_label_id": str(label.id),
                        "parse_run_id": str(parse_run.id),
                        "label_value": label.label_value,
                        "raw_name": label.raw_name,
                        "raw_payload": label.raw_payload,
                    },
                    row_index=label.row_index,
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
            message=f"candidate generation succeeded, output_count={len(candidate_rows)}",
            from_status=ImportBatchStatus.parsed.value,
            to_status=ImportBatchStatus.candidate_generated.value,
            payload_json={
                "generation_run_id": str(gen_run.id),
                "output_count": len(candidate_rows),
            },
        )
        await import_batch_service.apply_batch_status_in_session(
            session,
            batch,
            ImportBatchStatus.candidate_generated,
            message="batch advanced to candidate_generated after candidate generation",
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
                message=f"candidate generation failed: {exc}",
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


async def list_generation_runs_for_batch(
    session: AsyncSession, batch_id: uuid.UUID
) -> list[CandidateGenerationRun]:
    await import_batch_service.get_batch(session, batch_id)
    q = (
        select(CandidateGenerationRun)
        .where(CandidateGenerationRun.batch_id == batch_id)
        .order_by(CandidateGenerationRun.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def get_generation_run(
    session: AsyncSession, generation_run_id: uuid.UUID
) -> CandidateGenerationRun:
    row = await session.get(CandidateGenerationRun, generation_run_id)
    if row is None:
        raise CandidateGenerationRunNotFoundError(str(generation_run_id))
    return row


async def get_candidate_region(
    session: AsyncSession, candidate_id: uuid.UUID
) -> CandidateBrainRegion | None:
    return await session.get(CandidateBrainRegion, candidate_id)


def _apply_candidate_filters(
    stmt,
    *,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    generation_run_id: uuid.UUID | None,
    parse_run_id: uuid.UUID | None,
    candidate_status: str | None,
    laterality: str | None,
    granularity_level: str | None = None,
):
    if resource_id:
        stmt = stmt.where(CandidateBrainRegion.resource_id == resource_id)
    if batch_id:
        stmt = stmt.where(CandidateBrainRegion.batch_id == batch_id)
    if generation_run_id:
        stmt = stmt.where(CandidateBrainRegion.generation_run_id == generation_run_id)
    if parse_run_id:
        stmt = stmt.where(CandidateBrainRegion.parse_run_id == parse_run_id)
    if candidate_status:
        stmt = stmt.where(CandidateBrainRegion.candidate_status == candidate_status)
    if laterality:
        stmt = stmt.where(CandidateBrainRegion.laterality == laterality)
    if granularity_level:
        stmt = stmt.where(CandidateBrainRegion.granularity_level == granularity_level)
    return stmt


async def list_candidate_regions(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    parse_run_id: uuid.UUID | None = None,
    candidate_status: str | None = None,
    laterality: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateBrainRegion], int]:
    base = _apply_candidate_filters(
        select(CandidateBrainRegion),
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        parse_run_id=parse_run_id,
        candidate_status=candidate_status,
        laterality=laterality,
        granularity_level=granularity_level,
    )
    count_q = _apply_candidate_filters(
        select(func.count()).select_from(CandidateBrainRegion),
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        parse_run_id=parse_run_id,
        candidate_status=candidate_status,
        laterality=laterality,
        granularity_level=granularity_level,
    )
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(CandidateBrainRegion.row_index).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def candidate_status_summary(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
) -> tuple[int, list[tuple[str, int]]]:
    stmt = _apply_candidate_filters(
        select(CandidateBrainRegion.candidate_status, func.count()),
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        parse_run_id=None,
        candidate_status=None,
        laterality=None,
    ).group_by(CandidateBrainRegion.candidate_status)

    rows = (await session.execute(stmt)).all()
    by_status = [(status, int(count)) for status, count in rows]
    total = sum(count for _, count in by_status)
    return total, by_status
