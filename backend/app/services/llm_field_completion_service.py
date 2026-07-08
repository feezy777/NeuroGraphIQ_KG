"""Universal field completion service (Step 10.3).

Mirror/candidate writes only — never final_* / kg_* / auto-approve / auto-promote.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_field_completion import LlmFieldCompletionItem, LlmFieldCompletionRun
from app.schemas.llm_field_completion import (
    FieldCompletionItemRead,
    FieldCompletionRelatedGroup,
    FieldCompletionRelatedTargetsResponse,
    FieldCompletionRunDetail,
    FieldCompletionRunRead,
    FieldScope,
    FieldUpdateSummary,
    ItemStatus,
    OverwritePolicy,
    RunStatus,
    TargetType,
    UniversalFieldCompletionRequest,
    UniversalFieldCompletionResponse,
)
from app.services.field_completion_registry import (
    GLOBAL_READONLY_FIELDS,
    REGISTRY,
    TargetTypeNotImplementedError,
    UnsupportedTargetTypeError,
    get_allowed_fields,
    get_field_value,
    get_mirror_column,
    get_overlay_value,
    get_registry_entry,
    is_deterministic_field,
    is_empty_value,
    is_overlay_field,
    object_to_json,
    resolve_field_name,
    write_to_overlay,
)
from app.services.field_completion_prompt_engineering import (
    BUNDLE_CONSISTENCY_KEY,
    CIRCUIT_FAMILY_TYPES,
    resolve_prompt_template,
    select_field_completion_prompt_key,
)
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import ProviderNotConfiguredError, UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config
from app.utils.json_safety import json_dumps_safe, to_jsonable

logger = logging.getLogger(__name__)

CN_FORMAL_FIELDS = frozenset({"name_cn", "step_name_cn", "function_term_cn"})
EN_FORMAL_FIELDS = frozenset({"name_en", "step_name_en", "function_term_en"})


class MirrorCircuitFunctionsNotInitializedForFieldCompletionError(Exception):
    """Raised when mirror_circuit_functions table is missing (migration 033)."""

    code = "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED"
    migration_path = "backend/migrations/033_mirror_circuit_functions.sql"


def _contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _get_existing_overlay_dict(target: Any) -> dict[str, Any]:
    for attr in ("normalized_payload_json", "raw_payload_json"):
        payload = getattr(target, attr, None)
        if isinstance(payload, dict):
            overlay = payload.get("formal_field_overlay")
            if isinstance(overlay, dict):
                return dict(overlay)
    attrs = getattr(target, "attributes", None)
    if isinstance(attrs, dict):
        overlay = attrs.get("formal_field_overlay")
        if isinstance(overlay, dict):
            return dict(overlay)
    return {}


def _resolve_circuit_id(target: Any, target_type: TargetType) -> uuid.UUID | None:
    if target_type == TargetType.circuit:
        return getattr(target, "id", None)
    circuit_id = getattr(target, "circuit_id", None)
    return circuit_id if isinstance(circuit_id, uuid.UUID) else None


async def build_circuit_bundle_context(
    session: AsyncSession,
    circuit_id: uuid.UUID,
) -> tuple[dict[str, Any], list[str]]:
    """Read-only bundle context for circuit + steps + functions."""
    from app.models.candidate import CandidateBrainRegion
    from app.models.mirror_kg import MirrorCircuitRegion, MirrorRegionCircuit
    from app.models.mirror_macro_clinical import MirrorCircuitStep

    warnings: list[str] = []
    circuit = await session.get(MirrorRegionCircuit, circuit_id)
    if circuit is None:
        return {}, [f"circuit {circuit_id} not found for bundle context"]

    step_stmt = (
        select(MirrorCircuitStep)
        .where(MirrorCircuitStep.circuit_id == circuit_id)
        .order_by(MirrorCircuitStep.step_order)
    )
    steps = list((await session.execute(step_stmt)).scalars().all())

    cf_entry = REGISTRY.get(TargetType.circuit_function)
    circuit_functions: list[dict[str, Any]] = []
    if cf_entry is not None and cf_entry.supported:
        from app.services import mirror_macro_clinical_service

        try:
            rows, _ = await mirror_macro_clinical_service.list_mirror_circuit_functions(
                session,
                circuit_id=circuit_id,
                limit=5,
                offset=0,
            )
            for row in rows:
                circuit_functions.append({
                    "id": str(row.id)[:12],
                    "function_term_en": (row.function_term_en or "")[:80] or None,
                    "function_term_cn": (row.function_term_cn or "")[:80] or None,
                    "function_domain": row.function_domain,
                    "function_role": row.function_role,
                })
        except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError:
            warnings.append(MirrorCircuitFunctionsNotInitializedForFieldCompletionError.code)

    region_ids: set[uuid.UUID] = set()
    for step in steps:
        if step.region_candidate_id:
            region_ids.add(step.region_candidate_id)

    cr_stmt = select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == circuit_id)
    for cr in (await session.execute(cr_stmt)).scalars().all():
        if cr.region_candidate_id:
            region_ids.add(cr.region_candidate_id)

    regions: list[dict[str, Any]] = []
    if region_ids:
        r_stmt = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(region_ids))
        regions = [object_to_json(r) for r in (await session.execute(r_stmt)).scalars().all()]

    overlay: dict[str, Any] = {}
    for obj in (circuit, *steps):
        overlay.update(_get_existing_overlay_dict(obj))

    evidence: list[dict[str, Any]] = []
    if circuit.evidence_text:
        evidence.append({"source": "circuit", "text": circuit.evidence_text})
    for step in steps:
        if step.evidence_text:
            evidence.append({"source": "circuit_step", "step_id": str(step.id), "text": step.evidence_text})

    ctx = {
        "circuit": object_to_json(circuit),
        "circuit_steps": [object_to_json(s) for s in steps],
        "circuit_functions": circuit_functions,
        "related_regions": regions,
        "related_projections": [],
        "evidence": evidence,
        "existing_overlay": overlay,
    }
    return to_jsonable(ctx), warnings


async def get_bundle_context_for_target(
    session: AsyncSession,
    target: Any,
    target_type: TargetType,
    cache: dict[uuid.UUID, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    circuit_id = _resolve_circuit_id(target, target_type)
    if circuit_id is None:
        return {}, []
    if circuit_id in cache:
        return cache[circuit_id], []
    try:
        ctx, warnings = await build_circuit_bundle_context(session, circuit_id)
    except Exception as exc:
        logger.debug("bundle context DB lookup failed for %s: %s", circuit_id, exc)
        ctx = {
            "circuit": object_to_json(target) if target_type == TargetType.circuit else {},
            "circuit_steps": [],
            "circuit_functions": [],
            "related_regions": [],
            "related_projections": [],
            "evidence": [],
            "existing_overlay": _get_existing_overlay_dict(target),
        }
        warnings = []
    cache[circuit_id] = ctx
    return ctx, warnings


def build_template_plan(
    targets: dict[uuid.UUID, Any],
    entry,
    request: UniversalFieldCompletionRequest,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for tid, target in targets.items():
        fields = determine_fields_to_complete(
            target,
            entry,
            field_scope=request.field_scope,
            selected_fields=request.selected_fields,
        )
        for field_name in fields:
            if is_deterministic_field(entry, field_name):
                continue
            prompt_key = select_field_completion_prompt_key(request.target_type, field_name)
            plan.append({
                "target_type": request.target_type.value,
                "target_id": str(tid),
                "field_name": field_name,
                "prompt_key": prompt_key,
                "target_count": 1,
                "uses_deepseek": True,
            })
    return plan


def estimate_model_calls(
    template_plan: list[dict[str, Any]],
    circuit_ids: set[uuid.UUID],
    *,
    target_type: TargetType,
) -> int:
    del circuit_ids, target_type
    field_names = {p["field_name"] for p in template_plan if p.get("uses_deepseek", True)}
    return len(field_names)


def format_reasoning_with_consistency(upd: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if upd.get("reasoning_summary"):
        parts.append(str(upd["reasoning_summary"]))
    checks = upd.get("consistency_checks")
    if isinstance(checks, list) and checks:
        summaries: list[str] = []
        for check in checks:
            if isinstance(check, dict):
                summaries.append(
                    f"{check.get('check', '?')}: {check.get('status', '?')} — {check.get('message', '')}"
                )
        if summaries:
            parts.append("consistency: " + "; ".join(summaries))
    return " | ".join(parts) if parts else None


def validate_field_value_quality(
    field_name: str,
    value: Any,
) -> tuple[bool, str | None, list[str]]:
    """Return (accept, reject_reason, quality_warnings)."""
    quality_warnings: list[str] = []
    if value is None or is_empty_value(value):
        return True, None, quality_warnings
    if not isinstance(value, str):
        return True, None, quality_warnings
    if field_name in CN_FORMAL_FIELDS or field_name.endswith("_cn"):
        if not _contains_chinese(value):
            return False, f"{field_name} must contain Chinese characters", quality_warnings
    if field_name in EN_FORMAL_FIELDS or field_name.endswith("_en"):
        if _contains_chinese(value) and not re.search(r"[A-Za-z]", value):
            quality_warnings.append(f"{field_name} appears to be pure Chinese; expected English")
    return True, None, quality_warnings


def build_field_specific_prompt(
    entry,
    target: Any,
    field_name: str,
    request: UniversalFieldCompletionRequest,
    *,
    context: dict[str, Any],
    bundle_context: dict[str, Any],
    bundle_consistency: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any], str]:
    prompt_key = select_field_completion_prompt_key(request.target_type, field_name)
    if prompt_key == "universal_field_completion_v1":
        system_prompt, user_prompt, prompt_json = build_universal_prompt(
            entry,
            target,
            [field_name],
            request,
            context=context,
        )
        prompt_json["template_key"] = prompt_key
        prompt_json["field_name"] = field_name
        return system_prompt, user_prompt, prompt_json, prompt_key

    tpl = resolve_prompt_template(prompt_key, request.prompt_overrides)
    current_value = get_field_value(target, field_name)
    values = {
        "target_type": entry.target_type.value,
        "formal_schema": entry.formal_schema or "",
        "formal_table": entry.formal_table or entry.final_table or "",
        "field_name": field_name,
        "current_value": json_dumps_safe(current_value, ensure_ascii=False) if current_value is not None else "null",
        "missing_fields_json": json_dumps_safe(
            [field_name] if is_empty_value(current_value) else [],
            ensure_ascii=False,
        ),
        "overwrite_policy": request.overwrite_policy.value,
        "allowed_fields_json": json_dumps_safe(list(entry.enrichable_fields), ensure_ascii=False),
        "current_object_json": json_dumps_safe(context.get("current_object_json", object_to_json(target)), ensure_ascii=False),
        "bundle_context_json": json_dumps_safe(bundle_context, ensure_ascii=False),
        "related_steps_json": json_dumps_safe(bundle_context.get("circuit_steps", []), ensure_ascii=False),
        "related_functions_json": json_dumps_safe(bundle_context.get("circuit_functions", []), ensure_ascii=False),
        "related_regions_json": json_dumps_safe(bundle_context.get("related_regions", []), ensure_ascii=False),
        "related_projections_json": json_dumps_safe(bundle_context.get("related_projections", []), ensure_ascii=False),
        "evidence_json": json_dumps_safe(bundle_context.get("evidence", []), ensure_ascii=False),
        "provenance_json": json_dumps_safe(context.get("provenance_json", {}), ensure_ascii=False),
        "existing_overlay_json": json_dumps_safe(
            bundle_context.get("existing_overlay") or _get_existing_overlay_dict(target),
            ensure_ascii=False,
        ),
        "bundle_consistency_json": json_dumps_safe(bundle_consistency or {}, ensure_ascii=False),
        "field_specific_constraints": "",
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = to_jsonable({
        "template_key": prompt_key,
        "target_type": entry.target_type.value,
        "target_id": str(getattr(target, "id", "")),
        "field_name": field_name,
        "overwrite_policy": request.overwrite_policy.value,
    })
    return tpl.system_prompt, user_prompt, prompt_json, prompt_key


def build_bundle_consistency_prompt(
    bundle_context: dict[str, Any],
    *,
    missing_fields: list[str],
    prompt_overrides: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    tpl = resolve_prompt_template(BUNDLE_CONSISTENCY_KEY, prompt_overrides)
    values = {
        "circuit_json": json_dumps_safe(bundle_context.get("circuit", {}), ensure_ascii=False),
        "circuit_steps_json": json_dumps_safe(bundle_context.get("circuit_steps", []), ensure_ascii=False),
        "circuit_functions_json": json_dumps_safe(bundle_context.get("circuit_functions", []), ensure_ascii=False),
        "related_regions_json": json_dumps_safe(bundle_context.get("related_regions", []), ensure_ascii=False),
        "related_projections_json": json_dumps_safe(bundle_context.get("related_projections", []), ensure_ascii=False),
        "evidence_json": json_dumps_safe(bundle_context.get("evidence", []), ensure_ascii=False),
        "existing_overlay_json": json_dumps_safe(bundle_context.get("existing_overlay", {}), ensure_ascii=False),
        "missing_fields_json": json_dumps_safe(missing_fields, ensure_ascii=False),
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {"template_key": BUNDLE_CONSISTENCY_KEY}
    return tpl.system_prompt, user_prompt, prompt_json


async def run_bundle_consistency_check(
    session: AsyncSession,
    request: UniversalFieldCompletionRequest,
    *,
    bundle_context: dict[str, Any],
    missing_fields: list[str],
    provider_key: str,
    resolved_model: str,
) -> dict[str, Any]:
    system_prompt, user_prompt, _ = build_bundle_consistency_prompt(
        bundle_context,
        missing_fields=missing_fields,
        prompt_overrides=request.prompt_overrides,
    )
    tpl = resolve_prompt_template(BUNDLE_CONSISTENCY_KEY, request.prompt_overrides)
    if provider_key == "mock":
        return {}
    response = await call_provider(
        provider_key,
        model=resolved_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        response_schema=tpl.output_schema_json or None,
    )
    if response.parsed_json is not None:
        return to_jsonable(response.parsed_json)
    if response.raw_text:
        return to_jsonable(parse_llm_json_response(response.raw_text))
    return {}


class ProviderNotConfiguredServiceError(Exception):
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(message)


def _resolve_model(provider_key: str, model_name: str | None) -> str:
    if provider_key == "deepseek":
        cfg = get_deepseek_runtime_config()
        return model_name or cfg.default_model
    if provider_key == "kimi":
        cfg = get_kimi_runtime_config()
        return model_name or cfg.default_model
    raise UnknownProviderError(provider_key)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        raise ValueError(f"unknown prompt template: {template_key}")
    return tpl


def determine_fields_to_complete(
    target: Any,
    entry,
    *,
    field_scope: FieldScope,
    selected_fields: list[str],
) -> list[str]:
    enrichable = list(entry.enrichable_fields)
    if field_scope == FieldScope.all_enrichable_fields:
        candidates = enrichable
    elif field_scope == FieldScope.selected_fields:
        resolved = []
        for name in selected_fields:
            col = resolve_field_name(entry, name)
            if col and col in enrichable:
                resolved.append(col)
        candidates = resolved
    else:
        candidates = [f for f in enrichable if is_empty_value(get_field_value(target, f))]

    seen: set[str] = set()
    out: list[str] = []
    for f in candidates:
        if f not in seen and f not in GLOBAL_READONLY_FIELDS:
            seen.add(f)
            out.append(f)
    return out


def build_target_context(
    target: Any,
    entry,
    *,
    include_provenance: bool,
    include_related_objects: bool,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {"current_object_json": object_to_json(target)}
    if include_provenance:
        prov = {}
        for key in ("llm_run_id", "batch_id", "resource_id", "created_by"):
            val = get_field_value(target, key)
            if val is not None:
                prov[key] = str(val)
        ctx["provenance_json"] = prov
    if include_related_objects:
        related: dict[str, Any] = {}
        for rel_key in (
            "source_region_candidate_id",
            "target_region_candidate_id",
            "region_candidate_id",
            "circuit_id",
            "projection_id",
        ):
            val = get_field_value(target, rel_key)
            if val is not None:
                related[rel_key] = str(val)
        ctx["related_context_json"] = related
    ctx["target_schema_json"] = {
        "target_type": entry.target_type.value,
        "formal_database": "NeuroGraphIQ_KG_V3",
        "formal_schema": entry.formal_schema or "",
        "formal_table": entry.formal_table or entry.final_table or "",
        "mirror_table": entry.mirror_table,
        "enrichable_fields": list(entry.enrichable_fields),
        "required_fields": list(entry.required_fields),
        "allowed_fields": list(get_allowed_fields(entry)),
        "direct_write_fields": list(entry.direct_write_fields),
        "overlay_write_fields": list(entry.overlay_write_fields),
        "readonly_fields": list(entry.readonly_fields),
        "note": (
            "field_name must be one of enrichable_fields. "
            "Use exact formal field names (e.g. name_cn, name_en, circuit_class). "
            "Do not use mirror-only names such as circuit_name or function_term."
        ),
    }
    return to_jsonable(ctx)


def build_universal_prompt(
    entry,
    target: Any,
    fields_to_complete: list[str],
    request: UniversalFieldCompletionRequest,
    *,
    context: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(request.prompt_template_key)
    missing = [f for f in fields_to_complete if is_empty_value(get_field_value(target, f))]
    values = {
        "target_type": entry.target_type.value,
        "target_schema_json": json_dumps_safe(context.get("target_schema_json", {}), ensure_ascii=False),
        "current_object_json": json_dumps_safe(context.get("current_object_json", {}), ensure_ascii=False),
        "missing_fields_json": json_dumps_safe(missing, ensure_ascii=False),
        "selected_fields_json": json_dumps_safe(fields_to_complete, ensure_ascii=False),
        "related_context_json": json_dumps_safe(context.get("related_context_json", {}), ensure_ascii=False),
        "provenance_json": json_dumps_safe(context.get("provenance_json", {}), ensure_ascii=False),
        "allowed_fields_json": json_dumps_safe(list(entry.enrichable_fields), ensure_ascii=False),
        "overwrite_policy": request.overwrite_policy.value,
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "target_type": entry.target_type.value,
        "target_id": str(getattr(target, "id", "")),
        "fields_to_complete": fields_to_complete,
        "overwrite_policy": request.overwrite_policy.value,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_field_completion_response(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        parsed = raw
    else:
        parsed = parse_llm_json_response(raw)
    updates = parsed.get("field_updates")
    if updates is None:
        updates = []
    if not isinstance(updates, list):
        raise ValueError("field_updates must be a list")
    warnings = parsed.get("warnings")
    if warnings is None:
        warnings = []
    if not isinstance(warnings, list):
        warnings = []
    return {"field_updates": updates, "warnings": warnings}


def parse_field_completion_provider_response(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse provider output: dict, JSON string, markdown fenced JSON, or content/message wrapper."""
    if isinstance(raw, dict):
        if "field_updates" in raw:
            return parse_field_completion_response(raw)
        for key in ("content", "message", "data", "result"):
            inner = raw.get(key)
            if inner is None:
                continue
            try:
                return parse_field_completion_provider_response(inner)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return parse_field_completion_response(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("empty provider response")
        return parse_field_completion_response(text)
    raise ValueError(f"unsupported provider response type: {type(raw).__name__}")


def validate_field_updates(entry, updates: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str | None]]:
    validated: list[tuple[dict[str, Any], str | None]] = []
    for upd in updates:
        if not isinstance(upd, dict):
            validated.append(({}, "invalid update object"))
            continue
        name = upd.get("field_name")
        if not isinstance(name, str):
            validated.append((upd, "missing field_name"))
            continue
        if name in entry.field_aliases and name not in entry.enrichable_fields:
            validated.append(
                (upd, f"legacy field_name: {name}. Use formal field names from NeuroGraphIQ_KG_V3."),
            )
            continue
        col = resolve_field_name(entry, name)
        if col is None:
            validated.append(
                (upd, f"invalid field_name: {name}. Use formal field names from NeuroGraphIQ_KG_V3."),
            )
            continue
        if col in entry.readonly_fields or col in GLOBAL_READONLY_FIELDS:
            validated.append((upd, f"readonly field_name: {name}"))
            continue
        normalized = dict(upd)
        normalized["field_name"] = col
        validated.append((normalized, None))
    return validated


async def load_targets(
    session: AsyncSession,
    target_type: TargetType,
    target_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Any]:
    entry = get_registry_entry(target_type)
    if target_type == TargetType.circuit_function:
        from app.services import mirror_macro_clinical_service

        try:
            await mirror_macro_clinical_service.list_mirror_circuit_functions(
                session, limit=1, offset=0
            )
        except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError as exc:
            raise MirrorCircuitFunctionsNotInitializedForFieldCompletionError() from exc
    found: dict[uuid.UUID, Any] = {}
    for tid in target_ids:
        obj = await session.get(entry.model_class, tid)
        if obj is not None:
            found[tid] = obj
    return found


async def create_completion_run(
    session: AsyncSession,
    request: UniversalFieldCompletionRequest,
    *,
    resolved_model: str,
) -> LlmFieldCompletionRun:
    now = datetime.now(timezone.utc)
    run = LlmFieldCompletionRun(
        id=uuid.uuid4(),
        provider=request.provider.lower(),
        model_name=resolved_model,
        target_type=request.target_type.value,
        target_count=len(request.target_ids),
        field_scope=request.field_scope.value,
        selected_fields_json=list(request.selected_fields),
        overwrite_policy=request.overwrite_policy.value,
        dry_run=request.dry_run,
        create_mirror_updates=request.create_mirror_updates,
        create_evidence=request.create_evidence,
        status=RunStatus.pending.value,
        request_json=to_jsonable(request.model_dump(mode="json")),
        started_at=now,
    )
    session.add(run)
    await session.flush()
    return run


def _make_item(
    run_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    field_name: str,
    *,
    old_value: Any,
    status: ItemStatus,
    suggested: Any = None,
    applied: Any = None,
    confidence: float | None = None,
    evidence_text: str | None = None,
    reasoning_summary: str | None = None,
    uncertainty_reason: str | None = None,
    error_message: str | None = None,
) -> LlmFieldCompletionItem:
    return LlmFieldCompletionItem(
        id=uuid.uuid4(),
        run_id=run_id,
        target_type=target_type,
        target_id=target_id,
        field_name=field_name,
        old_value_json=to_jsonable(old_value),
        suggested_value_json=to_jsonable(suggested),
        applied_value_json=to_jsonable(applied),
        confidence=to_jsonable(confidence) if confidence is not None else None,
        evidence_text=evidence_text,
        reasoning_summary=reasoning_summary,
        uncertainty_reason=uncertainty_reason,
        update_status=status.value,
        error_message=error_message,
    )


# ── Model tier priority for mirror_status ────────────────────────────────────
_MODEL_TIER = {
    "deepseek-reasoner": ("llm_reasoner", 40),
    "deepseek-v4-pro": ("llm_v4_pro", 30),
    "deepseek-chat": ("llm_suggested", 20),
    "kimi": ("llm_kimi", 10),
}
_DEFAULT_TIER_STATUS = "llm_suggested"
_DEFAULT_TIER_PRIORITY = 15


def _resolve_model_status(model_name: str | None) -> tuple[str, int]:
    """Return (mirror_status, priority) for a model. Higher priority wins."""
    if not model_name:
        return _DEFAULT_TIER_STATUS, _DEFAULT_TIER_PRIORITY
    model_lower = model_name.lower()
    # Check exact match first, then prefix match
    for prefix, (status, pri) in _MODEL_TIER.items():
        if model_lower == prefix or model_lower.startswith(prefix):
            return status, pri
    # Check for kimi prefix
    if "kimi" in model_lower or "moonshot" in model_lower:
        return _MODEL_TIER["kimi"]
    return _DEFAULT_TIER_STATUS, _DEFAULT_TIER_PRIORITY


def _should_update_mirror_status(target: Any, model_name: str | None) -> bool:
    """Only update mirror_status if new model has equal or higher priority than existing."""
    _, new_pri = _resolve_model_status(model_name)
    existing = getattr(target, "mirror_status", None) or ""
    # Map existing status to priority
    existing_pri = 0
    for _prefix, (_status, pri) in _MODEL_TIER.items():
        if existing == _status:
            existing_pri = pri
            break
    if existing_pri == 0:
        existing_pri = _DEFAULT_TIER_PRIORITY if existing == _DEFAULT_TIER_STATUS else 5
    return new_pri >= existing_pri


def apply_field_update(
    target: Any,
    field_name: str,
    value: Any,
    *,
    overwrite_policy: OverwritePolicy,
    create_mirror_updates: bool,
    entry=None,
    run_id: uuid.UUID | None = None,
    confidence: float | None = None,
    overlay_source: str | None = None,
    overlay_meta_extra: dict[str, Any] | None = None,
    resolved_model: str | None = None,
) -> ItemStatus:
    """Apply a formal field value to the mirror target (direct column or overlay).

    Never writes to final_* / kg_* / macro_clinical.*.
    """
    if field_name in GLOBAL_READONLY_FIELDS:
        return ItemStatus.skipped_readonly_field

    if value is None or is_empty_value(value):
        return ItemStatus.skipped_invalid_field

    effective_policy = overwrite_policy

    # Resolve model-tier mirror_status
    tier_status = _resolve_model_status(resolved_model)[0]

    def _update_tier():
        """Update mirror_status if model tier is higher than existing."""
        if hasattr(target, "mirror_status") and _should_update_mirror_status(target, resolved_model):
            target.mirror_status = tier_status

    def _result(status: ItemStatus) -> ItemStatus:
        _update_tier()
        return status

    if effective_policy == OverwritePolicy.suggest_only or not create_mirror_updates:
        return _result(ItemStatus.suggested)

    # ---- Overlay path (formal field with no direct mirror column) ------------
    if entry is not None and is_overlay_field(entry, field_name):
        existing = get_overlay_value(target, field_name)
        if not is_empty_value(existing) and effective_policy == OverwritePolicy.fill_missing_only:
            return _result(ItemStatus.skipped_existing_value)
        if write_to_overlay(
            target,
            field_name,
            value,
            run_id=run_id,
            confidence=confidence,
            source=overlay_source or "llm_field_completion",
            meta_extra=overlay_meta_extra,
        ):
            return _result(ItemStatus.applied_overlay)
        return _result(ItemStatus.suggested)

    # ---- Direct / alias write path -------------------------------------------
    mirror_col = get_mirror_column(entry, field_name) if entry is not None else field_name

    try:
        table_cols = {c.name for c in target.__table__.columns}  # type: ignore[attr-defined]
        if mirror_col not in table_cols:
            if write_to_overlay(
                target,
                field_name,
                value,
                run_id=run_id,
                confidence=confidence,
                source=overlay_source or "llm_field_completion",
                meta_extra=overlay_meta_extra,
            ):
                return _result(ItemStatus.applied_overlay)
            return _result(ItemStatus.suggested)
    except AttributeError:
        pass

    current = getattr(target, mirror_col, None)
    if not is_empty_value(current) and effective_policy == OverwritePolicy.fill_missing_only:
        return _result(ItemStatus.skipped_existing_value)

    setattr(target, mirror_col, value)
    return _result(ItemStatus.applied_direct)


async def call_provider(
    provider_key: str,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    response_schema: dict[str, Any] | None,
):
    provider = get_llm_provider(provider_key)
    return await provider.complete_json(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        response_schema=response_schema,
    )


def summarize_completion_run(
    run: LlmFieldCompletionRun,
    items: list[LlmFieldCompletionItem],
) -> dict[str, int]:
    counts: dict[str, int] = {
        "target_count": run.target_count,
        "field_update_count": len(items),
        "updated_count": 0,
        "suggested_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "applied_direct_count": 0,
        "applied_overlay_count": 0,
        "invalid_field_count": 0,
        "readonly_field_count": 0,
    }
    applied_statuses = {
        ItemStatus.applied.value,
        ItemStatus.applied_direct.value,
        ItemStatus.applied_overlay.value,
    }
    for item in items:
        st = item.update_status
        if st in applied_statuses:
            counts["updated_count"] += 1
            if st == ItemStatus.applied_direct.value:
                counts["applied_direct_count"] += 1
            elif st == ItemStatus.applied_overlay.value:
                counts["applied_overlay_count"] += 1
            else:
                # legacy applied — treat as overlay when field is overlay-only
                counts["applied_overlay_count"] += 1
        elif st == ItemStatus.suggested.value or st == ItemStatus.prompt_preview.value:
            counts["suggested_count"] += 1
        elif st == ItemStatus.skipped_invalid_field.value:
            counts["skipped_count"] += 1
            counts["invalid_field_count"] += 1
        elif st == ItemStatus.skipped_readonly_field.value:
            counts["skipped_count"] += 1
            counts["readonly_field_count"] += 1
        elif st.startswith("skipped"):
            counts["skipped_count"] += 1
        elif st == ItemStatus.failed.value:
            counts["failed_count"] += 1
    run.summary_json = to_jsonable(counts)
    return counts


def _build_response(
    run: LlmFieldCompletionRun,
    items: list[LlmFieldCompletionItem],
    *,
    prompt_preview: dict[str, Any] | None,
    warnings: list[str],
    errors: list[str],
) -> UniversalFieldCompletionResponse:
    counts = run.summary_json or summarize_completion_run(run, items)
    field_updates = [
        FieldUpdateSummary(
            target_id=item.target_id,
            field_name=item.field_name,
            update_status=ItemStatus(item.update_status),
            suggested_value=to_jsonable(item.suggested_value_json),
            applied_value=to_jsonable(item.applied_value_json),
        )
        for item in items
    ]
    safe_preview = to_jsonable(prompt_preview) if prompt_preview is not None else None
    safe_counts = to_jsonable(counts)
    return UniversalFieldCompletionResponse(
        run_id=run.id,
        status=RunStatus(run.status),
        provider=run.provider,
        model_name=run.model_name,
        target_type=TargetType(run.target_type),
        target_count=run.target_count,
        updated_count=safe_counts.get("updated_count", 0),
        suggested_count=safe_counts.get("suggested_count", 0),
        skipped_count=safe_counts.get("skipped_count", 0),
        failed_count=safe_counts.get("failed_count", 0),
        applied_direct_count=safe_counts.get("applied_direct_count", 0),
        applied_overlay_count=safe_counts.get("applied_overlay_count", 0),
        summary_json=safe_counts,
        field_updates=field_updates,
        prompt_preview=safe_preview,
        warnings=list(warnings),
        errors=list(errors),
        dry_run=run.dry_run,
    )


async def run_universal_field_completion(
    session: AsyncSession,
    request: UniversalFieldCompletionRequest,
) -> UniversalFieldCompletionResponse:
    warnings: list[str] = list()
    errors: list[str] = list()

    try:
        entry = get_registry_entry(request.target_type)
    except UnsupportedTargetTypeError:
        raise
    except TargetTypeNotImplementedError:
        raise

    provider_key = request.provider.lower()
    if provider_key not in ("deepseek", "kimi", "mock"):
        raise UnknownProviderError(request.provider)

    resolved_model = (
        _resolve_model(provider_key, request.model_name)
        if provider_key != "mock"
        else (request.model_name or "mock")
    )

    if not request.dry_run and provider_key != "mock":
        cfg = get_deepseek_runtime_config() if provider_key == "deepseek" else get_kimi_runtime_config()
        if not (cfg.api_key or "").strip():
            raise ProviderNotConfiguredServiceError(provider_key, f"provider is not configured: {provider_key}")

    if request.overwrite_policy == OverwritePolicy.overwrite_with_review:
        warnings.append("overwrite_with_review: values will be overwritten (review record creation not yet implemented).")

    if request.create_evidence:
        warnings.append("create_evidence is not implemented in Step 10.3; no new evidence rows created.")

    run = await create_completion_run(session, request, resolved_model=resolved_model)
    items: list[LlmFieldCompletionItem] = []
    prompt_previews: list[dict[str, Any]] = []

    targets = await load_targets(session, request.target_type, request.target_ids)

    for tid in request.target_ids:
        if tid not in targets:
            item = _make_item(
                run.id,
                request.target_type.value,
                tid,
                field_name="_target_",
                old_value=None,
                status=ItemStatus.skipped_target_not_found,
                error_message="target not found",
            )
            session.add(item)
            items.append(item)

    bundle_context_cache: dict[uuid.UUID, dict[str, Any]] = {}
    consistency_cache: dict[uuid.UUID, dict[str, Any]] = {}
    circuit_ids: set[uuid.UUID] = set()
    for target in targets.values():
        cid = _resolve_circuit_id(target, request.target_type)
        if cid is not None:
            circuit_ids.add(cid)

    from app.services.field_completion_execution import (
        apply_deterministic_fields,
        build_deterministic_plan,
        execute_batched_llm_fields,
        execute_circuit_bundle_fields,
        execute_per_connection_fields,
    )
    from app.services.field_completion_prompt_engineering import (
        build_batch_field_prompt,
        build_compact_field_context,
        estimate_prompt_tokens,
    )

    deterministic_plan = build_deterministic_plan(targets, entry, request)
    template_plan = build_template_plan(targets, entry, request)
    estimated_model_calls = estimate_model_calls(
        template_plan,
        circuit_ids,
        target_type=request.target_type,
    )

    if request.dry_run:
        run.status = RunStatus.dry_run.value
        det_applied, canonical_cache, resolver_warn = await apply_deterministic_fields(
            session,
            run,
            request,
            entry,
            targets,
            items,
            warnings,
            make_item=_make_item,
            apply_field_update=apply_field_update,
            overwrite_policy=request.overwrite_policy,
            create_mirror_updates=request.create_mirror_updates,
        )
        llm_field_names: set[str] = {p["field_name"] for p in template_plan}
        for field_name in sorted(llm_field_names):
            records: list[dict[str, Any]] = []
            for tid, target in targets.items():
                fields = determine_fields_to_complete(
                    target,
                    entry,
                    field_scope=request.field_scope,
                    selected_fields=request.selected_fields,
                )
                if field_name not in fields or is_deterministic_field(entry, field_name):
                    continue
                canonical_resolution = canonical_cache.get(tid, {})
                compact = build_compact_field_context(
                    target,
                    field_name,
                    canonical_resolution=canonical_resolution,
                )
                compact["target_id"] = str(tid)
                records.append(compact)
            if not records:
                continue
            system_prompt, user_prompt, prompt_json, prompt_key = build_batch_field_prompt(
                entry,
                field_name,
                records,
                request,
                prompt_overrides=request.prompt_overrides,
            )
            prompt_previews.append({
                "field_name": field_name,
                "prompt_key": prompt_key,
                "batch_size": len(records),
                "compact_context": True,
                "uses_deepseek": True,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt[:4000],
                "prompt_json": prompt_json,
            })

        est_input = sum(
            estimate_prompt_tokens(p.get("user_prompt", ""))
            + estimate_prompt_tokens(p.get("system_prompt", ""))
            for p in prompt_previews
        )
        run.completed_at = datetime.now(timezone.utc)
        run.warnings_json = to_jsonable(warnings)
        run.errors_json = to_jsonable(errors)
        counts = summarize_completion_run(run, items)
        counts["model_call_count"] = 0
        counts["estimated_model_calls"] = estimated_model_calls
        counts["deterministic_applied_count"] = det_applied
        counts["llm_applied_count"] = 0
        counts["resolver_warning_count"] = resolver_warn
        counts["estimated_input_tokens"] = est_input
        counts["estimated_output_tokens"] = 0
        counts["pack_count"] = len([p for p in prompt_previews if p.get("batch_size")])
        counts["deterministic_fields_count"] = len(deterministic_plan)
        counts["llm_fields_count"] = len(template_plan)
        counts["rejected_count"] = 0
        counts["warning_count"] = len(warnings)
        run.summary_json = to_jsonable(counts)
        await session.commit()
        preview = to_jsonable({
            "template_plan": template_plan,
            "deterministic_plan": deterministic_plan,
            "deterministic_fields": [p["field_name"] for p in deterministic_plan],
            "llm_fields": sorted({p["field_name"] for p in template_plan}),
            "compact_context_enabled": True,
            "estimated_model_calls": estimated_model_calls,
            "estimated_input_tokens": est_input,
            "target_count": len(targets),
            "field_count": len(template_plan) + len(deterministic_plan),
            "allowed_fields": list(entry.enrichable_fields),
            "previews": prompt_previews,
            "warnings": warnings,
        })
        return _build_response(run, items, prompt_preview=preview, warnings=warnings, errors=errors)

    # Non-dry-run: execute synchronously (used by legacy direct POST /run, and
    # also from the background task via _execute_field_completion_core).
    items, warnings, errors = await _execute_field_completion_core(session, run, request)
    await session.refresh(run)
    return _build_response(run, items, prompt_preview=None, warnings=warnings, errors=errors)


async def list_field_completion_runs(
    session: AsyncSession,
    *,
    target_type: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LlmFieldCompletionRun], int]:
    limit = min(limit, 200)
    q = select(LlmFieldCompletionRun)
    count_q = select(func.count()).select_from(LlmFieldCompletionRun)
    if target_type:
        q = q.where(LlmFieldCompletionRun.target_type == target_type)
        count_q = count_q.where(LlmFieldCompletionRun.target_type == target_type)
    if status:
        q = q.where(LlmFieldCompletionRun.status == status)
        count_q = count_q.where(LlmFieldCompletionRun.status == status)
    if provider:
        q = q.where(LlmFieldCompletionRun.provider == provider)
        count_q = count_q.where(LlmFieldCompletionRun.provider == provider)
    q = q.order_by(LlmFieldCompletionRun.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    total = (await session.execute(count_q)).scalar_one()
    return list(rows), total


async def list_field_completion_items(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    field_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LlmFieldCompletionItem], int]:
    limit = min(limit, 200)
    q = select(LlmFieldCompletionItem)
    count_q = select(func.count()).select_from(LlmFieldCompletionItem)
    if run_id:
        q = q.where(LlmFieldCompletionItem.run_id == run_id)
        count_q = count_q.where(LlmFieldCompletionItem.run_id == run_id)
    if target_type:
        q = q.where(LlmFieldCompletionItem.target_type == target_type)
        count_q = count_q.where(LlmFieldCompletionItem.target_type == target_type)
    if target_id:
        q = q.where(LlmFieldCompletionItem.target_id == target_id)
        count_q = count_q.where(LlmFieldCompletionItem.target_id == target_id)
    if field_name:
        q = q.where(LlmFieldCompletionItem.field_name == field_name)
        count_q = count_q.where(LlmFieldCompletionItem.field_name == field_name)
    if status:
        q = q.where(LlmFieldCompletionItem.update_status == status)
        count_q = count_q.where(LlmFieldCompletionItem.update_status == status)
    q = q.order_by(LlmFieldCompletionItem.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    total = (await session.execute(count_q)).scalar_one()
    return list(rows), total


async def get_field_completion_run(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> FieldCompletionRunDetail | None:
    run = await session.get(LlmFieldCompletionRun, run_id)
    if run is None:
        return None
    await session.refresh(run)  # ensure all attrs loaded before model_validate
    items, _ = await list_field_completion_items(session, run_id=run_id, limit=200, offset=0)
    base = FieldCompletionRunRead.model_validate(run)
    return FieldCompletionRunDetail(
        **base.model_dump(),
        items=[FieldCompletionItemRead.model_validate(i) for i in items],
    )


async def get_related_field_completion_targets(
    session: AsyncSession,
    *,
    target_type: TargetType,
    target_ids: list[uuid.UUID],
    include: list[str],
) -> FieldCompletionRelatedTargetsResponse:
    """Read-only lookup of related field-completion targets (Mirror only, no writes)."""
    if target_type != TargetType.circuit:
        raise ValueError(
            f"related-targets only supports target_type=circuit, got {target_type.value}"
        )

    include_set = {part.strip() for part in include if part.strip()}
    groups: list[FieldCompletionRelatedGroup] = [
        FieldCompletionRelatedGroup(
            target_type=TargetType.circuit.value,
            target_ids=list(target_ids),
            count=len(target_ids),
        )
    ]
    warnings: list[str] = []

    if "circuit_step" in include_set:
        from app.models.mirror_macro_clinical import MirrorCircuitStep

        stmt = select(MirrorCircuitStep.id).where(MirrorCircuitStep.circuit_id.in_(target_ids))
        step_ids = list((await session.execute(stmt)).scalars().all())
        groups.append(
            FieldCompletionRelatedGroup(
                target_type=TargetType.circuit_step.value,
                target_ids=step_ids,
                count=len(step_ids),
            )
        )

    if "circuit_function" in include_set:
        cf_warnings: list[str] = []
        cf_ids: list[uuid.UUID] = []
        cf_entry = REGISTRY.get(TargetType.circuit_function)
        if cf_entry is None or not cf_entry.supported:
            reason = (
                (cf_entry.unsupported_reason if cf_entry else None)
                or "circuit_function field completion is not supported."
            )
            cf_warnings.append(reason)
            warnings.append(reason)
        else:
            from app.models.mirror_macro_clinical import MirrorCircuitFunction
            from app.services import mirror_macro_clinical_service

            try:
                await mirror_macro_clinical_service.list_mirror_circuit_functions(
                    session, limit=1, offset=0
                )
                stmt = select(MirrorCircuitFunction.id).where(
                    MirrorCircuitFunction.circuit_id.in_(target_ids)
                )
                cf_ids = list((await session.execute(stmt)).scalars().all())
            except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError:
                msg = (
                    "mirror_circuit_functions table is not initialized. "
                    "Please run backend/migrations/033_mirror_circuit_functions.sql."
                )
                cf_warnings.append(MirrorCircuitFunctionsNotInitializedForFieldCompletionError.code)
                cf_warnings.append(msg)
                warnings.append(msg)
            if not cf_ids and not cf_warnings:
                msg = (
                    "No mirror_circuit_functions found for selected circuits. "
                    "Run circuit_to_functions extraction first."
                )
                cf_warnings.append(msg)
                warnings.append(msg)
        groups.append(
            FieldCompletionRelatedGroup(
                target_type=TargetType.circuit_function.value,
                target_ids=cf_ids,
                count=len(cf_ids),
                warnings=cf_warnings,
            )
        )

    return FieldCompletionRelatedTargetsResponse(
        source_target_type=target_type.value,
        source_target_ids=list(target_ids),
        groups=groups,
        warnings=warnings,
    )


async def _check_cancelled(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Return True if the run has been cancelled. Lightweight status-only query."""
    stmt = select(LlmFieldCompletionRun.status).where(LlmFieldCompletionRun.id == run_id)
    result = await session.execute(stmt)
    status_val = result.scalar_one_or_none()
    return status_val == RunStatus.cancelled.value


async def cancel_field_completion_run(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> LlmFieldCompletionRun | None:
    """Set a pending or running field completion run to cancelled."""
    run = await session.get(LlmFieldCompletionRun, run_id)
    if run is None:
        return None
    if run.status not in (RunStatus.pending.value, RunStatus.running.value):
        return run
    run.status = RunStatus.cancelled.value
    run.completed_at = datetime.now(timezone.utc)
    run.warnings_json = to_jsonable(list(run.warnings_json or []) + ["Cancelled by user"])
    await session.commit()
    await session.refresh(run)  # re-load to avoid MissingGreenlet on model_validate
    return run


async def start_field_completion_async(
    session: AsyncSession,
    request: UniversalFieldCompletionRequest,
) -> FieldCompletionStartResponse:
    """Validate, create a pending run, and return a start response.

    The actual execution happens in ``execute_field_completion_background``.
    """
    from app.schemas.llm_field_completion import FieldCompletionStartResponse

    try:
        entry = get_registry_entry(request.target_type)
    except UnsupportedTargetTypeError:
        raise
    except TargetTypeNotImplementedError:
        raise

    provider_key = request.provider.lower()
    if provider_key not in ("deepseek", "kimi", "mock"):
        raise UnknownProviderError(request.provider)

    resolved_model = (
        _resolve_model(provider_key, request.model_name)
        if provider_key != "mock"
        else (request.model_name or "mock")
    )

    if provider_key != "mock":
        cfg = get_deepseek_runtime_config() if provider_key == "deepseek" else get_kimi_runtime_config()
        if not (cfg.api_key or "").strip():
            raise ProviderNotConfiguredServiceError(provider_key, f"provider is not configured: {provider_key}")

    warnings: list[str] = []
    if request.overwrite_policy == OverwritePolicy.overwrite_with_review:
        warnings.append("overwrite_with_review: values will be overwritten (review record creation not yet implemented).")
    if request.create_evidence:
        warnings.append("create_evidence is not implemented; no new evidence rows created.")

    run = LlmFieldCompletionRun(
        id=uuid.uuid4(),
        provider=provider_key,
        model_name=resolved_model,
        target_type=request.target_type.value,
        target_count=len(request.target_ids),
        field_scope=request.field_scope.value,
        selected_fields_json=list(request.selected_fields),
        overwrite_policy=request.overwrite_policy.value,
        dry_run=False,
        create_mirror_updates=request.create_mirror_updates,
        create_evidence=request.create_evidence,
        status=RunStatus.pending.value,
        request_json=to_jsonable(request.model_dump(mode="json")),
        warnings_json=to_jsonable(warnings),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    return FieldCompletionStartResponse(
        run_id=run.id,
        status=RunStatus.pending,
        provider=run.provider,
        model_name=run.model_name,
        target_type=TargetType(run.target_type),
        target_count=run.target_count,
        dry_run=False,
        warnings=warnings,
    )


async def _mark_run_failed(run_id: uuid.UUID, error: str) -> None:
    """Mark a run as failed in a recovery session."""
    from app.database import AsyncSessionLocal

    try:
        if AsyncSessionLocal is None:
            return
        async with AsyncSessionLocal() as s:
            r = await s.get(LlmFieldCompletionRun, run_id)
            if r is not None and r.status not in (RunStatus.succeeded.value, RunStatus.failed.value):
                r.status = RunStatus.failed.value
                r.completed_at = datetime.now(timezone.utc)
                errors = list(r.errors_json or [])
                errors.append(error)
                r.errors_json = to_jsonable(errors)
                await s.commit()
    except Exception:
        logger.exception("[field-completion][background] mark_failed failed run_id=%s", run_id)


async def execute_field_completion_background(
    run_id: uuid.UUID,
    request_payload: dict[str, Any],
) -> None:
    """Background worker — uses a fresh DB session for async field completion."""
    from app.database import AsyncSessionLocal

    print(f"[field-completion] BACKGROUND START run={run_id}", flush=True)
    if AsyncSessionLocal is None:
        logger.error("[field-completion][background] AsyncSessionLocal unavailable")
        return

    try:
        request = UniversalFieldCompletionRequest.model_validate(request_payload)
    except Exception as exc:
        logger.exception("[field-completion][background] invalid payload run=%s", run_id)
        await _mark_run_failed(run_id, f"Invalid payload: {exc}")
        return

    # Retry up to 3 times to find the run (DB commit may not be visible yet)
    run_found = False
    for attempt in range(3):
        async with AsyncSessionLocal() as session:
            run = await session.get(LlmFieldCompletionRun, run_id)
            if run is not None:
                run_found = True
                break
        if not run_found and attempt < 2:
            await asyncio.sleep(0.5)
    if not run_found:
        logger.error("[field-completion][background] run not found after retries: %s", run_id)
        await _mark_run_failed(run_id, "Run never started: not found in DB after retries")
        return

    async with AsyncSessionLocal() as session:
        try:
            run = await session.get(LlmFieldCompletionRun, run_id)
            if run is None:
                return

            if await _check_cancelled(session, run_id):
                return

            run.status = RunStatus.running.value
            run.started_at = datetime.now(timezone.utc)
            await session.commit()

            # Wrap execution with timeout proportional to target count
            timeout = max(300, run.target_count * 30)  # ~30s per circuit (2-3 LLM calls each)
            await asyncio.wait_for(
                _execute_field_completion_core(session, run, request),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error("[field-completion][background] timeout run_id=%s", run_id)
            await _mark_run_failed(run_id, "Execution timed out after 5 minutes")
        except Exception as exc:
            logger.exception("[field-completion][background] unhandled failure run_id=%s", run_id)
            await _mark_run_failed(run_id, f"Background failure: {exc}")


async def _execute_field_completion_core(
    session: AsyncSession,
    run: LlmFieldCompletionRun,
    request: UniversalFieldCompletionRequest,
) -> tuple[list[LlmFieldCompletionItem], list[str], list[str]]:
    """Core execution shared by sync (dry_run) and async (background) paths.

    Returns (items, warnings, errors) for the caller to build a response.
    """
    warnings: list[str] = list(run.warnings_json or [])
    errors: list[str] = list(run.errors_json or [])

    try:
        entry = get_registry_entry(request.target_type)
    except UnsupportedTargetTypeError:
        raise
    except TargetTypeNotImplementedError:
        raise

    provider_key = request.provider.lower()
    resolved_model = _resolve_model(provider_key, request.model_name) if provider_key != "mock" else (request.model_name or "mock")

    if request.overwrite_policy == OverwritePolicy.overwrite_with_review:
        warnings.append("overwrite_with_review: values will be overwritten (review record creation not yet implemented).")

    if request.create_evidence:
        warnings.append("create_evidence is not implemented in Step 10.3; no new evidence rows created.")

    items: list[LlmFieldCompletionItem] = []

    targets = await load_targets(session, request.target_type, request.target_ids)

    for tid in request.target_ids:
        if tid not in targets:
            item = _make_item(
                run.id,
                request.target_type.value,
                tid,
                field_name="_target_",
                old_value=None,
                status=ItemStatus.skipped_target_not_found,
                error_message="target not found",
            )
            session.add(item)
            items.append(item)

    from app.services.field_completion_execution import (
        apply_deterministic_fields,
        build_deterministic_plan,
        execute_batched_llm_fields,
        execute_circuit_bundle_fields,
        execute_per_connection_fields,
    )
    from app.services.field_completion_prompt_engineering import (
        build_batch_field_prompt,
        build_compact_field_context,
        estimate_prompt_tokens,
    )

    deterministic_plan = build_deterministic_plan(targets, entry, request)
    template_plan = build_template_plan(targets, entry, request)
    estimated_model_calls = estimate_model_calls(
        template_plan,
        set(),
        target_type=request.target_type,
    )

    # ── Cancellation check ────────────────────────────────────────────────
    if await _check_cancelled(session, run.id):
        run.status = RunStatus.cancelled.value
        run.completed_at = datetime.now(timezone.utc)
        run.warnings_json = to_jsonable(warnings)
        run.errors_json = to_jsonable(errors)
        await session.commit()
        return items, warnings, errors

    det_applied, canonical_cache, resolver_warn = await apply_deterministic_fields(
        session,
        run,
        request,
        entry,
        targets,
        items,
        warnings,
        make_item=_make_item,
        apply_field_update=apply_field_update,
        overwrite_policy=request.overwrite_policy,
        create_mirror_updates=request.create_mirror_updates,
        resolved_model=resolved_model,
    )

    # ── Cancellation check ────────────────────────────────────────────────
    if await _check_cancelled(session, run.id):
        run.status = RunStatus.cancelled.value
        run.completed_at = datetime.now(timezone.utc)
        counts = summarize_completion_run(run, items)
        counts["deterministic_applied_count"] = det_applied
        counts["resolver_warning_count"] = resolver_warn
        run.summary_json = to_jsonable(counts)
        run.warnings_json = to_jsonable(warnings)
        run.errors_json = to_jsonable(errors)
        await session.commit()
        return items, warnings, errors

    estimated_input_tokens = 0
    pack_count = 0
    rejected_count = 0

    if request.target_type == TargetType.circuit:
        if template_plan:
            model_call_count, llm_applied = await execute_circuit_bundle_fields(
                session, run, request, targets, items, warnings, errors,
                provider_key=provider_key, resolved_model=resolved_model,
                make_item=_make_item, apply_field_update=apply_field_update,
                call_provider=call_provider, check_cancelled=_check_cancelled,
            )
        else:
            model_call_count, llm_applied = 0, 0
    elif request.target_type == TargetType.projection:
        model_call_count, llm_applied = await execute_per_connection_fields(
            session, run, request, entry, targets,
            items, warnings, errors,
            provider_key=provider_key, resolved_model=resolved_model,
            make_item=_make_item, apply_field_update=apply_field_update,
            call_provider=call_provider, check_cancelled=_check_cancelled,
        )
    else:
        model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied = (
            await execute_batched_llm_fields(
                session, run, request, entry, targets, items, warnings, errors,
                provider_key=provider_key, resolved_model=resolved_model,
                canonical_cache=canonical_cache or {},
                make_item=_make_item, apply_field_update=apply_field_update,
                call_provider=call_provider,
                parse_field_completion_provider_response=parse_field_completion_provider_response,
                validate_field_updates=validate_field_updates,
                validate_field_value_quality=validate_field_value_quality,
                format_reasoning_with_consistency=format_reasoning_with_consistency,
                check_cancelled=_check_cancelled,
            )
        )

    # ── Post-LLM cancellation check ─────────────────────────────────────
    if await _check_cancelled(session, run.id):
        run.status = RunStatus.cancelled.value
        run.completed_at = datetime.now(timezone.utc)
        run.warnings_json = to_jsonable(list(warnings) + ["Cancelled by user during LLM execution"])
        counts = summarize_completion_run(run, items)
        counts["model_call_count"] = model_call_count
        counts["rejected_count"] = 0
        counts["estimated_input_tokens"] = 0
        counts["pack_count"] = run.target_count
        counts["llm_applied"] = llm_applied
        run.summary_json = to_jsonable(counts)
        run.errors_json = to_jsonable(errors)
        await session.commit()
        return items, warnings, errors

    warning_count = len(warnings)
    counts = summarize_completion_run(run, items)
    counts["model_call_count"] = model_call_count
    counts["estimated_model_calls"] = estimated_model_calls
    counts["deterministic_applied_count"] = det_applied
    counts["llm_applied_count"] = llm_applied
    counts["resolver_warning_count"] = resolver_warn
    counts["estimated_input_tokens"] = estimated_input_tokens
    counts["estimated_output_tokens"] = 0
    counts["pack_count"] = pack_count if pack_count > 0 else run.target_count
    counts["deterministic_fields_count"] = len(deterministic_plan)
    counts["llm_fields_count"] = len(template_plan)
    counts["rejected_count"] = rejected_count
    counts["warning_count"] = warning_count
    run.summary_json = to_jsonable(counts)

    updated = counts.get("updated_count", 0)
    failed = counts.get("failed_count", 0)
    skipped = counts.get("skipped_count", 0)
    if updated > 0 and failed == 0 and skipped == 0 and not errors:
        run.status = RunStatus.succeeded.value
    elif updated > 0 and (failed > 0 or skipped > 0 or errors):
        run.status = RunStatus.partially_succeeded.value
    elif updated == 0 and failed > 0:
        run.status = RunStatus.failed.value
    elif errors and updated == 0:
        run.status = RunStatus.failed.value
    else:
        run.status = RunStatus.succeeded.value

    run.completed_at = datetime.now(timezone.utc)
    run.warnings_json = to_jsonable(warnings)
    run.errors_json = to_jsonable(errors)
    await session.commit()
    return items, warnings, errors
