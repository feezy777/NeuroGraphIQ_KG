"""Consolidated prompt template metadata (display names, categories, lookups).

Previously spread across:
- llm_extraction_prompt_engineering.py  → EXTRACTION_PROMPT_DISPLAY_NAMES (4 entries)
- field_completion_prompt_engineering.py → EXTRACTION_PROMPT_METADATA (6 entries, 4 duplicated)
                                            PROMPT_TEMPLATE_METADATA (15 entries)

All display_name / metadata lookups now live here so the two service modules
stay focused on their actual logic (pair packing, token estimation, etc.).
"""

from __future__ import annotations

from typing import Any

from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES

# ──────────────────────────────────────────────────────────────────────────────
# Extraction prompt metadata (connection / circuit / projection → functions)
# ──────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT_METADATA: list[dict[str, str | None]] = [
    {
        "key": "same_granularity_connection_completion_v1",
        "title": "Same-granularity connection completion v1",
        "display_name": "同粒度脑区连接提取（Same-granularity Brain Region Projection Extraction）",
        "category": "extraction",
        "target_type": "projection",
        "field_name": None,
        "description": "Extract mirror_region_connections (projection semantics) from same-granularity candidate pairs.",
    },
    {
        "key": "projection_to_functions_v1",
        "title": "Projection to functions v1 (macro_clinical)",
        "display_name": "连接功能抽取（Projection Function Extraction）",
        "category": "extraction",
        "target_type": "projection_function",
        "field_name": None,
        "description": "Extract mirror_projection_functions from mirror_region_connections.",
    },
    {
        "key": "connection_with_function",
        "title": "Connection with function composite workflow",
        "display_name": "连接与连接功能组合抽取（Projection and Projection Function Composite Extraction）",
        "category": "composite",
        "target_type": "composite",
        "field_name": None,
        "description": "Composite workflow: extract connections then projection functions.",
    },
    {
        "key": "circuit_to_functions_extraction_v1",
        "title": "Circuit to functions extraction v1 (macro_clinical)",
        "display_name": "回路功能抽取（Circuit-to-Functions Extraction）",
        "category": "extraction",
        "target_type": "circuit",
        "field_name": None,
        "description": "Extract mirror_circuit_functions from mirror_region_circuits (Step 10.6.3).",
    },
    {
        "key": "circuit_to_steps_v1",
        "title": "Circuit to steps v1 (macro_clinical)",
        "display_name": "回路步骤抽取（Circuit-to-Steps Extraction）",
        "category": "extraction",
        "target_type": "circuit",
        "field_name": None,
        "description": "Extract circuit steps from regions-to-circuits result.",
    },
    {
        "key": "same_granularity_circuit_completion_v1",
        "title": "Same-granularity circuit completion v1",
        "display_name": "回路抽取（Circuit Extraction）",
        "category": "extraction",
        "target_type": "circuit",
        "field_name": None,
        "description": "Extract candidate circuits from region projections within same granularity.",
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# Field-completion prompt metadata
# ──────────────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE_METADATA: list[dict[str, str | None]] = [
    {
        "key": "circuit_bundle_consistency_v1",
        "title": "Circuit bundle consistency",
        "display_name": "回路组合一致性检查（Circuit Bundle Consistency Check）",
        "target_type": "circuit",
        "field_name": None,
    },
    {
        "key": "circuit_field_completion_name_cn_v1",
        "title": "Circuit name_cn completion",
        "display_name": "回路中文名补全（Circuit Chinese Name Completion）",
        "target_type": "circuit",
        "field_name": "name_cn",
    },
    {
        "key": "circuit_field_completion_name_en_v1",
        "title": "Circuit name_en completion",
        "display_name": "回路英文名补全（Circuit English Name Completion）",
        "target_type": "circuit",
        "field_name": "name_en",
    },
    {
        "key": "circuit_field_completion_circuit_class_v1",
        "title": "Circuit circuit_class completion",
        "display_name": None,
        "target_type": "circuit",
        "field_name": "circuit_class",
    },
    {
        "key": "circuit_field_completion_description_v1",
        "title": "Circuit description completion",
        "display_name": None,
        "target_type": "circuit",
        "field_name": "description",
    },
    {
        "key": "circuit_step_field_completion_step_name_cn_v1",
        "title": "Circuit step step_name_cn completion",
        "display_name": None,
        "target_type": "circuit_step",
        "field_name": "step_name_cn",
    },
    {
        "key": "circuit_step_field_completion_step_name_en_v1",
        "title": "Circuit step step_name_en completion",
        "display_name": None,
        "target_type": "circuit_step",
        "field_name": "step_name_en",
    },
    {
        "key": "circuit_step_field_completion_role_in_circuit_v1",
        "title": "Circuit step role_in_circuit completion",
        "display_name": None,
        "target_type": "circuit_step",
        "field_name": "role_in_circuit",
    },
    {
        "key": "circuit_function_field_completion_function_term_cn_v1",
        "title": "Circuit function function_term_cn completion",
        "display_name": "回路功能中文术语补全（Circuit Function Chinese Term Completion）",
        "target_type": "circuit_function",
        "field_name": "function_term_cn",
    },
    {
        "key": "circuit_function_field_completion_function_term_en_v1",
        "title": "Circuit function function_term_en completion",
        "display_name": "回路功能英文术语补全（Circuit Function English Term Completion）",
        "target_type": "circuit_function",
        "field_name": "function_term_en",
    },
    {
        "key": "circuit_function_field_completion_function_domain_v1",
        "title": "Circuit function function_domain completion",
        "display_name": "回路功能领域补全（Circuit Function Domain Completion）",
        "target_type": "circuit_function",
        "field_name": "function_domain",
    },
    {
        "key": "circuit_function_field_completion_function_role_v1",
        "title": "Circuit function function_role completion",
        "display_name": "回路功能角色补全（Circuit Function Role Completion）",
        "target_type": "circuit_function",
        "field_name": "function_role",
    },
    {
        "key": "universal_field_completion_v1",
        "title": "Universal field completion fallback",
        "display_name": None,
        "target_type": None,
        "field_name": None,
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Lookup helpers
# ──────────────────────────────────────────────────────────────────────────────

def prompt_display_name(prompt_key: str) -> str | None:
    """Return a human-readable Chinese+English display name for *any* prompt key.

    Searches extraction metadata first, then field-completion metadata.
    Single source of truth — no more duplicated display-name dictionaries.
    """
    # Check extraction metadata
    for meta in EXTRACTION_PROMPT_METADATA:
        if meta["key"] == prompt_key and meta.get("display_name"):
            return meta["display_name"]
    # Check field-completion metadata
    for meta in PROMPT_TEMPLATE_METADATA:
        if meta["key"] == prompt_key and meta.get("display_name"):
            return meta["display_name"]
    # Fallback: check DEFAULT_TEMPLATES for .name attribute
    tpl = DEFAULT_TEMPLATES.get(prompt_key)
    if tpl is not None:
        return tpl.description or tpl.name
    return None


def list_extraction_prompt_template_items() -> list[dict[str, str | None]]:
    """Return extraction-category prompt templates with display_name, template, system_prompt.

    Used by the /api/llm-extraction/prompt-templates endpoint.
    """
    items: list[dict[str, str | None]] = []
    for meta in EXTRACTION_PROMPT_METADATA:
        key = str(meta["key"])
        tpl = DEFAULT_TEMPLATES.get(key)
        if tpl is None:
            if meta.get("category") == "composite":
                items.append({
                    "key": key,
                    "title": str(meta["title"]),
                    "display_name": meta.get("display_name"),
                    "category": meta.get("category", "extraction"),
                    "target_type": meta.get("target_type"),
                    "field_name": meta.get("field_name"),
                    "description": meta.get("description"),
                    "template": "",
                    "system_prompt": "",
                })
            continue
        items.append({
            "key": key,
            "title": str(meta["title"]),
            "display_name": meta.get("display_name"),
            "category": meta.get("category", "extraction"),
            "target_type": meta.get("target_type"),
            "field_name": meta.get("field_name"),
            "description": meta.get("description"),
            "template": tpl.user_prompt_template,
            "system_prompt": tpl.system_prompt,
        })
    return items


def list_field_completion_prompt_template_items() -> list[dict[str, str | None]]:
    """Return field-completion prompt templates with display_name, template, system_prompt.

    Used by the /api/llm-extraction/field-completion/prompt-templates endpoint.
    """
    items: list[dict[str, str | None]] = []
    for meta in PROMPT_TEMPLATE_METADATA:
        key = str(meta["key"])
        tpl = DEFAULT_TEMPLATES.get(key)
        if tpl is None:
            continue
        items.append({
            "key": key,
            "title": str(meta["title"]),
            "display_name": meta.get("display_name"),
            "target_type": meta.get("target_type"),
            "field_name": meta.get("field_name"),
            "template": tpl.user_prompt_template,
            "system_prompt": tpl.system_prompt,
        })
    return items
