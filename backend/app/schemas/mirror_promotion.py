"""Mirror KG promotion schemas (Step 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MirrorPromotionTargetType(StrEnum):
    connection = "connection"
    function = "function"
    circuit = "circuit"
    triple = "triple"


class MirrorPromotionRunStatus(StrEnum):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MirrorPromotionRecordStatus(StrEnum):
    promoted = "promoted"
    skipped_duplicate = "skipped_duplicate"
    skipped_ineligible = "skipped_ineligible"
    failed = "failed"


class MirrorPromotionScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_status: list[str] | None = None
    review_status: list[str] | None = None
    promotion_status: list[str] | None = None


class MirrorPromotionRequest(BaseModel):
    target_types: list[str]
    scope: MirrorPromotionScope | None = None
    connection_ids: list[uuid.UUID] | None = None
    function_ids: list[uuid.UUID] | None = None
    circuit_ids: list[uuid.UUID] | None = None
    triple_ids: list[uuid.UUID] | None = None
    dry_run: bool = True
    operator: str | None = None
    reason: str | None = None
    confirmation_text: str | None = None
    limit: int = Field(default=1000, ge=1, le=5000)


class MirrorPromotionPreviewItem(BaseModel):
    target_type: str
    mirror_target_id: uuid.UUID
    display_label: str
    eligible: bool
    ineligible_reason: str | None = None
    final_target_type: str | None = None
    planned_action: str | None = None
    duplicate: bool = False
    confidence: float | None = None
    review_record_id: uuid.UUID | None = None
    validation_summary: dict[str, Any] | None = None


class MirrorPromotionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    dry_run: bool
    required_confirmation: str | None = None
    object_count: int = 0
    eligible_count: int = 0
    promoted_count: int = 0
    skipped_duplicate_count: int = 0
    skipped_ineligible_count: int = 0
    failed_count: int = 0
    preview_items: list[MirrorPromotionPreviewItem] = Field(default_factory=list)
    promotion_record_ids: list[uuid.UUID] = Field(default_factory=list)
    final_object_ids: dict[str, list[uuid.UUID]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class MirrorPromotionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_types: list[str]
    scope_json: dict[str, Any] = Field(default_factory=dict)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    status: str
    object_count: int
    eligible_count: int
    promoted_count: int
    skipped_duplicate_count: int
    skipped_ineligible_count: int
    failed_count: int
    dry_run: bool
    confirmation_text: str | None = None
    required_confirmation: str | None = None
    operator: str | None = None
    reason: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class MirrorPromotionRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    target_type: str
    mirror_target_id: uuid.UUID
    final_target_type: str | None = None
    final_target_id: uuid.UUID | None = None
    review_record_id: uuid.UUID | None = None
    status: str
    message: str | None = None
    before_mirror_json: dict[str, Any] = Field(default_factory=dict)
    after_mirror_json: dict[str, Any] = Field(default_factory=dict)
    final_object_json: dict[str, Any] = Field(default_factory=dict)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    created_at: datetime


class MirrorPromotionRunDetail(MirrorPromotionRunRead):
    records_summary: dict[str, int] = Field(default_factory=dict)


class MirrorPromotionRunListResponse(BaseModel):
    items: list[MirrorPromotionRunRead]
    total: int
    limit: int
    offset: int


class MirrorPromotionRecordListResponse(BaseModel):
    items: list[MirrorPromotionRecordRead]
    total: int
    limit: int
    offset: int
