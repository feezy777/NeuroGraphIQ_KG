"""Mirror KG macro_clinical alignment ORM models (Step 8.6).

circuit_step, projection_function, circuit_projection_membership, dual_model_verification.
NOT final_* / kg_*.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MirrorCircuitStep(Base):
    __tablename__ = "mirror_circuit_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    circuit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_circuits.id", ondelete="CASCADE"),
        nullable=False,
    )
    region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="SET NULL"),
        nullable=True,
    )
    region_final_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(512), nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorCircuitFunction(Base):
    __tablename__ = "mirror_circuit_functions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    circuit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_circuits.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    primary_evidence_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    function_term_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    function_term_cn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    function_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    function_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    effect_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_db: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True, default="active")
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    validation_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorProjectionFunction(Base):
    __tablename__ = "mirror_projection_functions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    projection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    function_term: Mapped[str] = mapped_column(String(512), nullable=False)
    function_category: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="associated_with")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorCircuitProjectionMembership(Base):
    __tablename__ = "mirror_circuit_projection_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    circuit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_circuits.id", ondelete="CASCADE"),
        nullable=False,
    )
    projection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_circuit_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_circuit_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role_in_circuit: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    source_method: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    verification_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unverified")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorDualModelVerificationRun(Base):
    __tablename__ = "mirror_dual_model_verification_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    verification_task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model_a_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="deepseek")
    model_a_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_a_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    model_b_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="kimi")
    model_b_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_b_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    source_atlas: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consensus_supported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consensus_rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insufficient_information_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_human_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MirrorDualModelVerificationResult(Base):
    __tablename__ = "mirror_dual_model_verification_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_dual_model_verification_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_a_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_a_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    model_a_confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    model_a_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model_b_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_b_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    model_b_confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    model_b_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    consensus_status: Mapped[str] = mapped_column(String(64), nullable=False)
    consensus_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    conflict_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_review_priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    source_atlas: Mapped[str | None] = mapped_column(String(128), nullable=True)
    granularity_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
