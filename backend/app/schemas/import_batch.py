"""Pydantic schemas for Import Batch / Task Module.

Import Batch status is independent of Candidate and Promotion state machines.
Batch completed does NOT mean candidate_created or promoted_to_final.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.resource_file import ResourceFileRead

BATCH_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "cancelled"})


class BatchType(str, Enum):
    atlas_import = "atlas_import"
    label_import = "label_import"
    ontology_import = "ontology_import"
    connectivity_import = "connectivity_import"
    evidence_import = "evidence_import"
    metadata_import = "metadata_import"


class ImportBatchStatus(str, Enum):
    created = "created"
    queued = "queued"
    running = "running"
    parsed = "parsed"
    candidate_generated = "candidate_generated"
    validation_dispatched = "validation_dispatched"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FileRoleInBatch(str, Enum):
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


class BatchEventType(str, Enum):
    created = "created"
    file_attached = "file_attached"
    status_changed = "status_changed"
    cancelled = "cancelled"
    failed = "failed"
    completed = "completed"
    note = "note"
    parse_started = "parse_started"
    parse_succeeded = "parse_succeeded"
    parse_failed = "parse_failed"
    candidate_generation_started = "candidate_generation_started"
    candidate_generation_succeeded = "candidate_generation_succeeded"
    candidate_generation_failed = "candidate_generation_failed"
    rule_validation_started = "rule_validation_started"
    rule_validation_succeeded = "rule_validation_succeeded"
    rule_validation_failed = "rule_validation_failed"
    parse_macro96_started = "parse_macro96_started"
    parse_macro96_succeeded = "parse_macro96_succeeded"
    parse_macro96_failed = "parse_macro96_failed"
    rollback_started = "rollback_started"
    rollback_succeeded = "rollback_succeeded"
    rollback_failed = "rollback_failed"


ALLOWED_TRANSITIONS: dict[ImportBatchStatus, frozenset[ImportBatchStatus]] = {
    ImportBatchStatus.created: frozenset(
        {ImportBatchStatus.queued, ImportBatchStatus.cancelled, ImportBatchStatus.failed}
    ),
    ImportBatchStatus.queued: frozenset(
        {ImportBatchStatus.running, ImportBatchStatus.cancelled, ImportBatchStatus.failed}
    ),
    ImportBatchStatus.running: frozenset(
        {
            ImportBatchStatus.parsed,
            ImportBatchStatus.completed,
            ImportBatchStatus.failed,
            ImportBatchStatus.cancelled,
        }
    ),
    ImportBatchStatus.parsed: frozenset(
        {
            ImportBatchStatus.completed,
            ImportBatchStatus.failed,
            ImportBatchStatus.candidate_generated,
        }
    ),
    ImportBatchStatus.candidate_generated: frozenset(
        {ImportBatchStatus.validation_dispatched, ImportBatchStatus.completed}
    ),
    ImportBatchStatus.validation_dispatched: frozenset({ImportBatchStatus.completed}),
    ImportBatchStatus.failed: frozenset(),
    ImportBatchStatus.cancelled: frozenset(),
    ImportBatchStatus.completed: frozenset(),
}


class InvalidBatchTransitionError(ValueError):
    def __init__(self, from_status: str, to_status: str, reason: str):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(f"invalid transition {from_status} -> {to_status}: {reason}")


def validate_import_batch_transition(
    from_status: ImportBatchStatus | str,
    to_status: ImportBatchStatus | str,
) -> None:
    """Validate Import Batch state transition; raises InvalidBatchTransitionError."""
    src = ImportBatchStatus(from_status) if isinstance(from_status, str) else from_status
    dst = ImportBatchStatus(to_status) if isinstance(to_status, str) else to_status

    if src.value in TERMINAL_STATUSES:
        raise InvalidBatchTransitionError(
            src.value, dst.value, f"{src.value} is terminal"
        )
    if src == dst:
        raise InvalidBatchTransitionError(src.value, dst.value, "same status")
    allowed = ALLOWED_TRANSITIONS.get(src, frozenset())
    if dst not in allowed:
        raise InvalidBatchTransitionError(
            src.value, dst.value, "transition not allowed"
        )


class ImportBatchFileBinding(BaseModel):
    file_id: uuid.UUID
    file_role_in_batch: FileRoleInBatch = FileRoleInBatch.unknown
    sort_order: int | None = Field(default=None, ge=0)


class ImportBatchCreate(BaseModel):
    batch_code: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    resource_id: uuid.UUID
    batch_type: BatchType
    parser_key: str | None = Field(default=None, max_length=128)
    files: list[ImportBatchFileBinding] = Field(default_factory=list)
    description: str | None = None
    remark: str | None = None

    @field_validator("batch_code")
    @classmethod
    def validate_batch_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip()
        if not BATCH_CODE_PATTERN.match(code):
            raise ValueError(
                "batch_code must match ^[a-z][a-z0-9_]*$ (e.g. aal3_v1_import_20260529_ab12)"
            )
        return code


class ImportBatchStatusUpdate(BaseModel):
    status: ImportBatchStatus
    message: str | None = None
    error_message: str | None = None


class ImportBatchUpdate(BaseModel):
    """Metadata patch — field eligibility enforced by batch.status in service."""

    batch_code: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    batch_type: BatchType | None = None
    parser_key: str | None = Field(default=None, max_length=128)
    description: str | None = None
    remark: str | None = None

    @field_validator("batch_code")
    @classmethod
    def validate_batch_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip()
        if not BATCH_CODE_PATTERN.match(code):
            raise ValueError(
                "batch_code must match ^[a-z][a-z0-9_]*$ (e.g. aal3_v1_import_20260529_ab12)"
            )
        return code


class ImportBatchFilesUpdate(BaseModel):
    files: list[ImportBatchFileBinding] = Field(default_factory=list)


class ImportBatchFileAttach(BaseModel):
    file_id: uuid.UUID
    file_role_in_batch: FileRoleInBatch = FileRoleInBatch.unknown
    sort_order: int | None = Field(default=None, ge=0)


class ImportBatchFilePatch(BaseModel):
    file_role_in_batch: FileRoleInBatch | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ImportBatchFileEnrichedRead(BaseModel):
    """Binding row enriched with resource file metadata for management UI."""

    id: uuid.UUID
    batch_id: uuid.UUID
    file_id: uuid.UUID
    resource_id: uuid.UUID
    file_role_in_batch: FileRoleInBatch
    sort_order: int
    created_at: datetime
    original_filename: str | None = None
    file_type: str | None = None
    file_role: str | None = None
    file_status: str | None = None
    sha256: str | None = None
    file_size: int | None = None
    intermediate_status: str | None = None
    latest_intermediate_artifact_id: uuid.UUID | None = None
    is_active: bool = False
    can_parse: bool = False
    inactive_reason: str | None = None
    warning: str | None = None
    file: ResourceFileRead | None = None


class ImportBatchFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    file_id: uuid.UUID
    resource_id: uuid.UUID
    file_role_in_batch: FileRoleInBatch
    sort_order: int
    created_at: datetime
    file: ResourceFileRead | None = None


class ImportBatchEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    event_type: BatchEventType
    from_status: ImportBatchStatus | None = None
    to_status: ImportBatchStatus | None = None
    message: str | None
    payload_json: dict[str, Any] | None = None
    created_at: datetime


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_code: str
    resource_id: uuid.UUID
    batch_type: BatchType
    parser_key: str | None
    status: ImportBatchStatus
    description: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    error_message: str | None


class ImportBatchDetail(ImportBatchRead):
    files: list[ImportBatchFileEnrichedRead] = Field(default_factory=list)
    recent_events: list[ImportBatchEventRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_allowed_actions: list[str] = Field(default_factory=list)


class ImportBatchListResponse(BaseModel):
    items: list[ImportBatchRead]
    total: int
    limit: int
    offset: int


class ImportBatchFileListResponse(BaseModel):
    items: list[ImportBatchFileEnrichedRead]
    total: int
    warnings: list[str] = Field(default_factory=list)


class ImportBatchEventListResponse(BaseModel):
    items: list[ImportBatchEventRead]
    total: int
    limit: int
    offset: int


class ImportBatchOptionsResponse(BaseModel):
    batch_type: list[str]
    status: list[str]
    file_role_in_batch: list[str]
