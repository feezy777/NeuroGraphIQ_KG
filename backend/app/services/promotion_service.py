"""Promotion business logic — promote manual_approved candidates to final_brain_regions.

Boundaries (guide §18.10 / §5.2-5.5 / §25):
  - ONLY this module writes final_brain_regions. Never kg_* / legacy staging_*.
  - Only manual_approved candidates may be promoted; all others are rejected.
  - Advances candidate_status: manual_approved -> promoted_to_final via the Candidate
    state machine (validate_candidate_transition enforced).
  - Idempotent: a candidate already in promoted_to_final is skipped (no duplicate final row).
  - Writes promotion_records (audit trail, before/after snapshots).
  - Does NOT change Import Batch status (decoupled from batch state machine).
  - Does NOT do Human Review, Rule Validation, LLM, Neo4j, kg_*, mapping, NIfTI.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.human_review import CandidateReviewRecord
from app.models.promotion import FinalBrainRegion, PromotionRecord
from app.models.resource import AtlasResource
from app.models.rule_validation import CandidateRuleValidationResult
from app.schemas.candidate import CandidateStatus, validate_candidate_transition

logger = logging.getLogger(__name__)


class CandidateNotFoundError(Exception):
    pass


class CandidateNotPromotableError(Exception):
    def __init__(self, candidate_id: uuid.UUID, current_status: str):
        self.candidate_id = candidate_id
        self.current_status = current_status
        super().__init__(
            f"candidate {candidate_id} is not promotable (status={current_status}); "
            "only manual_approved candidates may be promoted"
        )


class AlreadyPromotedError(Exception):
    def __init__(self, candidate_id: uuid.UUID, final_region_id: uuid.UUID):
        self.candidate_id = candidate_id
        self.final_region_id = final_region_id
        super().__init__(
            f"candidate {candidate_id} is already promoted "
            f"(final_region_id={final_region_id})"
        )


class FinalRegionNotFoundError(Exception):
    pass


class PromotionRecordNotFoundError(Exception):
    pass


def _log_action(
    *, action: str, result: str, candidate_id: uuid.UUID, error: str | None = None
) -> None:
    logger.info(
        "event_type=promotion action=%s result=%s candidate_id=%s error=%s",
        action,
        result,
        candidate_id,
        error,
    )


def _candidate_snapshot(c: CandidateBrainRegion) -> dict[str, Any]:
    return {
        "candidate_id": str(c.id),
        "candidate_status": c.candidate_status,
        "raw_name": c.raw_name,
        "std_name": c.std_name,
        "en_name": c.en_name,
        "cn_name": c.cn_name,
        "laterality": c.laterality,
        "region_base_name": c.region_base_name,
        "label_value": c.label_value,
        "source_label_id": c.source_label_id,
        "source_atlas": c.source_atlas,
        "source_version": c.source_version,
        "granularity_level": c.granularity_level,
        "granularity_family": c.granularity_family,
    }


async def _latest_review_record_id(
    session: AsyncSession, candidate_id: uuid.UUID
) -> uuid.UUID | None:
    q = (
        select(CandidateReviewRecord.id)
        .where(CandidateReviewRecord.candidate_id == candidate_id)
        .order_by(CandidateReviewRecord.created_at.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _latest_validation_result_id(
    session: AsyncSession, candidate_id: uuid.UUID
) -> uuid.UUID | None:
    q = (
        select(CandidateRuleValidationResult.id)
        .where(CandidateRuleValidationResult.candidate_id == candidate_id)
        .order_by(CandidateRuleValidationResult.created_at.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _existing_final_region(
    session: AsyncSession, candidate_id: uuid.UUID
) -> FinalBrainRegion | None:
    q = select(FinalBrainRegion).where(FinalBrainRegion.candidate_id == candidate_id)
    return (await session.execute(q)).scalar_one_or_none()


async def promote_candidate(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    promoted_by: str,
    reason: str | None = None,
) -> tuple[FinalBrainRegion, PromotionRecord]:
    """Promote a single manual_approved candidate to final_brain_regions.

    Idempotent: raises AlreadyPromotedError if already promoted.
    Advances candidate_status manual_approved -> promoted_to_final.
    Writes PromotionRecord (succeeded) and FinalBrainRegion.
    Does NOT write kg_* / legacy staging_*.
    """
    candidate = await session.get(CandidateBrainRegion, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError(str(candidate_id))

    if candidate.candidate_status != CandidateStatus.manual_approved.value:
        raise CandidateNotPromotableError(candidate_id, candidate.candidate_status)

    existing = await _existing_final_region(session, candidate_id)
    if existing is not None:
        raise AlreadyPromotedError(candidate_id, existing.id)

    review_id = await _latest_review_record_id(session, candidate_id)
    validation_id = await _latest_validation_result_id(session, candidate_id)

    before_snapshot = _candidate_snapshot(candidate)

    record = PromotionRecord(
        candidate_id=candidate.id,
        resource_id=candidate.resource_id,
        batch_id=candidate.batch_id,
        parse_run_id=candidate.parse_run_id,
        generation_run_id=candidate.generation_run_id,
        source_file_id=candidate.source_file_id,
        source_raw_label_id=candidate.source_raw_label_id,
        latest_review_record_id=review_id,
        latest_validation_result_id=validation_id,
        status="running",
        from_status=candidate.candidate_status,
        to_status=CandidateStatus.promoted_to_final.value,
        promoted_by=promoted_by,
        reason=reason,
        before_snapshot=before_snapshot,
    )
    session.add(record)
    await session.flush()

    try:
        final_region = FinalBrainRegion(
            candidate_id=candidate.id,
            resource_id=candidate.resource_id,
            batch_id=candidate.batch_id,
            parse_run_id=candidate.parse_run_id,
            generation_run_id=candidate.generation_run_id,
            source_file_id=candidate.source_file_id,
            source_raw_label_id=candidate.source_raw_label_id,
            latest_review_record_id=review_id,
            latest_validation_result_id=validation_id,
            source_atlas=candidate.source_atlas,
            source_version=candidate.source_version,
            source_label_id=candidate.source_label_id,
            label_value=candidate.label_value,
            raw_name=candidate.raw_name,
            std_name=candidate.std_name,
            en_name=candidate.en_name,
            cn_name=candidate.cn_name,
            laterality=candidate.laterality,
            region_base_name=candidate.region_base_name,
            granularity_level=candidate.granularity_level,
            granularity_family=candidate.granularity_family,
            promoted_by=promoted_by,
        )
        session.add(final_region)
        await session.flush()

        validate_candidate_transition(
            candidate.candidate_status, CandidateStatus.promoted_to_final
        )
        candidate.candidate_status = CandidateStatus.promoted_to_final.value

        after_snapshot = _candidate_snapshot(candidate)
        record.status = "succeeded"
        record.final_region_id = final_region.id
        record.after_snapshot = after_snapshot

        await session.commit()
        await session.refresh(final_region)
        await session.refresh(record)

        _log_action(action="promote", result="success", candidate_id=candidate_id)
        return final_region, record

    except Exception as exc:
        await session.rollback()
        _log_action(action="promote", result="error", candidate_id=candidate_id, error=str(exc))
        try:
            failed_record = PromotionRecord(
                candidate_id=candidate.id,
                resource_id=candidate.resource_id,
                batch_id=candidate.batch_id,
                parse_run_id=candidate.parse_run_id,
                generation_run_id=candidate.generation_run_id,
                source_file_id=candidate.source_file_id,
                source_raw_label_id=candidate.source_raw_label_id,
                latest_review_record_id=review_id,
                latest_validation_result_id=validation_id,
                status="failed",
                from_status=before_snapshot["candidate_status"],
                to_status=CandidateStatus.promoted_to_final.value,
                promoted_by=promoted_by,
                reason=reason,
                before_snapshot=before_snapshot,
                after_snapshot={},
                error_message=str(exc),
            )
            session.add(failed_record)
            await session.commit()
        except Exception as inner:
            await session.rollback()
            _log_action(
                action="promote_failure_record",
                result="error",
                candidate_id=candidate_id,
                error=str(inner),
            )
        raise


async def get_final_region(
    session: AsyncSession, final_region_id: uuid.UUID
) -> FinalBrainRegion:
    row = await session.get(FinalBrainRegion, final_region_id)
    if row is None:
        raise FinalRegionNotFoundError(str(final_region_id))
    return row


async def get_final_region_for_candidate(
    session: AsyncSession, candidate_id: uuid.UUID
) -> FinalBrainRegion | None:
    return await _existing_final_region(session, candidate_id)


async def list_final_regions(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FinalBrainRegion], int]:
    base = select(FinalBrainRegion)
    count_q = select(func.count()).select_from(FinalBrainRegion)
    if resource_id:
        base = base.where(FinalBrainRegion.resource_id == resource_id)
        count_q = count_q.where(FinalBrainRegion.resource_id == resource_id)
    if batch_id:
        base = base.where(FinalBrainRegion.batch_id == batch_id)
        count_q = count_q.where(FinalBrainRegion.batch_id == batch_id)
    if status:
        base = base.where(FinalBrainRegion.status == status)
        count_q = count_q.where(FinalBrainRegion.status == status)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(FinalBrainRegion.promoted_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def list_promotion_records(
    session: AsyncSession,
    *,
    candidate_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    status: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PromotionRecord], int]:
    base = select(PromotionRecord)
    count_q = select(func.count()).select_from(PromotionRecord)
    if candidate_id:
        base = base.where(PromotionRecord.candidate_id == candidate_id)
        count_q = count_q.where(PromotionRecord.candidate_id == candidate_id)
    if batch_id:
        base = base.where(PromotionRecord.batch_id == batch_id)
        count_q = count_q.where(PromotionRecord.batch_id == batch_id)
    if resource_id:
        base = base.where(PromotionRecord.resource_id == resource_id)
        count_q = count_q.where(PromotionRecord.resource_id == resource_id)
    if status:
        base = base.where(PromotionRecord.status == status)
        count_q = count_q.where(PromotionRecord.status == status)
    if granularity_level:
        base = base.join(AtlasResource, PromotionRecord.resource_id == AtlasResource.id).where(
            AtlasResource.granularity_level == granularity_level
        )
        count_q = count_q.join(AtlasResource, PromotionRecord.resource_id == AtlasResource.id).where(
            AtlasResource.granularity_level == granularity_level
        )

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(PromotionRecord.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_promotion_record(
    session: AsyncSession, record_id: uuid.UUID
) -> PromotionRecord:
    row = await session.get(PromotionRecord, record_id)
    if row is None:
        raise PromotionRecordNotFoundError(str(record_id))
    return row
