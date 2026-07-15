"""Human Review business logic — manual review of candidate_brain_regions.

Boundaries (guide §18.9 / §5.2 / §25):
  - Reads candidate_brain_regions; writes the review side ONLY
    (candidate_review_records) and advances the Candidate state machine.
  - Does NOT promote, write final_* / kg_*, generate final regions / promotion_event,
    call LLM/Agent, re-run rule validation, or auto-merge same-name regions.
  - Does NOT change Import Batch status (review is decoupled from the batch state machine).
  - Transitions (via validate_candidate_transition):
      submit:  <pre-review status> -> manual_review_pending
      approve: manual_review_pending -> manual_approved
      reject:  manual_review_pending -> manual_rejected
    request_changes / mark_uncertain keep the candidate in manual_review_pending
    (recorded as audit only; the state machine has no such status).
  - manual_approved != promoted_to_final; manual_rejected is NEVER deleted.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.human_review import CandidateReviewRecord
from app.schemas.candidate import CandidateStatus, validate_candidate_transition
from app.schemas.human_review import REVIEW_DECISION_ACTIONS, ReviewAction
from app.services import candidate_service

logger = logging.getLogger(__name__)


class CandidateNotFoundError(Exception):
    pass


class InvalidReviewActionError(Exception):
    pass


class CandidateNotInReviewError(Exception):
    def __init__(self, candidate_id: uuid.UUID, current_status: str):
        self.candidate_id = candidate_id
        self.current_status = current_status
        super().__init__(
            f"candidate {candidate_id} is not pending review (status={current_status})"
        )


class ReviewRecordNotFoundError(Exception):
    pass


# Decision action -> resulting candidate status (None = keep current status).
_DECISION_TARGET: dict[ReviewAction, CandidateStatus | None] = {
    ReviewAction.approve: CandidateStatus.manual_approved,
    ReviewAction.reject: CandidateStatus.manual_rejected,
    ReviewAction.request_changes: None,
    ReviewAction.mark_uncertain: None,
}


def _log_action(*, action: str, result: str, candidate_id: uuid.UUID, error: str | None = None) -> None:
    logger.info(
        "event_type=human_review action=%s result=%s candidate_id=%s error=%s",
        action,
        result,
        candidate_id,
        error,
    )


def _snapshot(candidate: CandidateBrainRegion) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.id),
        "candidate_status": candidate.candidate_status,
        "raw_name": candidate.raw_name,
        "std_name": candidate.std_name,
        "en_name": candidate.en_name,
        "cn_name": candidate.cn_name,
        "laterality": candidate.laterality,
        "region_base_name": candidate.region_base_name,
        "label_value": candidate.label_value,
        "source_label_id": candidate.source_label_id,
        "granularity_level": candidate.granularity_level,
        "granularity_family": candidate.granularity_family,
    }


def _record(
    candidate: CandidateBrainRegion,
    *,
    action: ReviewAction,
    from_status: str,
    to_status: str,
    reviewed_by: str,
    reason: str | None,
) -> CandidateReviewRecord:
    return CandidateReviewRecord(
        candidate_id=candidate.id,
        batch_id=candidate.batch_id,
        resource_id=candidate.resource_id,
        generation_run_id=candidate.generation_run_id,
        parse_run_id=candidate.parse_run_id,
        action=action.value,
        from_status=from_status,
        to_status=to_status,
        reviewed_by=reviewed_by,
        reason=reason,
        snapshot=_snapshot(candidate),
    )


async def submit_candidate_to_review(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    reviewed_by: str,
    reason: str | None = None,
) -> tuple[CandidateBrainRegion, CandidateReviewRecord]:
    """Submit a candidate to the manual review queue (-> manual_review_pending).

    The Candidate state machine enforces eligibility: candidate_created / rule_validating
    cannot reach manual_review_pending, so they are rejected with an invalid-transition error.
    """
    candidate = await session.get(CandidateBrainRegion, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError(str(candidate_id))

    from_status = candidate.candidate_status
    # Snapshot is taken before mutating the candidate status.
    record = _record(
        candidate,
        action=ReviewAction.submit,
        from_status=from_status,
        to_status=CandidateStatus.manual_review_pending.value,
        reviewed_by=reviewed_by,
        reason=reason,
    )
    validate_candidate_transition(from_status, CandidateStatus.manual_review_pending)
    candidate.candidate_status = CandidateStatus.manual_review_pending.value

    session.add(record)
    await session.commit()
    await session.refresh(candidate)
    await session.refresh(record)
    _log_action(action="submit", result="success", candidate_id=candidate_id)
    return candidate, record


async def decide_candidate(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    action: ReviewAction,
    reviewed_by: str,
    reason: str | None = None,
) -> tuple[CandidateBrainRegion, CandidateReviewRecord]:
    """Apply a human review decision on a candidate pending review.

    approve -> manual_approved; reject -> manual_rejected.
    request_changes / mark_uncertain keep manual_review_pending (audit only).
    """
    if action not in REVIEW_DECISION_ACTIONS:
        raise InvalidReviewActionError(f"{action.value} is not a decision action")

    candidate = await session.get(CandidateBrainRegion, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError(str(candidate_id))

    from_status = candidate.candidate_status
    if from_status != CandidateStatus.manual_review_pending.value:
        raise CandidateNotInReviewError(candidate_id, from_status)

    target = _DECISION_TARGET[action]
    to_status = from_status if target is None else target.value

    record = _record(
        candidate,
        action=action,
        from_status=from_status,
        to_status=to_status,
        reviewed_by=reviewed_by,
        reason=reason,
    )
    if target is not None:
        validate_candidate_transition(from_status, target)
        candidate.candidate_status = target.value

    session.add(record)
    await session.commit()
    await session.refresh(candidate)
    await session.refresh(record)
    _log_action(action=action.value, result="success", candidate_id=candidate_id)
    return candidate, record


async def list_pending_candidates(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateBrainRegion], int]:
    """List candidates waiting for review (candidate_status == manual_review_pending)."""
    return await candidate_service.list_candidate_regions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        generation_run_id=generation_run_id,
        candidate_status=CandidateStatus.manual_review_pending.value,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )


async def list_candidate_records(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateReviewRecord], int]:
    base = select(CandidateReviewRecord).where(
        CandidateReviewRecord.candidate_id == candidate_id
    )
    count_q = (
        select(func.count())
        .select_from(CandidateReviewRecord)
        .where(CandidateReviewRecord.candidate_id == candidate_id)
    )
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(CandidateReviewRecord.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def list_records(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    action: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateReviewRecord], int]:
    base = select(CandidateReviewRecord)
    count_q = select(func.count()).select_from(CandidateReviewRecord)
    if batch_id:
        base = base.where(CandidateReviewRecord.batch_id == batch_id)
        count_q = count_q.where(CandidateReviewRecord.batch_id == batch_id)
    if resource_id:
        base = base.where(CandidateReviewRecord.resource_id == resource_id)
        count_q = count_q.where(CandidateReviewRecord.resource_id == resource_id)
    if action:
        base = base.where(CandidateReviewRecord.action == action)
        count_q = count_q.where(CandidateReviewRecord.action == action)
    if granularity_level:
        base = base.join(CandidateBrainRegion, CandidateReviewRecord.candidate_id == CandidateBrainRegion.id).where(CandidateBrainRegion.granularity_level == granularity_level)
        count_q = count_q.join(CandidateBrainRegion, CandidateReviewRecord.candidate_id == CandidateBrainRegion.id).where(CandidateBrainRegion.granularity_level == granularity_level)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(CandidateReviewRecord.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_record(
    session: AsyncSession, record_id: uuid.UUID
) -> CandidateReviewRecord:
    row = await session.get(CandidateReviewRecord, record_id)
    if row is None:
        raise ReviewRecordNotFoundError(str(record_id))
    return row
