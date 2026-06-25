"""Circuit-to-steps extraction — LLM run/item + mirror_circuit_steps (Step 8.7).

Decomposes an existing mirror_region_circuit into ordered mirror_circuit_steps.
Does NOT write projection/membership/final_*/kg_*; does NOT auto approve/promote.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitStep
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitStepCreate,
    MirrorCircuitStepRole,
    MirrorCircuitStepType,
)
from app.services import mirror_kg_service, mirror_macro_clinical_service
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

CIRCUIT_TO_STEPS_TEMPLATE_KEY = "circuit_to_steps_v1"
DEFAULT_MAX_STEPS = 12

VALID_STEP_TYPES = frozenset({
    MirrorCircuitStepType.region,
    MirrorCircuitStepType.region_group,
    MirrorCircuitStepType.relay,
    MirrorCircuitStepType.hub,
    MirrorCircuitStepType.modulator,
    MirrorCircuitStepType.functional_stage,
    MirrorCircuitStepType.unknown,
})

VALID_ROLES = frozenset({
    MirrorCircuitStepRole.source,
    MirrorCircuitStepRole.target,
    MirrorCircuitStepRole.relay,
    MirrorCircuitStepRole.hub,
    MirrorCircuitStepRole.modulator,
    MirrorCircuitStepRole.participant,
    MirrorCircuitStepRole.unknown,
})

STEP_TYPES_ALLOWING_NO_REGION = frozenset({
    MirrorCircuitStepType.functional_stage,
    MirrorCircuitStepType.region_group,
    MirrorCircuitStepType.unknown,
})


class MirrorCircuitNotFoundError(Exception):
    pass


class InvalidCircuitError(Exception):
    pass


class CrossAtlasRegionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class CrossGranularityRegionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class MirrorStepsTableMissingError(Exception):
    pass


@dataclass
class InvolvedRegion:
    region_candidate_id: uuid.UUID
    en_name: str | None
    cn_name: str | None
    laterality: str | None
    source_atlas: str
    granularity_level: str
    granularity_family: str | None
    role: str
    sort_order: int
    label: str


@dataclass
class CircuitToStepsResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.circuit_to_steps
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    circuit_id: uuid.UUID | None = None
    input_region_count: int = 0
    step_count: int = 0
    mirror_step_created_count: int = 0
    mirror_step_skipped_duplicate_count: int = 0
    dry_run: bool = False
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[CIRCUIT_TO_STEPS_TEMPLATE_KEY]
    return tpl


def _region_label(c: CandidateBrainRegion) -> str:
    return c.en_name or c.cn_name or c.std_name or c.raw_name


def _serialize_circuit(circuit: MirrorRegionCircuit) -> str:
    return json.dumps(
        {
            "circuit_id": str(circuit.id),
            "circuit_name": circuit.circuit_name,
            "circuit_type": circuit.circuit_type,
            "function_association": circuit.function_association,
            "description": circuit.description,
            "confidence": float(circuit.confidence) if circuit.confidence is not None else None,
            "evidence_text": circuit.evidence_text,
            "uncertainty_reason": circuit.uncertainty_reason,
            "source_atlas": circuit.source_atlas,
            "granularity_level": circuit.granularity_level,
            "granularity_family": circuit.granularity_family,
        },
        ensure_ascii=False,
        indent=2,
    )


def _serialize_regions(regions: list[InvolvedRegion]) -> str:
    return json.dumps(
        [
            {
                "region_candidate_id": str(r.region_candidate_id),
                "en_name": r.en_name,
                "cn_name": r.cn_name,
                "laterality": r.laterality,
                "source_atlas": r.source_atlas,
                "granularity_level": r.granularity_level,
                "granularity_family": r.granularity_family,
                "role": r.role,
                "sort_order": r.sort_order,
            }
            for r in regions
        ],
        ensure_ascii=False,
        indent=2,
    )


async def load_involved_regions(
    session: AsyncSession,
    circuit: MirrorRegionCircuit,
    *,
    include_circuit_regions: bool,
) -> tuple[list[InvolvedRegion], list[str]]:
    warnings: list[str] = []
    if not include_circuit_regions:
        return [], warnings

    _, circuit_regions = await mirror_kg_service.get_mirror_circuit(session, circuit.id)
    if not circuit_regions:
        warnings.append("NO_CIRCUIT_REGIONS: circuit has no mirror_circuit_regions; continuing with empty region context")
        return [], warnings

    involved: list[InvolvedRegion] = []
    for cr in sorted(circuit_regions, key=lambda x: x.sort_order):
        if cr.region_candidate_id is None:
            warnings.append(f"circuit_region {cr.id} has no region_candidate_id; skipped")
            continue
        cand = await session.get(CandidateBrainRegion, cr.region_candidate_id)
        if cand is None:
            warnings.append(f"region_candidate {cr.region_candidate_id} not found; skipped")
            continue
        if cand.source_atlas != circuit.source_atlas:
            raise CrossAtlasRegionError(
                f"region {cand.id} source_atlas {cand.source_atlas} != circuit {circuit.source_atlas}"
            )
        if cand.granularity_level != circuit.granularity_level:
            raise CrossGranularityRegionError(
                f"region {cand.id} granularity_level {cand.granularity_level} != circuit {circuit.granularity_level}"
            )
        if cand.granularity_family != circuit.granularity_family:
            raise CrossGranularityRegionError(
                f"region {cand.id} granularity_family mismatch with circuit"
            )
        involved.append(
            InvolvedRegion(
                region_candidate_id=cand.id,
                en_name=cand.en_name,
                cn_name=cand.cn_name,
                laterality=cand.laterality,
                source_atlas=cand.source_atlas,
                granularity_level=cand.granularity_level,
                granularity_family=cand.granularity_family,
                role=cr.role,
                sort_order=cr.sort_order,
                label=_region_label(cand),
            )
        )
    return involved, warnings


def build_circuit_to_steps_prompt(
    circuit: MirrorRegionCircuit,
    involved_regions: list[InvolvedRegion],
    *,
    template_key: str = CIRCUIT_TO_STEPS_TEMPLATE_KEY,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    circuit_json = _serialize_circuit(circuit)
    regions_json = _serialize_regions(involved_regions)
    values = {
        "source_atlas": circuit.source_atlas,
        "granularity_level": circuit.granularity_level,
        "granularity_family": circuit.granularity_family or "",
        "circuit_json": circuit_json,
        "regions_json": regions_json,
        "function_association": circuit.function_association or "",
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "circuit_json": circuit_json,
        "regions_json": regions_json,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_circuit_to_steps_response(raw_text: str) -> dict[str, Any]:
    return parse_llm_json_response(raw_text)


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_circuit_steps(
    parsed: dict[str, Any],
    *,
    involved_regions: list[InvolvedRegion],
    max_steps: int = DEFAULT_MAX_STEPS,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    allowed_region_ids = {r.region_candidate_id for r in involved_regions}
    region_labels = {r.region_candidate_id: r.label for r in involved_regions}

    raw_steps = parsed.get("circuit_steps")
    if raw_steps is None:
        return [], ["circuit_steps array missing; treating as empty"]
    if not isinstance(raw_steps, list):
        raise ValueError("circuit_steps must be an array")

    normalized: list[dict[str, Any]] = []
    seen_orders: set[int] = set()
    duplicate_region_ids: list[str] = []

    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            warnings.append(f"circuit_steps[{idx}] skipped: not an object")
            continue

        step_order = step.get("step_order")
        if step_order is None:
            step_order = idx + 1
            warnings.append(f"circuit_steps[{idx}] step_order missing; assigned {step_order}")
        try:
            step_order = int(step_order)
        except (TypeError, ValueError):
            warnings.append(f"circuit_steps[{idx}] skipped: invalid step_order")
            continue
        if step_order < 1:
            warnings.append(f"circuit_steps[{idx}] skipped: step_order < 1")
            continue
        if step_order in seen_orders:
            warnings.append(f"circuit_steps[{idx}] skipped: duplicate step_order {step_order}")
            continue

        step_type = str(step.get("step_type") or MirrorCircuitStepType.unknown)
        if step_type not in VALID_STEP_TYPES:
            step_type = MirrorCircuitStepType.unknown
            warnings.append(f"circuit_steps[{idx}] step_type coerced to unknown")

        role = str(step.get("role") or MirrorCircuitStepRole.unknown)
        if role not in VALID_ROLES:
            role = MirrorCircuitStepRole.unknown
            warnings.append(f"circuit_steps[{idx}] role coerced to unknown")

        region_id: uuid.UUID | None = None
        raw_rid = step.get("region_candidate_id")
        if raw_rid is not None and str(raw_rid).strip():
            try:
                region_id = uuid.UUID(str(raw_rid))
            except (ValueError, TypeError, AttributeError):
                warnings.append(f"circuit_steps[{idx}] skipped: invalid region_candidate_id")
                continue
            if region_id not in allowed_region_ids:
                warnings.append(f"circuit_steps[{idx}] skipped: unknown region_candidate_id {region_id}")
                continue
            if str(region_id) in duplicate_region_ids:
                warnings.append(f"circuit_steps[{idx}] duplicate region_candidate_id {region_id}")
            duplicate_region_ids.append(str(region_id))
        elif step_type not in STEP_TYPES_ALLOWING_NO_REGION:
            warnings.append(
                f"circuit_steps[{idx}] skipped: region_candidate_id required for step_type {step_type}"
            )
            continue

        step_name = str(step.get("step_name") or "").strip()
        if not step_name:
            if region_id and region_id in region_labels:
                step_name = region_labels[region_id]
            else:
                step_name = f"Step {step_order}"
            warnings.append(f"circuit_steps[{idx}] step_name empty; fallback to {step_name!r}")

        evidence_text = step.get("evidence_text")
        if not evidence_text:
            warnings.append(f"circuit_steps[{idx}] missing evidence_text")

        normalized.append({
            "step_order": step_order,
            "step_name": step_name,
            "step_type": step_type,
            "region_candidate_id": str(region_id) if region_id else None,
            "role": role,
            "description": step.get("description"),
            "confidence": _clamp_confidence(step.get("confidence")),
            "evidence_text": evidence_text,
            "uncertainty_reason": step.get("uncertainty_reason"),
            "raw": step,
        })
        seen_orders.add(step_order)

    if len(normalized) > max_steps:
        warnings.append(
            f"circuit_steps truncated from {len(normalized)} to max_steps={max_steps}"
        )
        normalized = normalized[:max_steps]

    return normalized, warnings


async def _step_exists(
    session: AsyncSession,
    circuit_id: uuid.UUID,
    step_order: int,
) -> MirrorCircuitStep | None:
    q = select(MirrorCircuitStep).where(
        MirrorCircuitStep.circuit_id == circuit_id,
        MirrorCircuitStep.step_order == step_order,
    )
    return (await session.execute(q)).scalar_one_or_none()


async def persist_circuit_steps(
    session: AsyncSession,
    *,
    circuit: MirrorRegionCircuit,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    steps: list[dict[str, Any]],
) -> tuple[int, int, list[str]]:
    created = 0
    skipped = 0
    warnings: list[str] = []

    for step in steps:
        existing = await _step_exists(session, circuit.id, step["step_order"])
        if existing is not None:
            skipped += 1
            warnings.append(
                f"EXISTING_STEP_ORDER_DIFFERENT_CONTENT: step_order {step['step_order']} already exists"
            )
            continue

        region_id = uuid.UUID(step["region_candidate_id"]) if step.get("region_candidate_id") else None
        payload = MirrorCircuitStepCreate(
            circuit_id=circuit.id,
            region_candidate_id=region_id,
            resource_id=circuit.resource_id,
            batch_id=circuit.batch_id,
            llm_run_id=run.id,
            llm_item_id=item.id,
            granularity_level=circuit.granularity_level,
            granularity_family=circuit.granularity_family,
            source_atlas=circuit.source_atlas,
            source_version=circuit.source_version,
            step_order=step["step_order"],
            step_name=step["step_name"],
            step_type=step["step_type"],
            role=step["role"],
            description=step.get("description"),
            confidence=step.get("confidence"),
            evidence_text=step.get("evidence_text"),
            uncertainty_reason=step.get("uncertainty_reason"),
            mirror_status=MirrorStatus.llm_suggested,
            review_status=MirrorReviewStatus.pending,
            promotion_status=MirrorPromotionStatus.not_promoted,
            raw_payload_json=step.get("raw") or step,
            normalized_payload_json=step,
        )
        try:
            await mirror_macro_clinical_service.create_circuit_step(session, payload)
            created += 1
        except mirror_macro_clinical_service.DuplicateStepOrderError:
            skipped += 1
            warnings.append(f"duplicate step_order {step['step_order']} on persist")

    return created, skipped, warnings


async def run_circuit_to_steps_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    circuit_id: uuid.UUID,
    prompt_template_key: str = CIRCUIT_TO_STEPS_TEMPLATE_KEY,
    temperature: float = 0.2,
    max_tokens: int = 3000,
    dry_run: bool = False,
    max_steps: int = DEFAULT_MAX_STEPS,
    include_circuit_regions: bool = True,
    create_mirror_records: bool = True,
) -> CircuitToStepsResult:
    circuit = await session.get(MirrorRegionCircuit, circuit_id)
    if circuit is None:
        raise MirrorCircuitNotFoundError(str(circuit_id))
    if not circuit.source_atlas:
        raise InvalidCircuitError("circuit missing source_atlas")
    if not circuit.granularity_level:
        raise InvalidCircuitError("circuit missing granularity_level")

    provider_key = provider_name.lower()
    if provider_key == "deepseek":
        cfg = get_deepseek_runtime_config()
        resolved_model = model_name or cfg.default_model
    elif provider_key == "kimi":
        cfg = get_kimi_runtime_config()
        resolved_model = model_name or cfg.default_model
    else:
        raise UnknownProviderError(provider_name)

    if not dry_run and not cfg.api_key.strip():
        raise ProviderNotConfiguredServiceError(
            provider_key, f"provider is not configured: {provider_key}"
        )

    involved_regions, load_warnings = await load_involved_regions(
        session, circuit, include_circuit_regions=include_circuit_regions
    )
    all_warnings = list(load_warnings)

    system_prompt, user_prompt, prompt_json = build_circuit_to_steps_prompt(
        circuit,
        involved_regions,
        template_key=prompt_template_key,
    )

    result = CircuitToStepsResult(
        circuit_id=circuit.id,
        input_region_count=len(involved_regions),
        dry_run=dry_run,
        provider=provider_key,
        model_name=resolved_model,
        warnings=all_warnings,
    )

    if dry_run:
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt
        return result

    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.circuit_to_steps,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "circuit_id": str(circuit.id),
            "include_circuit_regions": include_circuit_regions,
            "max_steps": max_steps,
            "create_mirror_records": create_mirror_records,
        },
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        source_atlas=circuit.source_atlas,
        source_version=circuit.source_version,
        status=LlmRunStatus.running,
        input_count=len(involved_regions),
        temperature=temperature,
        max_tokens=max_tokens,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    item = LlmExtractionItem(
        run_id=run.id,
        candidate_id=None,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        task_type=LlmTaskType.circuit_to_steps,
        item_index=0,
        input_json={
            "circuit_id": str(circuit.id),
            "circuit_json": json.loads(_serialize_circuit(circuit)),
            "regions_json": json.loads(_serialize_regions(involved_regions)),
            "input_region_count": len(involved_regions),
            "max_steps": max_steps,
        },
        prompt_json=prompt_json,
        status=LlmItemStatus.running,
    )
    session.add(item)
    await session.flush()

    provider = get_llm_provider(provider_key)
    response = await provider.complete_json(
        model=resolved_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    item.raw_response_text = response.raw_text or None
    run.request_payload_redacted = response.request_payload_redacted
    run.usage_json = response.usage.as_dict() if response.usage else {}

    normalized_steps: list[dict[str, Any]] = []

    if response.error_message:
        item.status = LlmItemStatus.failed
        item.error_message = response.error_message
        run.status = LlmRunStatus.failed
        run.error_count = 1
    elif response.parsed_json is None:
        try:
            parsed = parse_circuit_to_steps_response(response.raw_text or "")
            response.parsed_json = parsed
        except Exception as exc:
            item.status = LlmItemStatus.failed
            item.error_message = f"failed to parse model JSON: {exc}"
            run.status = LlmRunStatus.failed
            run.error_count = 1
            parsed = None
        if parsed is not None:
            item.parsed_response_json = parsed
    else:
        item.parsed_response_json = response.parsed_json

    if response.parsed_json is not None and item.status != LlmItemStatus.failed:
        try:
            normalized_steps, norm_warnings = normalize_circuit_steps(
                response.parsed_json,
                involved_regions=involved_regions,
                max_steps=max_steps,
            )
            all_warnings.extend(norm_warnings)
        except ValueError as exc:
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            run.status = LlmRunStatus.failed
            run.error_count = 1
            normalized_steps = []

    if item.status != LlmItemStatus.failed:
        item.normalized_output_json = {"circuit_steps": normalized_steps}
        confidences = [s["confidence"] for s in normalized_steps if s.get("confidence") is not None]
        if confidences:
            item.confidence = sum(confidences) / len(confidences)
        evidences = [s.get("evidence_text") for s in normalized_steps if s.get("evidence_text")]
        if evidences:
            item.evidence_text = "; ".join(str(e) for e in evidences[:3])
        item.status = LlmItemStatus.succeeded if normalized_steps else LlmItemStatus.needs_review
        run.output_count = len(normalized_steps)
        run.status = LlmRunStatus.succeeded

        if create_mirror_records and normalized_steps:
            try:
                mc, skip, pw = await persist_circuit_steps(
                    session,
                    circuit=circuit,
                    run=run,
                    item=item,
                    steps=normalized_steps,
                )
                result.mirror_step_created_count = mc
                result.mirror_step_skipped_duplicate_count = skip
                all_warnings.extend(pw)
            except ProgrammingError as exc:
                run.status = LlmRunStatus.failed
                run.error_message = f"mirror_circuit_steps table missing or inaccessible: {exc}"
                item.status = LlmItemStatus.failed
                item.error_message = run.error_message
                raise MirrorStepsTableMissingError(run.error_message) from exc
            except Exception as exc:
                run.status = LlmRunStatus.partially_succeeded
                run.error_message = f"mirror persist failed: {exc}"
                all_warnings.append(str(exc))

    run.finished_at = datetime.now(timezone.utc)
    result.run_id = run.id
    result.item_id = item.id
    result.status = run.status
    result.step_count = len(normalized_steps)
    result.warnings = all_warnings

    await session.commit()
    await session.refresh(run)
    await session.refresh(item)
    return result
