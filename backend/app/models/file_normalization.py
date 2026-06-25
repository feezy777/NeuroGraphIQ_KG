"""ORM models for file normalization runs and intermediate artifacts.

These tables store the unified intermediate state generated from raw uploaded files.
They do NOT reference raw_aal3_region_labels, candidate_brain_regions, final_*, or kg_*.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FileNormalizationRun(Base):
    """Tracks a single normalization attempt for a file_id.

    Multiple runs per file are allowed; the latest succeeded run
    with active artifacts is the canonical intermediate state.
    """

    __tablename__ = "file_normalization_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_code: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="RESTRICT"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_files.id", ondelete="RESTRICT"), nullable=False
    )
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalizer_key: Mapped[str] = mapped_column(String(128), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FileIntermediateArtifact(Base):
    """Stores a single intermediate artifact produced by a normalization run.

    artifact_kind describes the semantic shape; content_jsonb stores the structured data.
    Does NOT write to raw_aal3_region_labels, candidate_brain_regions, final_*, or kg_*.
    """

    __tablename__ = "file_intermediate_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("file_normalization_runs.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(256), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="intermediate_v1")
    source_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    preview_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warnings_jsonb: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
