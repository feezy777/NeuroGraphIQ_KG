from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _empty_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class CompositeWorkflowType(StrEnum):
    connection_with_function = "connection_with_function"
    circuit_with_function_steps = "circuit_with_function_steps"
    triple_generation = "triple_generation"


class CompositeWorkflowStatus(StrEnum):
    pending = "pending"
    running = "running"
    pause_requested = "pause_requested"
    paused = "paused"
    cancelling = "cancelling"
    cancelled = "cancelled"
    cleanup_in_progress = "cleanup_in_progress"
    cleanup_done = "cleanup_done"
    cleanup_failed = "cleanup_failed"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    no_edges = "no_edges"
    failed = "failed"
    dry_run = "dry_run"


class CompositeStepStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    skipped = "skipped"
    skipped_no_projection = "skipped_no_projection"
    skipped_dependency_failed = "skipped_dependency_failed"
    cancelled = "cancelled"
    failed = "failed"


class CompositeWorkflowRunRequest(BaseModel):
    workflow_type: CompositeWorkflowType
    provider: str = "deepseek"
    model_name: str | None = None
    dry_run: bool = True
    candidate_ids: list[uuid.UUID] = Field(default_factory=list)
    candidate_pool_id: uuid.UUID | None = Field(
        default=None,
        description="When set, resolve candidate_ids from this pool instead of using the candidate_ids field"
    )
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    create_mirror_records: bool = True
    create_triples: bool = True
    create_evidence: bool = True
    include_region_context: bool = True
    include_existing_context: bool = True
    explicit_batching_enabled: bool = False
    batch_strategy: str | None = None
    batch_size: int | None = None
    notes: str | None = None
    debug_max_packs: int | None = Field(default=None, ge=1, le=500)
    debug_single_pack: bool = False
    max_circuits: int | None = Field(default=None, ge=1, le=5000)
    max_tokens: int | None = Field(default=None, ge=256, le=8192)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    dry_run_sample_pack: bool = False
    prompt_template_key: str | None = None
    prompt_overrides: dict[str, str] | None = None
    parse_error_fail_fast_enabled: bool = True
    parse_error_fail_fast_threshold: int = Field(default=3, ge=1, le=20)

    @field_validator("resource_id", "batch_id", mode="before")
    @classmethod
    def empty_uuid_to_none(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @field_validator(
        "source_atlas",
        "source_version",
        "granularity_level",
        "granularity_family",
        "batch_strategy",
        "notes",
        "model_name",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @field_validator("candidate_ids", mode="before")
    @classmethod
    def clean_candidate_ids(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [v for v in value if not (isinstance(v, str) and v.strip() == "")]
        return value


class CompositeWorkflowStepRead(BaseModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID
    step_order: int
    step_key: str
    step_label: str | None = None
    status: CompositeStepStatus
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    created_counts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    execution_summary: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CompositeWorkflowCreatedTarget(BaseModel):
    target_type: str
    target_table: str | None = None
    ids: list[str] = Field(default_factory=list)
    count: int = 0
    step_key: str | None = None


class CompositeWorkflowRunResponse(BaseModel):
    workflow_run_id: uuid.UUID
    workflow_type: CompositeWorkflowType
    status: CompositeWorkflowStatus
    dry_run: bool
    candidate_count: int
    pair_count: int
    steps: list[CompositeWorkflowStepRead]
    progress_percent: float = 0.0
    result_summary: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    display_status: str | None = None
    semantic_status: str | None = None
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    created_targets: list[CompositeWorkflowCreatedTarget] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


class CompositeWorkflowStartResponse(BaseModel):
    workflow_run_id: uuid.UUID
    workflow_type: CompositeWorkflowType
    status: CompositeWorkflowStatus
    dry_run: bool
    candidate_count: int
    pair_count: int
    steps: list[CompositeWorkflowStepRead]
    progress_percent: float = 0.0
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompositeWorkflowRunRead(BaseModel):
    id: uuid.UUID
    workflow_type: CompositeWorkflowType
    status: CompositeWorkflowStatus
    provider: str | None = None
    model_name: str | None = None
    dry_run: bool
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    candidate_count: int
    pair_count: int
    progress_percent: float = 0.0
    result_summary: dict[str, Any] = Field(default_factory=dict)
    provider_audit: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    outcome: str | None = None
    display_status: str | None = None
    semantic_status: str | None = None
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    steps: list[CompositeWorkflowStepRead] = Field(default_factory=list)


class CompositeWorkflowRunListResponse(BaseModel):
    items: list[CompositeWorkflowRunRead]
    total: int
    limit: int
    offset: int


class CompositeWorkflowStepListResponse(BaseModel):
    items: list[CompositeWorkflowStepRead]
    total: int


class CompositeWorkflowCancelRequest(BaseModel):
    cleanup: bool = True
    reason: str = "user_closed_modal"


class CompositeWorkflowCancelResponse(BaseModel):
    workflow_run_id: uuid.UUID
    status: CompositeWorkflowStatus
    cleanup: bool
    deleted: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CompositeWorkflowRawResponseItem(BaseModel):
    step_key: str
    pack_id: int | str | None = None
    status: str | None = None
    response_char_count: int = 0
    raw_response_preview: str | None = None
    parse_error: str | None = None
    parse_error_type: str | None = None


class CompositeWorkflowRawResponsesDebugResponse(BaseModel):
    workflow_run_id: uuid.UUID
    items: list[CompositeWorkflowRawResponseItem] = Field(default_factory=list)
    diagnostic_error: str | None = None
