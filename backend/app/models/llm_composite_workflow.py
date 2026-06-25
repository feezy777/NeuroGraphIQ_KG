from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmCompositeWorkflowRun(Base):
    __tablename__ = "llm_composite_workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_atlas: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granularity_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_ids_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    errors_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LlmCompositeWorkflowStep(Base):
    __tablename__ = "llm_composite_workflow_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_composite_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    step_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    dependency_step_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_counts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    errors_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
