"""Pydantic schemas for Mirror KG circuit-projection cross validation (Step 8.11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CircuitProjectionCrossValidationStatus:
    bidirectionally_supported = "bidirectionally_supported"
    circuit_supported_only = "circuit_supported_only"
    projection_supported_only = "projection_supported_only"
    conflict = "conflict"
    insufficient_evidence = "insufficient_evidence"
    unknown = "unknown"


class CircuitProjectionSupportLevel:
    strong = "strong"
    moderate = "moderate"
    weak = "weak"
    conflicting = "conflicting"
    unknown = "unknown"


class CrossValidationRunStatus:
    created = "created"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MirrorCircuitProjectionCrossValidationScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    circuit_ids: list[uuid.UUID] | None = None
    projection_ids: list[uuid.UUID] | None = None
    membership_ids: list[uuid.UUID] | None = None
    include_unverified: bool = True
    include_conflicts: bool = True


class MirrorCircuitProjectionCrossValidationRequest(BaseModel):
    scope: MirrorCircuitProjectionCrossValidationScope | None = None
    dry_run: bool = True
    apply_updates: bool = False
    update_bidirectional: bool = True
    update_conflicts: bool = False
    limit: int = Field(default=1000, ge=1, le=5000)


class MirrorCircuitProjectionCrossValidationResultPreview(BaseModel):
    circuit_id: uuid.UUID
    projection_id: uuid.UUID
    circuit_to_projection_membership_id: uuid.UUID | None = None
    projection_to_circuit_membership_id: uuid.UUID | None = None
    validation_status: str
    support_level: str
    agreement_score: float | None = None
    source_step_agreement: bool | None = None
    target_step_agreement: bool | None = None
    direction_agreement: bool | None = None
    scope_agreement: bool | None = None
    conflict_reason: str | None = None
    details_json: dict[str, Any] = Field(default_factory=dict)


class MirrorCircuitProjectionCrossValidationResponse(BaseModel):
    run_id: uuid.UUID | None = None
    dry_run: bool
    apply_updates: bool
    membership_count: int = 0
    circuit_supported_count: int = 0
    projection_supported_count: int = 0
    bidirectionally_supported_count: int = 0
    conflict_count: int = 0
    insufficient_evidence_count: int = 0
    updated_membership_count: int = 0
    results_preview: list[MirrorCircuitProjectionCrossValidationResultPreview] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


class MirrorCircuitProjectionCrossValidationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope_json: dict[str, Any]
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    status: str
    membership_count: int
    circuit_supported_count: int
    projection_supported_count: int
    bidirectionally_supported_count: int
    conflict_count: int
    insufficient_evidence_count: int
    updated_membership_count: int
    dry_run: bool
    apply_updates: bool
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class MirrorCircuitProjectionCrossValidationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    circuit_id: uuid.UUID
    projection_id: uuid.UUID
    circuit_to_projection_membership_id: uuid.UUID | None = None
    projection_to_circuit_membership_id: uuid.UUID | None = None
    validation_status: str
    support_level: str
    agreement_score: float | None = None
    source_step_agreement: bool | None = None
    target_step_agreement: bool | None = None
    direction_agreement: bool | None = None
    scope_agreement: bool | None = None
    conflict_reason: str | None = None
    details_json: dict[str, Any] = Field(default_factory=dict)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    created_at: datetime


class MirrorCircuitProjectionCrossValidationRunListResponse(BaseModel):
    items: list[MirrorCircuitProjectionCrossValidationRunRead]
    total: int
    limit: int
    offset: int


class MirrorCircuitProjectionCrossValidationResultListResponse(BaseModel):
    items: list[MirrorCircuitProjectionCrossValidationResultRead]
    total: int
    limit: int
    offset: int
