"""Pydantic schemas for the LLM Extraction Workbench (MVP 2 Step 1).

DeepSeek candidate-side extraction = ADVISORY field completion / explanation.
Results live on the candidate side only (candidate_llm_extractions). They are NOT
facts: never written to final_* / kg_*, never auto-approved or promoted, and they
do NOT mutate the Candidate state machine in this step.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Bumped when the extraction prompt or expected JSON shape changes.
PROMPT_VERSION = "v1"
# Hard cap for legacy batch-extract helper only — NOT applied to same-granularity
# connection/circuit/function request schemas (candidate_ids have no max_length).
MAX_BATCH_SIZE = 20

LATERALITY_VALUES = ("left", "right", "bilateral", "midline", "unknown")


class LlmExtractionStatus(str):  # noqa: SLOT000 - simple string constants
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class LlmSuggestion(BaseModel):
    """Structured advisory result parsed from the DeepSeek response."""

    candidate_id: str | None = None
    suggested_cn_name: str | None = None
    suggested_en_name: str | None = None
    suggested_aliases: list[str] = Field(default_factory=list)
    suggested_description: str | None = None
    suggested_region_base_name: str | None = None
    suggested_laterality: str | None = None
    confidence: float | None = None
    evidence_summary: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    needs_human_review: bool = True


class LlmExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    generation_run_id: uuid.UUID
    parse_run_id: uuid.UUID
    run_id: uuid.UUID
    provider: str
    model: str
    prompt_version: str
    status: str
    raw_response: str | None
    structured_result: dict[str, Any] | None
    error_message: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    created_at: datetime
    updated_at: datetime


class LlmExtractionListResponse(BaseModel):
    items: list[LlmExtractionRead]
    total: int
    limit: int
    offset: int


class BatchExtractRequest(BaseModel):
    # No max_length on candidate_ids — open-ended extraction (Step 9.14/9.16).
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)


class BatchExtractResponse(BaseModel):
    run_id: uuid.UUID
    requested: int
    succeeded: int
    failed: int
    items: list[LlmExtractionRead]


class LlmExtractionOptions(BaseModel):
    provider: str
    model: str
    prompt_version: str
    max_batch_size: int
    laterality_values: list[str]
    api_key_configured: bool


# ---------------------------------------------------------------------------
# Infrastructure (Step 1) — task types, runs, items
# ---------------------------------------------------------------------------


class LlmTaskType(str):
    region_field_completion = "region_field_completion"
    region_alias_completion = "region_alias_completion"
    region_description_completion = "region_description_completion"
    same_granularity_connection_completion = "same_granularity_connection_completion"
    same_granularity_function_completion = "same_granularity_function_completion"
    same_granularity_circuit_completion = "same_granularity_circuit_completion"
    triple_candidate_generation = "triple_candidate_generation"
    translation = "translation"
    evidence_explanation = "evidence_explanation"
    uncertainty_flagging = "uncertainty_flagging"
    # Step 8.5 — macro_clinical aligned (planned only)
    regions_to_circuits = "regions_to_circuits"
    circuit_to_steps = "circuit_to_steps"
    circuit_steps_to_projections = "circuit_steps_to_projections"
    projections_to_circuits = "projections_to_circuits"
    circuit_projection_cross_validation = "circuit_projection_cross_validation"
    dual_model_verification = "dual_model_verification"
    region_to_functions = "region_to_functions"
    circuit_to_functions = "circuit_to_functions"
    projection_to_functions = "projection_to_functions"
    macro_clinical_triple_generation = "macro_clinical_triple_generation"
    evidence_uncertainty_review = "evidence_uncertainty_review"


PLANNED_MACRO_CLINICAL_TASK_TYPES = frozenset({
    LlmTaskType.regions_to_circuits,
    LlmTaskType.circuit_projection_cross_validation,
    LlmTaskType.region_to_functions,
    LlmTaskType.macro_clinical_triple_generation,
    LlmTaskType.evidence_uncertainty_review,
})


IMPLEMENTED_TASK_TYPES = frozenset({
    LlmTaskType.region_field_completion,
    LlmTaskType.same_granularity_connection_completion,
    LlmTaskType.same_granularity_function_completion,
    LlmTaskType.same_granularity_circuit_completion,
    LlmTaskType.circuit_to_steps,
    LlmTaskType.circuit_steps_to_projections,
    LlmTaskType.circuit_to_functions,
    LlmTaskType.projection_to_functions,
    LlmTaskType.projections_to_circuits,
    LlmTaskType.dual_model_verification,
})


class LlmProviderName(str):
    deepseek = "deepseek"
    kimi = "kimi"


class LlmRunStatus(str):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    succeeded_no_edges = "succeeded_no_edges"
    failed = "failed"
    failed_provider_not_called = "failed_provider_not_called"
    failed_provider_not_configured = "failed_provider_not_configured"
    failed_provider_error = "failed_provider_error"
    failed_provider_empty_response = "failed_provider_empty_response"
    failed_parse_error = "failed_parse_error"
    failed_empty_prompt = "failed_empty_prompt"
    failed_no_output = "failed_no_output"
    cancelled = "cancelled"


class LlmItemStatus(str):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    needs_review = "needs_review"
    cancelled = "cancelled"


class LlmScopeType(str):
    single_candidate = "single_candidate"
    single_circuit = "single_circuit"
    candidate_batch = "candidate_batch"
    resource = "resource"
    manual_selection = "manual_selection"
    projection_selection = "projection_selection"
    unknown = "unknown"


class LlmTaskTypeInfo(BaseModel):
    task_type: str
    label: str
    implemented: bool
    description: str


class LlmProviderInfo(BaseModel):
    name: str
    configured: bool
    default_model: str
    enabled: bool = True


class LlmProvidersResponse(BaseModel):
    providers: list[LlmProviderInfo]


class LlmTaskTypesResponse(BaseModel):
    task_types: list[LlmTaskTypeInfo]


class LlmPromptTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_key: str
    task_type: str
    version: str
    name: str
    description: str | None
    system_prompt: str
    user_prompt_template: str
    output_schema_json: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class LlmExtractionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    provider: str
    model_name: str
    prompt_template_id: uuid.UUID | None
    prompt_template_key: str | None
    prompt_version: str | None
    scope_type: str
    scope_json: dict[str, Any]
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    granularity_level: str | None
    granularity_family: str | None
    source_atlas: str | None
    source_version: str | None
    status: str
    input_count: int
    output_count: int
    error_count: int
    temperature: float | None = None
    max_tokens: int | None = None
    request_payload_redacted: dict[str, Any]
    usage_json: dict[str, Any]
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class LlmExtractionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    candidate_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    task_type: str
    item_index: int
    input_json: dict[str, Any]
    prompt_json: dict[str, Any]
    raw_response_text: str | None
    parsed_response_json: dict[str, Any]
    normalized_output_json: dict[str, Any]
    status: str
    confidence: float | None = None
    evidence_text: str | None
    uncertainty_reason: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class LlmExtractionRunDetail(LlmExtractionRunRead):
    items: list[LlmExtractionItemRead] = Field(default_factory=list)


class LlmRunListResponse(BaseModel):
    items: list[LlmExtractionRunRead]
    total: int
    limit: int
    offset: int


class LlmItemListResponse(BaseModel):
    items: list[LlmExtractionItemRead]
    total: int
    limit: int
    offset: int


class RegionFieldCompletionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)
    prompt_template_key: str = "region_field_completion_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=256, le=8192)
    dry_run: bool = False


class RegionFieldCompletionResponse(BaseModel):
    run_id: uuid.UUID
    requested: int
    succeeded: int
    failed: int
    dry_run: bool
    items: list[LlmExtractionItemRead]
    legacy_extractions: list[LlmExtractionRead] = Field(default_factory=list)


class LlmRunTaskRequest(BaseModel):
    task_type: str
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    candidate_ids: list[uuid.UUID] = Field(default_factory=list)
    circuit_id: uuid.UUID | None = None
    prompt_template_key: str | None = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=256, le=8192)
    dry_run: bool = False
    max_steps: int = Field(default=12, ge=2, le=30)
    include_circuit_regions: bool = True
    create_mirror_records: bool = True
    max_projections: int = Field(default=20, ge=1, le=100)
    step_ids: list[uuid.UUID] = Field(default_factory=list)
    include_existing_projections: bool = True
    create_memberships: bool = True
    create_triples: bool = True
    create_evidence: bool = True
    projection_ids: list[uuid.UUID] = Field(default_factory=list)
    max_functions_per_projection: int = Field(default=5, ge=1, le=10)
    include_circuit_context: bool = True
    include_region_context: bool = True
    max_circuits: int = Field(default=10, ge=1, le=30)
    max_steps_per_circuit: int = Field(default=20, ge=2, le=50)
    include_existing_circuits: bool = True
    reuse_existing_circuits: bool = True
    create_mirror_circuits: bool = True
    create_circuit_steps: bool = True
    object_type: str | None = None
    object_ids: list[uuid.UUID] = Field(default_factory=list)
    model_a_provider: str = "deepseek"
    model_a_name: str | None = None
    model_b_provider: str = "kimi"
    model_b_name: str | None = None
    max_objects: int = Field(default=50, ge=1, le=200)
    include_cross_validation_context: bool = True
    include_evidence_context: bool = True
    include_review_context: bool = False
    create_results: bool = True


class ConnectionExtractionScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class SameGranularityConnectionExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    # No max_length — large candidate lists allowed; min_length=2 enforced in service too.
    candidate_ids: list[uuid.UUID] = Field(..., min_length=2)
    scope: ConnectionExtractionScope | None = None
    prompt_template_key: str = "same_granularity_connection_completion_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8000, ge=256, le=16384)
    dry_run: bool = False
    max_candidate_pairs: int = Field(default=200, ge=1, le=5000)
    pair_strategy: str = Field(default="all_pairs")
    center_candidate_id: uuid.UUID | None = None
    allowed_connection_types: list[str] | None = None
    create_mirror_records: bool = True
    create_triples: bool = True
    create_evidence: bool = True
    debug_max_packs: int | None = Field(default=None, ge=1, le=500)
    debug_single_pack: bool = False
    parse_error_fail_fast_enabled: bool = True
    parse_error_fail_fast_threshold: int = Field(default=3, ge=1, le=20)


class SameGranularityConnectionExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.same_granularity_connection_completion
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    candidate_count: int
    pair_count: int
    connection_count: int = 0
    mirror_connection_created_count: int = 0
    mirror_connection_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    prompt_preview: dict[str, Any] | None = None
    pack_count: int = 0
    processed_pair_count: int = 0
    unprocessed_pair_count: int = 0
    no_connection_count: int = 0
    created_connection_ids: list[uuid.UUID] = Field(default_factory=list)
    execution_summary: dict[str, Any] | None = None
    provider_call_count: int = 0
    provider_success_count: int = 0
    provider_error_count: int = 0
    provider_empty_response_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class FunctionExtractionScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class SameGranularityFunctionExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)
    scope: FunctionExtractionScope | None = None
    prompt_template_key: str = "same_granularity_function_completion_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, ge=256, le=8192)
    dry_run: bool = False
    max_functions_per_region: int = Field(default=5, ge=1, le=10)
    allowed_function_categories: list[str] | None = None
    allowed_relation_types: list[str] | None = None
    create_mirror_records: bool = True
    create_triples: bool = True
    create_evidence: bool = True


class SameGranularityFunctionExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.same_granularity_function_completion
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    candidate_count: int
    function_count: int = 0
    mirror_function_created_count: int = 0
    mirror_function_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CircuitExtractionScope(BaseModel):
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


class SameGranularityCircuitExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    # No max_length — 96+ candidates must not trigger Pydantic 422.
    candidate_ids: list[uuid.UUID] = Field(..., min_length=2)
    scope: CircuitExtractionScope | None = None
    prompt_template_key: str = "same_granularity_circuit_completion_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=5000, ge=256, le=8192)
    dry_run: bool = False
    max_circuits: int = Field(default=100, ge=1, le=5000)
    min_regions_per_circuit: int = Field(default=2, ge=2, le=20)
    max_regions_per_circuit: int = Field(default=12, ge=2, le=20)
    include_connection_context: bool = True
    include_function_context: bool = True
    connection_ids: list[uuid.UUID] | None = None
    function_ids: list[uuid.UUID] | None = None
    allowed_circuit_types: list[str] | None = None
    create_mirror_records: bool = True
    create_triples: bool = True
    create_evidence: bool = True


class SameGranularityCircuitExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.same_granularity_circuit_completion
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    candidate_count: int
    connection_context_count: int = 0
    function_context_count: int = 0
    circuit_count: int = 0
    mirror_circuit_created_count: int = 0
    mirror_circuit_skipped_duplicate_count: int = 0
    circuit_region_created_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CircuitToStepsExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    circuit_id: uuid.UUID
    prompt_template_key: str = "circuit_to_steps_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=3000, ge=256, le=8192)
    dry_run: bool = False
    max_steps: int = Field(default=12, ge=2, le=30)
    include_circuit_regions: bool = True
    create_mirror_records: bool = True


class CircuitToStepsExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.circuit_to_steps
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    circuit_id: uuid.UUID
    input_region_count: int = 0
    step_count: int = 0
    mirror_step_created_count: int = 0
    mirror_step_skipped_duplicate_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CircuitStepsToProjectionsExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    circuit_id: uuid.UUID
    prompt_template_key: str = "circuit_steps_to_projections_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, ge=256, le=8192)
    dry_run: bool = False
    max_projections: int = Field(default=20, ge=1, le=100)
    step_ids: list[uuid.UUID] = Field(default_factory=list)
    include_existing_projections: bool = True
    create_mirror_records: bool = True
    create_memberships: bool = True
    create_triples: bool = True
    create_evidence: bool = True


class CircuitStepsToProjectionsExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.circuit_steps_to_projections
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    circuit_id: uuid.UUID
    input_step_count: int = 0
    existing_projection_context_count: int = 0
    projection_count: int = 0
    mirror_projection_created_count: int = 0
    mirror_projection_skipped_duplicate_count: int = 0
    membership_created_count: int = 0
    membership_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ProjectionToFunctionsExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    projection_ids: list[uuid.UUID] = Field(..., min_length=1)
    prompt_template_key: str = "projection_to_functions_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, ge=256, le=8192)
    dry_run: bool = False
    max_functions_per_projection: int = Field(default=5, ge=1, le=10)
    include_circuit_context: bool = True
    include_region_context: bool = True
    create_mirror_records: bool = True
    create_triples: bool = True
    create_evidence: bool = True


class ProjectionToFunctionsExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.projection_to_functions
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    projection_count: int = 0
    circuit_context_count: int = 0
    function_count: int = 0
    mirror_projection_function_created_count: int = 0
    mirror_projection_function_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CircuitFunctionCreatedTarget(BaseModel):
    target_type: str = "circuit_function"
    target_table: str = "mirror_circuit_functions"
    ids: list[str] = Field(default_factory=list)
    count: int = 0


class CircuitToFunctionsExtractionRequest(BaseModel):
    circuit_ids: list[uuid.UUID] | None = None
    batch_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    provider: str = LlmProviderName.deepseek
    model_name: str | None = "deepseek-chat"
    dry_run: bool = True
    overwrite_policy: str = "fill_missing_only"
    include_related_steps: bool = True
    include_provenance: bool = True
    prompt_template_key: str = "circuit_to_functions_extraction_v1"
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, ge=256, le=8192)
    limit: int | None = Field(default=None, ge=1)


class CircuitToFunctionsExtractionResponse(BaseModel):
    status: str
    target_type: str = "circuit_function"
    source_target_type: str = "circuit"
    circuit_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    created_ids: list[uuid.UUID] = Field(default_factory=list)
    updated_ids: list[uuid.UUID] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    prompt_preview: dict[str, Any] | None = None
    estimated_model_calls: int = 0
    estimated_input_tokens: int = 0
    dry_run: bool
    created_targets: list[CircuitFunctionCreatedTarget] = Field(default_factory=list)


class ProjectionsToCircuitsExtractionRequest(BaseModel):
    provider: str = LlmProviderName.deepseek
    model_name: str | None = None
    projection_ids: list[uuid.UUID] = Field(..., min_length=2)
    prompt_template_key: str = "projections_to_circuits_v1"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=5000, ge=256, le=8192)
    dry_run: bool = False
    max_circuits: int = Field(default=10, ge=1, le=30)
    max_steps_per_circuit: int = Field(default=20, ge=2, le=50)
    include_existing_circuits: bool = True
    reuse_existing_circuits: bool = True
    create_mirror_circuits: bool = True
    create_circuit_steps: bool = True
    create_memberships: bool = True
    create_triples: bool = True
    create_evidence: bool = True


class ProjectionsToCircuitsExtractionResponse(BaseModel):
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.projections_to_circuits
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    projection_count: int = 0
    existing_circuit_context_count: int = 0
    inferred_circuit_count: int = 0
    mirror_circuit_created_count: int = 0
    mirror_circuit_reused_count: int = 0
    mirror_circuit_skipped_duplicate_count: int = 0
    circuit_step_created_count: int = 0
    circuit_step_skipped_duplicate_count: int = 0
    membership_created_count: int = 0
    membership_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)



class ExtractionPromptTemplateItem(BaseModel):
    key: str
    title: str
    display_name: str | None = None
    category: str = "extraction"
    target_type: str | None = None
    field_name: str | None = None
    description: str | None = None
    template: str
    system_prompt: str


class ExtractionPromptTemplateListResponse(BaseModel):
    items: list[ExtractionPromptTemplateItem]


class ConnectionParseReplayPair(BaseModel):
    pair_id: str
    source_region_candidate_id: uuid.UUID
    target_region_candidate_id: uuid.UUID


class ConnectionParseReplayRequest(BaseModel):
    raw_text: str = Field(..., min_length=1)
    pack_pairs: list[ConnectionParseReplayPair] = Field(default_factory=list)


class ConnectionParseReplayResponse(BaseModel):
    parsed: bool
    parsed_projection_count: int = 0
    parsed_no_connection_count: int = 0
    rejected_item_count: int = 0
    unprocessed_pair_count: int = 0
    normalized_payload: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    parse_error_type: str | None = None
    raw_response_preview: str | None = None


class ProviderRawDebugRequest(BaseModel):
    provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    prompt: str = Field(..., min_length=1)
    temperature: float = 0.0
    max_tokens: int = Field(default=256, ge=1, le=8192)
    response_format: dict[str, Any] | None = None


class ProviderRawDebugResponse(BaseModel):
    provider: str
    model_name: str
    transport_ok: bool
    raw_text_present: bool
    raw_text_preview: str | None = None
    response_char_count: int = 0
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    fallback_raw_response_used: bool = False
    error: str | None = None
    raw_response_keys: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
