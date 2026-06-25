from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportBatchRollbackRecord(Base):
    """Audit record for import batch rollback execute (strong confirmation)."""

    __tablename__ = "import_batch_rollback_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    parser_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_status: Mapped[str] = mapped_column(Text, nullable=False)
    target_status: Mapped[str] = mapped_column(Text, nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confirmation_text: Mapped[str] = mapped_column(Text, nullable=False)
    required_confirmation: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    preview_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    delete_plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    keep_plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dependency_counts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_counts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    kept_counts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
