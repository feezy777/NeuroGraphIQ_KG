"""Final KG read schemas (Step 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinalRegionConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_mirror_connection_id: uuid.UUID | None = None
    source_region_candidate_id: uuid.UUID | None = None
    target_region_candidate_id: uuid.UUID | None = None
    source_region_final_id: uuid.UUID | None = None
    target_region_final_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    review_record_id: uuid.UUID | None = None
    promotion_record_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    connection_type: str
    directionality: str
    strength: str | None = None
    modality: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    final_status: str
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FinalRegionFunctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_mirror_function_id: uuid.UUID | None = None
    region_candidate_id: uuid.UUID | None = None
    region_final_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    review_record_id: uuid.UUID | None = None
    promotion_record_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    function_term: str
    function_category: str
    relation_type: str
    confidence: float | None = None
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    final_status: str
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FinalRegionCircuitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_mirror_circuit_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    review_record_id: uuid.UUID | None = None
    promotion_record_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    circuit_name: str
    circuit_type: str
    function_association: str | None = None
    description: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    final_status: str
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FinalCircuitRegionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    final_circuit_id: uuid.UUID
    source_mirror_circuit_region_id: uuid.UUID | None = None
    region_candidate_id: uuid.UUID | None = None
    region_final_id: uuid.UUID | None = None
    role: str
    sort_order: int
    created_at: datetime


class FinalKgTripleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_mirror_triple_id: uuid.UUID | None = None
    subject_type: str
    subject_id: uuid.UUID | None = None
    subject_label: str
    predicate: str
    object_type: str
    object_id: uuid.UUID | None = None
    object_label: str
    triple_scope: str
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    review_record_id: uuid.UUID | None = None
    promotion_record_id: uuid.UUID | None = None
    source_final_connection_id: uuid.UUID | None = None
    source_final_function_id: uuid.UUID | None = None
    source_final_circuit_id: uuid.UUID | None = None
    source_mirror_connection_id: uuid.UUID | None = None
    source_mirror_function_id: uuid.UUID | None = None
    source_mirror_circuit_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    final_status: str
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    normalized_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FinalEvidenceRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evidence_target_type: str
    evidence_target_id: uuid.UUID
    source_mirror_evidence_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    review_record_id: uuid.UUID | None = None
    promotion_record_id: uuid.UUID | None = None
    evidence_type: str
    evidence_text: str
    source_document_id: uuid.UUID | None = None
    source_reference_text: str | None = None
    citation_json: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    uncertainty_reason: str | None = None
    created_at: datetime


class FinalListResponse(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int
