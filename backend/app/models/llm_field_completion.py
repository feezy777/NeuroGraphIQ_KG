"""Universal field completion audit ORM models (Step 10.3).

Writes audit rows only; target object updates go to candidate/mirror tables via service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmFieldCompletionRun(Base):
    __tablename__ = "llm_field_completion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="deepseek")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    field_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="missing_only")
    selected_fields_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    overwrite_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="fill_missing_only")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    create_mirror_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    create_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    errors_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LlmFieldCompletionItem(Base):
    __tablename__ = "llm_field_completion_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_field_completion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    suggested_value_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    applied_value_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_status: Mapped[str] = mapped_column(String(64), nullable=False, default="suggested")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
