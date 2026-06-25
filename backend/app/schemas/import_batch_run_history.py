"""Schemas for import batch run history (read-only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RawParseRunHistoryItem(BaseModel):
    id: uuid.UUID
    parser_key: str
    status: str
    input_count: int = 0
    output_count: int = 0
    raw_row_count: int = 0
    active: bool = False
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    note: str | None = None


class CandidateGenerationRunHistoryItem(BaseModel):
    id: uuid.UUID
    generator_key: str
    status: str
    input_count: int = 0
    output_count: int = 0
    candidate_count: int = 0
    active: bool = False
    created_at: datetime | None = None
    finished_at: datetime | None = None
    note: str | None = None


class RuleValidationRunHistoryItem(BaseModel):
    id: uuid.UUID
    status: str
    passed_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    result_count: int = 0
    active: bool = False
    created_at: datetime | None = None
    finished_at: datetime | None = None
    note: str | None = None


class RollbackRecordHistoryItem(BaseModel):
    id: uuid.UUID
    from_status: str
    target_status: str
    operator: str
    reason: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)
    status: str
    created_at: datetime | None = None
    finished_at: datetime | None = None


class RunHistoryEventItem(BaseModel):
    id: uuid.UUID
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    message: str | None = None
    created_at: datetime | None = None


class RunHistoryCurrentActive(BaseModel):
    raw_parse_run_id: uuid.UUID | None = None
    candidate_generation_run_id: uuid.UUID | None = None
    validation_run_id: uuid.UUID | None = None
    rollback_record_id: uuid.UUID | None = None


class RunHistorySummary(BaseModel):
    raw_row_count: int = 0
    candidate_count: int = 0
    validation_result_count: int = 0
    review_record_count: int = 0
    promotion_record_count: int = 0
    final_region_count: int = 0


class ImportBatchRunHistoryResponse(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    resource_id: uuid.UUID
    parser_key: str | None
    status: str
    summary: RunHistorySummary = Field(default_factory=RunHistorySummary)
    raw_parse_runs: list[RawParseRunHistoryItem] = Field(default_factory=list)
    candidate_generation_runs: list[CandidateGenerationRunHistoryItem] = Field(default_factory=list)
    rule_validation_runs: list[RuleValidationRunHistoryItem] = Field(default_factory=list)
    rollback_records: list[RollbackRecordHistoryItem] = Field(default_factory=list)
    events: list[RunHistoryEventItem] = Field(default_factory=list)
    current_active: RunHistoryCurrentActive = Field(default_factory=RunHistoryCurrentActive)
    warnings: list[str] = Field(default_factory=list)
