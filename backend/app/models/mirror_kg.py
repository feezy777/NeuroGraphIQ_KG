"""Mirror KG ORM models — formal-KG precursor layer (NOT final_*).

LLM and manual candidates for connections, functions, circuits, triples, and evidence.
Must preserve lineage to llm_extraction_runs/items and candidate/resource/batch context.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MirrorRegionConnection(Base):
    __tablename__ = "mirror_region_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_region_final_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_region_final_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connection_type: Mapped[str] = mapped_column(String(64), nullable=False)
    directionality: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    strength: Mapped[str | None] = mapped_column(String(64), nullable=True)
    modality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorRegionFunction(Base):
    __tablename__ = "mirror_region_functions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="SET NULL"),
        nullable=True,
    )
    region_final_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    function_term: Mapped[str] = mapped_column(String(512), nullable=False)
    region_name_cn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    region_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    function_category: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="associated_with")
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorRegionCircuit(Base):
    __tablename__ = "mirror_region_circuits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    circuit_name: Mapped[str] = mapped_column(String(512), nullable=False)
    circuit_type: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    function_association: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorCircuitRegion(Base):
    __tablename__ = "mirror_circuit_regions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    circuit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_circuits.id", ondelete="CASCADE"),
        nullable=False,
    )
    region_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_brain_regions.id", ondelete="SET NULL"),
        nullable=True,
    )
    region_final_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="participant")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MirrorKgTriple(Base):
    __tablename__ = "mirror_kg_triples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_label: Mapped[str] = mapped_column(String(512), nullable=False)
    predicate: Mapped[str] = mapped_column(String(256), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    object_label: Mapped[str] = mapped_column(String(512), nullable=False)
    triple_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="same_granularity")
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    source_mirror_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_mirror_function_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_functions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_mirror_circuit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mirror_region_circuits.id", ondelete="SET NULL"),
        nullable=True,
    )
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mirror_status: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_suggested")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    promotion_status: Mapped[str] = mapped_column(String(64), nullable=False, default="not_promoted")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MirrorEvidenceRecord(Base):
    __tablename__ = "mirror_evidence_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    llm_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_extraction_items.id", ondelete="SET NULL"), nullable=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_explanation")
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_reference_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    uncertainty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
