"""Pydantic schemas for file normalization runs and intermediate artifacts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NormalizationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_code: str
    resource_id: uuid.UUID
    file_id: uuid.UUID
    file_sha256: str | None
    original_filename: str | None
    file_type: str | None
    file_role: str | None
    normalizer_key: str
    normalizer_version: str
    status: str
    artifact_count: int
    warning_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IntermediateArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    resource_id: uuid.UUID
    file_id: uuid.UUID
    artifact_key: str
    artifact_kind: str
    schema_version: str
    source_format: str | None
    row_count: int | None
    content_jsonb: dict[str, Any] | None
    preview_jsonb: dict[str, Any] | None
    metadata_jsonb: dict[str, Any] | None
    warnings_jsonb: list[Any] | None
    status: str
    created_at: datetime
    updated_at: datetime


class FileIntermediateStatusResponse(BaseModel):
    """Summary of intermediate state for a file — shown in file list and import batch UI."""

    file_id: uuid.UUID
    status: str = "missing"
    has_active_intermediate: bool
    latest_run_id: uuid.UUID | None
    latest_run_status: str | None
    latest_artifact_kind: str | None
    latest_artifact: IntermediateArtifactRead | None = None
    latest_run_created_at: datetime | None
    latest_run_error: str | None = None
    artifact_count: int
    artifacts: list[IntermediateArtifactRead] = []
    runs: list[NormalizationRunRead] = []


class FileNormalizeResponse(BaseModel):
    """Response after triggering normalization."""

    run_id: uuid.UUID
    run_code: str
    status: str
    artifact_count: int
    warning_count: int
    error_message: str | None
    artifacts: list[IntermediateArtifactRead]


class IntermediatePreviewResponse(BaseModel):
    """Lightweight preview of the intermediate artifact."""

    file_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_kind: str
    source_format: str | None
    row_count: int | None
    preview: dict[str, Any] | None
    metadata: dict[str, Any] | None
