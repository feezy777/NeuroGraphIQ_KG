"""Universal field completion API schemas (Step 10.3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TargetType(str, Enum):
    candidate_region = "candidate_region"
    projection = "projection"
    region_function = "region_function"
    circuit = "circuit"
    circuit_step = "circuit_step"
    projection_function = "projection_function"
    circuit_function = "circuit_function"
    circuit_projection_membership = "circuit_projection_membership"
    triple = "triple"
    evidence = "evidence"


class FieldScope(str, Enum):
    missing_only = "missing_only"
    selected_fields = "selected_fields"
    all_enrichable_fields = "all_enrichable_fields"


class OverwritePolicy(str, Enum):
    fill_missing_only = "fill_missing_only"
    suggest_only = "suggest_only"
    overwrite_with_review = "overwrite_with_review"


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    cancelled = "cancelled"
    dry_run = "dry_run"


class ItemStatus(str, Enum):
    prompt_preview = "prompt_preview"
    suggested = "suggested"
    applied = "applied"  # legacy; prefer applied_direct / applied_overlay
    applied_direct = "applied_direct"
    applied_overlay = "applied_overlay"
    skipped_existing_value = "skipped_existing_value"
    skipped_invalid_field = "skipped_invalid_field"
    skipped_readonly_field = "skipped_readonly_field"
    skipped_target_not_found = "skipped_target_not_found"
    failed = "failed"


class UniversalFieldCompletionRequest(BaseModel):
    provider: str = "deepseek"
    model_name: str | None = None
    target_type: TargetType
    target_ids: list[uuid.UUID] = Field(..., min_length=1)
    field_scope: FieldScope = FieldScope.missing_only
    selected_fields: list[str] = Field(default_factory=list)
    dry_run: bool = True
    create_mirror_updates: bool = True
    create_evidence: bool = False
    overwrite_policy: OverwritePolicy = OverwritePolicy.fill_missing_only
    include_existing_evidence: bool = True
    include_related_objects: bool = True
    include_provenance: bool = True
    prompt_template_key: str = "universal_field_completion_v1"
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    temperature: float = 0.2
    max_tokens: int = 2000


class FieldUpdateSummary(BaseModel):
    target_id: uuid.UUID
    field_name: str
    update_status: ItemStatus
    suggested_value: Any | None = None
    applied_value: Any | None = None


class UniversalFieldCompletionResponse(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    provider: str
    model_name: str | None
    target_type: TargetType
    target_count: int
    updated_count: int = 0
    suggested_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    applied_direct_count: int = 0
    applied_overlay_count: int = 0
    summary_json: dict[str, Any] = Field(default_factory=dict)
    field_updates: list[FieldUpdateSummary] = Field(default_factory=list)
    prompt_preview: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    dry_run: bool


class FieldCompletionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    field_name: str
    old_value_json: Any | None = None
    suggested_value_json: Any | None = None
    applied_value_json: Any | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    reasoning_summary: str | None = None
    uncertainty_reason: str | None = None
    update_status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class FieldCompletionStartResponse(BaseModel):
    """Returned when a non-dry-run field completion is launched asynchronously (202)."""

    run_id: uuid.UUID
    status: RunStatus
    provider: str
    model_name: str | None
    target_type: TargetType
    target_count: int
    dry_run: bool
    warnings: list[str] = Field(default_factory=list)


class FieldCompletionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    model_name: str | None
    target_type: str
    target_count: int
    field_scope: str
    selected_fields_json: list[Any]
    overwrite_policy: str
    dry_run: bool
    create_mirror_updates: bool
    create_evidence: bool
    status: str
    request_json: dict[str, Any]
    summary_json: dict[str, Any]
    warnings_json: list[Any]
    errors_json: list[Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class FieldCompletionRunDetail(FieldCompletionRunRead):
    items: list[FieldCompletionItemRead] = Field(default_factory=list)


class FieldCompletionRunListResponse(BaseModel):
    items: list[FieldCompletionRunRead]
    total: int


class FieldCompletionItemListResponse(BaseModel):
    items: list[FieldCompletionItemRead]
    total: int


class FieldCompletionRelatedGroup(BaseModel):
    target_type: str
    target_ids: list[uuid.UUID]
    count: int
    warnings: list[str] = Field(default_factory=list)


class FieldCompletionRelatedTargetsResponse(BaseModel):
    source_target_type: str
    source_target_ids: list[uuid.UUID]
    groups: list[FieldCompletionRelatedGroup]
    warnings: list[str] = Field(default_factory=list)


class FieldCompletionPromptTemplateItem(BaseModel):
    key: str
    title: str
    display_name: str | None = None
    target_type: str | None = None
    field_name: str | None = None
    template: str
    system_prompt: str


class FieldCompletionPromptTemplateListResponse(BaseModel):
    items: list[FieldCompletionPromptTemplateItem]
