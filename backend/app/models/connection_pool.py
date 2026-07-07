"""Connection Pool ORM models — cross-source connection accumulation for LLM extraction."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ConnectionPool(Base):
    __tablename__ = "connection_pools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_granularity: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    connection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list["ConnectionPoolMembership"]] = relationship(
        "ConnectionPoolMembership", back_populates="pool", cascade="all, delete-orphan"
    )


class ConnectionPoolMembership(Base):
    __tablename__ = "connection_pool_memberships"
    __table_args__ = (
        UniqueConstraint("pool_id", "connection_id", name="uq_conn_pool_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connection_pools.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mirror_region_connections.id", ondelete="CASCADE"), nullable=False
    )
    added_source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pool: Mapped["ConnectionPool"] = relationship("ConnectionPool", back_populates="memberships")
