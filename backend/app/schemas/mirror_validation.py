"""Pydantic schemas for Mirror KG Rule Validation (Step 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MirrorValidationTargetType:
    connection = "connection"
    function = "function"
    circuit = "circuit"
    triple = "triple"
    projection = "projection"
    circuit_step = "circuit_step"
    projection_function = "projection_function"
    circuit_projection_membership = "circuit_projection_membership"
    circuit_projection_cross_validation_result = "circuit_projection_cross_validation_result"
    dual_model_verification_result = "dual_model_verification_result"


VALID_MIRROR_VALIDATION_TARGET_TYPES = frozenset({
    MirrorValidationTargetType.connection,
    MirrorValidationTargetType.function,
    MirrorValidationTargetType.circuit,
    MirrorValidationTargetType.triple,
    MirrorValidationTargetType.projection,
    MirrorValidationTargetType.circuit_step,
    MirrorValidationTargetType.projection_function,
    MirrorValidationTargetType.circuit_projection_membership,
    MirrorValidationTargetType.circuit_projection_cross_validation_result,
    MirrorValidationTargetType.dual_model_verification_result,
})


class MirrorValidationSeverity:
    info = "info"
    warning = "warning"
    error = "error"
    blocker = "blocker"


class MirrorValidationResultStatus:
    passed = "passed"
    warning = "warning"
    failed = "failed"
    blocked = "blocked"


class MirrorValidationRunStatus:
    created = "created"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MirrorValidationScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_status: list[str] | None = None
    review_status: list[str] | None = None
    promotion_status: list[str] | None = None


class MirrorValidationFilters(BaseModel):
    circuit_id: uuid.UUID | None = None
    projection_id: uuid.UUID | None = None
    object_type: str | None = None
    validation_status: str | None = None
    consensus_status: str | None = None
    verification_status: str | None = None


class MirrorValidationRequest(BaseModel):
    target_types: list[str] = Field(min_length=1)
    scope: MirrorValidationScope | None = None
    filters: MirrorValidationFilters | None = None
    connection_ids: list[uuid.UUID] | None = None
    function_ids: list[uuid.UUID] | None = None
    circuit_ids: list[uuid.UUID] | None = None
    triple_ids: list[uuid.UUID] | None = None
    circuit_step_ids: list[uuid.UUID] | None = None
    projection_function_ids: list[uuid.UUID] | None = None
    membership_ids: list[uuid.UUID] | None = None
    cross_validation_result_ids: list[uuid.UUID] | None = None
    dual_model_result_ids: list[uuid.UUID] | None = None
    projection_ids: list[uuid.UUID] | None = None
    dry_run: bool = True
    apply_status_update: bool = False
    limit: int = Field(default=1000, ge=1, le=5000)


class MirrorValidationResultPreview(BaseModel):
    target_type: str
    target_id: uuid.UUID
    rule_code: str
    severity: str
    status: str
    message: str
    details_json: dict[str, Any] = Field(default_factory=dict)


class MirrorValidationResponse(BaseModel):
    dry_run: bool
    run_id: uuid.UUID | None = None
    target_counts: dict[str, int] = Field(default_factory=dict)
    passed_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    high_review_priority_count: int = 0
    result_count: int = 0
    status_updates: dict[str, int] = Field(default_factory=dict)
    results_preview: list[MirrorValidationResultPreview] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MirrorValidationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    rule_code: str
    severity: str
    status: str
    message: str
    details_json: dict[str, Any]
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    source_atlas: str | None
    granularity_level: str | None
    granularity_family: str | None
    created_at: datetime


class MirrorValidationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_types: list[str]
    scope_json: dict[str, Any]
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    source_atlas: str | None
    source_version: str | None
    granularity_level: str | None
    granularity_family: str | None
    status: str
    object_count: int
    passed_count: int
    warning_count: int
    failed_count: int
    blocked_count: int
    result_count: int
    dry_run: bool
    apply_status_update: bool
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class MirrorValidationRunDetailRead(MirrorValidationRunRead):
    results_summary: dict[str, int] = Field(default_factory=dict)


class MirrorValidationRunListResponse(BaseModel):
    items: list[MirrorValidationRunRead]
    total: int


class MirrorValidationResultListResponse(BaseModel):
    items: list[MirrorValidationResultRead]
    total: int
