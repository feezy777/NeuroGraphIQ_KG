"""Execution Plan schemas — unified plan for both Dry Run and real execution."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class OutputTokenEstimate(BaseModel):
    schema_min: int = 0
    expected: int = 0
    historical_sample_count: int = 0
    max_tokens: int = 0
    estimation_method: Literal["historical_usage", "schema_based", "fallback"] = "fallback"


class CostEstimate(BaseModel):
    currency: str = "CNY"
    base_estimated: float = 0.0       # -1.0 if price missing
    retry_risk: float = 0.0
    repair_risk: float = 0.0
    upper_bound: float = 0.0
    estimation_confidence: Literal["historical", "schema_based", "fallback"] = "fallback"


class RetryPolicy(BaseModel):
    max_attempts: int = 2
    backoff: str = "immediate"


class PlannedCall(BaseModel):
    planned_call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stage_name: str
    pack_index: int = 0
    pair_count: int = 0
    item_count: int = 0
    provider: str
    model: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    input_token_count: int = 0
    output_token_estimate: OutputTokenEstimate = Field(default_factory=OutputTokenEstimate)
    max_output_token_count: int = 0
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    cost_estimate: CostEstimate = Field(default_factory=CostEstimate)
    pricing_key: str = ""


class StagePlan(BaseModel):
    stage_name: str
    step_order: int
    required: bool = True
    depends_on: str | None = None
    estimated_item_count: int = 0
    planned_call_count: int = 0
    total_input_tokens: int = 0
    total_expected_output_tokens: int = 0
    total_max_output_tokens: int = 0
    total_base_cost: float = 0.0     # -1.0 if price missing
    total_retry_risk_cost: float = 0.0
    total_upper_bound_cost: float = 0.0
    estimation_method: Literal["historical_usage", "schema_based", "fallback"] = "fallback"
    calls: list[PlannedCall] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """Unified execution plan — used by both Dry Run (plan_only=true) and real execution."""
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_type: str = ""
    extraction_mode: str = "balanced"
    provider: str = ""
    model: str = ""                     # global default model (stage may override)
    candidate_count: int = 0
    total_pair_count: int = 0

    # Skip-existing stats
    skipped_existing_connections: int = 0
    skipped_existing_functions: int = 0
    planned_screening_pairs: int = 0    # balanced mode: pairs entering Step0
    planned_detail_pairs: int = 0       # pairs entering connection detail stage
    planned_function_items: int = 0     # projections entering function stage

    # Budget
    budget_cny: float = 10.0
    exceeds_budget: bool = False

    # Stage plans
    stages: list[StagePlan] = Field(default_factory=list)
    total_pack_count: int = 0
    total_planned_llm_calls: int = 0
    total_base_cost: float = 0.0    # -1.0 if any stage has missing pricing
    total_upper_bound_cost: float = 0.0

    # Stage model config
    stage_model_config: dict[str, dict[str, str]] = Field(default_factory=dict)

    # Pricing metadata
    pricing_model_version: str = ""
    pricing_missing: list[str] = Field(default_factory=list)
    cache_strategy: str = "conservative_cache_miss"
    estimation_timestamp: str = ""
    warnings: list[str] = Field(default_factory=list)


# ── DryRunPlan (backward compat alias) ────────────────────────

# DryRunPlan is now just ExecutionPlan. Keep an alias for transition.
DryRunPlan = ExecutionPlan
