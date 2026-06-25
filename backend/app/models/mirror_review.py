"""Mirror KG human review ORM models (Step 8).

Audit trail for manual review of mirror connections/functions/circuits/triples.
Separate from candidate_review_records — different semantic layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MirrorHumanReviewRecord(Base):
    __tablename__ = "mirror_human_review_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_mirror_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_mirror_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_review_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_review_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_promotion_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_promotion_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(256), nullable=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_patch_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
