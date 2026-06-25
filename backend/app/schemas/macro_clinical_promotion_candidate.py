"""Promotion candidate list/preview schemas (Step 10.6.6)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

PromotionReadiness = Literal["ready", "needs_review", "blocked"]


class PromotionCandidateSourceInfo(BaseModel):
    target_type: str
    source_table: str
    formal_table: str
    formal_schema: str = "macro_clinical"
    model_name: str


class CircuitFunctionPromotionCandidateItem(BaseModel):
    id: uuid.UUID
    circuit_id: uuid.UUID
    function_term_en: str | None = None
    function_term_cn: str | None = None
    function_domain: str | None = None
    function_role: str | None = None
    effect_type: str | None = None
    confidence_score: float | None = None
    evidence_level: str | None = None
    review_status: str
    promotion_status: str
    validation_status: str | None = None
    status: str | None = None
    readiness: PromotionReadiness
    missing_required_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CircuitFunctionPromotionCandidateListResponse(BaseModel):
    target_type: str = "circuit_function"
    source_table: str = "mirror_circuit_functions"
    formal_table: str = "macro_clinical.circuit_function"
    source: PromotionCandidateSourceInfo
    items: list[CircuitFunctionPromotionCandidateItem]
    total: int
    limit: int
    offset: int
    warnings: list[str] = Field(default_factory=list)


class CircuitFunctionPromotionPreviewResponse(BaseModel):
    target_type: str = "circuit_function"
    source_id: uuid.UUID
    source_table: str = "mirror_circuit_functions"
    formal_table: str = "macro_clinical.circuit_function"
    formal_payload_preview: dict[str, Any]
    readiness: PromotionReadiness
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    review_status: str
    promotion_status: str
    actual_promotion_allowed: bool = False


class CircuitFunctionPromotionAttemptResponse(BaseModel):
    allowed: bool
    code: str
    message: str
    readiness: PromotionReadiness | None = None
