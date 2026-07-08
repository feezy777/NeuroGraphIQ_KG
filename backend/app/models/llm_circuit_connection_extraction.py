"""Circuit → Connection LLM extraction audit ORM models.

Writes audit rows only; target object updates go to mirror_region_connections
and mirror_region_circuits via service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmCircuitConnectionExtractionRun(Base):
    __tablename__ = "llm_circuit_connection_extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="deepseek")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)  # "multi_connection" | "main_pair"
    circuit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    create_mirror_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    overwrite_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="fill_missing_only")
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


class LlmCircuitConnectionExtractionItem(Base):
    __tablename__ = "llm_circuit_connection_extraction_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_circuit_connection_extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    circuit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_circuits.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_region_name: Mapped[str | None] = mapped_column(String(256), nullable=True)  # LLM raw output
    target_region_name: Mapped[str | None] = mapped_column(String(256), nullable=True)  # LLM raw output
    source_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # matched
    target_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # matched
    connection_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(  # resulting mirror_region_connection
        UUID(as_uuid=True),
        ForeignKey("mirror_region_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # "created" | "updated" | "skipped" | "no_match"
    action_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
