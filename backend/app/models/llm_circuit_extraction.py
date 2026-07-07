"""Circuit pack extraction run ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CircuitExtractionRun(Base):
    __tablename__ = "circuit_extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    pack_count: Mapped[int] = mapped_column(Integer, default=0)
    circuit_count: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    function_count: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_packs: Mapped[int] = mapped_column(Integer, default=0)
    no_findings_packs: Mapped[int] = mapped_column(Integer, default=0)
    failed_packs: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    usage_summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pack_results_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    errors_json: Mapped[list] = mapped_column(JSONB, default=list)
    warnings_json: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
