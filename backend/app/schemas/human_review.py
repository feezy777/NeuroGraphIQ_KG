"""Pydantic schemas for Human Review Module.

Human review is the final gate before promotion. It records review actions on
candidate_brain_regions and advances the Candidate state machine:
  rule_passed (or other pre-review states) -> manual_review_pending
  manual_review_pending -> manual_approved / manual_rejected

`request_changes` and `mark_uncertain` are recorded as review actions but keep the
candidate in manual_review_pending (the Candidate state machine has no separate
"needs changes" / "uncertain" status). Review never writes final_* / kg_* and never
promotes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.candidate import CandidateBrainRegionRead


class ReviewAction(str, Enum):
    submit = "submit"
    approve = "approve"
    reject = "reject"
    request_changes = "request_changes"
    mark_uncertain = "mark_uncertain"


# Decision actions taken on a candidate already in manual_review_pending.
REVIEW_DECISION_ACTIONS: frozenset[ReviewAction] = frozenset(
    {
        ReviewAction.approve,
        ReviewAction.reject,
        ReviewAction.request_changes,
        ReviewAction.mark_uncertain,
    }
)


class ReviewSubmitRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=4000)


class ReviewDecisionRequest(BaseModel):
    action: ReviewAction
    reviewed_by: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=4000)


class CandidateReviewRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    generation_run_id: uuid.UUID
    parse_run_id: uuid.UUID
    action: ReviewAction
    from_status: str
    to_status: str
    reviewed_by: str
    reason: str | None
    snapshot: dict
    created_at: datetime


class CandidateReviewRecordListResponse(BaseModel):
    items: list[CandidateReviewRecordRead]
    total: int
    limit: int
    offset: int


class ReviewActionResponse(BaseModel):
    candidate: CandidateBrainRegionRead
    record: CandidateReviewRecordRead


class PendingReviewListResponse(BaseModel):
    items: list[CandidateBrainRegionRead]
    total: int
    limit: int
    offset: int


class HumanReviewOptionsResponse(BaseModel):
    actions: list[str]
    decision_actions: list[str]
    pending_status: str
    approved_status: str
    rejected_status: str
