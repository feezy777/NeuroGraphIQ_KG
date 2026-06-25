"""Pydantic schemas for File Upload & File Management.

Full audit_log persistence is deferred to Logging & Audit module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FileType(str, Enum):
    nifti = "nifti"
    label_table = "label_table"
    spreadsheet = "spreadsheet"
    pdf = "pdf"
    ontology = "ontology"
    json = "json"
    text = "text"
    connectivity_matrix = "connectivity_matrix"
    image = "image"
    other = "other"


class FileRole(str, Enum):
    primary_atlas_volume = "primary_atlas_volume"
    label_dictionary = "label_dictionary"
    documentation = "documentation"
    ontology_source = "ontology_source"
    connectivity_source = "connectivity_source"
    evidence_source = "evidence_source"
    metadata = "metadata"
    auxiliary = "auxiliary"
    macro_region_pool_source = "macro_region_pool_source"
    unknown = "unknown"


class FileStatus(str, Enum):
    active = "active"
    archived = "archived"


class ResourceFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_id: uuid.UUID
    file_code: str | None
    original_filename: str
    stored_filename: str
    storage_path: str
    file_ext: str
    mime_type: str | None
    file_size: int
    sha256: str
    file_type: FileType
    file_role: FileRole
    status: FileStatus
    description: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    source_workspace_file_id: uuid.UUID | None = None
    intermediate_status: str | None = None
    latest_intermediate_artifact_id: uuid.UUID | None = None
    latest_normalization_run_id: uuid.UUID | None = None
    latest_intermediate_kind: str | None = None
    latest_intermediate_row_count: int | None = None
    latest_intermediate_error: str | None = None


class ResourceFileUpdate(BaseModel):
    file_type: FileType | None = None
    file_role: FileRole | None = None
    description: str | None = None
    remark: str | None = None
    status: FileStatus | None = None


PreviewKind = Literal["text", "json", "xml", "csv", "image", "binary", "unsupported", "missing", "error"]


class FilePreviewResponse(BaseModel):
    file_id: uuid.UUID
    filename: str
    file_type: FileType
    mime_type: str | None
    preview_kind: PreviewKind
    is_truncated: bool = False
    max_bytes: int
    size_bytes: int
    encoding: str | None = None
    content: str | None = None
    metadata: dict[str, Any]
    error_message: str | None = None


class ResourceFileListResponse(BaseModel):
    items: list[ResourceFileRead]
    total: int
    limit: int
    offset: int


class FileOptionsResponse(BaseModel):
    file_type: list[str]
    file_role: list[str]
    status: list[str]
    preview_supported_types: list[str] = []


class DuplicateExistingResourceFile(BaseModel):
    """Subset of resource file fields returned on duplicate upload (409)."""

    id: uuid.UUID
    original_filename: str | None = None
    file_type: str | None = None
    file_role: str | None = None
    status: str | None = None
    file_size_bytes: int | None = None
    created_at: datetime | None = None
    intermediate_status: str | None = None
    latest_intermediate_artifact_id: uuid.UUID | None = None
    latest_intermediate_kind: str | None = None
    latest_intermediate_row_count: int | None = None


class DuplicateResourceFileDetail(BaseModel):
    code: str
    message: str
    resource_id: uuid.UUID | None = None
    sha256: str
    existing_file: DuplicateExistingResourceFile | dict[str, str] | None = None
    suggestion: str | None = None


class FileUploadFormMeta(BaseModel):
    """Non-file fields validated after multipart parse."""

    file_type: FileType | None = None
    file_role: FileRole = FileRole.unknown
    file_code: str | None = Field(default=None, max_length=128)
    description: str | None = None
    remark: str | None = None


class FileDeleteRequest(BaseModel):
    confirmation_text: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    delete_physical_file: bool = False


class FileDeleteResult(BaseModel):
    file_id: uuid.UUID
    resource_id: uuid.UUID
    status: str = "deleted"
    deleted_counts: dict[str, int] = Field(default_factory=dict)
    can_reupload_same_sha256: bool = True
    physical_file_deleted: bool = False
    physical_file_error: str | None = None
