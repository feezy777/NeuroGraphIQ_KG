"""Pydantic schemas for Workspace Public Files.

Workspace files are staging files without resource_id.
They must be attached to a resource before entering any import pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_file_code: str | None
    original_filename: str
    safe_filename: str
    stored_filename: str
    storage_path: str
    file_ext: str
    mime_type: str | None
    file_type: str
    file_role: str
    file_size_bytes: int
    sha256: str
    status: str
    description: str | None
    remark: str | None
    uploaded_by: str | None
    source: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class WorkspaceFileUpdate(BaseModel):
    file_type: str | None = None
    file_role: str | None = None
    description: str | None = None
    remark: str | None = None
    status: str | None = None


class WorkspaceFileListResponse(BaseModel):
    items: list[WorkspaceFileRead]
    total: int
    limit: int
    offset: int


class AttachToResourceRequest(BaseModel):
    resource_id: uuid.UUID
    file_type: str | None = None
    file_role: str | None = None
    description: str | None = None
    remark: str | None = None
