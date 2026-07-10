"""ORM model for Macro96 raw region rows.

raw_macro96_region_rows stores one record per Excel row extracted from
Brain volume list.xlsx via the macro96_xlsx parser.

Boundaries (strictly enforced):
- References raw_parse_runs, import_batches, atlas_resources, resource_files.
- Does NOT reference candidate_brain_regions, final_*, or kg_*.
- Does NOT trigger LLM, candidate generation, or promotion.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawMacro96RegionRow(Base):
    """One Excel row from Brain volume list.xlsx — not a candidate, not final."""

    __tablename__ = "raw_macro96_region_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_parse_runs.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_files.id", ondelete="RESTRICT"), nullable=False
    )
    intermediate_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    region_index: Mapped[int] = mapped_column(Integer, nullable=False)
    en_name: Mapped[str] = mapped_column(Text, nullable=False)
    cn_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_brain_structure: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_cn_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(256), nullable=True)

    granularity_level: Mapped[str] = mapped_column(String(64), nullable=False, default="macro")
    parser_key: Mapped[str] = mapped_column(String(64), nullable=False, default="macro96_xlsx")
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
