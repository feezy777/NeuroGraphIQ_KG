"""Schemas for import batch rollback preview and execute."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class RollbackTargetStatus(str, Enum):
    running = "running"
    parsed = "parsed"
    candidate_generated = "candidate_generated"
    validated = "validated"
    reviewed = "reviewed"


class RollbackRiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RollbackPreviewResponse(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    resource_id: uuid.UUID
    parser_key: str | None
    current_status: str
    target_status: str
    supported: bool = True
    will_change_status: bool = True
    required_confirmation: str
    warnings: list[str] = Field(default_factory=list)
    delete_plan: dict[str, int] = Field(default_factory=dict)
    keep_plan: dict[str, int] = Field(default_factory=dict)
    dependency_counts: dict[str, int] = Field(default_factory=dict)
    risk_level: RollbackRiskLevel
    next_api: str | None = None
    generated_at: datetime


class RollbackExecuteRequest(BaseModel):
    target_status: str
    confirmation_text: str
    operator: str
    reason: str
    preview_token: str | None = None
    expected_delete_plan: dict[str, int] | None = None
    expected_dependency_counts: dict[str, int] | None = None

    @field_validator("operator", "reason")
    @classmethod
    def non_empty_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("confirmation_text")
    @classmethod
    def non_empty_confirmation(cls, v: str) -> str:
        if not v:
            raise ValueError("confirmation_text is required")
        return v


class RollbackExecuteResponse(BaseModel):
    rollback_record_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    resource_id: uuid.UUID
    parser_key: str | None
    from_status: str
    target_status: str
    status: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)
    kept_counts: dict[str, int] = Field(default_factory=dict)
    batch_status: str
    warnings: list[str] = Field(default_factory=list)
    events_written: list[str] = Field(default_factory=list)
    finished_at: datetime | None = None
