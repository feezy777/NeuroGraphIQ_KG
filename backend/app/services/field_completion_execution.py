"""Deterministic + batched LLM field completion execution (Step 10.5.8)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

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
    resolved_model: str | None = None,
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
                    # fill_missing_only: skip non-empty fields
                    # overwrite_with_review: overwrite existing values
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
                    # Update mirror_status for overlay writes too
                    if hasattr(target, "mirror_status") and resolved_model:
                        from app.services.llm_field_completion_service import (
                            _resolve_model_status,
                            _should_update_mirror_status,
                        )
                        tier_status = _resolve_model_status(resolved_model)[0]
                        if _should_update_mirror_status(target, resolved_model):
                            target.mirror_status = tier_status
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
                    resolved_model=resolved_model,
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


_PER_CONN_SYSTEM_PROMPT = (
    "You are a neuroscientist annotating brain connectivity data. "
    "For each connection, infer all metadata fields based on source/target region names "
    "and neuroanatomical knowledge. Output ONLY valid JSON. "
    "Never use UUIDs or hash values in any field. "
    "Use descriptive English names for name_en, evidence-based descriptions."
)

_PER_CONN_USER_TEMPLATE = (
    "Connection: {source_name} → {target_name}\n"
    "Atlas: {atlas}\nGranularity: {granularity}\n\n"
    "Current metadata:\n{current_metadata}\n\n"
    "Based on neuroanatomical knowledge about these regions, "
    "infer the most accurate values for ALL fields. "
    "Improve existing values where possible; fill in missing ones.\n\n"
    "Output ONLY this JSON:\n"
    '{{"projection_type":"structural_connection|functional_connectivity|effective_connectivity|projection|association|coactivation|uncertain_connection|unknown",'
    '"directionality":"directed|undirected|bidirectional|unknown",'
    '"modality":"structural_connection|functional_connection|diffusion_tensor|other",'
    '"strength_score":0.0,"confidence_score":0.0,'
    '"evidence_text":"...","canonical_id":"region1→region2","name_en":"...","name_cn":"...",'
    '"description":"...","source_db":"neuroanatomical_literature|inferred|computational_model|unknown",'
    '"status":"validated|proposed|uncertain"}}'
)


_CIRCUIT_BUNDLE_SYSTEM = (
    "You are a neuroscientist annotating brain circuit data.\n"
    "Based on the circuit description and step information below, infer and fill in ALL missing values.\n"
    "circuit_strength (0.0-1.0) rates the circuit's IMPACT/SIGNIFICANCE in brain function:\n"
    "  0.0-0.3 = minor/auxiliary, 0.4-0.6 = moderate, 0.7-0.9 = major pathway, 1.0 = critical\n"
    "Judge this based on clinical relevance, functional importance, and network centrality.\n"
    "Output ONLY valid JSON matching the exact structure below. No markdown, no explanation.\n\n"
    'JSON STRUCTURE:\n'
    '{"circuit":{"name_en":"English circuit name","name_cn":"Chinese circuit name",'
    '"circuit_class":"functional classification","description":"circuit function description",'
    '"start_region_name":"entry brain region name","end_region_name":"exit brain region name",'
    '"circuit_strength":0.7,"source_db":"inferred","status":"proposed"},'
    '"steps":[{"step_name_en":"Step English name","step_name_cn":"Step Chinese name",'
    '"step_no":1,"role_in_circuit":"source|relay|output","description":"step description",'
    '"region_name":"brain region this step operates on",'
    '"source_db":"inferred","status":"proposed",'
    '"connection":{"projection_id":"uuid from candidates or null",'
    '"match_confidence":0.5,"is_suspected":false,"evidence":"matching rationale"},'
    '"functions":[{"function_term_en":"function name","function_term_cn":"Chinese function name",'
    '"function_domain":"cognitive|memory|motor|sensory|emotional|autonomic|other",'
    '"function_role":"execution|modulation|inhibition|gating|integration|other",'
    '"effect_type":"excitatory|inhibitory|modulatory|unknown",'
    '"confidence_score":0.5,"evidence_level":"moderate|weak|strong",'
    '"description":"function description","source_db":"inferred","status":"proposed"}]}]}\n\n'
    "IMPORTANT: Always include ALL provided steps in the steps array. Never return an empty steps array."
)

_CIRCUIT_BUNDLE_USER = (
    "Complete the fields for this brain circuit:\n\n"
    "{name} (type: {type})\n"
    "Description: {desc}\n"
    "Function: {func}\n\n"
    "Step context:\n{steps_context}\n\n"
    "Functions:\n{functions_context}\n\n"
    "MUST include: name_en, name_cn, circuit_class, circuit_strength,"
    "start_region_name, end_region_name, description, source_db, status"
)

# ── Step-only prompt (Call 2 — separate LLM call per circuit with steps) ─
_CIRCUIT_STEPS_SYSTEM = (
    "You are a neuroscientist. For each circuit step, infer its name, role,\n"
    "description, and brain region name from the circuit description.\n\n"
    'Output ONLY a JSON array. No markdown, no explanation.\n'
    '[{"step_no":1,"step_name_en":"Amygdala to Accumbens","step_name_cn":"杏仁核至伏隔核",'
    '"role_in_circuit":"source","description":"Projects from amygdala to nucleus accumbens",'
    '"region_name":"left amygdala","source_db":"inferred","status":"proposed","functions":[]}]'
)

_CIRCUIT_STEPS_USER = (
    "Circuit: {name} (type: {type})\nDescription: {desc}\n\n"
    "Steps ({step_count} total):\n{steps_context}\n\n"
    "Output all {step_count} steps as a JSON array."
)


async def _build_step_connection_candidates(
    session: AsyncSession,
    steps: list,
) -> dict:
    """For each step, find up to 20 candidate connections from mirror_region_connections."""
    from app.models.mirror_kg import MirrorRegionConnection
    from sqlalchemy import select as sa_select

    candidates: dict = {}
    for step in steps:
        rid = getattr(step, 'region_candidate_id', None)
        if not rid:
            candidates[step.id] = []
            continue
        stmt = (
            sa_select(MirrorRegionConnection)
            .where(
                (MirrorRegionConnection.source_region_candidate_id == rid)
                | (MirrorRegionConnection.target_region_candidate_id == rid)
            )
            .limit(20)
        )
        result = await session.execute(stmt)
        conns = result.scalars().all()
        candidates[step.id] = [
            {
                "id": str(c.id),
                "source_name": getattr(c, 'source_region_name_en', '') or '?',
                "target_name": getattr(c, 'target_region_name_en', '') or '?',
                "type": getattr(c, 'connection_type', '') or 'unknown',
                "confidence": float(getattr(c, 'confidence', 0) or 0),
                "strength": float(getattr(c, 'strength', 0) or 0),
            }
            for c in conns
        ]
    return candidates


def _format_steps_context(steps, candidates) -> str:
    """Format steps + connection candidates for LLM prompt."""
    lines = []
    for s in sorted(steps, key=lambda s: getattr(s, 'step_order', 0) or 0):
        rid = str(getattr(s, 'region_candidate_id', ''))[:12] if getattr(s, 'region_candidate_id', None) else 'none'
        lines.append(f"Step {getattr(s, 'step_order', '?')}: {getattr(s, 'step_name', '')} (role:{getattr(s, 'role', 'unknown')}, region:{rid})")
        desc = getattr(s, 'description', '') or ''
        if desc:
            lines.append(f"  desc: {desc}")
        cands = candidates.get(s.id, [])
        if cands:
            lines.append(f"  Candidates ({len(cands)}):")
            for c in cands:
                lines.append(
                    f"    [{c['id'][:12]}] {c['source_name']}->{c['target_name']}"
                    f" type={c['type']} conf={c['confidence']} strength={c['strength']}"
                )
        else:
            lines.append("  Candidates: none")
    return '\n'.join(lines)


def _find_step_by_order(steps, order):
    return next((s for s in steps if getattr(s, 'step_order', None) == order), None)


async def _ensure_circuit_region(session, circuit_id, region_id, sort_order=0):
    """Idempotent: create mirror_circuit_region if not exists."""
    from app.models.mirror_kg import MirrorCircuitRegion
    from sqlalchemy import select as sa_select

    existing = await session.execute(
        sa_select(MirrorCircuitRegion).where(
            MirrorCircuitRegion.circuit_id == circuit_id,
            MirrorCircuitRegion.region_candidate_id == region_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    cr = MirrorCircuitRegion(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        region_candidate_id=region_id,
        sort_order=sort_order,
    )
    session.add(cr)


async def _upsert_membership(session, circuit_id, step_id, projection_id, *,
                             verification_status='circuit_supported', confidence=0.5, evidence_text=''):
    """Insert or update mirror_circuit_projection_membership via confidence competition."""
    from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership
    from sqlalchemy import select as sa_select

    existing = await session.execute(
        sa_select(MirrorCircuitProjectionMembership).where(
            MirrorCircuitProjectionMembership.circuit_id == circuit_id,
            MirrorCircuitProjectionMembership.projection_id == projection_id,
            MirrorCircuitProjectionMembership.source_step_id == step_id,
        )
    )
    m = existing.scalar_one_or_none()
    if m:
        if confidence > (float(getattr(m, 'confidence', 0) or 0)):
            m.confidence = confidence
            m.verification_status = verification_status
            m.evidence_text = evidence_text
    else:
        m = MirrorCircuitProjectionMembership(
            id=uuid.uuid4(),
            circuit_id=circuit_id,
            projection_id=projection_id,
            source_step_id=step_id,
            verification_status=verification_status,
            confidence=confidence,
            evidence_text=evidence_text,
            role_in_circuit='unknown',
            source_method='circuit_to_projection',
            source_atlas='llm_bundle',
            granularity_level='macro',
            mirror_status='llm_suggested',
            review_status='pending',
            promotion_status='not_promoted',
            raw_payload_json={},
            normalized_payload_json={},
        )
        session.add(m)


async def execute_circuit_bundle_fields(
    session: AsyncSession,
    run: LlmFieldCompletionRun,
    request: UniversalFieldCompletionRequest,
    targets: dict[uuid.UUID, Any],
    items: list[LlmFieldCompletionItem],
    warnings: list[str],
    errors: list[str],
    *,
    provider_key: str,
    resolved_model: str,
    make_item,
    apply_field_update,
    call_provider,
    check_cancelled=None,
) -> tuple[int, int]:
    """One LLM call per circuit — all circuit+step+function fields at once. Returns (model_call_count, llm_applied)."""
    import json as _json
    from app.services.field_completion_registry import (
        get_field_value, get_registry_entry, is_empty_value, resolve_field_name,
    )
    from app.services.llm_field_completion_service import _get_existing_overlay_dict

    model_call_count = 0
    llm_applied = 0
    processed = 0
    total = len(targets)

    logger.info("Circuit bundle: executing for %d circuits, provider=%s, model=%s", total, provider_key, resolved_model)
    for cid, circuit in targets.items():
        if check_cancelled and await check_cancelled(session, run.id):
            warnings.append(f"Cancelled after {processed}/{total} circuits")
            break

        # ── Gather circuit context ──────────────────────────────────────────
        from app.models.mirror_macro_clinical import MirrorCircuitStep, MirrorCircuitFunction
        from app.services.llm_circuit_connection_extraction_service import match_region_name
        from sqlalchemy import select as sa_select

        steps_q = sa_select(MirrorCircuitStep).where(MirrorCircuitStep.circuit_id == cid).order_by(MirrorCircuitStep.step_order)
        steps_result = await session.execute(steps_q)
        steps = list(steps_result.scalars().all())

        funcs_q = sa_select(MirrorCircuitFunction).where(MirrorCircuitFunction.circuit_id == cid)
        funcs_result = await session.execute(funcs_q)
        funcs = list(funcs_result.scalars().all())

        # Map functions to steps
        step_funcs: dict[uuid.UUID, list] = {}
        for f in funcs:
            step_funcs.setdefault(getattr(f, 'step_id', None) or cid, []).append(f)

        # ── Build context ────────────────────────────────────────────────────
        name = getattr(circuit, 'circuit_name', '') or str(cid)
        _type = getattr(circuit, 'circuit_type', '') or 'unknown'
        desc = getattr(circuit, 'description', '') or ''
        func = getattr(circuit, 'function_association', '') or ''

        # Existing overlay values
        existing_overlay = _get_existing_overlay_dict(circuit)
        overlay_str = _json.dumps(existing_overlay, ensure_ascii=False) if existing_overlay else '{}'

        # Steps context with connection candidates
        candidates = await _build_step_connection_candidates(session, steps)
        steps_context = _format_steps_context(steps, candidates)

        # Functions context
        func_lines = []
        for f in funcs:
            ft = getattr(f, 'function_term_en', '') or ''
            func_lines.append(f"  Function: {ft} domain={getattr(f, 'function_domain', '')} role={getattr(f, 'function_role', '')}")
        functions_context = '\n'.join(func_lines)

        # ── LLM call ─────────────────────────────────────────────────────────
        parsed: dict[str, Any] = {}
        try:
            response = await call_provider(
                provider_key,
                model=resolved_model,
                system_prompt=_CIRCUIT_BUNDLE_SYSTEM,
                user_prompt=_CIRCUIT_BUNDLE_USER.format(
                    name=name,
                    type=_type,
                    desc=desc,
                    func=func,
                    steps_context=steps_context,
                    functions_context=functions_context,
                ),
                temperature=request.temperature,
                max_tokens=max(request.max_tokens, 2000 + len(steps) * 800),
                response_schema=None,
            )
            model_call_count += 1
            raw_text = getattr(response, 'raw_text', '') or ''
            raw_parsed = getattr(response, 'parsed_json', None)
            if isinstance(raw_parsed, dict):
                parsed = raw_parsed
            elif raw_text:
                cleaned = raw_text.strip()
                # Strip markdown code fences
                if cleaned.startswith('```'):
                    lines = cleaned.split('\n')
                    lines = [l for l in lines if not l.startswith('```')]
                    cleaned = '\n'.join(lines).strip()
                try:
                    parsed = _json.loads(cleaned)
                except (_json.JSONDecodeError, TypeError):
                    # Try to extract JSON from mixed text (common DeepSeek output pattern)
                    _re = __import__('re')
                    _match = _re.search(r'\{.*\}', cleaned, _re.DOTALL)
                    if _match:
                        try:
                            parsed = _json.loads(_match.group(0))
                        except (_json.JSONDecodeError, TypeError):
                            pass
            if not isinstance(parsed, dict):
                logger.warning("Circuit %s: failed to parse LLM response, raw len=%d raw=%s",
                               str(cid)[:12], len(raw_text), raw_text[:500])
                parsed = {}
        except Exception as exc:
            errors.append(f"Circuit {str(cid)[:12]}: LLM failed - {exc}")
            logger.warning("Circuit %s: LLM exception: %s", str(cid)[:12], exc)
            processed += 1
            continue

        # ── Fallback: LLM returned flat fields instead of bundle → wrap as circuit ──
        _circuit_field_names = {'name_en', 'name_cn', 'circuit_class', 'description', 'source_db', 'status', 'canonical_id'}
        if 'circuit' not in parsed and 'steps' not in parsed and 'field_updates' not in parsed:
            if any(k in parsed for k in _circuit_field_names):
                parsed = {'circuit': {k: v for k, v in parsed.items() if k in _circuit_field_names}, 'steps': []}

        # ── Backward compat: field_updates format (legacy per-field tests) ──
        if 'field_updates' in parsed and 'circuit' not in parsed and 'steps' not in parsed:
            _circuit_entry = get_registry_entry(TargetType.circuit)
            raw_updates = parsed.get('field_updates', [])
            for u in raw_updates:
                if not isinstance(u, dict):
                    continue
                fname = u.get('field_name', '')
                value = u.get('value')
                if not fname or value is None or is_empty_value(value):
                    continue
                # Validate field name through registry
                resolved = resolve_field_name(_circuit_entry, fname)
                if resolved is None:
                    item = make_item(run.id, request.target_type.value, cid, fname,
                                     old_value=get_field_value(circuit, fname),
                                     status=ItemStatus.skipped_invalid_field,
                                     suggested=value,
                                     error_message=f"invalid field_name: {fname}")
                    session.add(item)
                    items.append(item)
                    continue
                try:
                    old_val = get_field_value(circuit, resolved)
                    status = apply_field_update(
                        circuit, resolved, value,
                        overwrite_policy=request.overwrite_policy,
                        create_mirror_updates=request.create_mirror_updates,
                        entry=_circuit_entry, run_id=run.id, resolved_model=resolved_model,
                    )
                    _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                    if _applied_flag:
                        llm_applied += 1
                    item = make_item(run.id, request.target_type.value, cid, resolved, old_value=old_val, status=status, suggested=value, applied=value if _applied_flag else None)
                    session.add(item)
                    items.append(item)
                except Exception as _ex:
                    logger.warning("Circuit %s: backward compat apply failed field=%s: %s", str(cid)[:12], fname, _ex)
            processed += 1
            continue

        # ── Apply circuit fields ─────────────────────────────────────────────
        _circuit_entry = get_registry_entry(TargetType.circuit)
        circuit_data = parsed.get('circuit', {})

        # Fix garbage names: propagate overlay name_en to circuit_name column
        current_col_name = getattr(circuit, 'circuit_name', '') or ''
        if 'unknown_region' in str(current_col_name).lower():
            overlay_name = get_field_value(circuit, 'name_en')
            if not is_empty_value(overlay_name) and 'unknown_region' not in str(overlay_name).lower():
                circuit.circuit_name = str(overlay_name)

        for fname in ('name_en', 'name_cn', 'circuit_class', 'description', 'circuit_strength',
                      'source_db', 'status', 'canonical_id'):
            value = circuit_data.get(fname)
            if value is None or is_empty_value(value):
                continue
            # Force-overwrite garbage names
            _effective_policy = request.overwrite_policy
            if fname in ('name_en', 'name_cn') and not is_empty_value(value):
                current_name = getattr(circuit, 'circuit_name', '') or ''
                if 'unknown_region' in str(current_name).lower():
                    _effective_policy = OverwritePolicy.overwrite_with_review
            try:
                old_val = get_field_value(circuit, fname)
                status = apply_field_update(
                    circuit, fname, value,
                    overwrite_policy=_effective_policy,
                    create_mirror_updates=request.create_mirror_updates,
                    entry=_circuit_entry, run_id=run.id, resolved_model=resolved_model,
                )
                _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                if _applied_flag:
                    llm_applied += 1
                item = make_item(run.id, request.target_type.value, cid, fname, old_value=old_val, status=status, suggested=value, applied=value if _applied_flag else None)
                session.add(item)
                items.append(item)
            except Exception as _e:
                logger.warning("Circuit bundle: apply circuit field failed cid=%s field=%s: %s", str(cid)[:12], fname, _e)

        # ── Match + backfill region IDs ──────────────────────────────────────
        start_name = circuit_data.get('start_region_name', '')
        end_name = circuit_data.get('end_region_name', '')
        start_id = await match_region_name(session, start_name) if start_name else None
        end_id = await match_region_name(session, end_name) if end_name else None

        if start_id:
            try:
                old_val = get_field_value(circuit, 'canonical_start_region_id')
                status = apply_field_update(
                    circuit, 'canonical_start_region_id', str(start_id),
                    overwrite_policy=request.overwrite_policy,
                    create_mirror_updates=request.create_mirror_updates,
                    run_id=run.id, resolved_model=resolved_model,
                )
                _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                if _applied_flag:
                    llm_applied += 1
                item = make_item(run.id, request.target_type.value, cid, 'canonical_start_region_id',
                                 old_value=old_val, status=status, suggested=str(start_id),
                                 applied=str(start_id) if _applied_flag else None)
                session.add(item)
                items.append(item)
            except Exception as _e:
                logger.warning("Circuit bundle: start region failed cid=%s: %s", str(cid)[:12], _e)
        if end_id:
            try:
                old_val = get_field_value(circuit, 'canonical_end_region_id')
                status = apply_field_update(
                    circuit, 'canonical_end_region_id', str(end_id),
                    overwrite_policy=request.overwrite_policy,
                    create_mirror_updates=request.create_mirror_updates,
                    run_id=run.id, resolved_model=resolved_model,
                )
                _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                if _applied_flag:
                    llm_applied += 1
                item = make_item(run.id, request.target_type.value, cid, 'canonical_end_region_id',
                                 old_value=old_val, status=status, suggested=str(end_id),
                                 applied=str(end_id) if _applied_flag else None)
                session.add(item)
                items.append(item)
            except Exception as _e:
                logger.warning("Circuit bundle: end region failed cid=%s: %s", str(cid)[:12], _e)

        # Create circuit_regions
        if start_id:
            await _ensure_circuit_region(session, cid, start_id, sort_order=0)
        if end_id:
            await _ensure_circuit_region(session, cid, end_id, sort_order=1)

        # ── Step LLM call (Call 2) — if circuit LLM didn't return steps ────
        steps_data = parsed.get('steps', [])
        if not steps_data and steps:
            try:
                step_response = await call_provider(
                    provider_key,
                    model=resolved_model,
                    system_prompt=_CIRCUIT_STEPS_SYSTEM,
                    user_prompt=_CIRCUIT_STEPS_USER.format(
                        name=name, type=_type, desc=desc,
                        step_count=len(steps),
                        steps_context=steps_context,
                    ),
                    temperature=request.temperature,
                    max_tokens=max(2000, len(steps) * 800),
                    response_schema=None,
                )
                model_call_count += 1
                steps_parsed = getattr(step_response, 'parsed_json', None)
                if not isinstance(steps_parsed, list):
                    raw = getattr(step_response, 'raw_text', '') or ''
                    if raw:
                        cleaned = raw.strip()
                        if cleaned.startswith('```'):
                            lines = cleaned.split('\n')
                            lines = [l for l in lines if not l.startswith('```')]
                            cleaned = '\n'.join(lines).strip()
                        try:
                            steps_parsed = _json.loads(cleaned)
                        except (_json.JSONDecodeError, TypeError):
                            _re = __import__('re')
                            _match = _re.search(r'\[.*\]', cleaned, _re.DOTALL)
                            if _match:
                                try:
                                    steps_parsed = _json.loads(_match.group(0))
                                except (_json.JSONDecodeError, TypeError):
                                    pass
                if isinstance(steps_parsed, list):
                    steps_data = steps_parsed
            except Exception as _step_exc:
                logger.warning("Circuit %s: step LLM call failed: %s", str(cid)[:12], _step_exc)

        # ── Apply step + function fields ─────────────────────────────────────
        for sdata in steps_data:
            step_no = sdata.get('step_no', 1)
            match_step = _find_step_by_order(steps, step_no)
            if not match_step:
                continue

            # Step fields
            for fname in ('step_name_en', 'step_name_cn', 'role_in_circuit', 'description',
                          'source_db', 'status'):
                value = sdata.get(fname)
                if value is None or is_empty_value(value):
                    continue
                try:
                    old_val = get_field_value(match_step, fname)
                    status = apply_field_update(match_step, fname, value, overwrite_policy=request.overwrite_policy, create_mirror_updates=request.create_mirror_updates, run_id=run.id, resolved_model=resolved_model)
                    _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                    if _applied_flag:
                        llm_applied += 1
                    item = make_item(run.id, 'circuit_step', match_step.id, fname, old_value=old_val, status=status, suggested=value, applied=value if _applied_flag else None)
                    session.add(item)
                    items.append(item)
                except Exception as _e:
                    logger.warning("Circuit bundle: step field failed field=%s: %s", fname, _e)

            # Step region matching
            region_name = sdata.get('region_name', '')
            if region_name:
                region_id = await match_region_name(session, region_name)
                if region_id:
                    match_step.region_candidate_id = region_id

            # Connection mapping -> membership (backend-driven via region matching)
            if match_step.region_candidate_id:
                await session.flush()  # flush step update before query
                from app.models.mirror_kg import MirrorRegionConnection
                from sqlalchemy import select as _sa_select, desc as _sa_desc
                proj_stmt = (
                    _sa_select(MirrorRegionConnection)
                    .where(
                        (MirrorRegionConnection.source_region_candidate_id == match_step.region_candidate_id)
                        | (MirrorRegionConnection.target_region_candidate_id == match_step.region_candidate_id)
                    )
                    .order_by(_sa_desc(MirrorRegionConnection.confidence))
                    .limit(5)
                )
                proj_result = await session.execute(proj_stmt)
                best_proj = proj_result.scalars().first()
                if best_proj:
                    conn_conf = float(getattr(best_proj, 'confidence', 0.5) or 0.5)
                    is_suspected = conn_conf < 0.5
                    await _upsert_membership(
                        session, cid, match_step.id, best_proj.id,
                        verification_status='unverified' if is_suspected else 'circuit_supported',
                        confidence=conn_conf,
                        evidence_text=f"Backend-matched via region={str(region_id)[:12]}",
                    )

            # Functions
            for fdata in sdata.get('functions', []):
                for fname in ('function_term_en', 'function_term_cn', 'function_domain', 'function_role', 'effect_type', 'confidence_score', 'evidence_level', 'description', 'source_db', 'status', 'projection_id', 'projection_name'):
                    value = fdata.get(fname)
                    if value is None or is_empty_value(value):
                        continue
                    # Find matching existing function or create new placeholder
                    target_func = next((f for f in funcs if getattr(f, 'function_term_en', '') == fdata.get('function_term_en', '')), None)
                    if target_func:
                        try:
                            old_val = get_field_value(target_func, fname)
                            status = apply_field_update(target_func, fname, value, overwrite_policy=request.overwrite_policy, create_mirror_updates=request.create_mirror_updates, run_id=run.id, resolved_model=resolved_model)
                            _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                            if _applied_flag:
                                llm_applied += 1
                            item = make_item(run.id, 'circuit_function', target_func.id, fname, old_value=old_val, status=status, suggested=value, applied=value if _applied_flag else None)
                            session.add(item)
                            items.append(item)
                        except Exception as _e:
                            logger.warning("Circuit bundle: func field failed field=%s: %s", fname, _e)

        # circuit_strength: dedicated LLM call (always, since bundle prompt buries this field)
        if request.create_mirror_updates and not request.dry_run:
                try:
                    _sr = await call_provider(
                        provider_key, model=resolved_model,
                        system_prompt='Rate this brain circuit impact 0-1. Output ONLY a number.',
                        user_prompt=f'Circuit: {name}\nType: {_type}\nDesc: {desc}\nFunc: {func}',
                        temperature=0.5, max_tokens=20, response_schema=None,
                    )
                    model_call_count += 1
                    _raw = getattr(_sr, 'raw_text', '') or ''
                    _val = float(_raw.strip()) if _raw.strip() else None
                    if _val is not None and 0 <= _val <= 1:
                        write_to_overlay(circuit, 'circuit_strength', _val,
                                         run_id=run.id, confidence=0.9,
                                         source='llm_strength_rating')
                except Exception:
                    pass

        processed += 1
        # Count memberships + regions for this circuit
        _m_count = 0
        _r_count = 0
        try:
            from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership
            from app.models.mirror_kg import MirrorCircuitRegion
            from sqlalchemy import select as _sa_select, func as _sa_func
            _mq = _sa_select(_sa_func.count()).select_from(MirrorCircuitProjectionMembership).where(
                MirrorCircuitProjectionMembership.circuit_id == cid)
            _rq = _sa_select(_sa_func.count()).select_from(MirrorCircuitRegion).where(
                MirrorCircuitRegion.circuit_id == cid)
            _m_count = (await session.execute(_mq)).scalar_one()
            _r_count = (await session.execute(_rq)).scalar_one()
        except Exception as _cnt_exc:
            logger.warning("Circuit %s: membership/region count failed: %s", str(cid)[:12], _cnt_exc)

        if processed % 10 == 0 or processed == total:
            run.summary_json = to_jsonable({
                **(run.summary_json or {}),
                "total_packs": total, "processed_packs": processed,
                "processed_items": len(items),
                "model_call_count": model_call_count, "llm_applied": llm_applied,
                "memberships_count": (run.summary_json or {}).get("memberships_count", 0) + _m_count,
                "regions_count": (run.summary_json or {}).get("regions_count", 0) + _r_count,
            })
            flag_modified(run, "summary_json")
            await session.commit()

    return model_call_count, llm_applied


async def execute_per_connection_fields(
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
    make_item,
    apply_field_update,
    call_provider,
    check_cancelled=None,
) -> tuple[int, int]:
    """One LLM call per connection — all 11 fields at once. Returns (model_call_count, llm_applied)."""
    import json as _json
    from app.services.field_completion_registry import is_deterministic_field, is_empty_value, get_field_value
    from app.services.llm_field_completion_service import OverwritePolicy

    enrichable = list(entry.enrichable_fields)
    det_fields = {f for f in enrichable if is_deterministic_field(entry, f)}
    llm_fields = [f for f in enrichable if f not in det_fields]

    model_call_count = 0
    llm_applied = 0
    processed = 0
    total = len(targets)

    for tid, target in targets.items():
        if check_cancelled and await check_cancelled(session, run.id):
            warnings.append(f"Cancelled after {processed}/{total} connections")
            break

        # Build context from existing data
        src_name = getattr(target, 'source_region_name_en', '') or getattr(target, 'source_region_name_cn', '') or str(getattr(target, 'source_region_candidate_id', ''))[:8]
        tgt_name = getattr(target, 'target_region_name_en', '') or getattr(target, 'target_region_name_cn', '') or str(getattr(target, 'target_region_candidate_id', ''))[:8]
        atlas = getattr(target, 'source_atlas', '') or ''

        current_lines = []
        for f in enrichable:
            val = get_field_value(target, f)
            if not is_empty_value(val):
                current_lines.append(f"  {f}: {val}")
        current_metadata = '\n'.join(current_lines) if current_lines else '  (no existing values)'

        user_prompt = _PER_CONN_USER_TEMPLATE.format(
            source_name=src_name or 'unknown',
            target_name=tgt_name or 'unknown',
            atlas=atlas or 'unknown',
            granularity=getattr(target, 'granularity_level', '') or 'macro',
            current_metadata=current_metadata,
        )

        try:
            response = await call_provider(
                provider_key,
                model=resolved_model,
                system_prompt=_PER_CONN_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                response_schema=None,
            )
            model_call_count += 1
            raw_text = response.raw_text or ''
            parsed = response.parsed_json
            if parsed is None and raw_text:
                cleaned = raw_text.strip()
                if cleaned.startswith('```'):
                    lines = cleaned.split('\n')
                    lines = [l for l in lines if not l.startswith('```')]
                    cleaned = '\n'.join(lines).strip()
                try:
                    parsed = _json.loads(cleaned)
                except _json.JSONDecodeError:
                    pass
            if parsed is None:
                parsed = {}
        except Exception as exc:
            errors.append(f"Connection {str(tid)[:12]}: LLM failed - {exc}")
            processed += 1
            continue

        # Normalize values to DB-valid enums
        _conn_type_map = {
            'structural': 'structural_connection', 'functional': 'functional_connectivity',
            'diffusion_tensor': 'structural_connection', 'other': 'uncertain_connection',
        }
        _dir_map = {'directed': 'directed', 'undirected': 'undirected', 'bidirectional': 'bidirectional'}

        # Apply each field from LLM response
        for field_name in llm_fields:
            value = parsed.get(field_name)
            if value is None or is_empty_value(value):
                continue
            # Normalize connection_type and directionality to DB-valid values
            if field_name == 'projection_type':
                v = str(value).strip().lower()
                value = _conn_type_map.get(v, v if v in (
                    'structural_connection','functional_connectivity','effective_connectivity',
                    'projection','association','coactivation','uncertain_connection','unknown'
                ) else 'uncertain_connection')
            elif field_name == 'directionality':
                v = str(value).strip().lower()
                value = _dir_map.get(v, v if v in ('directed','undirected','bidirectional','unknown') else 'unknown')
            try:
                old_value = get_field_value(target, field_name)  # Capture BEFORE mutation
                status = apply_field_update(
                    target, field_name, value,
                    entry=entry, overwrite_policy=request.overwrite_policy,
                    create_mirror_updates=request.create_mirror_updates,
                    run_id=run.id, resolved_model=resolved_model,
                    confidence=parsed.get('confidence_score'),
                )
                if status and 'applied' in (status.value if hasattr(status, 'value') else str(status)):
                    llm_applied += 1
                item = make_item(
                    run.id, request.target_type.value, tid, field_name,
                    old_value=old_value,
                    status=status,
                    suggested=value,
                    reasoning_summary=f"Per-connection LLM completion for {field_name}",
                )
                session.add(item)
                items.append(item)
            except Exception as exc:
                logger.warning("field completion failed target=%s field=%s: %s", tid, field_name, exc)
                errors.append(f"target {str(tid)[:12]} field {field_name}: {exc}")

        processed += 1
        # Progress update every 10 connections
        if processed % 10 == 0 or processed == total:
            run.summary_json = to_jsonable({
                **(run.summary_json or {}),
                "total_packs": total,
                "processed_packs": processed,
                "current_field": "all_fields",
                "processed_items": len(items),
                "model_call_count": model_call_count,
                "llm_applied": llm_applied,
                "skipped_existing": len(items) - llm_applied,
            })
            flag_modified(run, "summary_json")
            await session.commit()

    return model_call_count, llm_applied


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
    check_cancelled=None,
) -> tuple[int, int, int, int, int]:
    """Returns model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied."""
    from app.services.llm_field_completion_service import determine_fields_to_complete

    model_call_count = 0
    rejected_count = 0
    llm_applied = 0
    estimated_input_tokens = 0
    pack_count = 0
    processed_packs = 0

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

    # Pre-count total packs for progress tracking
    total_packs = 0
    for pf_name in sorted(llm_field_names):
        pf_records: list[dict[str, Any]] = []
        for ptid, ptarget in targets.items():
            pf_fields = determine_fields_to_complete(
                ptarget, entry,
                field_scope=request.field_scope,
                selected_fields=request.selected_fields,
            )
            if pf_name not in pf_fields or is_deterministic_field(entry, pf_name):
                continue
            pcircuit_id = ptid if request.target_type == TargetType.circuit else None
            pcanonical = canonical_cache.get(pcircuit_id or ptid, {})
            pcompact = build_compact_field_context(
                ptarget, pf_name, canonical_resolution=pcanonical,
            )
            pcompact["target_id"] = str(ptid)
            pf_records.append(pcompact)
        if pf_records:
            sys_prompt, usr_prompt, _, _ = build_batch_field_prompt(
                entry, pf_name, pf_records, request, prompt_overrides=request.prompt_overrides,
            )
            total_packs += len(pack_target_batches(pf_records, system_prompt=sys_prompt, template_body=usr_prompt))

    run.summary_json = to_jsonable({
        **(run.summary_json or {}),
        "total_packs": total_packs,
        "processed_packs": 0,
        "current_field": "",
        "processed_items": 0,
    })
    flag_modified(run, "summary_json")
    await session.commit()

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

            # ── Cancellation check before LLM call ────────────────────────
            if check_cancelled is not None and await check_cancelled(session, run.id):
                # Abort mid-execution: return current counts without processing remaining packs
                return model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied

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

            # Inject field_name into each update before validation (LLM may omit it)
            raw_updates = parsed.get("field_updates", [])
            for u in raw_updates:
                if isinstance(u, dict) and "field_name" not in u:
                    u["field_name"] = field_name

            validated = validate_field_updates(entry, raw_updates)
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
                    resolved_model=resolved_model,
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

            # ── Incremental progress update after each pack ───────────────
            processed_packs += 1
            # Count live stats from items list (covers both deterministic + LLM phases)
            live_applied = sum(1 for i in items if getattr(i, 'update_status', None) in ('applied_direct', 'applied_overlay'))
            live_skipped = sum(1 for i in items if getattr(i, 'update_status', None) in ('skipped_existing_value', 'skipped_readonly_field', 'skipped_invalid_field'))
            run.summary_json = to_jsonable({
                **(run.summary_json or {}),
                "total_packs": total_packs,
                "processed_packs": processed_packs,
                "current_field": field_name,
                "processed_items": len(items),
                "model_call_count": model_call_count,
                "skipped_existing": live_skipped,
                "llm_applied": live_applied,
            })
            flag_modified(run, "summary_json")
            await session.commit()

    return model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied
