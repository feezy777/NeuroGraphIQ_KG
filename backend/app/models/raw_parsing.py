from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawParseRun(Base):
    """AAL3 raw parsing execution record (not candidate, not final)."""

    __tablename__ = "raw_parse_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="RESTRICT"), nullable=False
    )
    parser_key: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    input_file_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    output_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RawAal3RegionLabel(Base):
    """Raw AAL3 label row extracted from source files — not a candidate entity."""

    __tablename__ = "raw_aal3_region_labels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_parse_runs.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="RESTRICT"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_label_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    label_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False)
    en_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cn_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    laterality: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    granularity_level: Mapped[str] = mapped_column(String(64), nullable=False, default="macro")
    region_base_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
