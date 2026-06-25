"""Pydantic schemas for Promotion to final_* Module.

Promotion is the controlled move of an approved candidate into the official store.
Only manual_approved candidates may be promoted. Promotion writes final_brain_regions
(a separate table from candidate_brain_regions) and never kg_* / legacy staging_*.
The candidate advances manual_approved -> promoted_to_final.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PromotionStatus(str, Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class FinalRegionStatus(str, Enum):
    active = "active"
    archived = "archived"


class PromoteRequest(BaseModel):
    promoted_by: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=4000)


class FinalBrainRegionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    resource_id: uuid.UUID
    batch_id: uuid.UUID
    parse_run_id: uuid.UUID
    generation_run_id: uuid.UUID
    source_file_id: uuid.UUID
    source_raw_label_id: uuid.UUID
    latest_review_record_id: uuid.UUID | None
    latest_validation_result_id: uuid.UUID | None
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
    status: FinalRegionStatus
    promoted_by: str
    promoted_at: datetime
    created_at: datetime
    updated_at: datetime


class PromotionRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    final_region_id: uuid.UUID | None
    resource_id: uuid.UUID
    batch_id: uuid.UUID
    parse_run_id: uuid.UUID
    generation_run_id: uuid.UUID
    source_file_id: uuid.UUID
    source_raw_label_id: uuid.UUID
    latest_review_record_id: uuid.UUID | None
    latest_validation_result_id: uuid.UUID | None
    status: PromotionStatus
    from_status: str
    to_status: str
    promoted_by: str
    reason: str | None
    before_snapshot: dict
    after_snapshot: dict
    error_message: str | None
    created_at: datetime


class PromoteResponse(BaseModel):
    final_region: FinalBrainRegionRead
    record: PromotionRecordRead


class FinalBrainRegionListResponse(BaseModel):
    items: list[FinalBrainRegionRead]
    total: int
    limit: int
    offset: int


class PromotionRecordListResponse(BaseModel):
    items: list[PromotionRecordRead]
    total: int
    limit: int
    offset: int


class PromotionOptionsResponse(BaseModel):
    promotion_status: list[str]
    final_region_status: list[str]
    promotable_candidate_status: str
    promoted_candidate_status: str
