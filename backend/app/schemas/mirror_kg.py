"""Pydantic schemas for Mirror KG (Step 2).

Mirror KG is a precursor layer — NOT final facts. Create schemas enforce defaults
and block client-side promotion; same-granularity validation runs in service layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums (string constants)
# ---------------------------------------------------------------------------


class MirrorStatus(str):
    llm_suggested = "llm_suggested"
    rule_checked = "rule_checked"
    human_review_pending = "human_review_pending"
    human_approved = "human_approved"
    human_rejected = "human_rejected"
    promoted_to_final = "promoted_to_final"
    superseded = "superseded"


class MirrorReviewStatus(str):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    needs_revision = "needs_revision"
    not_required = "not_required"


class MirrorPromotionStatus(str):
    not_promoted = "not_promoted"
    promoted = "promoted"
    failed = "failed"
    blocked = "blocked"


class ConnectionType(str):
    structural_connection = "structural_connection"
    functional_connectivity = "functional_connectivity"
    effective_connectivity = "effective_connectivity"
    projection = "projection"
    association = "association"
    coactivation = "coactivation"
    uncertain_connection = "uncertain_connection"
    unknown = "unknown"


class Directionality(str):
    directed = "directed"
    undirected = "undirected"
    bidirectional = "bidirectional"
    unknown = "unknown"


class FunctionCategory(str):
    motor = "motor"
    sensory = "sensory"
    visual = "visual"
    auditory = "auditory"
    language = "language"
    memory = "memory"
    emotion = "emotion"
    executive_control = "executive_control"
    attention = "attention"
    autonomic = "autonomic"
    default_mode = "default_mode"
    salience = "salience"
    reward = "reward"
    cognitive = "cognitive"
    unknown = "unknown"


class FunctionRelationType(str):
    involved_in = "involved_in"
    associated_with = "associated_with"
    necessary_for = "necessary_for"
    modulates = "modulates"
    participates_in = "participates_in"
    uncertain_association = "uncertain_association"
    unknown = "unknown"


class CircuitType(str):
    sensory_circuit = "sensory_circuit"
    motor_circuit = "motor_circuit"
    limbic_circuit = "limbic_circuit"
    cognitive_control_circuit = "cognitive_control_circuit"
    default_mode_related = "default_mode_related"
    salience_related = "salience_related"
    memory_related = "memory_related"
    reward_related = "reward_related"
    language_related = "language_related"
    attention_related = "attention_related"
    uncertain_circuit = "uncertain_circuit"
    unknown = "unknown"


class TripleSubjectType(str):
    region_candidate = "region_candidate"
    region_final = "region_final"
    connection = "connection"
    circuit = "circuit"
    function = "function"
    term = "term"
    literal = "literal"
    unknown = "unknown"


class TripleObjectType(str):
    region_candidate = "region_candidate"
    region_final = "region_final"
    connection = "connection"
    circuit = "circuit"
    function = "function"
    term = "term"
    literal = "literal"
    unknown = "unknown"


class TripleScope(str):
    same_granularity = "same_granularity"
    cross_granularity_mapping = "cross_granularity_mapping"
    evidence_link = "evidence_link"
    unknown = "unknown"


class EvidenceTargetType(str):
    mirror_connection = "mirror_connection"
    mirror_function = "mirror_function"
    mirror_circuit = "mirror_circuit"
    mirror_triple = "mirror_triple"
    unknown = "unknown"


class EvidenceType(str):
    llm_explanation = "llm_explanation"
    literature = "literature"
    curated_database = "curated_database"
    manual_note = "manual_note"
    rule_validation = "rule_validation"
    unknown = "unknown"


class CircuitRegionRole(str):
    participant = "participant"
    source = "source"
    target = "target"
    hub = "hub"
    relay = "relay"
    modulator = "modulator"
    unknown = "unknown"


def _reject_promoted_status(v: str | None, field_name: str) -> str | None:
    if v == MirrorPromotionStatus.promoted:
        raise ValueError(f"{field_name} cannot be set to 'promoted' via create API")
    return v


class MirrorCircuitRegionCreate(BaseModel):
    region_candidate_id: uuid.UUID | None = None
    region_final_id: uuid.UUID | None = None
    role: str = CircuitRegionRole.participant
    sort_order: int = 0


class MirrorCircuitRegionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    circuit_id: uuid.UUID
    region_candidate_id: uuid.UUID | None
    region_final_id: uuid.UUID | None
    role: str
    sort_order: int
    created_at: datetime


class MirrorRegionConnectionCreate(BaseModel):
    source_region_candidate_id: uuid.UUID | None = None
    target_region_candidate_id: uuid.UUID | None = None
    source_region_final_id: uuid.UUID | None = None
    target_region_final_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    connection_type: str
    directionality: str = Directionality.unknown
    strength: str | None = None
    modality: str | None = None
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


class MirrorRegionConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_region_candidate_id: uuid.UUID | None
    target_region_candidate_id: uuid.UUID | None
    source_region_final_id: uuid.UUID | None
    target_region_final_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
    connection_type: str
    directionality: str
    strength: str | None
    modality: str | None
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
        """Alias for overlay storage (formal_field_overlay lives in normalized_payload_json)."""
        return self.normalized_payload_json or {}


class MirrorRegionConnectionListResponse(BaseModel):
    items: list[MirrorRegionConnectionRead]
    total: int
    limit: int
    offset: int


class MirrorRegionFunctionCreate(BaseModel):
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
    function_term: str
    region_name_cn: str | None = None
    region_name_en: str | None = None
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

    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str) -> str:
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorRegionFunctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
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
    function_term: str
    region_name_cn: str | None = None
    region_name_en: str | None = None
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


class MirrorRegionFunctionListResponse(BaseModel):
    items: list[MirrorRegionFunctionRead]
    total: int
    limit: int
    offset: int


class MirrorRegionCircuitCreate(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
    circuit_name: str
    circuit_type: str = CircuitType.unknown
    function_association: str | None = None
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
    circuit_regions: list[MirrorCircuitRegionCreate] = Field(default_factory=list)

    @field_validator("promotion_status")
    @classmethod
    def block_promoted(cls, v: str) -> str:
        return _reject_promoted_status(v, "promotion_status")  # type: ignore[return-value]


class MirrorRegionCircuitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
    circuit_name: str
    circuit_type: str
    function_association: str | None
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
    circuit_regions: list[MirrorCircuitRegionRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attributes(self) -> dict[str, Any]:
        return self.normalized_payload_json or {}


class MirrorRegionCircuitListResponse(BaseModel):
    items: list[MirrorRegionCircuitRead]
    total: int
    limit: int
    offset: int


class MirrorKgTripleCreate(BaseModel):
    subject_type: str
    subject_id: uuid.UUID | None = None
    subject_label: str
    predicate: str
    object_type: str
    object_id: uuid.UUID | None = None
    object_label: str
    triple_scope: str = TripleScope.same_granularity
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    source_mirror_connection_id: uuid.UUID | None = None
    source_mirror_function_id: uuid.UUID | None = None
    source_mirror_circuit_id: uuid.UUID | None = None
    granularity_level: str
    granularity_family: str | None = None
    source_atlas: str
    source_version: str | None = None
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


class MirrorKgTripleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID | None
    subject_label: str
    predicate: str
    object_type: str
    object_id: uuid.UUID | None
    object_label: str
    triple_scope: str
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    source_mirror_connection_id: uuid.UUID | None
    source_mirror_function_id: uuid.UUID | None
    source_mirror_circuit_id: uuid.UUID | None
    granularity_level: str
    granularity_family: str | None
    source_atlas: str
    source_version: str | None
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


class MirrorKgTripleListResponse(BaseModel):
    items: list[MirrorKgTripleRead]
    total: int
    limit: int
    offset: int


class MirrorEvidenceRecordCreate(BaseModel):
    evidence_target_type: str
    evidence_target_id: uuid.UUID
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    evidence_type: str = EvidenceType.llm_explanation
    evidence_text: str
    source_document_id: uuid.UUID | None = None
    source_reference_text: str | None = None
    citation_json: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    uncertainty_reason: str | None = None


class MirrorEvidenceRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evidence_target_type: str
    evidence_target_id: uuid.UUID
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None
    llm_item_id: uuid.UUID | None
    evidence_type: str
    evidence_text: str
    source_document_id: uuid.UUID | None
    source_reference_text: str | None
    citation_json: dict[str, Any]
    confidence: float | None = None
    uncertainty_reason: str | None
    created_at: datetime


class MirrorEvidenceRecordListResponse(BaseModel):
    items: list[MirrorEvidenceRecordRead]
    total: int
    limit: int
    offset: int


class MirrorTripleConsolidationScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class MirrorTripleConsolidationRequest(BaseModel):
    source_types: list[str] = Field(default_factory=lambda: ["connection", "function", "circuit"], min_length=1)
    scope: MirrorTripleConsolidationScope | None = None
    mirror_status: list[str] | None = None
    review_status: list[str] | None = None
    promotion_status: list[str] | None = None
    connection_ids: list[uuid.UUID] | None = None
    function_ids: list[uuid.UUID] | None = None
    circuit_ids: list[uuid.UUID] | None = None
    include_existing: bool = False
    dry_run: bool = True
    limit: int = Field(default=1000, ge=1, le=5000)


class MirrorTriplePreviewItem(BaseModel):
    subject_type: str
    subject_id: uuid.UUID | None = None
    subject_label: str
    predicate: str
    object_type: str
    object_id: uuid.UUID | None = None
    object_label: str
    source_type: str
    source_id: str
    confidence: float | None = None
    evidence_text: str | None = None
    duplicate: bool = False


class MirrorTripleConsolidationResponse(BaseModel):
    dry_run: bool
    source_counts: dict[str, int] = Field(default_factory=dict)
    planned_triple_count: int = 0
    created_triple_count: int = 0
    skipped_duplicate_count: int = 0
    skipped_invalid_count: int = 0
    existing_triple_count: int = 0
    created_triple_ids: list[uuid.UUID] = Field(default_factory=list)
    triples_preview: list[MirrorTriplePreviewItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
