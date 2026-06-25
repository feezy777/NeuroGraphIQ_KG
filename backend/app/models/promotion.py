from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FinalBrainRegion(Base):
    """Official (final) brain region promoted from an approved candidate.

    Separate table from candidate_brain_regions (never merged). Only the Promotion
    module writes this table. Never written to kg_* / legacy staging_*.
    Full lineage back to candidate / raw label / batch / resource is preserved.
    """

    __tablename__ = "final_brain_regions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_parse_runs.id", ondelete="RESTRICT"), nullable=False
    )
    generation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_generation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_raw_label_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_aal3_region_labels.id", ondelete="RESTRICT"),
        nullable=False,
    )
    latest_review_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_review_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    latest_validation_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_rule_validation_results.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_label_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    label_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False)
    std_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    en_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cn_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    laterality: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    region_base_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    promoted_by: Mapped[str] = mapped_column(String(256), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PromotionRecord(Base):
    """One promotion attempt for a candidate (audit trail of candidate -> final).

    Records before/after snapshots and the candidate status transition
    (manual_approved -> promoted_to_final). Does NOT write kg_* / legacy staging_*.
    """

    __tablename__ = "promotion_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    final_region_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("final_brain_regions.id", ondelete="RESTRICT"), nullable=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_parse_runs.id", ondelete="RESTRICT"), nullable=False
    )
    generation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_generation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_raw_label_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_aal3_region_labels.id", ondelete="RESTRICT"),
        nullable=False,
    )
    latest_review_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_review_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    latest_validation_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_rule_validation_results.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    from_status: Mapped[str] = mapped_column(String(64), nullable=False)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    promoted_by: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    after_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
