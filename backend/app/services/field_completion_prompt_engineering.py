"""Field-specific prompt selection and metadata for universal field completion (Step 10.5.6)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.models.mirror_macro_clinical import MirrorCircuitFunction
from app.schemas.llm_field_completion import TargetType
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, PromptTemplateDefaults, render_user_prompt
from app.services.prompt_metadata import (
    EXTRACTION_PROMPT_METADATA,
    PROMPT_TEMPLATE_METADATA,
    list_extraction_prompt_template_items,
    list_field_completion_prompt_template_items,
)
from app.utils.json_safety import json_dumps_safe, to_jsonable

FIELD_COMPLETION_FALLBACK_KEY = "universal_field_completion_v1"
BUNDLE_CONSISTENCY_KEY = "circuit_bundle_consistency_v1"
DEFAULT_INPUT_TOKEN_BUDGET = 6000

DETERMINISTIC_FIELD_KEYS = frozenset({
    "canonical_start_region_id",
    "canonical_end_region_id",
    "source_db",
    "status",
})
# (target_type, field_name) -> template_key
FIELD_PROMPT_KEY_MAP: dict[tuple[str, str], str] = {
    ("circuit", "name_cn"): "circuit_field_completion_name_cn_v1",
    ("circuit", "name_en"): "circuit_field_completion_name_en_v1",
    ("circuit", "circuit_class"): "circuit_field_completion_circuit_class_v1",
    ("circuit", "description"): "circuit_field_completion_description_v1",
    ("circuit_step", "step_name_cn"): "circuit_step_field_completion_step_name_cn_v1",
    ("circuit_step", "step_name_en"): "circuit_step_field_completion_step_name_en_v1",
    ("circuit_step", "role_in_circuit"): "circuit_step_field_completion_role_in_circuit_v1",
    ("circuit_function", "function_term_cn"): "circuit_function_field_completion_function_term_cn_v1",
    ("circuit_function", "function_term_en"): "circuit_function_field_completion_function_term_en_v1",
    ("circuit_function", "function_domain"): "circuit_function_field_completion_function_domain_v1",
    ("circuit_function", "function_role"): "circuit_function_field_completion_function_role_v1",
    ("circuit_function", "effect_type"): "universal_field_completion_v1",
    ("circuit_function", "description"): "universal_field_completion_v1",
    ("circuit_function", "evidence_level"): "universal_field_completion_v1",
}

CIRCUIT_FAMILY_TYPES = {
    TargetType.circuit,
    TargetType.circuit_step,
    TargetType.circuit_function,
}


def select_field_completion_prompt_key(
    target_type: TargetType | str,
    field_name: str,
    *,
    bundle_mode: bool = False,
) -> str:
    """Select prompt template key by target_type + field_name."""
    del bundle_mode  # reserved for future bundle-only prompts
    tt = target_type.value if isinstance(target_type, TargetType) else str(target_type)
    return FIELD_PROMPT_KEY_MAP.get((tt, field_name), FIELD_COMPLETION_FALLBACK_KEY)


def resolve_prompt_template(
    template_key: str,
    prompt_overrides: dict[str, str] | None = None,
) -> PromptTemplateDefaults:
    """Load template; apply per-request user_prompt override if provided."""
    base = DEFAULT_TEMPLATES.get(template_key)
    if base is None:
        base = DEFAULT_TEMPLATES[FIELD_COMPLETION_FALLBACK_KEY]
    override_text = (prompt_overrides or {}).get(template_key)
    if not override_text:
        return base
    return PromptTemplateDefaults(
        template_key=base.template_key,
        task_type=base.task_type,
        version=base.version,
        name=base.name,
        description=base.description,
        system_prompt=base.system_prompt,
        user_prompt_template=override_text,
        output_schema_json=base.output_schema_json,
    )


def estimate_prompt_tokens(text_or_payload: str | dict[str, Any] | list[Any]) -> int:
    """Conservative token estimate without external tokenizer."""
    if isinstance(text_or_payload, (dict, list)):
        text = json_dumps_safe(text_or_payload, ensure_ascii=False)
    else:
        text = str(text_or_payload)
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = len(text) - ascii_chars
    return max(1, int(ascii_chars / 4 + cjk_chars / 2))


def _short_id(value: Any) -> str:
    s = str(value)
    return s if len(s) <= 12 else f"{s[:10]}…"


def _clip(text: Any, limit: int = 240) -> str | None:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    return s if len(s) <= limit else s[: limit - 1] + "…"


def build_compact_field_context(
    target: Any,
    field_name: str,
    *,
    bundle_context: dict[str, Any] | None = None,
    canonical_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Minimal context for one field — no full attributes/raw JSON."""
    bundle_context = bundle_context or {}
    canonical_resolution = canonical_resolution or {}
    ctx: dict[str, Any] = {
        "id": _short_id(getattr(target, "id", "")),
        "field": field_name,
    }
    if isinstance(target, MirrorCircuitFunction):
        ctx["circuit_id"] = _short_id(getattr(target, "circuit_id", None))
        for key in (
            "function_term_en", "function_term_cn", "function_domain",
            "function_role", "effect_type", "confidence_score", "evidence_level",
            "description", "source_db", "status",
        ):
            val = getattr(target, key, None)
            if val is not None and str(val).strip():
                ctx[key] = _clip(val, 120 if key in ("description",) else 80)
        ev = getattr(target, "evidence_text", None)
        if ev:
            ctx["evidence_text"] = _clip(ev, 180)
        overlay = {}
        attrs = getattr(target, "attributes", None)
        if isinstance(attrs, dict):
            overlay = dict(attrs.get("formal_field_overlay") or {})
        if overlay:
            ctx["current_overlay"] = {k: _clip(v, 80) for k, v in list(overlay.items())[:6]}
        circuit = bundle_context.get("circuit") if isinstance(bundle_context.get("circuit"), dict) else {}
        if circuit:
            ctx["circuit_summary"] = {
                "name_en": _clip(circuit.get("circuit_name") or circuit.get("name_en"), 80),
                "circuit_class": _clip(circuit.get("circuit_type") or circuit.get("circuit_class"), 60),
            }
        steps = bundle_context.get("circuit_steps") or []
        if steps:
            ctx["step_summary"] = [
                {
                    "step_no": s.get("step_order"),
                    "name": _clip(s.get("step_name"), 60),
                    "role": _clip(s.get("role"), 40),
                }
                for s in steps[:5]
                if isinstance(s, dict)
            ]
        return to_jsonable(ctx)
    name_en = getattr(target, "circuit_name", None) or getattr(target, "step_name", None)
    if name_en:
        ctx["name_en"] = _clip(name_en, 120)
    circuit_class = getattr(target, "circuit_type", None)
    if circuit_class:
        ctx["circuit_class"] = _clip(circuit_class, 80)
    if canonical_resolution.get("start_region_id") or canonical_resolution.get("start_region_label"):
        ctx["start_region"] = {
            "id": _short_id(canonical_resolution.get("start_region_id")),
            "label": canonical_resolution.get("start_region_label"),
        }
    if canonical_resolution.get("end_region_id") or canonical_resolution.get("end_region_label"):
        ctx["end_region"] = {
            "id": _short_id(canonical_resolution.get("end_region_id")),
            "label": canonical_resolution.get("end_region_label"),
        }
    fn = getattr(target, "function_association", None)
    if fn:
        ctx["function"] = _clip(fn, 120)
    ev = getattr(target, "evidence_text", None)
    if ev:
        ctx["evidence"] = _clip(ev, 180)
    unc = getattr(target, "uncertainty_reason", None)
    if unc:
        ctx["uncertainty"] = _clip(unc, 120)
    steps = bundle_context.get("circuit_steps") or []
    if steps and field_name in ("circuit_class", "description", "name_cn"):
        ctx["steps_summary"] = [
            {
                "step_no": s.get("step_order"),
                "name": _clip(s.get("step_name"), 60),
            }
            for s in steps[:6]
            if isinstance(s, dict)
        ]
    return to_jsonable(ctx)


def pack_target_batches(
    records: list[dict[str, Any]],
    *,
    system_prompt: str,
    template_body: str,
    token_budget: int = DEFAULT_INPUT_TOKEN_BUDGET,
) -> list[list[dict[str, Any]]]:
    """Split records into packs that fit token budget (not a hard target cap)."""
    if not records:
        return []
    base_tokens = estimate_prompt_tokens(system_prompt) + estimate_prompt_tokens(template_body) + 32
    packs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = base_tokens
    for rec in records:
        rec_tokens = estimate_prompt_tokens(rec)
        if current and current_tokens + rec_tokens > token_budget:
            packs.append(current)
            current = []
            current_tokens = base_tokens
        current.append(rec)
        current_tokens += rec_tokens
    if current:
        packs.append(current)
    return packs


def build_batch_field_prompt(
    entry,
    field_name: str,
    records: list[dict[str, Any]],
    request,
    *,
    prompt_overrides: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any], str]:
    prompt_key = select_field_completion_prompt_key(request.target_type, field_name)
    tpl = resolve_prompt_template(prompt_key, prompt_overrides)
    payload = {
        "task": f"complete field {field_name} for multiple {entry.target_type.value} records",
        "field_name": field_name,
        "overwrite_policy": request.overwrite_policy.value,
        "records": records,
        "output_note": "Return field_updates with target_id for each record.",
    }
    override_text = (prompt_overrides or {}).get(prompt_key)
    if override_text:
        user_prompt = override_text + "\n\n" + json_dumps_safe(payload, ensure_ascii=False)
    else:
        user_prompt = (
            tpl.system_prompt[:120] + "\n\n"
            + f"Batch complete formal field `{field_name}` for records below. Output JSON only.\n"
            + json_dumps_safe(payload, ensure_ascii=False)
        )
    prompt_json = to_jsonable({
        "template_key": prompt_key,
        "field_name": field_name,
        "batch_size": len(records),
        "compact_context": True,
    })
    return tpl.system_prompt, user_prompt, prompt_json, prompt_key

