"""Pydantic schemas + Candidate state machine for Candidate DB Module.

Candidate entities live on the candidate side ONLY (never final_* / kg_*).
candidate_created != manual_approved != promoted_to_final.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class CandidateGenStatus(str, Enum):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class CandidateStatus(str, Enum):
    """Candidate lifecycle (guide §5.2). Only candidate_created is produced in this step."""

    candidate_created = "candidate_created"
    rule_validating = "rule_validating"
    rule_passed = "rule_passed"
    rule_failed = "rule_failed"
    llm_not_required = "llm_not_required"
    llm_validating = "llm_validating"
    llm_passed = "llm_passed"
    llm_conflict = "llm_conflict"
    manual_review_pending = "manual_review_pending"
    manual_approved = "manual_approved"
    manual_rejected = "manual_rejected"
    promoted_to_final = "promoted_to_final"
    archived = "archived"


# Candidate state machine transitions (guide §5.2).
# Rule Validation / LLM / Human Review / Promotion implement the actual moves later;
# this step only creates candidates in candidate_created and exposes the validator.
CANDIDATE_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {CandidateStatus.manual_rejected.value, CandidateStatus.archived.value}
)

CANDIDATE_ALLOWED_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.candidate_created: frozenset(
        {CandidateStatus.rule_validating, CandidateStatus.archived}
    ),
    CandidateStatus.rule_validating: frozenset(
        {CandidateStatus.rule_passed, CandidateStatus.rule_failed}
    ),
    CandidateStatus.rule_passed: frozenset(
        {
            CandidateStatus.llm_not_required,
            CandidateStatus.llm_validating,
            CandidateStatus.manual_review_pending,
        }
    ),
    CandidateStatus.rule_failed: frozenset(
        {CandidateStatus.manual_review_pending, CandidateStatus.archived}
    ),
    CandidateStatus.llm_not_required: frozenset({CandidateStatus.manual_review_pending}),
    CandidateStatus.llm_validating: frozenset(
        {CandidateStatus.llm_passed, CandidateStatus.llm_conflict}
    ),
    CandidateStatus.llm_passed: frozenset({CandidateStatus.manual_review_pending}),
    CandidateStatus.llm_conflict: frozenset({CandidateStatus.manual_review_pending}),
    CandidateStatus.manual_review_pending: frozenset(
        {CandidateStatus.manual_approved, CandidateStatus.manual_rejected}
    ),
    CandidateStatus.manual_approved: frozenset(
        {CandidateStatus.promoted_to_final, CandidateStatus.archived}
    ),
    CandidateStatus.promoted_to_final: frozenset({CandidateStatus.archived}),
    CandidateStatus.manual_rejected: frozenset(),
    CandidateStatus.archived: frozenset(),
}


class InvalidCandidateTransitionError(ValueError):
    def __init__(self, from_status: str, to_status: str, reason: str):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(f"invalid candidate transition {from_status} -> {to_status}: {reason}")


def validate_candidate_transition(
    from_status: CandidateStatus | str,
    to_status: CandidateStatus | str,
) -> None:
    """Validate a Candidate state transition; raises InvalidCandidateTransitionError."""
    src = CandidateStatus(from_status) if isinstance(from_status, str) else from_status
    dst = CandidateStatus(to_status) if isinstance(to_status, str) else to_status

    if src.value in CANDIDATE_TERMINAL_STATUSES:
        raise InvalidCandidateTransitionError(src.value, dst.value, f"{src.value} is terminal")
    if src == dst:
        raise InvalidCandidateTransitionError(src.value, dst.value, "same status")
    if dst not in CANDIDATE_ALLOWED_TRANSITIONS.get(src, frozenset()):
        raise InvalidCandidateTransitionError(src.value, dst.value, "transition not allowed")


class CandidateGenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    parse_run_id: uuid.UUID
    generator_key: str
    generator_version: str
    status: CandidateGenStatus
    output_count: int
    skipped_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateBrainRegionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generation_run_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    parse_run_id: uuid.UUID
    source_raw_label_id: uuid.UUID
    source_raw_table: str
    source_file_id: uuid.UUID
    source_atlas: str
    source_version: str
    source_label_id: str | None
    label_value: int | None
    raw_name: str
    std_name: str | None
    en_name: str | None
    cn_name: str | None
    laterality: str
    region_base_name: str | None
    granularity_level: str
    granularity_family: str
    candidate_status: CandidateStatus
    raw_payload: dict[str, Any]
    row_index: int
    created_at: datetime
    updated_at: datetime


class CandidateBrainRegionListResponse(BaseModel):
    items: list[CandidateBrainRegionRead]
    total: int
    limit: int
    offset: int


class GenerateCandidatesResponse(BaseModel):
    generation_run: CandidateGenerationRunRead
    output_count: int
    skipped_count: int = 0
    batch_status: str


class GenerateMacro96CandidatesResponse(BaseModel):
    generation_run_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    parse_run_id: uuid.UUID
    generator_key: str
    candidate_count: int
    status: CandidateGenStatus
    batch_status: str


class CandidateStatusCount(BaseModel):
    candidate_status: CandidateStatus
    count: int


class CandidateStatusSummary(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    generation_run_id: uuid.UUID | None = None
    total: int
    by_status: list[CandidateStatusCount]


class CandidateOptionsResponse(BaseModel):
    candidate_status: list[str]
    generation_run_status: list[str]
    laterality: list[str]
