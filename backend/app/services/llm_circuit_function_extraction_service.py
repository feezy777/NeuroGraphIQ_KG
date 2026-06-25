"""Circuit-to-functions extraction — LLM run/item + mirror_circuit_functions (Step 10.6.3).

Derives mirror_circuit_functions from mirror_region_circuits.
Does NOT write final_*/kg_* / macro_clinical.*; does NOT auto approve/promote.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitFunction
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_macro_clinical import MirrorCircuitFunctionCreate
from app.services import mirror_kg_service, mirror_macro_clinical_service
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

CIRCUIT_TO_FUNCTIONS_EXTRACTION_TEMPLATE_KEY = "circuit_to_functions_extraction_v1"

VALID_EVIDENCE_LEVELS = frozenset({"low", "moderate", "high", "insufficient"})
LEGACY_FIELD_NAMES = frozenset({
    "function_association",
    "function_term",
    "circuit_function",
    "function_name",
    "function_category",
    "relation_type",
    "confidence",
})
_CN_RE = re.compile(r"[\u4e00-\u9fff]")
_EN_RE = re.compile(r"[A-Za-z]")


class EmptyCircuitsError(Exception):
    pass


class CircuitNotFoundError(Exception):
    def __init__(self, circuit_id: str):
        self.circuit_id = circuit_id
        super().__init__(f"circuit not found: {circuit_id}")


class InvalidRequestError(Exception):
    pass


class MirrorCircuitFunctionsTableMissingError(Exception):
    pass


@dataclass
class CircuitToFunctionsResult:
    status: str = "completed"
    target_type: str = "circuit_function"
    source_target_type: str = "circuit"
    circuit_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    created_ids: list[uuid.UUID] = field(default_factory=list)
    updated_ids: list[uuid.UUID] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prompt_preview: dict[str, Any] | None = None
    estimated_model_calls: int = 0
    estimated_input_tokens: int = 0
    dry_run: bool = True
    created_targets: list[dict[str, Any]] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[CIRCUIT_TO_FUNCTIONS_EXTRACTION_TEMPLATE_KEY]
    return tpl


def _clip(text: Any, limit: int = 240) -> str | None:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _short_id(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= 12 else f"{s[:8]}…"


def _circuit_payload_dict(circuit: MirrorRegionCircuit) -> dict[str, Any]:
    norm = circuit.normalized_payload_json if isinstance(circuit.normalized_payload_json, dict) else {}
    raw = circuit.raw_payload_json if isinstance(circuit.raw_payload_json, dict) else {}
    overlay = norm.get("formal_field_overlay") if isinstance(norm.get("formal_field_overlay"), dict) else {}
    attrs = norm.get("attributes") if isinstance(norm.get("attributes"), dict) else {}
    raw_attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    nested_raw = raw_attrs.get("raw") if isinstance(raw_attrs.get("raw"), dict) else {}
    return {
        "normalized": norm,
        "raw": raw,
        "overlay": overlay,
        "attributes": attrs,
        "raw_attributes": raw_attrs,
        "nested_raw": nested_raw,
    }


def _pick_function_signal(circuit: MirrorRegionCircuit) -> tuple[str | None, str]:
    """Return (signal_text, source_key)."""
    payload = _circuit_payload_dict(circuit)
    checks: list[tuple[str | None, str]] = [
        (circuit.function_association, "circuit.function_association"),
        (payload["attributes"].get("function_association"), "attributes.function_association"),
        (payload["nested_raw"].get("function_association"), "attributes.raw.function_association"),
        (payload["raw_attributes"].get("function_association"), "raw.attributes.function_association"),
        (payload["raw"].get("function_association"), "raw.function_association"),
        (payload["attributes"].get("description"), "attributes.description"),
        (circuit.description, "circuit.description"),
        (payload["attributes"].get("evidence_text"), "attributes.evidence_text"),
        (circuit.evidence_text, "circuit.evidence_text"),
    ]
    for value, source in checks:
        if value is not None and str(value).strip():
            return str(value).strip(), source
    return None, ""


def _infer_function_domain(term: str) -> str:
    t = term.lower()
    mapping = (
        ("sensorimotor", ("sensorimotor", "somatosensory")),
        ("motor", ("motor", "movement")),
        ("visual", ("visual", "vision")),
        ("auditory", ("auditory", "hearing")),
        ("limbic", ("limbic", "emotion", "affective")),
        ("autonomic", ("autonomic", "visceral")),
        ("cognitive", ("cognitive", "memory", "attention", "executive")),
        ("integrative", ("integration", "integrative")),
    )
    for domain, keys in mapping:
        if any(k in t for k in keys):
            return domain
    return "unknown"


def _infer_function_role(term: str) -> str:
    t = term.lower()
    if any(k in t for k in ("integration", "integrative")):
        return "integration"
    if any(k in t for k in ("modulation", "modulatory", "modulate")):
        return "modulation"
    if "relay" in t:
        return "relay"
    if any(k in t for k in ("regulation", "regulatory")):
        return "regulation"
    if any(k in t for k in ("execution", "executive")):
        return "execution"
    if "coordination" in t:
        return "coordination"
    return "unknown"


def _circuit_confidence(circuit: MirrorRegionCircuit) -> float | None:
    payload = _circuit_payload_dict(circuit)
    for val in (
        circuit.confidence,
        payload["attributes"].get("confidence"),
        payload["overlay"].get("confidence"),
    ):
        if val is not None:
            try:
                return max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                continue
    return None


def extract_function_seed_from_circuit(circuit: MirrorRegionCircuit) -> dict[str, Any] | None:
    signal, source = _pick_function_signal(circuit)
    if not signal:
        return None
    confidence = _circuit_confidence(circuit) or 0.5
    domain = _infer_function_domain(signal)
    role = _infer_function_role(signal)
    payload = _circuit_payload_dict(circuit)
    evidence = circuit.evidence_text or payload["attributes"].get("evidence_text")
    return {
        "function_term_en": signal if _EN_RE.search(signal) else None,
        "function_term_cn": signal if _CN_RE.search(signal) and not _EN_RE.search(signal) else None,
        "function_domain": domain,
        "function_role": role,
        "confidence_score": confidence,
        "evidence_level": "low",
        "description": _clip(
            f"The circuit is associated with {signal} based on {source}.",
            300,
        ),
        "evidence_text": _clip(evidence, 300),
        "source_key": source,
    }


def _name_cn_overlay(circuit: MirrorRegionCircuit) -> str | None:
    payload = _circuit_payload_dict(circuit)
    for val in (
        payload["overlay"].get("name_cn"),
        payload["overlay"].get("circuit_name_cn"),
        payload["attributes"].get("name_cn"),
    ):
        if val and str(val).strip():
            return _clip(val, 120)
    return None


async def _load_step_summary(
    session: AsyncSession,
    circuit_id: uuid.UUID,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    try:
        steps, _ = await mirror_macro_clinical_service.list_circuit_steps(
            session, circuit_id=circuit_id, limit=limit, offset=0
        )
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for step in steps[:limit]:
        out.append({
            "step_order": step.step_order,
            "step_name": _clip(step.step_name, 80),
            "role": _clip(step.role, 40),
            "step_type": _clip(step.step_type, 40),
        })
    return out


async def _load_region_summary(
    session: AsyncSession,
    circuit_id: uuid.UUID,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    try:
        _, regions = await mirror_kg_service.get_mirror_circuit(session, circuit_id)
    except mirror_kg_service.MirrorCircuitNotFoundError:
        return []
    out: list[dict[str, Any]] = []
    for cr in regions[:limit]:
        label = None
        if cr.region_candidate_id:
            cand = await session.get(CandidateBrainRegion, cr.region_candidate_id)
            if cand:
                label = cand.en_name or cand.cn_name or cand.raw_name
        out.append({
            "role": cr.role,
            "sort_order": cr.sort_order,
            "label": _clip(label, 60),
        })
    return out


def build_compact_circuit_function_context(
    circuit: MirrorRegionCircuit,
    *,
    related_steps: list[dict[str, Any]] | None = None,
    region_summary: list[dict[str, Any]] | None = None,
    include_provenance: bool = True,
) -> dict[str, Any]:
    payload = _circuit_payload_dict(circuit)
    signal, _ = _pick_function_signal(circuit)
    ctx: dict[str, Any] = {
        "circuit_id": _short_id(circuit.id),
        "name_en": _clip(circuit.circuit_name, 120),
        "circuit_class": _clip(circuit.circuit_type, 80),
        "description": _clip(circuit.description or payload["attributes"].get("description"), 240),
        "function_association": _clip(signal or circuit.function_association, 120),
        "evidence_text": _clip(circuit.evidence_text or payload["attributes"].get("evidence_text"), 180),
        "uncertainty_reason": _clip(circuit.uncertainty_reason, 120),
        "source_db": circuit.source_atlas,
        "confidence": _circuit_confidence(circuit),
    }
    name_cn = _name_cn_overlay(circuit)
    if name_cn:
        ctx["name_cn"] = name_cn
    if related_steps:
        ctx["step_summary"] = related_steps[:5]
    if region_summary:
        ctx["region_summary"] = region_summary[:5]
    if include_provenance:
        ctx["provenance_hint"] = "mirror_region_circuit"
    return ctx


def build_circuit_to_functions_prompt(
    *,
    compact_context: dict[str, Any],
    seed: dict[str, Any],
    template_key: str = CIRCUIT_TO_FUNCTIONS_EXTRACTION_TEMPLATE_KEY,
    prompt_overrides: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    values = {
        "compact_context_json": json.dumps(compact_context, ensure_ascii=False, separators=(",", ":")),
        "seed_json": json.dumps(seed, ensure_ascii=False, separators=(",", ":")),
    }
    if prompt_overrides:
        values.update({k: v for k, v in prompt_overrides.items() if v is not None})
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "compact_context_json": compact_context,
        "seed_json": seed,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _normalize_evidence_level(value: Any) -> str:
    if value is None:
        return "low"
    s = str(value).strip().lower()
    if s in VALID_EVIDENCE_LEVELS:
        return s
    return "low"


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "unknown":
        return None
    return s


def _reject_legacy_fields(item: dict[str, Any], warnings: list[str]) -> None:
    for key in LEGACY_FIELD_NAMES:
        if key in item and item[key] is not None:
            warnings.append(f"legacy field ignored: {key}")


def _is_cjk_only(text: str) -> bool:
    return bool(_CN_RE.search(text)) and not bool(_EN_RE.search(text))


def _is_latin_only(text: str) -> bool:
    return bool(_EN_RE.search(text)) and not bool(_CN_RE.search(text))


def parse_circuit_function_extraction_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        parsed = parse_llm_json_response(raw)
    else:
        raise ValueError("unsupported response type")
    if "circuit_functions" not in parsed and "message" in parsed:
        content = parsed.get("message")
        if isinstance(content, dict):
            parsed = content
        elif isinstance(content, str):
            parsed = parse_llm_json_response(content)
    if not isinstance(parsed.get("circuit_functions"), list):
        raise ValueError("circuit_functions must be a list")
    return parsed


def normalize_circuit_functions(
    parsed: dict[str, Any],
    *,
    seed: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    out: list[dict[str, Any]] = []
    for raw_item in parsed.get("circuit_functions") or []:
        if not isinstance(raw_item, dict):
            warnings.append("skipped non-object circuit_function entry")
            continue
        _reject_legacy_fields(raw_item, warnings)
        term_en = _normalize_optional_str(raw_item.get("function_term_en"))
        term_cn = _normalize_optional_str(raw_item.get("function_term_cn"))
        if not term_en and not term_cn:
            warnings.append("skipped circuit_function without function_term_en/cn")
            continue
        if term_cn and _is_latin_only(term_cn):
            warnings.append(f"function_term_cn appears English-only: {term_cn}")
        if term_en and _is_cjk_only(term_en):
            warnings.append(f"function_term_en appears Chinese-only: {term_en}")
        fn = {
            "function_term_en": term_en or (seed or {}).get("function_term_en"),
            "function_term_cn": term_cn or (seed or {}).get("function_term_cn"),
            "function_domain": _normalize_optional_str(raw_item.get("function_domain"))
            or (seed or {}).get("function_domain")
            or "unknown",
            "function_role": _normalize_optional_str(raw_item.get("function_role"))
            or (seed or {}).get("function_role")
            or "unknown",
            "effect_type": _normalize_optional_str(raw_item.get("effect_type")),
            "confidence_score": _clamp_confidence(
                raw_item.get("confidence_score", (seed or {}).get("confidence_score"))
            ),
            "evidence_level": _normalize_evidence_level(
                raw_item.get("evidence_level", (seed or {}).get("evidence_level"))
            ),
            "description": _normalize_optional_str(raw_item.get("description"))
            or (seed or {}).get("description"),
            "remark": _normalize_optional_str(raw_item.get("remark")),
            "evidence_text": _normalize_optional_str(raw_item.get("evidence_text"))
            or (seed or {}).get("evidence_text"),
            "uncertainty_reason": _normalize_optional_str(raw_item.get("uncertainty_reason")),
        }
        if not fn["function_term_en"] and not fn["function_term_cn"]:
            warnings.append("skipped empty circuit_function after normalization")
            continue
        out.append(fn)
    for w in parsed.get("warnings") or []:
        if w:
            warnings.append(str(w))
    return out, warnings


def circuit_function_dedup_key(circuit_id: uuid.UUID, fn: dict[str, Any]) -> tuple[Any, ...]:
    domain = (fn.get("function_domain") or "unknown").strip().lower()
    role = (fn.get("function_role") or "unknown").strip().lower()
    term_en = (fn.get("function_term_en") or "").strip().lower()
    term_cn = (fn.get("function_term_cn") or "").strip().lower()
    if term_en:
        return (str(circuit_id), term_en, domain, role)
    return (str(circuit_id), term_cn, domain, role)


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, dict) and not value:
        return True
    return False


async def _find_existing_circuit_function(
    session: AsyncSession,
    circuit_id: uuid.UUID,
    fn: dict[str, Any],
) -> MirrorCircuitFunction | None:
    try:
        rows, _ = await mirror_macro_clinical_service.list_mirror_circuit_functions(
            session, circuit_id=circuit_id, limit=200, offset=0
        )
    except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError:
        raise
    key = circuit_function_dedup_key(circuit_id, fn)
    for row in rows:
        existing = {
            "function_term_en": row.function_term_en,
            "function_term_cn": row.function_term_cn,
            "function_domain": row.function_domain,
            "function_role": row.function_role,
        }
        if circuit_function_dedup_key(circuit_id, existing) == key:
            return row
    return None


def _build_attributes(
    *,
    seed: dict[str, Any],
    compact_context: dict[str, Any],
    provider_raw: dict[str, Any] | None,
    fn: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": "circuit_to_functions_extraction",
        "seed": {k: v for k, v in seed.items() if k != "source_key"},
        "compact_context": compact_context,
        "provider_raw_compact": provider_raw or {},
        "uncertainty_reason": fn.get("uncertainty_reason"),
    }


async def upsert_mirror_circuit_function(
    session: AsyncSession,
    *,
    circuit: MirrorRegionCircuit,
    parsed_function: dict[str, Any],
    seed: dict[str, Any],
    compact_context: dict[str, Any],
    overwrite_policy: str,
    run: LlmExtractionRun | None,
    item: LlmExtractionItem | None,
    warnings: list[str],
) -> tuple[str, uuid.UUID | None]:
    if overwrite_policy == "suggest_only":
        warnings.append(f"suggest_only: not persisting function for circuit {circuit.id}")
        return "skipped", None

    if overwrite_policy == "overwrite_with_review":
        warnings.append("overwrite_with_review treated as fill_missing_only for circuit_function extraction")

    existing = await _find_existing_circuit_function(session, circuit.id, parsed_function)
    attrs = _build_attributes(
        seed=seed,
        compact_context=compact_context,
        provider_raw={"function_term_en": parsed_function.get("function_term_en")},
        fn=parsed_function,
    )

    if existing is None:
        payload = MirrorCircuitFunctionCreate(
            circuit_id=circuit.id,
            resource_id=circuit.resource_id,
            batch_id=circuit.batch_id,
            llm_run_id=run.id if run else circuit.llm_run_id,
            llm_item_id=item.id if item else circuit.llm_item_id,
            granularity_level=circuit.granularity_level,
            granularity_family=circuit.granularity_family,
            source_atlas=circuit.source_atlas,
            source_version=circuit.source_version,
            function_term_en=parsed_function.get("function_term_en"),
            function_term_cn=parsed_function.get("function_term_cn"),
            function_domain=parsed_function.get("function_domain"),
            function_role=parsed_function.get("function_role"),
            effect_type=parsed_function.get("effect_type"),
            confidence_score=parsed_function.get("confidence_score"),
            evidence_level=parsed_function.get("evidence_level"),
            description=parsed_function.get("description"),
            remark=parsed_function.get("remark"),
            attributes=attrs,
            source_db=circuit.source_atlas,
            status="active",
            confidence=parsed_function.get("confidence_score"),
            evidence_text=parsed_function.get("evidence_text") or circuit.evidence_text,
            provenance="circuit_to_functions_extraction",
            uncertainty_reason=parsed_function.get("uncertainty_reason"),
            raw_payload_json={"circuit_function": parsed_function, "seed": seed},
            normalized_payload_json={"macro_clinical_semantic_type": "circuit_function", "attributes": attrs},
        )
        row = await mirror_macro_clinical_service.create_circuit_function(session, payload)
        return "created", row.id

    updated = False
    field_map = {
        "function_term_en": parsed_function.get("function_term_en"),
        "function_term_cn": parsed_function.get("function_term_cn"),
        "function_domain": parsed_function.get("function_domain"),
        "function_role": parsed_function.get("function_role"),
        "effect_type": parsed_function.get("effect_type"),
        "confidence_score": parsed_function.get("confidence_score"),
        "evidence_level": parsed_function.get("evidence_level"),
        "description": parsed_function.get("description"),
        "remark": parsed_function.get("remark"),
        "confidence": parsed_function.get("confidence_score"),
        "evidence_text": parsed_function.get("evidence_text") or circuit.evidence_text,
        "provenance": "circuit_to_functions_extraction",
        "uncertainty_reason": parsed_function.get("uncertainty_reason"),
    }
    for attr, new_val in field_map.items():
        if _is_empty_value(getattr(existing, attr, None)) and not _is_empty_value(new_val):
            setattr(existing, attr, new_val)
            updated = True
    merged_attrs = dict(existing.attributes or {})
    if _is_empty_value(merged_attrs):
        merged_attrs = attrs
        updated = True
    else:
        for key in ("source", "seed", "compact_context"):
            if key not in merged_attrs and key in attrs:
                merged_attrs[key] = attrs[key]
                updated = True
    if updated:
        existing.attributes = merged_attrs
        if run:
            existing.llm_run_id = run.id
        if item:
            existing.llm_item_id = item.id
        await session.flush()
        await session.refresh(existing)
        return "updated", existing.id
    return "skipped", existing.id


async def load_circuits_for_request(
    session: AsyncSession,
    *,
    circuit_ids: list[uuid.UUID] | None,
    batch_id: uuid.UUID | None,
    resource_id: uuid.UUID | None,
    limit: int | None,
) -> list[MirrorRegionCircuit]:
    if circuit_ids:
        circuits: list[MirrorRegionCircuit] = []
        for cid in circuit_ids:
            circuit = await session.get(MirrorRegionCircuit, cid)
            if circuit is None:
                raise CircuitNotFoundError(str(cid))
            circuits.append(circuit)
    else:
        if batch_id is None and resource_id is None:
            raise InvalidRequestError("circuit_ids or batch_id/resource_id required")
        fetch_limit = limit if limit is not None else 500
        circuits, _ = await mirror_kg_service.list_mirror_circuits(
            session,
            batch_id=batch_id,
            resource_id=resource_id,
            limit=fetch_limit,
            offset=0,
        )
    if limit is not None and len(circuits) > limit:
        circuits = circuits[:limit]
    if not circuits:
        raise EmptyCircuitsError()
    return circuits


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def run_circuit_to_functions_extraction(
    session: AsyncSession,
    *,
    circuit_ids: list[uuid.UUID] | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    provider_name: str = "deepseek",
    model_name: str | None = None,
    dry_run: bool = True,
    overwrite_policy: str = "fill_missing_only",
    include_related_steps: bool = True,
    include_provenance: bool = True,
    prompt_template_key: str = CIRCUIT_TO_FUNCTIONS_EXTRACTION_TEMPLATE_KEY,
    prompt_overrides: dict[str, str] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    limit: int | None = None,
) -> CircuitToFunctionsResult:
    try:
        await mirror_macro_clinical_service.list_mirror_circuit_functions(session, limit=1, offset=0)
    except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError as exc:
        raise MirrorCircuitFunctionsTableMissingError(str(exc.migration_path)) from exc

    circuits = await load_circuits_for_request(
        session,
        circuit_ids=circuit_ids,
        batch_id=batch_id,
        resource_id=resource_id,
        limit=limit,
    )

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

    result = CircuitToFunctionsResult(
        circuit_count=len(circuits),
        dry_run=dry_run,
    )

    prepared: list[dict[str, Any]] = []
    for circuit in circuits:
        seed = extract_function_seed_from_circuit(circuit)
        if seed is None:
            result.skipped_count += 1
            result.skipped.append({
                "circuit_id": str(circuit.id),
                "reason": "skipped_no_function_signal",
            })
            continue
        steps = await _load_step_summary(session, circuit.id) if include_related_steps else []
        regions = await _load_region_summary(session, circuit.id)
        compact = build_compact_circuit_function_context(
            circuit,
            related_steps=steps,
            region_summary=regions,
            include_provenance=include_provenance,
        )
        system_prompt, user_prompt, prompt_json = build_circuit_to_functions_prompt(
            compact_context=compact,
            seed=seed,
            template_key=prompt_template_key,
            prompt_overrides=prompt_overrides,
        )
        prepared.append({
            "circuit": circuit,
            "seed": seed,
            "compact": compact,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "prompt_json": prompt_json,
        })

    seed_count = len(prepared)
    skipped_no_seed = result.skipped_count
    token_estimate = sum(
        _estimate_tokens(p["system_prompt"]) + _estimate_tokens(p["user_prompt"]) for p in prepared
    )
    examples = [
        {
            "circuit_id": str(p["circuit"].id),
            "seed": {k: v for k, v in p["seed"].items() if k != "source_key"},
            "compact_context": p["compact"],
        }
        for p in prepared[:3]
    ]
    result.prompt_preview = {
        "template_key": prompt_template_key,
        "circuit_count": len(circuits),
        "seed_count": seed_count,
        "skipped_no_seed_count": skipped_no_seed,
        "estimated_model_calls": seed_count,
        "estimated_input_tokens": token_estimate,
        "compact_context_enabled": True,
        "examples": examples,
    }
    result.estimated_model_calls = seed_count
    result.estimated_input_tokens = token_estimate

    if dry_run:
        result.status = "preview"
        return result

    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.circuit_to_functions,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "circuit_ids": [str(c.id) for c in circuits],
            "batch_id": str(batch_id) if batch_id else None,
            "resource_id": str(resource_id) if resource_id else None,
            "overwrite_policy": overwrite_policy,
            "include_related_steps": include_related_steps,
        },
        resource_id=resource_id or (circuits[0].resource_id if len({c.resource_id for c in circuits}) == 1 else None),
        batch_id=batch_id or (circuits[0].batch_id if len({c.batch_id for c in circuits}) == 1 else None),
        granularity_level=circuits[0].granularity_level,
        granularity_family=circuits[0].granularity_family,
        source_atlas=circuits[0].source_atlas,
        source_version=circuits[0].source_version,
        status=LlmRunStatus.running,
        input_count=len(prepared),
        temperature=temperature,
        max_tokens=max_tokens,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    provider = get_llm_provider(provider_key)

    for idx, pack in enumerate(prepared):
        circuit = pack["circuit"]
        seed = pack["seed"]
        compact = pack["compact"]
        item = LlmExtractionItem(
            run_id=run.id,
            candidate_id=None,
            resource_id=circuit.resource_id,
            batch_id=circuit.batch_id,
            task_type=LlmTaskType.circuit_to_functions,
            item_index=idx,
            input_json={
                "circuit_id": str(circuit.id),
                "seed": seed,
                "compact_context": compact,
            },
            prompt_json=pack["prompt_json"],
            status=LlmItemStatus.running,
        )
        session.add(item)
        await session.flush()

        try:
            response = await provider.complete_json(
                model=resolved_model,
                system_prompt=pack["system_prompt"],
                user_prompt=pack["user_prompt"],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            result.failed_count += 1
            result.errors.append({"circuit_id": str(circuit.id), "message": str(exc)})
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            continue

        item.raw_response_text = response.raw_text or None
        parsed_raw = response.parsed_json
        if parsed_raw is None and response.raw_text:
            try:
                parsed_raw = parse_circuit_function_extraction_response(response.raw_text)
            except Exception as exc:
                result.failed_count += 1
                result.errors.append({
                    "circuit_id": str(circuit.id),
                    "message": f"failed to parse model JSON: {exc}",
                })
                item.status = LlmItemStatus.failed
                item.error_message = str(exc)
                continue

        if parsed_raw is None:
            result.failed_count += 1
            result.errors.append({"circuit_id": str(circuit.id), "message": "empty provider response"})
            item.status = LlmItemStatus.failed
            item.error_message = "empty provider response"
            continue

        try:
            functions, norm_warnings = normalize_circuit_functions(parsed_raw, seed=seed)
            result.warnings.extend(norm_warnings)
        except Exception as exc:
            result.failed_count += 1
            result.errors.append({"circuit_id": str(circuit.id), "message": str(exc)})
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            continue

        if not functions:
            result.skipped_count += 1
            result.skipped.append({"circuit_id": str(circuit.id), "reason": "no_valid_functions_in_response"})
            item.status = LlmItemStatus.skipped
            continue

        item.parsed_response_json = parsed_raw
        item.normalized_output_json = {"circuit_functions": functions}
        item.status = LlmItemStatus.succeeded

        for fn in functions:
            try:
                action, row_id = await upsert_mirror_circuit_function(
                    session,
                    circuit=circuit,
                    parsed_function=fn,
                    seed=seed,
                    compact_context=compact,
                    overwrite_policy=overwrite_policy,
                    run=run,
                    item=item,
                    warnings=result.warnings,
                )
            except Exception as exc:
                result.failed_count += 1
                result.errors.append({"circuit_id": str(circuit.id), "message": str(exc)})
                continue
            if action == "created" and row_id:
                result.created_count += 1
                result.created_ids.append(row_id)
            elif action == "updated" and row_id:
                result.updated_count += 1
                result.updated_ids.append(row_id)
            else:
                result.skipped_count += 1
                result.skipped.append({"circuit_id": str(circuit.id), "reason": "duplicate_or_no_changes"})

    run.status = (
        LlmRunStatus.failed if result.failed_count and not result.created_count and not result.updated_count
        else LlmRunStatus.partially_succeeded if result.failed_count
        else LlmRunStatus.succeeded
    )
    run.output_count = result.created_count + result.updated_count
    run.error_count = result.failed_count
    run.finished_at = datetime.now(timezone.utc)

    if result.created_ids:
        result.created_targets.append({
            "target_type": "circuit_function",
            "target_table": "mirror_circuit_functions",
            "ids": [str(i) for i in result.created_ids],
            "count": len(result.created_ids),
        })

    if result.failed_count and (result.created_count or result.updated_count):
        result.status = "partial"
    elif result.failed_count:
        result.status = "failed"
    elif result.created_count or result.updated_count:
        result.status = "completed"
    else:
        result.status = "skipped"

    return result
