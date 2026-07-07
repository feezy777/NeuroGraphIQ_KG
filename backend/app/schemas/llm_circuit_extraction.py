"""Circuit pack extraction Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CircuitExtractionRequest(BaseModel):
    provider: str = "deepseek"
    model_name: str | None = None
    candidate_ids: list[uuid.UUID] = Field(default_factory=list)
    connection_ids: list[uuid.UUID] = Field(default_factory=list,
        description="When provided, extract circuits from existing connections (connection-based mode)")
    pool_id: uuid.UUID | None = None
    candidates_per_pack: int = Field(default=20, ge=5, le=50)
    shuffle_rounds: int = Field(default=3, ge=1, le=10, description="每脑区至少出现在 N 个不同包中")
    temperature: float = Field(default=0.5, ge=0, le=2)
    max_tokens: int = Field(default=16384, ge=256, le=65536)
    pack_concurrency: int = Field(default=2, ge=1, le=8)
    skip_existing: bool = False
    dry_run: bool = False
    # Optional preset/config fields (stored in request_json, don't affect executor yet)
    preset_id: str | None = None
    extraction_target: str | None = None
    prompt_template_key: str | None = None
    output_tables: list[str] = Field(default_factory=list)
    run_instruction_overlay: str | None = None
    prompt_overrides: dict[str, str] = Field(default_factory=dict)


class CircuitExtractionStartResponse(BaseModel):
    run_id: uuid.UUID
    status: str = "pending"
    provider: str
    model_name: str | None
    candidate_count: int
    dry_run: bool
    estimated_packs: int = 0
    estimated_llm_calls: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_cny: float = 0.0


class PackResult(BaseModel):
    pack_index: int
    status: str  # succeeded | no_findings | failed | skipped
    parsed_circuit_count: int = 0
    parsed_step_count: int = 0
    parsed_function_count: int = 0
    mirror_created_count: int = 0
    mirror_merged_count: int = 0
    mirror_skipped_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    failed_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CircuitExtractionRunRead(BaseModel):
    id: uuid.UUID
    provider: str
    model_name: str | None
    candidate_count: int
    pack_count: int
    circuit_count: int
    step_count: int
    function_count: int
    status: str
    succeeded_packs: int = 0
    no_findings_packs: int = 0
    failed_packs: int = 0
    request_json: dict | None
    result_summary_json: dict | None
    usage_summary_json: dict | None
    pack_results_json: list[dict] | None = None
    errors_json: list = Field(default_factory=list)
    warnings_json: list = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}
