"""Final KG export / sync preparation schemas (Step 8.17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FinalKgExportFormat(str, Enum):
    jsonl = "jsonl"
    csv = "csv"
    neo4j_csv = "neo4j_csv"


class FinalKgExportTargetType(str, Enum):
    brain_region = "brain_region"
    region_function = "region_function"
    circuit = "circuit"
    circuit_step = "circuit_step"
    circuit_function = "circuit_function"
    projection = "projection"
    projection_function = "projection_function"
    circuit_projection_membership = "circuit_projection_membership"
    triple = "triple"
    evidence = "evidence"


DEFAULT_EXPORT_TARGET_TYPES = [t.value for t in FinalKgExportTargetType]
DEFAULT_EXPORT_FORMATS = [f.value for f in FinalKgExportFormat]

EXPORT_SCHEMA_VERSION = "final_macro_clinical_export_v1"


class FinalKgExportScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    final_status: str | None = None
    include_inactive: bool = False
    final_ids: list[uuid.UUID] | None = None
    region_candidate_ids: list[uuid.UUID] | None = None
    circuit_ids: list[uuid.UUID] | None = None
    projection_ids: list[uuid.UUID] | None = None


class FinalKgExportRequest(BaseModel):
    target_types: list[str] = Field(default_factory=lambda: list(DEFAULT_EXPORT_TARGET_TYPES))
    formats: list[str] = Field(default_factory=lambda: list(DEFAULT_EXPORT_FORMATS))
    scope: FinalKgExportScope | None = None
    dry_run: bool = True
    include_evidence: bool = True
    include_provenance: bool = True
    include_triples: bool = True
    include_readme: bool = True
    max_nodes: int = Field(default=100_000, ge=1, le=500_000)
    max_edges: int = Field(default=300_000, ge=1, le=1_000_000)
    export_label: str | None = None


class FinalKgExportPreviewResponse(BaseModel):
    dry_run: bool = True
    candidate_counts: dict[str, int] = Field(default_factory=dict)
    estimated_node_count: int = 0
    estimated_edge_count: int = 0
    estimated_file_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    sample_nodes: list[dict[str, Any]] = Field(default_factory=list)
    sample_edges: list[dict[str, Any]] = Field(default_factory=list)


class FinalKgExportManifestCounts(BaseModel):
    nodes: int = 0
    edges: int = 0
    evidence: int = 0
    provenance: int = 0


class FinalKgExportManifestBoundaries(BaseModel):
    write_final: bool = False
    write_mirror: bool = False
    write_kg: bool = False
    write_external_db: bool = False
    llm_called: bool = False


class FinalKgExportManifest(BaseModel):
    export_id: str
    created_at: str
    created_by: str = "local_api"
    export_label: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    formats: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)
    counts: FinalKgExportManifestCounts = Field(default_factory=FinalKgExportManifestCounts)
    files: dict[str, str] = Field(default_factory=dict)
    schema_version: str = EXPORT_SCHEMA_VERSION
    app_version: str = ""
    warnings: list[str] = Field(default_factory=list)
    boundaries: FinalKgExportManifestBoundaries = Field(default_factory=FinalKgExportManifestBoundaries)


class FinalKgExportRunResponse(BaseModel):
    dry_run: bool
    export_id: str | None = None
    export_dir: str | None = None
    manifest: FinalKgExportManifest | None = None
    files: list[str] = Field(default_factory=list)
    counts: FinalKgExportManifestCounts = Field(default_factory=FinalKgExportManifestCounts)
    warnings: list[str] = Field(default_factory=list)


class FinalKgExportManifestRead(BaseModel):
    export_id: str
    created_at: str
    scope: dict[str, Any] = Field(default_factory=dict)
    formats: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)
    counts: FinalKgExportManifestCounts = Field(default_factory=FinalKgExportManifestCounts)
    files: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    export_label: str | None = None


class FinalKgExportManifestListResponse(BaseModel):
    items: list[FinalKgExportManifestRead]
    total: int


class FinalKgExportFileRead(BaseModel):
    export_id: str
    filename: str
    size_bytes: int
    modified_at: datetime
    download_url: str


class FinalKgExportFileListResponse(BaseModel):
    export_id: str
    files: list[FinalKgExportFileRead]
