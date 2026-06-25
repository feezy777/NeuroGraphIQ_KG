"""Pydantic schemas for dual-model verification execution (Step 8.12)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.mirror_macro_clinical import (
    MirrorDualModelVerificationResultRead,
    MirrorDualModelVerificationRunRead,
)


class DualModelVerificationObjectType:
    circuit = "circuit"
    projection = "projection"
    circuit_projection_membership = "circuit_projection_membership"
    projection_function = "projection_function"
    circuit_step = "circuit_step"
    triple = "triple"


VALID_DUAL_MODEL_OBJECT_TYPES = frozenset({
    DualModelVerificationObjectType.circuit,
    DualModelVerificationObjectType.projection,
    DualModelVerificationObjectType.circuit_projection_membership,
    DualModelVerificationObjectType.projection_function,
    DualModelVerificationObjectType.circuit_step,
    DualModelVerificationObjectType.triple,
})


class DualModelDecision:
    support = "support"
    reject = "reject"
    uncertain = "uncertain"
    insufficient_information = "insufficient_information"
    unknown = "unknown"


class DualModelConsensusStatus:
    consensus_supported = "consensus_supported"
    consensus_rejected = "consensus_rejected"
    model_conflict = "model_conflict"
    insufficient_information = "insufficient_information"
    needs_human_review = "needs_human_review"
    unknown = "unknown"


class DualModelReviewPriority:
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class DualModelVerificationScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class DualModelVerificationRequest(BaseModel):
    object_type: str
    object_ids: list[uuid.UUID] | None = None
    scope: DualModelVerificationScope | None = None
    model_a_provider: str = "deepseek"
    model_a_name: str | None = None
    model_b_provider: str = "kimi"
    model_b_name: str | None = None
    prompt_template_key: str = "dual_model_verification_v1"
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=3000, ge=256, le=8192)
    dry_run: bool = False
    max_objects: int = Field(default=50, ge=1, le=200)
    include_cross_validation_context: bool = True
    include_evidence_context: bool = True
    include_review_context: bool = False
    create_results: bool = True


class DualModelVerificationResultPreview(BaseModel):
    object_type: str
    object_id: uuid.UUID
    model_a_decision: str | None = None
    model_a_confidence: float | None = None
    model_b_decision: str | None = None
    model_b_confidence: float | None = None
    consensus_status: str
    consensus_score: float | None = None
    conflict_summary: str | None = None
    recommended_review_priority: str
    evidence_text: str | None = None
    uncertainty_reason: str | None = None


class DualModelVerificationResponse(BaseModel):
    run_id: uuid.UUID | None = None
    object_type: str
    object_count: int = 0
    model_a_provider: str | None = None
    model_a_run_id: uuid.UUID | None = None
    model_b_provider: str | None = None
    model_b_run_id: uuid.UUID | None = None
    consensus_supported_count: int = 0
    consensus_rejected_count: int = 0
    model_conflict_count: int = 0
    insufficient_information_count: int = 0
    needs_human_review_count: int = 0
    result_count: int = 0
    dry_run: bool
    model_a_system_prompt: str | None = None
    model_a_user_prompt: str | None = None
    model_b_system_prompt: str | None = None
    model_b_user_prompt: str | None = None
    results_preview: list[DualModelVerificationResultPreview] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DualModelVerificationRunListResponse(BaseModel):
    items: list[MirrorDualModelVerificationRunRead]
    total: int
    limit: int
    offset: int


class DualModelVerificationResultListResponse(BaseModel):
    items: list[MirrorDualModelVerificationResultRead]
    total: int
    limit: int
    offset: int
