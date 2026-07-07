"""Unified execution plan builder — one code path for both Dry Run and real execution.

Replaces dry_run_plan_builder.py. Adds extraction_mode, skip-existing, stage model config,
budget checking, and connection_screening support.
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pricing.loader import (
    CostResult,
    estimate_cost,
    get_version,
    lookup,
    normalize_pricing_key,
)
from app.schemas.execution_plan import (
    CostEstimate,
    ExecutionPlan,
    OutputTokenEstimate,
    PlannedCall,
    RetryPolicy,
    StagePlan,
)
from app.schemas.llm_composite_workflow import CompositeWorkflowRunRequest
from app.services.field_completion_prompt_engineering import estimate_prompt_tokens
from app.services.llm_connection_extraction_service import (
    _resolve_template,
    compute_pairs,
)
from app.services.llm_extraction_prompt_engineering import (
    DEFAULT_PAIRS_PER_PACK,
    build_compact_pair_records,
    order_pairs_by_priority,
    pack_pair_records,
)
from app.services.llm_prompt_defaults import render_user_prompt
from app.services.skip_existing_service import (
    query_existing_canonical_keys,
    query_existing_function_projection_ids,
)
from app.utils.tiktoken_utils import count_tokens_in_payload

logger = logging.getLogger(__name__)

FALLBACK_TOKENS_PER_PAIR = 120
FALLBACK_ITEMS_PER_PAIR = 0.78

# Default stage models per extraction mode
DEFAULT_STAGE_MODELS: dict[str, dict[str, dict[str, str]]] = {
    "balanced": {
        "connection_screening": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "connection_detail":    {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "function_extraction":  {"provider": "deepseek", "model": "deepseek-v4-flash"},
    },
    "exhaustive": {
        "extract_connections":          {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "extract_projection_functions":  {"provider": "deepseek", "model": "deepseek-v4-flash"},
    },
    "region_centered": {
        "connection_detail":    {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "function_extraction":  {"provider": "deepseek", "model": "deepseek-v4-flash"},
    },
}

# Default budgets per mode
DEFAULT_BUDGETS = {"balanced": 10.0, "exhaustive": 30.0, "region_centered": 5.0}

# Stage definitions per extraction mode
MODE_STAGE_DEFS: dict[str, list[dict[str, Any]]] = {
    "balanced": [
        {"step_key": "connection_screening", "step_label": "Connection Screening", "step_order": 1, "required": True, "dependency_step_key": None},
        {"step_key": "connection_detail",    "step_label": "Connection Detail",    "step_order": 2, "required": True, "dependency_step_key": "connection_screening"},
        {"step_key": "function_extraction",  "step_label": "Function Extraction",  "step_order": 3, "required": False, "dependency_step_key": "connection_detail"},
    ],
    "exhaustive": [
        {"step_key": "extract_connections",          "step_label": "Extract Connections",           "step_order": 1, "required": True, "dependency_step_key": None},
        {"step_key": "extract_projection_functions",  "step_label": "Extract Projection Functions", "step_order": 2, "required": False, "dependency_step_key": "extract_connections"},
    ],
    "region_centered": [
        {"step_key": "connection_detail",   "step_label": "Connection Detail",   "step_order": 1, "required": True, "dependency_step_key": None},
        {"step_key": "function_extraction", "step_label": "Function Extraction", "step_order": 2, "required": False, "dependency_step_key": "connection_detail"},
    ],
}


async def build_execution_plan(
    session: AsyncSession,
    request: CompositeWorkflowRunRequest,
    candidates: list[Any],
    system_prompt: str,
    prompt_template_key: str,
) -> ExecutionPlan:
    """Build a unified ExecutionPlan for the given request.

    Called by:
    - plan_only=true → returned directly (Dry Run)
    - plan_only=false → validated before creating a composite workflow run
    """
    extraction_mode = getattr(request, 'extraction_mode', None) or 'balanced'
    candidate_ids = [c.id for c in candidates]
    pair_count = len(candidate_ids) * (len(candidate_ids) - 1) // 2

    logger.info(
        "[composite-workflow][planner] build plan workflow_type=%s extraction_mode=%s candidate_ids_count=%d",
        request.workflow_type.value if hasattr(request.workflow_type, 'value') else str(request.workflow_type),
        extraction_mode,
        len(candidate_ids),
    )
    provider = request.provider
    model = request.model_name or ""
    budget = _resolve_budget(request, extraction_mode)

    # Resolve stage model config (merge user overrides onto defaults)
    stage_model_config = dict(DEFAULT_STAGE_MODELS.get(extraction_mode, {}))
    user_config = getattr(request, 'stage_model_config', None) or {}
    for k, v in user_config.items():
        stage_model_config[k] = {**stage_model_config.get(k, {}), **v}

    # Skip-existing queries
    force_reextract = getattr(request, 'force_reextract', False)
    skip_conn = getattr(request, 'skip_existing_connections', True)
    skip_func = getattr(request, 'skip_existing_functions', True)

    existing_conn_keys: set[str] = set()
    existing_func_ids: set[str] = set()
    if not force_reextract and skip_conn:
        existing_conn_keys = await query_existing_canonical_keys(session, candidate_ids)
    if not force_reextract and skip_func:
        existing_func_ids = await query_existing_function_projection_ids(session, candidate_ids)

    plan = ExecutionPlan(
        workflow_type=request.workflow_type.value if hasattr(request.workflow_type, 'value') else str(request.workflow_type),
        extraction_mode=extraction_mode,
        provider=provider,
        model=model,
        candidate_count=len(candidate_ids),
        total_pair_count=pair_count,
        skipped_existing_connections=len(existing_conn_keys),
        skipped_existing_functions=len(existing_func_ids),
        budget_cny=budget,
        stage_model_config=stage_model_config,
        pricing_model_version=get_version(),
        estimation_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    stage_defs = MODE_STAGE_DEFS.get(extraction_mode, MODE_STAGE_DEFS["exhaustive"])

    # Compute pair_strategy
    pair_strategy = "all_pairs"
    center_id = None
    if extraction_mode == "region_centered":
        pair_strategy = "region_centered"
        center_id = getattr(request, 'center_region_id', None)
        if center_id:
            from uuid import UUID
            center_id = UUID(str(center_id))

    # Compute raw pairs and candidate map
    candidate_map = {c.id: c for c in candidates}
    raw_pairs = compute_pairs(candidate_ids, pair_strategy=pair_strategy, center_candidate_id=center_id)
    ordered_pairs = order_pairs_by_priority(raw_pairs, candidate_map)

    stages: list[StagePlan] = []
    total_base_cost = 0.0
    total_upper_bound = 0.0
    prev_stage_calls: list[PlannedCall] = []

    for step_def in stage_defs:
        stage = await _build_stage_plan(
            session=session,
            step_def=step_def,
            candidates=candidates,
            candidate_map=candidate_map,
            ordered_pairs=ordered_pairs,
            existing_conn_keys=existing_conn_keys,
            existing_func_ids=existing_func_ids,
            provider=provider,
            model=model,
            stage_model_config=stage_model_config,
            extraction_mode=extraction_mode,
            system_prompt=system_prompt,
            skip_conn=skip_conn and not force_reextract,
            skip_func=skip_func and not force_reextract,
            prev_stage_calls=prev_stage_calls,
        )
        stages.append(stage)
        prev_stage_calls = stage.calls

        if stage.total_base_cost < 0:
            total_base_cost = -1.0
        elif total_base_cost >= 0:
            total_base_cost += stage.total_base_cost
        if stage.total_upper_bound_cost < 0 or total_upper_bound < 0:
            total_upper_bound = -1.0
        elif total_upper_bound >= 0:
            total_upper_bound += stage.total_upper_bound_cost

    plan.stages = stages
    plan.total_pack_count = sum(s.planned_call_count for s in stages)
    plan.total_planned_llm_calls = plan.total_pack_count
    plan.total_base_cost = round(total_base_cost, 4) if total_base_cost >= 0 else -1.0
    plan.total_upper_bound_cost = round(total_upper_bound, 4) if total_upper_bound >= 0 else -1.0
    plan.exceeds_budget = total_base_cost > budget

    # Pricing missing check
    missing: list[str] = []
    for stage in stages:
        for call in stage.calls:
            if call.cost_estimate.base_estimated < 0:
                key = call.pricing_key
                if key and key not in missing:
                    missing.append(key)
    plan.pricing_missing = missing
    if missing:
        plan.warnings.append(f"Price not configured for: {', '.join(missing)}. Cannot estimate cost.")
    if plan.exceeds_budget and total_base_cost >= 0:
        plan.warnings.append(f"Estimated cost ¥{total_base_cost:.2f} exceeds budget ¥{budget:.2f}")

    return plan


async def _build_stage_plan(
    session: AsyncSession,
    step_def: dict[str, Any],
    candidates: list[Any],
    candidate_map: dict,
    ordered_pairs: list,
    existing_conn_keys: set[str],
    existing_func_ids: set[str],
    provider: str,
    model: str,
    stage_model_config: dict[str, dict[str, str]],
    extraction_mode: str,
    system_prompt: str,
    skip_conn: bool,
    skip_func: bool,
    prev_stage_calls: list[PlannedCall],
) -> StagePlan:
    stage_name = step_def["step_key"]
    step_order = step_def["step_order"]
    required = step_def.get("required", True)
    depends_on = step_def.get("dependency_step_key")

    # Resolve stage-specific model
    stage_model = stage_model_config.get(stage_name, {})
    stage_provider = stage_model.get("provider", provider)
    stage_model_name = stage_model.get("model", model)

    # Build calls based on stage type
    if stage_name in ("connection_screening",):
        calls = _build_screening_calls(ordered_pairs, candidates, candidate_map, existing_conn_keys, skip_conn, stage_provider, stage_model_name, stage_name)
    elif stage_name in ("connection_detail", "extract_connections"):
        calls = _build_detail_calls(ordered_pairs, candidates, candidate_map, existing_conn_keys, skip_conn, stage_provider, stage_model_name, system_prompt, stage_name, prev_stage_calls)
    elif stage_name in ("function_extraction", "extract_projection_functions"):
        calls = _build_function_calls(prev_stage_calls, stage_provider, stage_model_name, stage_name, existing_func_ids, skip_func)
    else:
        calls = []

    # Resolve output estimates and costs
    for call in calls:
        await _resolve_output_estimate(session, call, extraction_mode)
        _resolve_cost(call)

    stage = StagePlan(
        stage_name=stage_name,
        step_order=step_order,
        required=required,
        depends_on=depends_on,
        planned_call_count=len(calls),
        total_input_tokens=sum(c.input_token_count for c in calls),
        total_expected_output_tokens=sum(c.output_token_estimate.expected for c in calls),
        total_max_output_tokens=sum(c.output_token_estimate.max_tokens for c in calls),
        calls=calls,
    )

    if any(c.cost_estimate.base_estimated < 0 for c in calls):
        stage.total_base_cost = -1.0
        stage.total_retry_risk_cost = -1.0
        stage.total_upper_bound_cost = -1.0
    else:
        stage.total_base_cost = round(sum(c.cost_estimate.base_estimated for c in calls), 4)
        stage.total_retry_risk_cost = round(sum(c.cost_estimate.retry_risk for c in calls), 4)
        stage.total_upper_bound_cost = round(sum(c.cost_estimate.upper_bound for c in calls), 4)

    methods = {c.output_token_estimate.estimation_method for c in calls}
    if "fallback" in methods:
        stage.estimation_method = "fallback"
    elif "schema_based" in methods:
        stage.estimation_method = "schema_based"
    else:
        stage.estimation_method = "historical_usage"

    return stage


def _build_screening_calls(
    ordered_pairs: list,
    candidates: list[Any],
    candidate_map: dict,
    existing_conn_keys: set[str],
    skip_conn: bool,
    provider: str,
    model: str,
    stage_name: str,
) -> list[PlannedCall]:
    """Build PlannedCalls for connection_screening (balanced Step0)."""
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    # Filter out existing connections
    active_pairs = []
    for src_id, tgt_id in ordered_pairs:
        key = make_pair_id(src_id, tgt_id)
        if skip_conn and key in existing_conn_keys:
            continue
        active_pairs.append((src_id, tgt_id))

    if not active_pairs:
        return []

    compact = build_compact_pair_records(candidates=candidates, pairs=active_pairs)
    packs = pack_pair_records(compact, pairs_per_pack=DEFAULT_PAIRS_PER_PACK)

    logger.info(
        "[balanced][screening] pairs computed candidate_ids_count=%d pair_count=%d pack_count=%d",
        len(candidates), len(active_pairs), len(packs),
    )

    # Use screening template
    template = _resolve_template("connection_screening_v1")

    calls: list[PlannedCall] = []
    for idx, pack in enumerate(packs):
        pairs_json = _json.dumps(pack, ensure_ascii=False)
        user_prompt = render_user_prompt(template, {"pairs_json": pairs_json})

        payload = {"system": template.system_prompt, "user": user_prompt}
        input_tokens = count_tokens_in_payload(payload, model=model)

        call = PlannedCall(
            stage_name=stage_name,
            pack_index=idx,
            pair_count=len(pack),
            item_count=len(pack),
            provider=provider,
            model=model,
            input_payload=payload,
            input_token_count=input_tokens,
            max_output_token_count=8192,  # screening needs less output
            retry_policy=RetryPolicy(max_attempts=2),
            pricing_key=f"{normalize_pricing_key(provider, model)[0]}/{normalize_pricing_key(provider, model)[1]}",
        )
        calls.append(call)

    return calls


def _build_detail_calls(
    ordered_pairs: list,
    candidates: list[Any],
    candidate_map: dict,
    existing_conn_keys: set[str],
    skip_conn: bool,
    provider: str,
    model: str,
    system_prompt: str,
    stage_name: str,
    prev_stage_calls: list[PlannedCall],
) -> list[PlannedCall]:
    """Build PlannedCalls for connection_detail or extract_connections."""
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    # If this is a detail stage following screening, only process pairs from screening output
    if prev_stage_calls and stage_name == "connection_detail":
        # In plan mode, we estimate: screening outputs ~positive + uncertain pairs
        # Build full set of non-skipped pairs from the same ordered_pairs
        active_pairs = []
        for src_id, tgt_id in ordered_pairs:
            key = make_pair_id(src_id, tgt_id)
            if skip_conn and key in existing_conn_keys:
                continue
            active_pairs.append((src_id, tgt_id))
    else:
        # Exhaustive: all non-skipped pairs
        active_pairs = []
        for src_id, tgt_id in ordered_pairs:
            key = make_pair_id(src_id, tgt_id)
            if skip_conn and key in existing_conn_keys:
                continue
            active_pairs.append((src_id, tgt_id))

    if not active_pairs:
        return []

    compact = build_compact_pair_records(candidates=candidates, pairs=active_pairs)
    packs = pack_pair_records(compact, pairs_per_pack=DEFAULT_PAIRS_PER_PACK)

    template = _resolve_template("same_granularity_connection_completion_v1")

    calls: list[PlannedCall] = []
    for idx, pack in enumerate(packs):
        pairs_json = _json.dumps(pack, ensure_ascii=False)
        user_prompt = render_user_prompt(template, {"pairs_json": pairs_json})

        payload = {"system": system_prompt, "user": user_prompt}
        input_tokens = count_tokens_in_payload(payload, model=model)

        call = PlannedCall(
            stage_name=stage_name,
            pack_index=idx,
            pair_count=len(pack),
            item_count=len(pack),
            provider=provider,
            model=model,
            input_payload=payload,
            input_token_count=input_tokens,
            max_output_token_count=16384,
            retry_policy=RetryPolicy(max_attempts=2),
            pricing_key=f"{normalize_pricing_key(provider, model)[0]}/{normalize_pricing_key(provider, model)[1]}",
        )
        calls.append(call)

    return calls


def _build_function_calls(
    prev_stage_calls: list[PlannedCall],
    provider: str,
    model: str,
    stage_name: str,
    existing_func_ids: set[str],
    skip_func: bool,
) -> list[PlannedCall]:
    """Build PlannedCalls for function_extraction or extract_projection_functions."""
    if not prev_stage_calls:
        return []

    total_items = sum(c.item_count for c in prev_stage_calls)
    # Apply skip-existing for functions
    skipped = min(len(existing_func_ids), total_items) if skip_func else 0
    active_items = max(1, total_items - skipped)

    num_packs = max(1, (active_items + DEFAULT_PAIRS_PER_PACK - 1) // DEFAULT_PAIRS_PER_PACK)

    calls: list[PlannedCall] = []
    for idx in range(num_packs):
        items_in_pack = min(DEFAULT_PAIRS_PER_PACK, active_items - idx * DEFAULT_PAIRS_PER_PACK)
        call = PlannedCall(
            stage_name=stage_name,
            pack_index=idx,
            pair_count=0,
            item_count=items_in_pack,
            provider=provider,
            model=model,
            input_payload={},
            input_token_count=max(512, items_in_pack * 200),
            max_output_token_count=16384,
            retry_policy=RetryPolicy(max_attempts=2),
            pricing_key=f"{normalize_pricing_key(provider, model)[0]}/{normalize_pricing_key(provider, model)[1]}",
        )
        calls.append(call)

    return calls


async def _resolve_output_estimate(
    session: AsyncSession,
    call: PlannedCall,
    extraction_mode: str,
) -> None:
    max_tokens = call.max_output_token_count or 16384

    hist = await _get_historical_output_stats(session, call.stage_name, call.provider, call.model, extraction_mode)
    if hist and hist.get("sample_count", 0) > 0:
        avg = hist["avg_per_item"]
        expected = max(256, int(call.item_count * avg))
        schema_min = max(64, int(call.item_count * avg * 0.5))
        call.output_token_estimate = OutputTokenEstimate(
            schema_min=schema_min, expected=expected,
            historical_sample_count=hist["sample_count"],
            max_tokens=max_tokens, estimation_method="historical_usage",
        )
        return

    schema_min = _estimate_schema_min(call.stage_name, call.item_count)
    fallback = max(schema_min, call.item_count * FALLBACK_TOKENS_PER_PAIR)
    call.output_token_estimate = OutputTokenEstimate(
        schema_min=schema_min, expected=fallback,
        historical_sample_count=0, max_tokens=max_tokens,
        estimation_method="schema_based" if schema_min > 0 else "fallback",
    )


def _estimate_schema_min(stage_name: str, item_count: int) -> int:
    if stage_name in ("connection_screening",):
        min_obj = {"likely_connections": [{"source_id": "x", "target_id": "y", "label": "positive", "confidence": 0.5}], "summary": {"screened_pair_count": 1, "positive_count": 0, "uncertain_count": 0}}
    elif stage_name in ("connection_detail", "extract_connections"):
        min_obj = {"projections": [{"source_id": "x", "target_id": "y", "connection_type": "anatomical", "directionality": "unknown", "evidence_level": "low", "evidence": ["based on adjacency"]}], "no_connections": [], "warnings": []}
    elif stage_name in ("function_extraction", "extract_projection_functions"):
        min_obj = {"functions": [{"projection_id": "x", "function_name": "motor control", "function_category": "motor", "evidence_level": "low", "evidence": ["based on known function"]}], "no_functions": [], "warnings": []}
    else:
        min_obj = {"items": [{"id": "x", "name": "test"}]}

    min_json = _json.dumps(min_obj, ensure_ascii=False)
    return max(1, estimate_prompt_tokens(min_json) * item_count)


async def _get_historical_output_stats(
    session: AsyncSession, stage_name: str, provider: str, model: str, extraction_mode: str,
) -> dict[str, Any] | None:
    query = text("""
        SELECT COUNT(*) AS sample_count,
               AVG(CAST(completion_tokens AS FLOAT) / NULLIF(GREATEST(pair_count, 1), 0)) AS avg_per_item
        FROM llm_usage_history
        WHERE stage_name = :stage AND provider = :provider AND model = :model
    """)
    try:
        result = await session.execute(query, {"stage": stage_name, "provider": provider, "model": model})
        row = result.one_or_none()
        if row and row.sample_count > 0:
            return {"sample_count": row.sample_count, "avg_per_item": float(row.avg_per_item or 0)}
    except Exception:
        # Table may not exist yet (llm_usage_history created by migration 038)
        logger.debug("[execution-plan] historical stats query unavailable for %s/%s", stage_name, model)
    return None


def _resolve_cost(call: PlannedCall) -> None:
    price_entry = lookup(call.provider, call.model)
    if price_entry is None:
        call.cost_estimate = CostEstimate(currency="N/A", base_estimated=-1.0, retry_risk=-1.0, upper_bound=-1.0, estimation_confidence="fallback")
        return

    base_result = estimate_cost(call.input_token_count, call.output_token_estimate.expected, price_entry)
    max_result = estimate_cost(call.input_token_count, call.output_token_estimate.max_tokens, price_entry)

    retry_attempts = call.retry_policy.max_attempts - 1
    retry_rate = 0.08
    retry_cost = base_result.base_estimated * retry_rate * retry_attempts
    upper_bound = max_result.base_estimated * call.retry_policy.max_attempts

    confidence = "historical" if call.output_token_estimate.estimation_method == "historical_usage" else ("schema_based" if call.output_token_estimate.estimation_method == "schema_based" else "fallback")
    call.cost_estimate = CostEstimate(base_estimated=round(base_result.base_estimated, 4), retry_risk=round(retry_cost, 4), upper_bound=round(upper_bound, 4), estimation_confidence=confidence)


def _resolve_budget(request: CompositeWorkflowRunRequest, extraction_mode: str) -> float:
    budget = getattr(request, 'budget_cny', None)
    if budget is not None and budget > 0:
        return float(budget)
    return DEFAULT_BUDGETS.get(extraction_mode, 10.0)
