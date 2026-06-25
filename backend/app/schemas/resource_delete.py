from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class DependencyCounts(BaseModel):
    resource_files: int = 0
    file_intermediate_artifacts: int = 0
    file_normalization_runs: int = 0
    import_batches: int = 0
    import_batch_files: int = 0
    import_batch_events: int = 0
    raw_parse_runs: int = 0
    raw_aal3_region_labels: int = 0
    raw_macro96_region_rows: int = 0
    candidate_generation_runs: int = 0
    candidate_brain_regions: int = 0
    candidate_llm_extractions: int = 0
    rule_validation_runs: int = 0
    candidate_rule_validation_results: int = 0
    candidate_review_records: int = 0
    promotion_records: int = 0
    final_brain_regions: int = 0


class ResourceDeletePreview(BaseModel):
    resource_id: uuid.UUID
    resource_code: str
    source_atlas: str
    status: str
    can_delete: bool = True
    delete_mode: str = "destructive_cascade"
    dependency_counts: DependencyCounts
    will_release_resource_code: bool = True
    resource_code_after_delete_can_be_recreated: bool = True
    warnings: list[str]
    required_confirmation: str


class ResourceDeleteRequest(BaseModel):
    confirmation_text: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    delete_physical_files: bool = False


class DeletedCounts(BaseModel):
    final_brain_regions: int = 0
    promotion_records: int = 0
    candidate_llm_extractions: int = 0
    candidate_review_records: int = 0
    candidate_rule_validation_results: int = 0
    rule_validation_runs: int = 0
    candidate_brain_regions: int = 0
    candidate_generation_runs: int = 0
    raw_macro96_region_rows: int = 0
    raw_aal3_region_labels: int = 0
    raw_parse_runs: int = 0
    import_batch_events: int = 0
    import_batch_files: int = 0
    import_batches: int = 0
    file_intermediate_artifacts: int = 0
    file_normalization_runs: int = 0
    resource_files: int = 0
    atlas_resources: int = 0


class ResourceDeleteResult(BaseModel):
    resource_id: uuid.UUID
    resource_code: str
    status: str = "deleted"
    deleted_counts: DeletedCounts
    resource_code_released: bool = True
    can_recreate_resource_code: bool = True
    physical_files_deleted: bool = False
    physical_files_error: str | None = None
