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

# ── Circuit-level text fields (Call 3 fallback) ─────────────────────────
# The combined bundle prompt frequently returns an empty/unusable `circuit` object
# (large nested JSON), so circuit-level fields like name_cn never get filled. This
# focused call fills only the requested text fields; applied with fill_missing_only
# so existing values are preserved.
_CIRCUIT_FIELDS_SYSTEM = (
    "You are a neuroscientist annotating brain circuit metadata. "
    "Given a brain circuit, output ONLY a JSON object with the requested fields. "
    "name_en: concise English circuit name; name_cn: Chinese circuit name (中文名); "
    "circuit_class: functional classification (e.g. sensory_circuit, motor_circuit, "
    "limbic_circuit, cognitive_control_circuit, memory_related); "
    "description: one-sentence functional description. "
    "No markdown, no explanation, no code fences."
)

_CIRCUIT_FIELDS_USER = (
    "Circuit: {name}\nType: {type}\nDescription: {desc}\nFunction: {func}\n\n"
    "Output ONLY a JSON object with these fields: {fields}\n"
    'Example: {{"name_en":"...","name_cn":"...","circuit_class":"...","description":"..."}}'
)


# Values allowed by the DB CHECK constraint chk_mirror_circuit_type. The bundle LLM
# returns free-text circuit_class, which must be coerced before writing to circuit_type
# (an out-of-range value raises CheckViolation on flush and poisons the whole run).
_VALID_CIRCUIT_TYPES = frozenset({
    'sensory_circuit', 'motor_circuit', 'limbic_circuit', 'cognitive_control_circuit',
    'default_mode_related', 'salience_related', 'memory_related', 'reward_related',
    'language_related', 'attention_related', 'uncertain_circuit', 'unknown',
})

_CIRCUIT_TYPE_KEYWORDS = (
    ('sensor', 'sensory_circuit'),
    ('motor', 'motor_circuit'),
    ('limbic', 'limbic_circuit'),
    ('emotion', 'limbic_circuit'),
    ('cogni', 'cognitive_control_circuit'),
    ('executive', 'cognitive_control_circuit'),
    ('control', 'cognitive_control_circuit'),
    ('default', 'default_mode_related'),
    ('dmn', 'default_mode_related'),
    ('salien', 'salience_related'),
    ('memor', 'memory_related'),
    ('hippocamp', 'memory_related'),
    ('reward', 'reward_related'),
    ('languag', 'language_related'),
    ('attention', 'attention_related'),
)


def coerce_circuit_type(value: Any) -> str:
    """Map an LLM circuit_class to a value allowed by chk_mirror_circuit_type."""
    if value is None:
        return 'uncertain_circuit'
    normalized = str(value).strip().lower().replace(' ', '_').replace('-', '_')
    if normalized in _VALID_CIRCUIT_TYPES:
        return normalized
    for keyword, mapped in _CIRCUIT_TYPE_KEYWORDS:
        if keyword in normalized:
            return mapped
    return 'uncertain_circuit'


# Values allowed by chk_mirror_circuit_function_status. The bundle LLM tends to emit
# "proposed", which is NOT allowed and would raise CheckViolation on flush.
_VALID_FUNCTION_STATUS = frozenset({'active', 'inactive', 'deprecated', 'candidate', 'unknown'})


def coerce_function_status(value: Any) -> str:
    """Map an LLM function status to a value allowed by chk_mirror_circuit_function_status."""
    if value is None:
        return 'candidate'
    normalized = str(value).strip().lower()
    if normalized in _VALID_FUNCTION_STATUS:
        return normalized
    # "proposed" / "suggested" / "llm_*" → candidate; anything else → unknown
    if 'propos' in normalized or 'suggest' in normalized or 'candidate' in normalized or 'llm' in normalized:
        return 'candidate'
    return 'unknown'


def _extract_json_array(raw_text: str) -> list | None:
    """Best-effort parse of a JSON array from possibly fenced/mixed LLM text."""
    import json as _json
    import re as _re

    if not raw_text:
        return None
    cleaned = raw_text.strip()
    if cleaned.startswith('```'):
        cleaned = '\n'.join(l for l in cleaned.split('\n') if not l.startswith('```')).strip()
    try:
        parsed = _json.loads(cleaned)
        return parsed if isinstance(parsed, list) else None
    except (_json.JSONDecodeError, TypeError):
        match = _re.search(r'\[.*\]', cleaned, _re.DOTALL)
        if match:
            try:
                parsed = _json.loads(match.group(0))
                return parsed if isinstance(parsed, list) else None
            except (_json.JSONDecodeError, TypeError):
                return None
    return None


# ── Function completion (Call 4) — the bundle's steps[].functions[] is usually empty,
# so a circuit's existing functions never get their fields filled. This focused call
# annotates the circuit's functions directly. Only unconstrained columns are written.
_CIRCUIT_FUNCTIONS_SYSTEM = (
    "You are a neuroscientist annotating brain-circuit FUNCTIONS. For each function name "
    "given, infer its fields based on the circuit context and neuroanatomy. "
    "Output ONLY a JSON array, no markdown, no explanation.\n"
    "function_domain: cognitive|memory|motor|sensory|emotional|autonomic|other\n"
    "function_role: execution|modulation|inhibition|gating|integration|other\n"
    "effect_type: excitatory|inhibitory|modulatory|unknown\n"
    "function_term_cn: concise Chinese term; description: one-sentence function description.\n"
    '[{"function_term_en":"<copy from input>","function_term_cn":"...","function_domain":"...",'
    '"function_role":"...","effect_type":"...","description":"..."}]'
)

_CIRCUIT_FUNCTIONS_USER = (
    "Circuit: {name} (type: {type})\nDescription: {desc}\n\n"
    "Functions to annotate ({count}) — return one object per function, copy function_term_en exactly:\n"
    "{functions_list}"
)


def _extract_json_object(raw_text: str) -> dict | None:
    """Best-effort parse of a JSON object from possibly fenced/mixed LLM text."""
    import json as _json
    import re as _re

    if not raw_text:
        return None
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            l for l in cleaned.split("\n") if not l.startswith("```")
        ).strip()
    try:
        parsed = _json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except (_json.JSONDecodeError, TypeError):
        match = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
        if match:
            try:
                parsed = _json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except (_json.JSONDecodeError, TypeError):
                return None
    return None


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
        if not isinstance(circuit_data, dict):
            # LLM sometimes returns "circuit" as a string/list instead of an object —
            # coerce to empty dict so this circuit is skipped, never crashing the run.
            circuit_data = {}

        # Fix garbage names: propagate overlay name_en to circuit_name column
        current_col_name = getattr(circuit, 'circuit_name', '') or ''
        _is_garbage = (
            'unknown_region' in str(current_col_name).lower()
            or 'unknown' in str(current_col_name).lower()
            or bool(__import__('re').match(r'^R\d+_', str(current_col_name)))
        )
        if _is_garbage:
            overlay_name = get_field_value(circuit, 'name_en')
            if not is_empty_value(overlay_name) and 'unknown_region' not in str(overlay_name).lower():
                circuit.circuit_name = str(overlay_name)

        for fname in ('name_en', 'name_cn', 'circuit_class', 'description', 'circuit_strength',
                      'source_db', 'status', 'canonical_id'):
            value = circuit_data.get(fname)
            if value is None or is_empty_value(value):
                continue
            # circuit_class → circuit_type is a constrained column; coerce free-text to a valid enum.
            if fname == 'circuit_class':
                value = coerce_circuit_type(value)
            # Force-overwrite garbage names
            _effective_policy = request.overwrite_policy
            if fname in ('name_en', 'name_cn') and not is_empty_value(value):
                current_name = getattr(circuit, 'circuit_name', '') or ''
                if ('unknown_region' in str(current_name).lower()
                    or 'unknown' in str(current_name).lower()
                    or __import__('re').match(r'^R\d+_', str(current_name))):
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

        # ── Fallback (Call 3): fill circuit-level text fields the bundle missed ──
        # The combined bundle call often returns an empty `circuit` object, leaving
        # name_cn / circuit_class / description unfilled. Do a focused call for any
        # circuit-level field still empty on the target. Applied with fill_missing_only
        # so existing values are never overwritten.
        if request.create_mirror_updates and not request.dry_run:
            needed_fields = [
                f for f in ('name_en', 'name_cn', 'circuit_class', 'description')
                if is_empty_value(get_field_value(circuit, f))
            ]
            if needed_fields:
                try:
                    cf_resp = await call_provider(
                        provider_key,
                        model=resolved_model,
                        system_prompt=_CIRCUIT_FIELDS_SYSTEM,
                        user_prompt=_CIRCUIT_FIELDS_USER.format(
                            name=name, type=_type, desc=desc, func=func,
                            fields=', '.join(needed_fields),
                        ),
                        temperature=request.temperature,
                        max_tokens=600,
                        response_schema=None,
                    )
                    model_call_count += 1
                    cf_parsed = getattr(cf_resp, 'parsed_json', None)
                    if not isinstance(cf_parsed, dict):
                        cf_parsed = _extract_json_object(getattr(cf_resp, 'raw_text', '') or '')
                    if isinstance(cf_parsed, dict):
                        for fname in needed_fields:
                            value = cf_parsed.get(fname)
                            if value is None or is_empty_value(value):
                                continue
                            old_val = get_field_value(circuit, fname)
                            status = apply_field_update(
                                circuit, fname, value,
                                overwrite_policy=request.overwrite_policy,
                                create_mirror_updates=request.create_mirror_updates,
                                entry=_circuit_entry, run_id=run.id, resolved_model=resolved_model,
                            )
                            _applied_flag = status and 'applied' in str(getattr(status, 'value', status))
                            if _applied_flag:
                                llm_applied += 1
                            item = make_item(run.id, request.target_type.value, cid, fname,
                                             old_value=old_val, status=status, suggested=value,
                                             applied=value if _applied_flag else None)
                            session.add(item)
                            items.append(item)
                except Exception as _cf_exc:
                    logger.warning("Circuit %s: circuit-fields fallback failed: %s", str(cid)[:12], _cf_exc)

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
            if not isinstance(sdata, dict):
                continue
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

            # Step region matching + membership (backend-driven via region matching).
            # Wrapped so a single step's matching/DB failure never aborts the whole run.
            try:
                region_name = sdata.get('region_name', '')
                region_id = None
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
            except Exception as _rm_exc:
                logger.warning("Circuit bundle: region/membership step failed cid=%s: %s", str(cid)[:12], _rm_exc)

            # Functions
            for fdata in sdata.get('functions', []):
                if not isinstance(fdata, dict):
                    continue
                for fname in ('function_term_en', 'function_term_cn', 'function_domain', 'function_role', 'effect_type', 'confidence_score', 'evidence_level', 'description', 'source_db', 'status', 'projection_id', 'projection_name'):
                    value = fdata.get(fname)
                    if value is None or is_empty_value(value):
                        continue
                    if fname == 'status':
                        value = coerce_function_status(value)
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

        # ── Function completion (Call 4) — the bundle rarely embeds functions in steps,
        # so annotate the circuit's existing functions directly. Only unconstrained
        # columns are written (function_term_cn/domain/role/effect_type/description), so
        # the writes always persist (no CHECK constraint on these columns).
        _fn_fields = ('function_term_cn', 'function_domain', 'function_role', 'effect_type', 'description')
        if request.create_mirror_updates and not request.dry_run and funcs:
            _need_fn = [
                f for f in funcs
                if getattr(f, 'function_term_en', None)
                and any(is_empty_value(get_field_value(f, _ff)) for _ff in _fn_fields)
            ]
            if _need_fn:
                try:
                    _flist = '\n'.join(
                        f"  - {getattr(f, 'function_term_en', '') or '?'}" for f in _need_fn
                    )
                    _fn_resp = await call_provider(
                        provider_key, model=resolved_model,
                        system_prompt=_CIRCUIT_FUNCTIONS_SYSTEM,
                        user_prompt=_CIRCUIT_FUNCTIONS_USER.format(
                            name=name, type=_type, desc=desc,
                            count=len(_need_fn), functions_list=_flist,
                        ),
                        temperature=request.temperature,
                        max_tokens=max(800, len(_need_fn) * 200),
                        response_schema=None,
                    )
                    model_call_count += 1
                    _fn_parsed = getattr(_fn_resp, 'parsed_json', None)
                    if not isinstance(_fn_parsed, list):
                        _fn_parsed = _extract_json_array(getattr(_fn_resp, 'raw_text', '') or '')
                    if isinstance(_fn_parsed, list):
                        for _fd in _fn_parsed:
                            if not isinstance(_fd, dict):
                                continue
                            _tf = next(
                                (f for f in _need_fn
                                 if getattr(f, 'function_term_en', '') == _fd.get('function_term_en', '')),
                                None,
                            )
                            if _tf is None:
                                continue
                            for _ff in _fn_fields:
                                _val = _fd.get(_ff)
                                if _val is None or is_empty_value(_val):
                                    continue
                                try:
                                    _old = get_field_value(_tf, _ff)
                                    _st = apply_field_update(
                                        _tf, _ff, _val,
                                        overwrite_policy=request.overwrite_policy,
                                        create_mirror_updates=request.create_mirror_updates,
                                        run_id=run.id, resolved_model=resolved_model,
                                    )
                                    _af = _st and 'applied' in str(getattr(_st, 'value', _st))
                                    if _af:
                                        llm_applied += 1
                                    _it = make_item(
                                        run.id, 'circuit_function', _tf.id, _ff,
                                        old_value=_old, status=_st, suggested=_val,
                                        applied=_val if _af else None,
                                    )
                                    session.add(_it)
                                    items.append(_it)
                                except Exception as _e:
                                    logger.warning("Circuit %s: func-completion field %s failed: %s",
                                                   str(cid)[:12], _ff, _e)
                except Exception as _fn_exc:
                    logger.warning("Circuit %s: function completion call failed: %s", str(cid)[:12], _fn_exc)

        # circuit_strength: dedicated LLM call (always, since bundle prompt buries this field)
        if request.create_mirror_updates and not request.dry_run:
                try:
                    _sr = await call_provider(
                        provider_key, model=resolved_model,
                        system_prompt='Rate this brain circuit impact 0-1. Output ONLY a number between 0 and 1.',
                        user_prompt=f'Circuit: {name}\nType: {_type}\nDesc: {desc}\nFunc: {func}',
                        temperature=0.5, max_tokens=20, response_schema=None,
                    )
                    model_call_count += 1
                    _raw = (getattr(_sr, 'raw_text', '') or '').strip()
                    # Extract the first number from possibly-noisy text (e.g. "0.8 (high)").
                    _val = None
                    _m = __import__('re').search(r'-?\d+(?:\.\d+)?', _raw)
                    if _m:
                        try:
                            _val = float(_m.group(0))
                        except (TypeError, ValueError):
                            _val = None
                    if _val is not None and 0 <= _val <= 1:
                        _old_strength = get_field_value(circuit, 'circuit_strength')
                        if write_to_overlay(circuit, 'circuit_strength', _val,
                                             run_id=run.id, confidence=0.9,
                                             source='llm_strength_rating'):
                            llm_applied += 1
                            _s_item = make_item(
                                run.id, request.target_type.value, cid, 'circuit_strength',
                                old_value=_old_strength, status=ItemStatus.applied_overlay,
                                suggested=_val, applied=_val, confidence=0.9,
                            )
                            session.add(_s_item)
                            items.append(_s_item)
                    else:
                        logger.warning("Circuit %s: strength rating had no valid 0-1 value in %r",
                                       str(cid)[:12], _raw[:60])
                except Exception as _str_exc:
                    logger.warning("Circuit %s: circuit_strength call failed: %s", str(cid)[:12], _str_exc)

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

        # Persist this circuit's work. On any DB failure (e.g. a value violating a
        # CHECK constraint), roll back so the session stays usable and the remaining
        # circuits still process — instead of the whole run dying with PendingRollbackError.
        run.summary_json = to_jsonable({
            **(run.summary_json or {}),
            "total_packs": total, "processed_packs": processed,
            "processed_items": len(items),
            "model_call_count": model_call_count, "llm_applied": llm_applied,
            "memberships_count": (run.summary_json or {}).get("memberships_count", 0) + _m_count,
            "regions_count": (run.summary_json or {}).get("regions_count", 0) + _r_count,
        })
        flag_modified(run, "summary_json")
        try:
            await session.commit()
        except Exception as _commit_exc:
            logger.warning("Circuit %s: commit failed, rolling back: %s", str(cid)[:12], _commit_exc)
            errors.append(f"Circuit {str(cid)[:12]}: persist failed - {_commit_exc}")
            await session.rollback()

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

    # Build multi-field context records: one record per target, all LLM fields at once
    from app.services.field_completion_prompt_engineering import build_multi_field_batch_prompt

    records: list[dict[str, Any]] = []
    target_map: dict[str, tuple[uuid.UUID, Any]] = {}
    for tid, target in targets.items():
        fields = determine_fields_to_complete(
            target, entry,
            field_scope=request.field_scope,
            selected_fields=request.selected_fields,
        )
        _, llm_fields = split_deterministic_and_llm_fields(entry, fields)
        if not llm_fields:
            continue
        field_contexts: dict[str, Any] = {}
        circuit_id = tid if request.target_type == TargetType.circuit else None
        canonical_resolution = canonical_cache.get(circuit_id or tid, {})
        for fname in llm_fields:
            compact = build_compact_field_context(
                target, fname, canonical_resolution=canonical_resolution,
            )
            field_contexts[fname] = compact
        records.append({
            "target_id": str(tid),
            "target_type": entry.target_type.value,
            "fields": sorted(llm_fields),
            "field_contexts": field_contexts,
        })
        target_map[str(tid)] = (tid, target)

    if not records:
        return 0, 0, 0, 0, 0

    system_prompt, user_prompt, prompt_json, prompt_key = build_multi_field_batch_prompt(
        entry, records, request, prompt_overrides=request.prompt_overrides,
    )
    packs = pack_target_batches(records, system_prompt=system_prompt, template_body=user_prompt)
    pack_count = len(packs)
    total_packs = pack_count

    run.summary_json = to_jsonable({
        **(run.summary_json or {}),
        "total_packs": total_packs,
        "processed_packs": 0,
        "current_field": "multi_field",
        "processed_items": 0,
    })
    flag_modified(run, "summary_json")
    await session.commit()

    for pack_idx, pack in enumerate(packs):
        # Cancellation check before LLM call
        if check_cancelled is not None and await check_cancelled(session, run.id):
            return model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied

        _, batch_user_prompt, _, _ = build_multi_field_batch_prompt(
            entry, pack, request, prompt_overrides=request.prompt_overrides,
        )
        estimated_input_tokens += estimate_prompt_tokens(system_prompt) + estimate_prompt_tokens(batch_user_prompt)

        try:
            if provider_key == "mock":
                raise RuntimeError("mock provider must be patched in tests")
            from app.services.field_completion_prompt_engineering import resolve_prompt_template

            tpl = resolve_prompt_template("default_field_completion", request.prompt_overrides)
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
            logger.exception("multi-field batch completion failed")
            for rec in pack:
                tid_str = str(rec.get("target_id"))
                if not tid_str or tid_str not in target_map:
                    continue
                tid, target = target_map[tid_str]
                for fname in rec.get("fields", []):
                    errors.append(f"target {tid} field {fname}: {exc}")
                    item = make_item(
                        run.id, request.target_type.value, tid, fname,
                        old_value=get_field_value(target, fname),
                        status=ItemStatus.failed, error_message=str(exc),
                        reasoning_summary="prompt_key=multi_field_batch",
                    )
                    session.add(item)
                    items.append(item)
            continue

        # Parse multi-field updates from LLM response
        raw_updates = parsed.get("field_updates", [])
        if not isinstance(raw_updates, list):
            raw_updates = []
        validated = validate_field_updates(entry, raw_updates)
        handled_targets: dict[str, set[str]] = {}  # tid -> set of field_names handled
        for upd, err in validated:
            if not isinstance(upd, dict):
                continue
            upd_field = upd.get("field_name", "")
            tid_raw = upd.get("target_id")
            tid_key = str(tid_raw) if tid_raw is not None else ""
            if tid_key not in target_map:
                continue
            tid, target = target_map[tid_key]
            if tid_key not in handled_targets:
                handled_targets[tid_key] = set()
            handled_targets[tid_key].add(upd_field)

            if err:
                rejected_count += 1
                item = make_item(
                    run.id, request.target_type.value, tid, upd_field,
                    old_value=get_field_value(target, upd_field),
                    status=ItemStatus.skipped_invalid_field,
                    suggested=upd.get("value"), error_message=err,
                    reasoning_summary=format_reasoning_with_consistency(upd),
                )
                session.add(item)
                items.append(item)
                continue

            value = upd.get("value")
            accept, reject_reason, quality_warnings = validate_field_value_quality(upd_field, value)
            if quality_warnings:
                warnings.extend(quality_warnings)
            if not accept:
                rejected_count += 1
                item = make_item(
                    run.id, request.target_type.value, tid, upd_field,
                    old_value=get_field_value(target, upd_field),
                    status=ItemStatus.skipped_invalid_field,
                    suggested=value, error_message=reject_reason,
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

            old_value = get_field_value(target, upd_field)
            if value is None or is_empty_value(value):
                item = make_item(
                    run.id, request.target_type.value, tid, upd_field,
                    old_value=old_value, status=ItemStatus.suggested,
                    suggested=value, confidence=confidence,
                    evidence_text=upd.get("evidence_text"),
                    reasoning_summary=format_reasoning_with_consistency(upd),
                    uncertainty_reason=upd.get("uncertainty_reason"),
                )
                session.add(item)
                items.append(item)
                continue

            status = apply_field_update(
                target, upd_field, value,
                overwrite_policy=request.overwrite_policy,
                create_mirror_updates=request.create_mirror_updates,
                entry=entry, run_id=run.id,
                confidence=confidence, resolved_model=resolved_model,
            )
            if status in (ItemStatus.applied, ItemStatus.applied_direct, ItemStatus.applied_overlay):
                llm_applied += 1
            reasoning = format_reasoning_with_consistency(upd)
            reasoning = f"prompt_key=multi_field_batch | {reasoning}" if reasoning else "prompt_key=multi_field_batch"
            item = make_item(
                run.id, request.target_type.value, tid, upd_field,
                old_value=old_value, status=status, suggested=value,
                applied=value if status in (ItemStatus.applied, ItemStatus.applied_direct, ItemStatus.applied_overlay) else None,
                confidence=confidence, evidence_text=upd.get("evidence_text"),
                reasoning_summary=reasoning, uncertainty_reason=upd.get("uncertainty_reason"),
            )
            session.add(item)
            items.append(item)

        # Mark targets not handled in LLM response
        for rec in pack:
            tid_str = str(rec.get("target_id"))
            if tid_str not in target_map:
                continue
            tid, target = target_map[tid_str]
            handled = handled_targets.get(tid_str, set())
            for fname in rec.get("fields", []):
                if fname not in handled:
                    rejected_count += 1
                    item = make_item(
                        run.id, request.target_type.value, tid, fname,
                        old_value=get_field_value(target, fname),
                        status=ItemStatus.skipped_invalid_field,
                        error_message=f"no field_update for target {tid_str} field {fname}",
                        reasoning_summary="prompt_key=multi_field_batch",
                    )
                    session.add(item)
                    items.append(item)

        # Write after each pack
        processed_packs += 1
        live_applied = sum(1 for i in items if getattr(i, 'update_status', None) in ('applied_direct', 'applied_overlay'))
        live_skipped = sum(1 for i in items if getattr(i, 'update_status', None) in ('skipped_existing_value', 'skipped_readonly_field', 'skipped_invalid_field'))
        run.summary_json = to_jsonable({
            **(run.summary_json or {}),
            "total_packs": total_packs,
            "processed_packs": processed_packs,
            "current_field": "multi_field",
            "processed_items": len(items),
            "model_call_count": model_call_count,
            "skipped_existing": live_skipped,
            "llm_applied": live_applied,
        })
        flag_modified(run, "summary_json")
        await session.commit()

    return model_call_count, rejected_count, estimated_input_tokens, pack_count, llm_applied
