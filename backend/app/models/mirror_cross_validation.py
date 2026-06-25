"""Mirror KG circuit-projection cross validation ORM models (Step 8.11).

Deterministic comparison of circuit_to_projection vs projection_to_circuit memberships.
NOT final_* / kg_*; NOT LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MirrorCircuitProjectionCrossValidationRun(Base):
    __tablename__ = "mirror_circuit_projection_cross_validation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    membership_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_supported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projection_supported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bidirectionally_supported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    insufficient_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_membership_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    apply_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MirrorCircuitProjectionCrossValidationResult(Base):
    __tablename__ = "mirror_circuit_projection_cross_validation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_circuit_projection_cross_validation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    circuit_to_projection_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_circuit_projection_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    projection_to_circuit_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_circuit_projection_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    support_level: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    agreement_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    source_step_agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    target_step_agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    direction_agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    scope_agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    conflict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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
