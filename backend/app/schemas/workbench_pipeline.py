"""Read-only schemas for Workbench Pipeline Overview aggregation.

This module is strictly read-only; it never writes final_* / kg_* / candidate state.
next_allowed_actions is advisory: batch.status plus bound-file parse readiness for parse_aal3.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.candidate import CandidateBrainRegionRead, CandidateGenerationRunRead
from app.schemas.import_batch import ImportBatchEventRead, ImportBatchRead
from app.schemas.raw_parsing import RawAal3RegionLabelRead, RawParseRunRead
from app.schemas.rule_validation import RuleValidationRunRead


class PipelineAction(BaseModel):
    """A single advisory action the user may take next."""

    action: str
    label: str
    enabled: bool
    reason: str | None = None


class LatestValidationSummary(BaseModel):
    passed_count: int
    failed_count: int
    warning_count: int


class BoundFilePipelineRead(BaseModel):
    """Enriched bound-file row for Import Pipeline overview."""

    id: uuid.UUID
    file_id: uuid.UUID
    file_role_in_batch: str
    sort_order: int
    created_at: datetime
    original_filename: str | None = None
    file_type: str | None = None
    file_role: str | None = None
    file_status: str | None = None
    is_active: bool = False
    can_parse: bool = False
    inactive_reason: str | None = None
    intermediate_status: str | None = None
    latest_intermediate_artifact_id: uuid.UUID | None = None
    latest_intermediate_kind: str | None = None
    latest_intermediate_schema: str | None = None
    parser_compatible_for_aal3_xml: bool = False
    parser_incompatible_reason: str | None = None
    warning: str | None = None


class ImportBatchPipelineOverview(BaseModel):
    """Aggregated read-only view of the full import pipeline for one batch.

    Limits:
      - raw_labels_preview: max 20
      - candidates_preview: max 20
      - validation_runs: max 10 (most recent)
      - events: max 20 (most recent)
    """

    batch: ImportBatchRead
    bound_files: list[BoundFilePipelineRead]
    events: list[ImportBatchEventRead]
    parse_runs: list[RawParseRunRead]
    raw_label_count: int
    raw_labels_preview: list[RawAal3RegionLabelRead]
    generation_runs: list[CandidateGenerationRunRead]
    candidate_count: int
    candidate_status_counts: dict[str, int]
    candidates_preview: list[CandidateBrainRegionRead]
    validation_runs: list[RuleValidationRunRead]
    latest_validation_summary: LatestValidationSummary | None
    next_allowed_actions: list[PipelineAction]
