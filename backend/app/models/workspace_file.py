"""ORM model for workspace public file staging.

Workspace files do NOT have a resource_id. They must be attached to a resource
via attach-to-resource → resource_files before entering any import pipeline.
This table does NOT reference raw_aal3_region_labels, candidate_brain_regions,
final_*, or kg_*.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkspaceFile(Base):
    """Public workspace file staging table.

    Status lifecycle: active → archived | deleted
    Physical file is never deleted; only soft-deleted via status/archived_at.
    """

    __tablename__ = "workspace_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_file_code: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    safe_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_ext: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    file_role: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="workspace_upload")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
