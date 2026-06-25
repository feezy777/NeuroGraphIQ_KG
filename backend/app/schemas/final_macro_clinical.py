"""Pydantic schemas for Final macro_clinical promotion (Step 8.15)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

REQUIRED_PROMOTION_CONFIRM_TEXT = "PROMOTE HUMAN APPROVED MIRROR TO FINAL"

FinalMacroClinicalTargetType = Literal[
    "circuit", "circuit_step", "projection", "projection_function",
    "circuit_projection_membership", "region_function", "function",
    "circuit_function", "triple", "evidence",
]

FinalPromotionAction = Literal[
    "promoted", "skipped", "blocked", "duplicate", "failed", "dry_run_preview",
]

FinalPromotionEligibilityStatus = Literal[
    "eligible", "not_human_approved", "validation_blocked", "review_not_approved",
    "already_promoted", "duplicate_final_exists", "dependency_missing",
    "risk_requires_confirmation", "not_supported_target_type", "failed",
]

FinalPromotionRunStatus = Literal[
    "created", "running", "succeeded", "partially_succeeded", "failed", "cancelled",
]


class FinalMacroClinicalPromotionScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class FinalMacroClinicalPromotionRequest(BaseModel):
    target_types: list[str]
    scope: FinalMacroClinicalPromotionScope | None = None
    mirror_object_ids: list[uuid.UUID] | None = None
    dry_run: bool = True
    confirm_text: str = ""
    allow_projection_without_membership: bool = False
    allow_conflict_with_human_reason: bool = True
    promote_dependencies: bool = True
    promote_triples: bool = True
    promote_evidence: bool = True
    promote_circuit_function_association: bool = False
    limit: int = Field(default=1000, ge=1, le=5000)
    created_by: str | None = None

    @field_validator("target_types")
    @classmethod
    def non_empty_types(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("target_types required")
        return v


class FinalMacroClinicalPromotionRecordPreview(BaseModel):
    target_type: str
    mirror_object_id: uuid.UUID
    final_table: str | None = None
    final_object_id: uuid.UUID | None = None
    action: str
    eligibility_status: str
    reason: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    error_message: str | None = None
    duplicate_of_final_id: uuid.UUID | None = None


class FinalMacroClinicalPromotionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    dry_run: bool
    candidate_count: int = 0
    eligible_count: int = 0
    promoted_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    duplicate_count: int = 0
    risk_flag_count: int = 0
    records_preview: list[FinalMacroClinicalPromotionRecordPreview] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_confirm_text: str = REQUIRED_PROMOTION_CONFIRM_TEXT


class FinalMacroClinicalPromotionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope_json: dict[str, Any]
    target_types: list[str]
    dry_run: bool
    confirm_text: str | None
    status: str
    candidate_count: int
    eligible_count: int
    promoted_count: int
    skipped_count: int
    failed_count: int
    blocked_count: int
    duplicate_count: int
    risk_flag_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    created_by: str | None


class FinalMacroClinicalPromotionRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    target_type: str
    mirror_object_id: uuid.UUID
    final_table: str | None
    final_object_id: uuid.UUID | None
    action: str
    reason: str | None
    eligibility_status: str
    risk_flags: list[str]
    duplicate_of_final_id: uuid.UUID | None
    error_message: str | None
    created_at: datetime


class FinalMacroClinicalPromotionRunListResponse(BaseModel):
    items: list[FinalMacroClinicalPromotionRunRead]
    total: int
    limit: int
    offset: int


class FinalMacroClinicalPromotionRecordListResponse(BaseModel):
    items: list[FinalMacroClinicalPromotionRecordRead]
    total: int
    limit: int
    offset: int


class FinalObjectRead(BaseModel):
    id: uuid.UUID
    final_uid: str | None = None
    source_mirror_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    label: str | None = None
    confidence: float | None = None
    final_status: str = "active"
    promotion_run_id: uuid.UUID | None = None
    created_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class FinalObjectListResponse(BaseModel):
    items: list[FinalObjectRead]
    total: int
    limit: int
    offset: int
