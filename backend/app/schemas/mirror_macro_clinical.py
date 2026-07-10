"""Pydantic schemas for Mirror KG macro_clinical alignment (Step 8.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.schemas.mirror_kg import (
    FunctionCategory,
    FunctionRelationType,
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
    _reject_promoted_status,
)


class MirrorCircuitStepType(str):
    region = "region"
    region_group = "region_group"
    relay = "relay"
    hub = "hub"
    modulator = "modulator"
    functional_stage = "functional_stage"
    unknown = "unknown"


class MirrorCircuitStepRole(str):
    source = "source"
    target = "target"
    relay = "relay"
    hub = "hub"
    modulator = "modulator"
    participant = "participant"
    unknown = "unknown"


class MirrorCircuitProjectionRole(str):
    main_path = "main_path"
    feedback = "feedback"
    feedforward = "feedforward"
    modulatory = "modulatory"
    relay = "relay"
    parallel_branch = "parallel_branch"
    unknown = "unknown"


class MirrorMembershipSourceMethod(str):
    circuit_to_projection = "circuit_to_projection"
    projection_to_circuit = "projection_to_circuit"
    dual_model_consensus = "dual_model_consensus"
    human_curated = "human_curated"
    deterministic = "deterministic"
    unknown = "unknown"


class MirrorMembershipVerificationStatus(str):
    unverified = "unverified"
    circuit_supported = "circuit_supported"
    projection_supported = "projection_supported"
    bidirectionally_supported = "bidirectionally_supported"
    model_conflict = "model_conflict"
    human_approved = "human_approved"
    human_rejected = "human_rejected"
    unknown = "unknown"


class MirrorDualModelVerificationTaskType(str):
    circuit_projection_membership = "circuit_projection_membership"
    projection_function = "projection_function"
    circuit_step = "circuit_step"
    circuit = "circuit"
    projection = "projection"
    triple = "triple"
    unknown = "unknown"


class MirrorDualModelConsensusStatus(str):
    consensus_supported = "consensus_supported"
    consensus_rejected = "consensus_rejected"
    model_conflict = "model_conflict"
    insufficient_information = "insufficient_information"
    needs_human_review = "needs_human_review"
    unknown = "unknown"


class MirrorDualModelDecision(str):
    support = "support"
    reject = "reject"
    uncertain = "uncertain"
    insufficient_information = "insufficient_information"
    unknown = "unknown"


class MirrorReviewPriority(str):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class MirrorDualModelRunStatus(str):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MirrorCircuitStepCreate(BaseModel):
    circuit_id: uuid.UUID
    region_candidate_id: uuid.UUID | None = None
    region_final_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    step_order: int = Field(ge=0)
    step_name: str
    step_type: str = MirrorCircuitStepType.unknown
    role: str = MirrorCircuitStepRole.unknown
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    mirror_status: str = MirrorStatus.llm_suggested
    review_status: str = MirrorReviewStatus.pending
    promotion_status: str = MirrorPromotionStatus.not_promoted
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None

    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str) -> str:
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorCircuitStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    circuit_id: uuid.UUID
    region_candidate_id: uuid.UUID | None
    region_final_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
    step_order: int
    step_name: str
    step_type: str
    role: str
    description: str | None
    confidence: float | None = None
    evidence_text: str | None
    uncertainty_reason: str | None
    mirror_status: str
    review_status: str
    promotion_status: str
    raw_payload_json: dict[str, Any]
    normalized_payload_json: dict[str, Any]
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attributes(self) -> dict[str, Any]:
        return self.normalized_payload_json or {}


class MirrorCircuitStepListResponse(BaseModel):
    items: list[MirrorCircuitStepRead]
    total: int
    limit: int
    offset: int


class MirrorProjectionFunctionCreate(BaseModel):
    projection_id: uuid.UUID
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    function_term: str
    function_category: str = FunctionCategory.unknown
    relation_type: str = FunctionRelationType.associated_with
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    mirror_status: str = MirrorStatus.llm_suggested
    review_status: str = MirrorReviewStatus.pending
    promotion_status: str = MirrorPromotionStatus.not_promoted
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None

    @field_validator("function_term")
    @classmethod
    def function_term_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("function_term must not be empty")
        return v.strip()

    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str) -> str:
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorProjectionFunctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    projection_id: uuid.UUID
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
    connection_name_cn: str | None = None
    connection_name_en: str | None = None
    function_term: str
    function_category: str
    relation_type: str
    confidence: float | None = None
    evidence_text: str | None
    uncertainty_reason: str | None
    mirror_status: str
    review_status: str
    promotion_status: str
    raw_payload_json: dict[str, Any]
    normalized_payload_json: dict[str, Any]
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attributes(self) -> dict[str, Any]:
        return self.normalized_payload_json or {}


class MirrorProjectionFunctionListResponse(BaseModel):
    items: list[MirrorProjectionFunctionRead]
    total: int
    limit: int
    offset: int


class MirrorCircuitFunctionBase(BaseModel):
    circuit_id: uuid.UUID
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    primary_evidence_id: uuid.UUID | None = None
    external_code: str | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    function_term_en: str | None = None
    function_term_cn: str | None = None
    function_domain: str | None = None
    function_role: str | None = None
    effect_type: str | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_level: str | None = None
    description: str | None = None
    remark: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_db: str | None = None
    status: str | None = "active"
    mirror_status: str = MirrorStatus.llm_suggested
    review_status: str = MirrorReviewStatus.pending
    validation_status: str | None = None
    promotion_status: str = MirrorPromotionStatus.not_promoted
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_text: str | None = None
    provenance: str | None = None
    uncertainty_reason: str | None = None
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class MirrorCircuitFunctionCreate(MirrorCircuitFunctionBase):
    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str) -> str:
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorCircuitFunctionUpdate(BaseModel):
    function_term_en: str | None = None
    function_term_cn: str | None = None
    function_domain: str | None = None
    function_role: str | None = None
    effect_type: str | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_level: str | None = None
    description: str | None = None
    remark: str | None = None
    attributes: dict[str, Any] | None = None
    source_db: str | None = None
    status: str | None = None
    mirror_status: str | None = None
    review_status: str | None = None
    validation_status: str | None = None
    promotion_status: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_text: str | None = None
    provenance: str | None = None
    uncertainty_reason: str | None = None
    raw_payload_json: dict[str, Any] | None = None
    normalized_payload_json: dict[str, Any] | None = None
    updated_by: str | None = None

    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorCircuitFunctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    circuit_id: uuid.UUID
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    primary_evidence_id: uuid.UUID | None
    external_code: str | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
    function_term_en: str | None
    function_term_cn: str | None
    function_domain: str | None
    function_role: str | None
    effect_type: str | None
    confidence_score: float | None = None
    evidence_level: str | None
    description: str | None
    remark: str | None
    attributes: dict[str, Any]
    source_db: str | None
    status: str | None
    mirror_status: str
    review_status: str
    validation_status: str | None
    promotion_status: str
    confidence: float | None = None
    evidence_text: str | None
    provenance: str | None
    uncertainty_reason: str | None
    raw_payload_json: dict[str, Any]
    normalized_payload_json: dict[str, Any]
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("confidence_score", "confidence", mode="before")
    @classmethod
    def coerce_numeric(cls, v: Any) -> float | None:
        if v is None:
            return None
        return float(v)


class MirrorCircuitFunctionListResponse(BaseModel):
    items: list[MirrorCircuitFunctionRead]
    total: int
    limit: int
    offset: int
    warnings: list[str] = Field(default_factory=list)


class MirrorCircuitProjectionMembershipCreate(BaseModel):
    circuit_id: uuid.UUID
    projection_id: uuid.UUID
    source_step_id: uuid.UUID | None = None
    target_step_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    step_order: int | None = Field(default=None, ge=0)
    role_in_circuit: str = MirrorCircuitProjectionRole.unknown
    source_method: str = MirrorMembershipSourceMethod.unknown
    verification_status: str = MirrorMembershipVerificationStatus.unverified
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    mirror_status: str = MirrorStatus.llm_suggested
    review_status: str = MirrorReviewStatus.pending
    promotion_status: str = MirrorPromotionStatus.not_promoted
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None

    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str) -> str:
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorCircuitProjectionMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    circuit_id: uuid.UUID
    projection_id: uuid.UUID
    source_step_id: uuid.UUID | None
    target_step_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
    step_order: int | None
    role_in_circuit: str
    source_method: str
    verification_status: str
    confidence: float | None = None
    evidence_text: str | None
    uncertainty_reason: str | None
    mirror_status: str
    review_status: str
    promotion_status: str
    raw_payload_json: dict[str, Any]
    normalized_payload_json: dict[str, Any]
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attributes(self) -> dict[str, Any]:
        return self.normalized_payload_json or {}


class MirrorCircuitProjectionMembershipListResponse(BaseModel):
    items: list[MirrorCircuitProjectionMembershipRead]
    total: int
    limit: int
    offset: int


class MirrorDualModelVerificationRunCreate(BaseModel):
    verification_task_type: str
    model_a_provider: str = "deepseek"
    model_a_name: str | None = None
    model_a_run_id: uuid.UUID | None = None
    model_b_provider: str = "kimi"
    model_b_name: str | None = None
    model_b_run_id: uuid.UUID | None = None
    scope_json: dict[str, Any] = Field(default_factory=dict)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    status: str = MirrorDualModelRunStatus.created
    object_count: int = Field(default=0, ge=0)
    dry_run: bool = False
    error_message: str | None = None


class MirrorDualModelVerificationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    verification_task_type: str
    model_a_provider: str
    model_a_name: str | None
    model_a_run_id: uuid.UUID | None
    model_b_provider: str
    model_b_name: str | None
    model_b_run_id: uuid.UUID | None
    scope_json: dict[str, Any]
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    source_atlas: str | None
    source_version: str | None
    granularity_level: str | None
    granularity_family: str | None
    status: str
    object_count: int
    consensus_supported_count: int
    consensus_rejected_count: int
    model_conflict_count: int
    insufficient_information_count: int
    needs_human_review_count: int
    dry_run: bool
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class MirrorDualModelVerificationRunListResponse(BaseModel):
    items: list[MirrorDualModelVerificationRunRead]
    total: int
    limit: int
    offset: int


class MirrorDualModelVerificationResultCreate(BaseModel):
    run_id: uuid.UUID
    object_type: str
    object_id: uuid.UUID
    model_a_provider: str
    model_a_decision: str
    model_a_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_a_payload_json: dict[str, Any] = Field(default_factory=dict)
    model_b_provider: str
    model_b_decision: str
    model_b_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_b_payload_json: dict[str, Any] = Field(default_factory=dict)
    consensus_status: str
    consensus_score: float | None = Field(default=None, ge=0.0, le=1.0)
    conflict_summary: str | None = None
    recommended_review_priority: str = MirrorReviewPriority.normal
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class MirrorDualModelVerificationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    object_type: str
    object_id: uuid.UUID
    model_a_provider: str
    model_a_decision: str
    model_a_confidence: float | None = None
    model_a_payload_json: dict[str, Any]
    model_b_provider: str
    model_b_decision: str
    model_b_confidence: float | None = None
    model_b_payload_json: dict[str, Any]
    consensus_status: str
    consensus_score: float | None = None
    conflict_summary: str | None
    recommended_review_priority: str
    evidence_text: str | None
    uncertainty_reason: str | None
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    source_atlas: str | None
    granularity_level: str | None
    granularity_family: str | None
    created_at: datetime


class MirrorDualModelVerificationResultListResponse(BaseModel):
    items: list[MirrorDualModelVerificationResultRead]
    total: int
    limit: int
    offset: int
