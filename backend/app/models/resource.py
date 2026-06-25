from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AtlasResource(Base):
    """Atlas / brain-map resource metadata registry (MVP 1).

    Resource lifecycle status (active/inactive/archived) is independent of
    Import Task / Candidate / Promotion state machines.
    """

    __tablename__ = "atlas_resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, default="atlas")
    species: Mapped[str] = mapped_column(String(32), nullable=False, default="human")
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str] = mapped_column(String(64), nullable=False)
    template_space: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    cn_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    en_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
