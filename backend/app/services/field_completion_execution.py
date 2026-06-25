"""Deterministic + batched LLM field completion execution (Step 10.5.8)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_field_completion import LlmFieldCompletionItem, LlmFieldCompletionRun
from app.schemas.llm_field_completion import (
    ItemStatus,
    OverwritePolicy,
    TargetType,
    UniversalFieldCompletionRequest,
)
from app.services.canonical_region_resolver import (
    resolve_circuit_canonical_regions,
    resolve_source_db_default,
    resolve_status_default,
)
from app.services.field_completion_prompt_engineering import (
    build_batch_field_prompt,
    build_compact_field_context,
    estimate_prompt_tokens,
    pack_target_batches,
    select_field_completion_prompt_key,
)
from app.services.field_completion_registry import (
    get_field_value,
    is_deterministic_field,
    is_empty_value,
    is_overlay_field,
    split_deterministic_and_llm_fields,
    write_to_overlay,
)
from app.utils.json_safety import to_jsonable

logger = logging.getLogger(__name__)


def build_deterministic_plan(
    targets: dict[uuid.UUID, Any],
    entry,
    request: UniversalFieldCompletionRequest,
) -> list[dict[str, Any]]:
    from app.services.llm_field_completion_service import determine_fields_to_complete

    plan: list[dict[str, Any]] = []
    for tid, target in targets.items():
        fields = determine_fields_to_complete(
            target,
            entry,
            field_scope=request.field_scope,
            selected_fields=request.selected_fields,
        )
        for field_name in fields:
            if not is_deterministic_field(entry, field_name):
                continue
            resolver = entry.deterministic_fields.get(field_name, "deterministic")
            plan.append({
                "target_type": request.target_type.value,
                "target_id": str(tid),
                "field_name": field_name,
                "resolver": resolver,
                "uses_deepseek": False,
            })
    return plan


async def apply_deterministic_fields(
    session: AsyncSession,
    run: LlmFieldCompletionRun,
    request: UniversalFieldCompletionRequest,
    entry,
    targets: dict[uuid.UUID, Any],
    items: list[LlmFieldCompletionItem],
    warnings: list[str],
    *,
    make_item,
    apply_field_update,
    overwrite_policy,
    create_mirror_updates,
) -> tuple[int, dict[uuid.UUID, dict[str, Any]], int]:
    """Returns (applied_count, canonical_resolution_by_circuit_id, resolver_warning_count)."""
    from app.services.llm_field_completion_service import determine_fields_to_complete

    applied = 0
    resolver_warnings = 0
    canonical_cache: dict[uuid.UUID, dict[str, Any]] = {}

    for tid, target in targets.items():
        fields = determine_fields_to_complete(
            target,
            entry,
            field_scope=request.field_scope,
            selected_fields=request.selected_fields,
        )
        det_fields, _ = split_deterministic_and_llm_fields(entry, fields)
        if not det_fields:
            continue

        resolution = None
        if request.target_type == TargetType.circuit:
            circuit_id = tid
            if circuit_id not in canonical_cache:
                res = await resolve_circuit_canonical_regions(session, target)
                canonical_cache[circuit_id] = to_jsonable({
                    "start_region_id": res.start_region_id,
                    "end_region_id": res.end_region_id,
                    "start_region_label": res.start_region_label,
                    "end_region_label": res.end_region_label,
                    "method": res.method,
                    "confidence": res.confidence,
                    "warnings": res.warnings,
                })
                warnings.extend(res.warnings)
                resolver_warnings += len(res.warnings)
            resolution = canonical_cache[circuit_id]

        for field_name in det_fields:
            resolver_key = entry.deterministic_fields.get(field_name, "")
            old_value = get_field_value(target, field_name)
            value: Any = None
            confidence = 0.0
            method = resolver_key
            evidence_text = None
            reasoning = f"resolver={resolver_key}"
            uncertainty = None
            meta_extra: dict[str, Any] = {"resolver": resolver_key}

            if field_name == "canonical_start_region_id" and resolution:
                value = resolution.get("start_region_id")
                confidence = float(resolution.get("confidence") or 0.0)
                method = str(resolution.get("method") or method)
                evidence_text = f"region_candidate_ids={resolution.get('start_region_label') or value}"
                meta_extra["label"] = resolution.get("start_region_label")
                reasoning = f"resolver=canonical_region_resolver | method={method}"
                if resolution.get("warnings"):
                    uncertainty = "; ".join(str(w) for w in resolution.get("warnings", [])[:2])
            elif field_name == "canonical_end_region_id" and resolution:
                value = resolution.get("end_region_id")
                confidence = float(resolution.get("confidence") or 0.0)
                method = str(resolution.get("method") or method)
                evidence_text = f"region_candidate_ids={resolution.get('end_region_label') or value}"
                meta_extra["label"] = resolution.get("end_region_label")
                reasoning = f"resolver=canonical_region_resolver | method={method}"
                if resolution.get("warnings"):
                    uncertainty = "; ".join(str(w) for w in resolution.get("warnings", [])[:2])
            elif field_name == "source_db":
                value, method, confidence, w = resolve_source_db_default(target)
                if method == "skipped_existing":
                    continue
                warnings.extend(w)
                resolver_warnings += len(w)
                reasoning = f"resolver=source_db_resolver | method={method}"
            elif field_name == "status":
                value, method, confidence, w = resolve_status_default(target)
                if method == "skipped_existing":
                    continue
                warnings.extend(w)
                resolver_warnings += len(w)
                reasoning = f"resolver=status_default_resolver | method={method}"
            else:
                warnings.append(f"unknown deterministic resolver for {field_name}")
                item = make_item(
                    run.id,
                    request.target_type.value,
                    tid,
                    field_name,
                    old_value=old_value,
                    status=ItemStatus.skipped_invalid_field,
                    error_message=f"unknown deterministic resolver: {resolver_key}",
                    reasoning_summary=reasoning,
                )
                session.add(item)
                items.append(item)
                continue

            if value is None or is_empty_value(value):
                item = make_item(
                    run.id,
                    request.target_type.value,
                    tid,
                    field_name,
                    old_value=old_value,
                    status=ItemStatus.skipped_invalid_field,
                    error_message="deterministic resolver could not resolve value",
                    reasoning_summary=reasoning,
                    uncertainty_reason=uncertainty,
                )
                session.add(item)
                items.append(item)
                continue

            if request.dry_run:
                item = make_item(
                    run.id,
                    request.target_type.value,
                    tid,
                    field_name,
                    old_value=old_value,
                    status=ItemStatus.prompt_preview,
                    suggested=value,
                    confidence=confidence,
                    evidence_text=evidence_text,
                    reasoning_summary=reasoning,
                    uncertainty_reason=uncertainty,
                )
                session.add(item)
                items.append(item)
                continue

            if not create_mirror_updates:
                item = make_item(
                    run.id,
                    request.target_type.value,
                    tid,
                    field_name,
                    old_value=old_value,
                    status=ItemStatus.suggested,
                    suggested=value,
                    confidence=confidence,
                    evidence_text=evidence_text,
                    reasoning_summary=reasoning,
                    uncertainty_reason=uncertainty,
                )
                session.add(item)
                items.append(item)
                continue

            overlay_source = (
                "deterministic_canonical_region_resolver"
                if "canonical" in field_name
                else f"deterministic_{resolver_key}"
            )
            if entry is not None and is_overlay_field(entry, field_name):
                existing = get_field_value(target, field_name)
                if not is_empty_value(existing) and overwrite_policy == OverwritePolicy.fill_missing_only:
                    item = make_item(
                        run.id,
                        request.target_type.value,
                        tid,
                        field_name,
                        old_value=old_value,
                        status=ItemStatus.skipped_existing_value,
                        suggested=value,
                        reasoning_summary=reasoning,
                    )
                    session.add(item)
                    items.append(item)
                    continue
                if write_to_overlay(
                    target,
                    field_name,
                    value,
                    run_id=run.id,
                    confidence=confidence,
                    source=overlay_source,
                    meta_extra=meta_extra,
                ):
                    status = ItemStatus.applied_overlay
                else:
                    status = ItemStatus.suggested
            else:
                status = apply_field_update(
                    target,
                    field_name,
                    value,
                    overwrite_policy=overwrite_policy,
                    create_mirror_updates=create_mirror_updates,
                    entry=entry,
                    run_id=run.id,
                    confidence=confidence,
                    overlay_source=overlay_source,
                    overlay_meta_extra=meta_extra,
                )

            if status in (ItemStatus.applied, ItemStatus.applied_direct, ItemStatus.applied_overlay):
                applied += 1
            item = make_item(
                run.id,
                request.target_type.value,
                tid,
                field_name,
                old_value=old_value,
                status=status,
                suggested=value,
                applied=value if status in (
                    ItemStatus.applied,
                    ItemStatus.applied_direct,
                    ItemStatus.applied_overlay,
                ) else None,
                confidence=confidence,
                evidence_text=evidence_text,
                reasoning_summary=reasoning,
                uncertainty_reason=uncertainty,
            )
            session.add(item)
            items.append(item)

    return applied, canonical_cache, resolver_warnings


async def execute_batched_llm_fields(
    session: AsyncSession,
    run: LlmFieldCompletionRun,
    request: UniversalFieldCompletionRequest,
    entry,
    targets: dict[uuid.UUID, Any],
    items: list[LlmFieldCompletionItem],
    warnings: list[str],
    errors: list[str],
    *,
    provider_key: str,
    resolved_model: str,
    canonical_cache: dict[uuid.UUID, dict[str, Any]],
    make_item,
    apply_field_update,
    call_provider,
    parse_field_completion_provider_response,
    validate_field_updates,
    validate_field_value_quality,
    format_reasoning_with_consistency,
) -> tuple[int, int, int, int, int]:
    """Returns model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied."""
    from app.services.llm_field_completion_service import determine_fields_to_complete

    model_call_count = 0
    rejected_count = 0
    llm_applied = 0
    estimated_input_tokens = 0
    pack_count = 0

    llm_field_names: set[str] = set()
    for target in targets.values():
        fields = determine_fields_to_complete(
            target,
            entry,
            field_scope=request.field_scope,
            selected_fields=request.selected_fields,
        )
        _, llm_fields = split_deterministic_and_llm_fields(entry, fields)
        llm_field_names.update(llm_fields)

    for field_name in sorted(llm_field_names):
        records: list[dict[str, Any]] = []
        target_map: dict[str, tuple[uuid.UUID, Any]] = {}
        for tid, target in targets.items():
            fields = determine_fields_to_complete(
                target,
                entry,
                field_scope=request.field_scope,
                selected_fields=request.selected_fields,
            )
            if field_name not in fields or is_deterministic_field(entry, field_name):
                continue
            circuit_id = tid if request.target_type == TargetType.circuit else None
            canonical_resolution = canonical_cache.get(circuit_id or tid, {})
            compact = build_compact_field_context(
                target,
                field_name,
                canonical_resolution=canonical_resolution,
            )
            compact["target_id"] = str(tid)
            records.append(compact)
            target_map[str(tid)] = (tid, target)

        if not records:
            continue

        system_prompt, user_prompt, prompt_json, prompt_key = build_batch_field_prompt(
            entry,
            field_name,
            records,
            request,
            prompt_overrides=request.prompt_overrides,
        )
        packs = pack_target_batches(records, system_prompt=system_prompt, template_body=user_prompt)
        pack_count += len(packs)

        for pack in packs:
            _, batch_user_prompt, _, _ = build_batch_field_prompt(
                entry,
                field_name,
                pack,
                request,
                prompt_overrides=request.prompt_overrides,
            )
            estimated_input_tokens += estimate_prompt_tokens(system_prompt) + estimate_prompt_tokens(batch_user_prompt)

            try:
                if provider_key == "mock":
                    raise RuntimeError("mock provider must be patched in tests")
                from app.services.field_completion_prompt_engineering import resolve_prompt_template

                tpl = resolve_prompt_template(prompt_key, request.prompt_overrides)
                response = await call_provider(
                    provider_key,
                    model=resolved_model,
                    system_prompt=system_prompt,
                    user_prompt=batch_user_prompt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    response_schema=tpl.output_schema_json or None,
                )
                model_call_count += 1
                if response.parsed_json is None and response.raw_text:
                    parsed = parse_field_completion_provider_response(response.raw_text)
                elif response.parsed_json is not None:
                    parsed = parse_field_completion_provider_response(response.parsed_json)
                else:
                    raise ValueError("empty provider response")
            except Exception as exc:
                logger.exception("batch field completion failed field=%s", field_name)
                for rec in pack:
                    tid_str = rec.get("target_id")
                    if not tid_str or tid_str not in target_map:
                        continue
                    tid, target = target_map[tid_str]
                    errors.append(f"target {tid} field {field_name}: {exc}")
                    item = make_item(
                        run.id,
                        request.target_type.value,
                        tid,
                        field_name,
                        old_value=get_field_value(target, field_name),
                        status=ItemStatus.failed,
                        error_message=str(exc),
                        reasoning_summary=f"prompt_key={prompt_key}",
                    )
                    session.add(item)
                    items.append(item)
                continue

            validated = validate_field_updates(entry, parsed.get("field_updates", []))
            handled_targets: set[str] = set()
            for upd, err in validated:
                upd_field = upd.get("field_name", field_name)
                tid_raw = upd.get("target_id")
                if tid_raw is None and len(pack) == 1:
                    tid_raw = pack[0].get("target_id")
                tid_key = str(tid_raw) if tid_raw is not None else ""
                if tid_key not in target_map:
                    continue
                tid, target = target_map[tid_key]
                handled_targets.add(tid_key)
                if err or upd_field != field_name:
                    err = err or f"expected field_name={field_name}, got {upd_field}"
                    rejected_count += 1
                    item = make_item(
                        run.id,
                        request.target_type.value,
                        tid,
                        field_name,
                        old_value=get_field_value(target, field_name),
                        status=ItemStatus.skipped_invalid_field,
                        suggested=upd.get("value"),
                        error_message=err,
                        reasoning_summary=format_reasoning_with_consistency(upd),
                    )
                    session.add(item)
                    items.append(item)
                    continue

                value = upd.get("value")
                accept, reject_reason, quality_warnings = validate_field_value_quality(field_name, value)
                if quality_warnings:
                    warnings.extend(quality_warnings)
                if not accept:
                    rejected_count += 1
                    item = make_item(
                        run.id,
                        request.target_type.value,
                        tid,
                        field_name,
                        old_value=get_field_value(target, field_name),
                        status=ItemStatus.skipped_invalid_field,
                        suggested=value,
                        error_message=reject_reason,
                        reasoning_summary=format_reasoning_with_consistency(upd),
                    )
                    session.add(item)
                    items.append(item)
                    continue

                confidence = upd.get("confidence")
                try:
                    if confidence is not None:
                        confidence = max(0.0, min(1.0, float(confidence)))
                except (TypeError, ValueError):
                    confidence = None

                old_value = get_field_value(target, field_name)
                if value is None or is_empty_value(value):
                    item = make_item(
                        run.id,
                        request.target_type.value,
                        tid,
                        field_name,
                        old_value=old_value,
                        status=ItemStatus.suggested,
                        suggested=value,
                        confidence=confidence,
                        evidence_text=upd.get("evidence_text"),
                        reasoning_summary=format_reasoning_with_consistency(upd),
                        uncertainty_reason=upd.get("uncertainty_reason"),
                    )
                    session.add(item)
                    items.append(item)
                    continue

                status = apply_field_update(
                    target,
                    field_name,
                    value,
                    overwrite_policy=request.overwrite_policy,
                    create_mirror_updates=request.create_mirror_updates,
                    entry=entry,
                    run_id=run.id,
                    confidence=confidence,
                )
                if status in (ItemStatus.applied, ItemStatus.applied_direct, ItemStatus.applied_overlay):
                    llm_applied += 1
                reasoning = format_reasoning_with_consistency(upd)
                if reasoning:
                    reasoning = f"prompt_key={prompt_key} | {reasoning}"
                else:
                    reasoning = f"prompt_key={prompt_key}"
                item = make_item(
                    run.id,
                    request.target_type.value,
                    tid,
                    field_name,
                    old_value=old_value,
                    status=status,
                    suggested=value,
                    applied=value if status in (
                        ItemStatus.applied,
                        ItemStatus.applied_direct,
                        ItemStatus.applied_overlay,
                    ) else None,
                    confidence=confidence,
                    evidence_text=upd.get("evidence_text"),
                    reasoning_summary=reasoning,
                    uncertainty_reason=upd.get("uncertainty_reason"),
                )
                session.add(item)
                items.append(item)

            for rec in pack:
                tid_str = str(rec.get("target_id"))
                if tid_str in handled_targets:
                    continue
                tid, target = target_map[tid_str]
                rejected_count += 1
                item = make_item(
                    run.id,
                    request.target_type.value,
                    tid,
                    field_name,
                    old_value=get_field_value(target, field_name),
                    status=ItemStatus.skipped_invalid_field,
                    error_message=f"no field_update returned for target {tid_str}",
                    reasoning_summary=f"prompt_key={prompt_key}",
                )
                session.add(item)
                items.append(item)

    return model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied
