"""Final macro_clinical ORM models (Step 8.15)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FinalProjection(Base):
    __tablename__ = "final_projections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    final_uid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    source_mirror_type: Mapped[str] = mapped_column(String(64), nullable=False, default="projection")
    source_mirror_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    promotion_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    promotion_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    projection_type: Mapped[str] = mapped_column(String(64), nullable=False)
    directionality: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    strength: Mapped[str | None] = mapped_column(String(64), nullable=True)
    modality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cross_validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dual_model_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinalCircuitStep(Base):
    __tablename__ = "final_circuit_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    final_uid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    source_mirror_type: Mapped[str] = mapped_column(String(64), nullable=False, default="circuit_step")
    source_mirror_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    promotion_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    promotion_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("final_region_circuits.id", ondelete="CASCADE"), nullable=False)
    mirror_circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(512), nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dual_model_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinalCircuitFunction(Base):
    __tablename__ = "final_circuit_functions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    final_uid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    source_mirror_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_mirror_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    promotion_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    promotion_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("final_region_circuits.id", ondelete="CASCADE"), nullable=False)
    mirror_circuit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    function_term: Mapped[str] = mapped_column(String(512), nullable=False)
    function_category: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="associated_with")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dual_model_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinalProjectionFunction(Base):
    __tablename__ = "final_projection_functions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    final_uid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    source_mirror_type: Mapped[str] = mapped_column(String(64), nullable=False, default="projection_function")
    source_mirror_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    promotion_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    promotion_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_projection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("final_projections.id", ondelete="CASCADE"), nullable=False)
    mirror_projection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    function_term: Mapped[str] = mapped_column(String(512), nullable=False)
    function_category: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="associated_with")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dual_model_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinalCircuitProjectionMembership(Base):
    __tablename__ = "final_circuit_projection_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    final_uid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    source_mirror_type: Mapped[str] = mapped_column(String(64), nullable=False, default="circuit_projection_membership")
    source_mirror_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    promotion_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    promotion_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("final_region_circuits.id", ondelete="CASCADE"), nullable=False)
    final_projection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("final_projections.id", ondelete="CASCADE"), nullable=False)
    final_source_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("final_circuit_steps.id", ondelete="SET NULL"), nullable=True)
    final_target_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("final_circuit_steps.id", ondelete="SET NULL"), nullable=True)
    mirror_circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mirror_projection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mirror_source_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    mirror_target_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role_in_circuit: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    source_method: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    verification_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unverified")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cross_validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dual_model_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinalMacroClinicalPromotionRun(Base):
    __tablename__ = "final_macro_clinical_promotion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    target_types: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=False)
    confirm_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promoted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class FinalMacroClinicalPromotionRecord(Base):
    __tablename__ = "final_macro_clinical_promotion_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("final_macro_clinical_promotion_runs.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mirror_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    final_table: Mapped[str | None] = mapped_column(String(128), nullable=True)
    final_object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligibility_status: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_flags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cross_validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dual_model_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    duplicate_of_final_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
