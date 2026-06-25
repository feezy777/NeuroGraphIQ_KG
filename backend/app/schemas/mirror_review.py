"""Pydantic schemas for Mirror KG Human Review (Step 8 / 8.14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MirrorReviewTargetType:
    connection = "connection"
    function = "function"
    region_function = "region_function"
    circuit = "circuit"
    triple = "triple"
    projection = "projection"
    circuit_step = "circuit_step"
    projection_function = "projection_function"
    circuit_projection_membership = "circuit_projection_membership"
    circuit_projection_cross_validation_result = "circuit_projection_cross_validation_result"
    dual_model_verification_result = "dual_model_verification_result"


VALID_MIRROR_REVIEW_TARGET_TYPES = frozenset({
    MirrorReviewTargetType.connection,
    MirrorReviewTargetType.function,
    MirrorReviewTargetType.region_function,
    MirrorReviewTargetType.circuit,
    MirrorReviewTargetType.triple,
    MirrorReviewTargetType.projection,
    MirrorReviewTargetType.circuit_step,
    MirrorReviewTargetType.projection_function,
    MirrorReviewTargetType.circuit_projection_membership,
    MirrorReviewTargetType.circuit_projection_cross_validation_result,
    MirrorReviewTargetType.dual_model_verification_result,
})


class MirrorReviewAction:
    approve = "approve"
    reject = "reject"
    needs_revision = "needs_revision"
    edit = "edit"
    comment = "comment"
    accept_signal = "accept_signal"
    dismiss_signal = "dismiss_signal"
    flag_for_followup = "flag_for_followup"


class MirrorReviewQueueScope(BaseModel):
    target_types: list[str] | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_status: list[str] | None = None
    review_status: list[str] | None = None
    promotion_status: list[str] | None = None
    has_blocker: bool | None = None
    has_error: bool | None = None
    has_warning: bool | None = None
    has_model_conflict: bool | None = None
    has_cross_conflict: bool | None = None
    consensus_status: str | None = None
    verification_status: str | None = None
    recommended_review_priority: str | None = None
    search: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class MirrorReviewGating(BaseModel):
    can_approve: bool = False
    can_reject: bool = False
    can_edit: bool = False
    can_comment: bool = True
    can_accept_signal: bool = False
    can_dismiss_signal: bool = False
    gating_reasons: list[str] = Field(default_factory=list)
    requires_reviewer_reason: bool = False


class MirrorReviewQueueItem(BaseModel):
    target_type: str
    target_id: uuid.UUID
    display_label: str
    target_label: str | None = None
    summary: str | None = None
    target_summary: str | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_status: str
    review_status: str
    promotion_status: str
    confidence: float | None = None
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    latest_validation_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_count: int = 0
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    recommended_review_priority: str = "normal"
    blocker_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    consensus_status: str | None = None
    verification_status: str | None = None
    cross_validation_status: str | None = None
    can_approve: bool = False
    gating_reasons: list[str] = Field(default_factory=list)
    object_category: str = "domain_object"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MirrorReviewQueueResponse(BaseModel):
    items: list[MirrorReviewQueueItem]
    total: int
    limit: int
    offset: int


class MirrorReviewDetail(BaseModel):
    target_type: str
    target_id: uuid.UUID
    object_json: dict[str, Any]
    object_payload: dict[str, Any] | None = None
    evidence_records: list[dict[str, Any]] = Field(default_factory=list)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)
    cross_validation_results: list[dict[str, Any]] = Field(default_factory=list)
    dual_model_results: list[dict[str, Any]] = Field(default_factory=list)
    related_objects: dict[str, Any] = Field(default_factory=dict)
    review_records: list[dict[str, Any]] = Field(default_factory=list)
    llm_trace: dict[str, Any] = Field(default_factory=dict)
    editable_fields: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    latest_validation_summary: dict[str, Any] = Field(default_factory=dict)
    gating: MirrorReviewGating = Field(default_factory=MirrorReviewGating)
    recommended_review_priority: str = "normal"
    object_category: str = "domain_object"


class MirrorReviewActionRequest(BaseModel):
    target_type: str
    target_id: uuid.UUID
    action: Literal[
        "approve", "reject", "needs_revision", "edit", "comment",
        "accept_signal", "dismiss_signal", "flag_for_followup",
    ]
    reviewer: str
    reviewer_note: str | None = None
    edit_patch_json: dict[str, Any] = Field(default_factory=dict)
    allow_with_warnings: bool = True
    acknowledge_risk_flags: bool = False

    @field_validator("reviewer")
    @classmethod
    def reviewer_not_empty(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("reviewer is required")
        return v.strip()


class MirrorReviewActionResponse(BaseModel):
    review_record_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    action: str
    from_mirror_status: str | None = None
    to_mirror_status: str | None = None
    from_review_status: str | None = None
    to_review_status: str | None = None
    promotion_status: str | None = None
    updated_object: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class MirrorReviewRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    action: str
    from_mirror_status: str | None
    to_mirror_status: str | None
    from_review_status: str | None
    to_review_status: str | None
    from_promotion_status: str | None
    to_promotion_status: str | None
    reviewer: str
    reviewer_note: str | None
    edit_patch_json: dict[str, Any]
    before_json: dict[str, Any]
    after_json: dict[str, Any]
    validation_summary_json: dict[str, Any]
    evidence_summary_json: dict[str, Any]
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    source_atlas: str | None
    source_version: str | None
    granularity_level: str | None
    granularity_family: str | None
    created_at: datetime


class MirrorReviewRecordListResponse(BaseModel):
    items: list[MirrorReviewRecordRead]
    total: int
    limit: int
    offset: int


class MirrorReviewTargetTypeInfo(BaseModel):
    target_type: str
    label: str
    category: str
    supported_actions: list[str]
    description: str


class MirrorReviewTargetTypesResponse(BaseModel):
    items: list[MirrorReviewTargetTypeInfo]
