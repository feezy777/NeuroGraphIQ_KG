"""Target-type registry for universal field completion (Step 10.3 / 10.4.2).

Step 10.4.2: All enrichable_fields / required_fields now use real NeuroGraphIQ_KG_V3
formal field names (name_cn, circuit_class, step_no, function_term_cn, …).

Write strategy per formal field:
  - formal_to_mirror  → formal field maps to a real Mirror ORM column (direct write)
  - overlay_field_names → no Mirror column; value is written to
        normalized_payload_json["formal_field_overlay"][field_name]
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.utils.json_safety import to_jsonable

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import (
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_macro_clinical import (
    MirrorCircuitFunction,
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorProjectionFunction,
)
from app.schemas.llm_field_completion import TargetType

# Fields that must never be written by field completion
GLOBAL_READONLY_FIELDS = frozenset({
    "id",
    "created_at",
    "updated_at",
    "promotion_status",
    "review_status",
    "mirror_status",
    "llm_run_id",
    "llm_item_id",
    "batch_id",
    "resource_id",
})


FORMAL_DB = "NeuroGraphIQ_KG_V3"
FORMAL_READONLY_FIELDS = frozenset({"id", "created_at", "updated_at"})


@dataclass(frozen=True)
class TargetTypeRegistryEntry:
    target_type: TargetType
    mirror_table: str
    model_class: type
    supported: bool

    # Formal KG database info (NeuroGraphIQ_KG_V3)
    formal_schema: str = ""
    formal_table: str = ""
    formal_database: str = FORMAL_DB
    # Kept for backwards compatibility / display
    final_table: str = ""

    # All formal field names accepted in prompts / validation
    allowed_fields: tuple[str, ...] = ()
    # All formal field names allowed for LLM completion
    enrichable_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    readonly_fields: tuple[str, ...] = ("id", "created_at", "updated_at")

    # Maps formal_field_name → mirror ORM column name for direct writes.
    # If a formal field name equals the mirror column name, map it to itself.
    formal_to_mirror: dict[str, str] = field(default_factory=dict)

    # Formal field names that have NO mirror column.
    # Values are written to normalized_payload_json["formal_field_overlay"][field_name].
    overlay_field_names: tuple[str, ...] = ()

    # Resolver key per formal field — never sent to DeepSeek.
    deterministic_fields: dict[str, str] = field(default_factory=dict)

    # Legacy alias map {alias_or_old_name: formal_field_name} — kept for backward compat
    field_aliases: dict[str, str] = field(default_factory=dict)

    unsupported_reason: str | None = None

    @property
    def direct_write_fields(self) -> tuple[str, ...]:
        overlay = set(self.overlay_field_names)
        return tuple(
            f for f in self.formal_to_mirror
            if f not in overlay and f not in self.readonly_fields
        )

    @property
    def overlay_write_fields(self) -> tuple[str, ...]:
        return self.overlay_field_names


def _aliases(*pairs: tuple[str, str]) -> dict[str, str]:
    return dict(pairs)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: dict[TargetType, TargetTypeRegistryEntry] = {
    # ------------------------------------------------------------------ #
    # candidate_region — uses its own CandidateBrainRegion model          #
    # ------------------------------------------------------------------ #
    TargetType.candidate_region: TargetTypeRegistryEntry(
        target_type=TargetType.candidate_region,
        mirror_table="candidate_brain_regions",
        formal_schema="macro_clinical",
        formal_table="region",
        final_table="macro_clinical.region",
        model_class=CandidateBrainRegion,
        supported=True,
        enrichable_fields=("cn_name", "en_name", "std_name", "laterality", "region_base_name"),
        required_fields=("en_name",),
        formal_to_mirror={
            "cn_name": "cn_name",
            "en_name": "en_name",
            "std_name": "std_name",
            "laterality": "laterality",
            "region_base_name": "region_base_name",
        },
        overlay_field_names=(),
        field_aliases=_aliases(
            ("evidence_summary", "evidence_text"),
            ("description", "region_base_name"),
            ("name_cn", "cn_name"),
            ("name_en", "en_name"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # projection → macro_clinical.projection                              #
    # Mirror model: MirrorRegionConnection                                 #
    # Direct-write cols: connection_type, directionality, strength,       #
    #                    modality, confidence, evidence_text               #
    # Overlay fields: name_en, name_cn, description, remark, …           #
    # ------------------------------------------------------------------ #
    TargetType.projection: TargetTypeRegistryEntry(
        target_type=TargetType.projection,
        mirror_table="mirror_region_connections",
        formal_schema="macro_clinical",
        formal_table="projection",
        final_table="macro_clinical.projection",
        model_class=MirrorRegionConnection,
        supported=True,
        enrichable_fields=(
            "projection_type",   # formal name; mirror col: connection_type
            "directionality",    # direct
            "modality",          # direct
            "strength_score",    # formal; mirror col: strength
            "confidence_score",  # formal; mirror col: confidence
            "evidence_text",     # direct (mirror col same name)
            "name_en",           # overlay
            "name_cn",           # overlay
            "description",       # overlay
            "remark",            # overlay
            "source_db",         # overlay
            "status",            # overlay
        ),
        required_fields=("projection_type", "directionality"),
        formal_to_mirror={
            "projection_type": "connection_type",
            "directionality": "directionality",
            "modality": "modality",
            "strength_score": "strength",
            "confidence_score": "confidence",
            "evidence_text": "evidence_text",
        },
        overlay_field_names=(
            "name_en", "name_cn", "description", "remark",
            "source_db", "status", "evidence_level",
        ),
        field_aliases=_aliases(
            ("connection_type", "projection_type"),  # legacy mirror field accepted
            ("strength", "strength_score"),
            ("confidence", "confidence_score"),
            ("evidence_summary", "evidence_text"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # region_function → macro_clinical.region_function                    #
    # Mirror model: MirrorRegionFunction                                   #
    # Direct: function_term (→ function_term_en), function_category,      #
    #         relation_type, confidence, evidence_text                     #
    # Overlay: function_term_cn, function_domain, function_role, …       #
    # ------------------------------------------------------------------ #
    TargetType.region_function: TargetTypeRegistryEntry(
        target_type=TargetType.region_function,
        mirror_table="mirror_region_functions",
        formal_schema="macro_clinical",
        formal_table="region_function",
        final_table="macro_clinical.region_function",
        model_class=MirrorRegionFunction,
        supported=True,
        enrichable_fields=(
            "function_term_en",   # formal; mirror col: function_term
            "function_term_cn",   # overlay
            "function_domain",    # overlay
            "function_role",      # overlay
            "effect_type",        # overlay
            "confidence_score",   # formal; mirror col: confidence
            "evidence_text",      # direct
            "description",        # overlay
            "remark",             # overlay
            "source_db",          # overlay
            "status",             # overlay
        ),
        required_fields=("function_term_en",),
        formal_to_mirror={
            "function_term_en": "function_term",
            "confidence_score": "confidence",
            "evidence_text": "evidence_text",
        },
        overlay_field_names=(
            "function_term_cn", "function_domain", "function_role",
            "effect_type", "description", "remark", "source_db", "status",
        ),
        field_aliases=_aliases(
            ("function_term", "function_term_en"),      # legacy
            ("function_category", "function_term_en"),  # rough legacy compat
            ("evidence_summary", "evidence_text"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # circuit → macro_clinical.circuit                                     #
    # Mirror model: MirrorRegionCircuit                                    #
    # Direct: circuit_name (→ name_en), circuit_type (→ circuit_class),   #
    #         description, evidence_text, confidence                       #
    # Overlay: name_cn, remark, attributes, source_db, status, …         #
    # ------------------------------------------------------------------ #
    TargetType.circuit: TargetTypeRegistryEntry(
        target_type=TargetType.circuit,
        mirror_table="mirror_region_circuits",
        formal_schema="macro_clinical",
        formal_table="circuit",
        final_table="macro_clinical.circuit",
        model_class=MirrorRegionCircuit,
        supported=True,
        allowed_fields=(
            "id", "species_id", "canonical_start_region_id", "canonical_end_region_id",
            "data_source_id", "primary_evidence_id", "external_code",
            "name_en", "name_cn", "circuit_class", "description", "remark",
            "attributes", "source_db", "status", "created_at", "updated_at",
        ),
        enrichable_fields=(
            "species_id", "canonical_start_region_id", "canonical_end_region_id",
            "data_source_id", "primary_evidence_id", "external_code",
            "name_en",           # formal; mirror col: circuit_name
            "name_cn",           # overlay
            "circuit_class",     # formal; mirror col: circuit_type
            "description",       # direct (same name)
            "remark",            # overlay
            "attributes",        # overlay
            "source_db",         # overlay
            "status",            # overlay
        ),
        required_fields=("name_en", "name_cn", "circuit_class", "status"),
        readonly_fields=("id", "created_at", "updated_at"),
        formal_to_mirror={
            "name_en": "circuit_name",
            "circuit_class": "circuit_type",
            "description": "description",
            "confidence_score": "confidence",
            "evidence_text": "evidence_text",
        },
        overlay_field_names=(
            "name_cn", "remark", "attributes", "source_db", "status",
            "canonical_start_region_id", "canonical_end_region_id",
            "species_id", "data_source_id", "primary_evidence_id", "external_code",
        ),
        field_aliases=_aliases(
            ("circuit_name", "name_en"),    # legacy mirror field accepted
            ("circuit_type", "circuit_class"),
            ("evidence_summary", "evidence_text"),
        ),
        deterministic_fields={
            "canonical_start_region_id": "canonical_region_resolver",
            "canonical_end_region_id": "canonical_region_resolver",
            "source_db": "source_db_resolver",
            "status": "status_default_resolver",
        },
    ),

    # ------------------------------------------------------------------ #
    # circuit_step → macro_clinical.circuit_step                          #
    # Mirror model: MirrorCircuitStep                                      #
    # Direct: step_name (→ step_name_en), step_order (→ step_no int),     #
    #         description, evidence_text, confidence                       #
    # Overlay: step_name_cn, role_in_circuit, step_no, …                  #
    # ------------------------------------------------------------------ #
    TargetType.circuit_step: TargetTypeRegistryEntry(
        target_type=TargetType.circuit_step,
        mirror_table="mirror_circuit_steps",
        formal_schema="macro_clinical",
        formal_table="circuit_step",
        final_table="macro_clinical.circuit_step",
        model_class=MirrorCircuitStep,
        supported=True,
        enrichable_fields=(
            "step_name_en",    # formal; mirror col: step_name
            "step_name_cn",    # overlay
            "step_no",         # overlay (mirror has step_order, type differs)
            "role_in_circuit", # overlay (mirror has 'role')
            "description",     # direct
            "remark",          # overlay
            "source_db",       # overlay
            "status",          # overlay
        ),
        required_fields=("step_name_en", "step_no"),
        formal_to_mirror={
            "step_name_en": "step_name",
            "description": "description",
            "confidence_score": "confidence",
            "evidence_text": "evidence_text",
        },
        overlay_field_names=(
            "step_name_cn", "step_no", "role_in_circuit",
            "remark", "source_db", "status",
        ),
        field_aliases=_aliases(
            ("step_name", "step_name_en"),     # legacy
            ("step_order", "step_no"),
            ("role", "role_in_circuit"),
            ("evidence_summary", "evidence_text"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # projection_function → macro_clinical.projection_function            #
    # Mirror model: MirrorProjectionFunction                               #
    # Direct: function_term (→ function_term_en), confidence, evidence_text #
    # Overlay: function_term_cn, function_domain, function_role, …        #
    # ------------------------------------------------------------------ #
    TargetType.projection_function: TargetTypeRegistryEntry(
        target_type=TargetType.projection_function,
        mirror_table="mirror_projection_functions",
        formal_schema="macro_clinical",
        formal_table="projection_function",
        final_table="macro_clinical.projection_function",
        model_class=MirrorProjectionFunction,
        supported=True,
        enrichable_fields=(
            "function_term_en",  # formal; mirror col: function_term
            "function_term_cn",  # overlay
            "function_domain",   # overlay
            "function_role",     # overlay
            "effect_type",       # overlay
            "confidence_score",  # formal; mirror col: confidence
            "evidence_text",     # direct
            "description",       # overlay
            "remark",            # overlay
            "source_db",         # overlay
            "status",            # overlay
        ),
        required_fields=("function_term_en", "function_term_cn"),
        formal_to_mirror={
            "function_term_en": "function_term",
            "confidence_score": "confidence",
            "evidence_text": "evidence_text",
        },
        overlay_field_names=(
            "function_term_cn", "function_domain", "function_role",
            "effect_type", "description", "remark", "source_db", "status",
        ),
        field_aliases=_aliases(
            ("function_term", "function_term_en"),   # legacy mirror field name
            ("evidence_summary", "evidence_text"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # circuit_function → macro_clinical.circuit_function                   #
    # Mirror model: MirrorCircuitFunction                                  #
    # Direct: function_term_en/cn, function_domain, function_role,       #
    #         effect_type, confidence_score, evidence_level, description,  #
    #         remark, source_db, status                                    #
    # Overlay: attributes (extensions only)                                #
    # ------------------------------------------------------------------ #
    TargetType.circuit_function: TargetTypeRegistryEntry(
        target_type=TargetType.circuit_function,
        mirror_table="mirror_circuit_functions",
        formal_schema="macro_clinical",
        formal_table="circuit_function",
        final_table="macro_clinical.circuit_function",
        model_class=MirrorCircuitFunction,
        supported=True,
        allowed_fields=(
            "id", "circuit_id",
            "function_term_en", "function_term_cn",
            "function_domain", "function_role", "effect_type",
            "confidence_score", "evidence_level",
            "description", "remark", "attributes",
            "source_db", "status",
            "created_at", "updated_at",
        ),
        enrichable_fields=(
            "function_term_en", "function_term_cn",
            "function_domain", "function_role", "effect_type",
            "confidence_score", "evidence_level",
            "description", "remark",
            "source_db", "status",
        ),
        required_fields=("function_term_en", "function_term_cn", "status"),
        readonly_fields=("id", "circuit_id", "created_at", "updated_at"),
        formal_to_mirror={
            "function_term_en": "function_term_en",
            "function_term_cn": "function_term_cn",
            "function_domain": "function_domain",
            "function_role": "function_role",
            "effect_type": "effect_type",
            "confidence_score": "confidence_score",
            "evidence_level": "evidence_level",
            "description": "description",
            "remark": "remark",
            "source_db": "source_db",
            "status": "status",
            "evidence_text": "evidence_text",
            "confidence": "confidence",
        },
        overlay_field_names=("attributes",),
        field_aliases=_aliases(
            ("evidence_summary", "evidence_text"),
        ),
        deterministic_fields={
            "source_db": "source_db_resolver",
            "status": "status_default_resolver",
        },
    ),

    # ------------------------------------------------------------------ #
    # circuit_projection_membership                                        #
    # ------------------------------------------------------------------ #
    TargetType.circuit_projection_membership: TargetTypeRegistryEntry(
        target_type=TargetType.circuit_projection_membership,
        mirror_table="mirror_circuit_projection_memberships",
        formal_schema="",
        formal_table="",
        final_table="",
        model_class=MirrorCircuitProjectionMembership,
        supported=True,
        enrichable_fields=("role_in_circuit", "evidence_text", "confidence_score", "verification_status"),
        required_fields=("circuit_id", "projection_id"),
        formal_to_mirror={
            "role_in_circuit": "role_in_circuit",
            "evidence_text": "evidence_text",
            "confidence_score": "confidence",
            "verification_status": "verification_status",
        },
        overlay_field_names=(),
        field_aliases=_aliases(
            ("membership_role", "role_in_circuit"),
            ("confidence", "confidence_score"),
            ("evidence_summary", "evidence_text"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # triple                                                               #
    # ------------------------------------------------------------------ #
    TargetType.triple: TargetTypeRegistryEntry(
        target_type=TargetType.triple,
        mirror_table="mirror_kg_triples",
        formal_schema="",
        formal_table="",
        final_table="",
        model_class=MirrorKgTriple,
        supported=True,
        enrichable_fields=("confidence_score", "evidence_text"),
        required_fields=("subject_label", "predicate", "object_label"),
        formal_to_mirror={
            "confidence_score": "confidence",
            "evidence_text": "evidence_text",
        },
        overlay_field_names=(),
        field_aliases=_aliases(
            ("confidence", "confidence_score"),
            ("evidence_summary", "evidence_text"),
        ),
    ),

    # ------------------------------------------------------------------ #
    # evidence                                                             #
    # ------------------------------------------------------------------ #
    TargetType.evidence: TargetTypeRegistryEntry(
        target_type=TargetType.evidence,
        mirror_table="mirror_evidence_records",
        formal_schema="",
        formal_table="",
        final_table="",
        model_class=MirrorEvidenceRecord,
        supported=True,
        enrichable_fields=("source_reference_text", "confidence_score", "citation_json"),
        required_fields=("evidence_text", "evidence_target_type", "evidence_target_id"),
        formal_to_mirror={
            "source_reference_text": "source_reference_text",
            "confidence_score": "confidence",
            "citation_json": "citation_json",
        },
        overlay_field_names=(),
        field_aliases=_aliases(
            ("confidence", "confidence_score"),
            ("source_document", "source_document_id"),
            ("source_location", "source_reference_text"),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class UnsupportedTargetTypeError(Exception):
    def __init__(self, target_type: str):
        self.target_type = target_type
        super().__init__(f"unsupported target_type: {target_type}")


class TargetTypeNotImplementedError(Exception):
    def __init__(self, target_type: str, reason: str):
        self.target_type = target_type
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def get_allowed_fields(entry: TargetTypeRegistryEntry) -> tuple[str, ...]:
    if entry.allowed_fields:
        return entry.allowed_fields
    base = set(entry.enrichable_fields) | set(entry.required_fields) | set(entry.readonly_fields)
    return tuple(sorted(base))


def get_registry_entry(target_type: TargetType | str) -> TargetTypeRegistryEntry:
    if isinstance(target_type, str):
        try:
            target_type = TargetType(target_type)
        except ValueError as exc:
            raise UnsupportedTargetTypeError(target_type) from exc
    entry = REGISTRY.get(target_type)
    if entry is None:
        raise UnsupportedTargetTypeError(str(target_type))
    if not entry.supported:
        raise TargetTypeNotImplementedError(str(target_type), entry.unsupported_reason or "not supported")
    return entry


def resolve_field_name(entry: TargetTypeRegistryEntry, field_name: str) -> str | None:
    """Map incoming field name (formal or legacy alias) to canonical formal field name.

    Returns None when the field is globally readonly or not in enrichable/required.
    """
    if field_name in GLOBAL_READONLY_FIELDS:
        return None
    # Apply legacy alias first
    if field_name in entry.field_aliases:
        field_name = entry.field_aliases[field_name]
    allowed = set(entry.enrichable_fields) | set(entry.required_fields)
    if field_name in allowed:
        return field_name
    return None


def is_overlay_field(entry: TargetTypeRegistryEntry, field_name: str) -> bool:
    """True when the formal field has no direct Mirror ORM column."""
    return field_name in set(entry.overlay_field_names)


def get_mirror_column(entry: TargetTypeRegistryEntry, formal_field: str) -> str | None:
    """Return the Mirror ORM column name for a formal field, or None if overlay-only."""
    if is_overlay_field(entry, formal_field):
        return None
    return entry.formal_to_mirror.get(formal_field, formal_field)


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def get_overlay_value(obj: Any, field_name: str) -> Any:
    """Read a formal field from JSONB overlay (normalized_payload, attributes, etc.)."""
    for attr_name in ("attributes", "normalized_payload_json", "raw_payload_json"):
        payload = getattr(obj, attr_name, None)
        if isinstance(payload, dict):
            overlay = payload.get("formal_field_overlay")
            if isinstance(overlay, dict) and field_name in overlay:
                return overlay[field_name]
    return None


def get_attributes_dict(obj: Any) -> dict[str, Any] | None:
    """Return attributes dict if the model has an attributes column, else None."""
    if not hasattr(obj, "attributes"):
        return None
    val = getattr(obj, "attributes", None)
    if val is None:
        return {}
    if isinstance(val, dict):
        return dict(val)
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {"_raw_attributes": val}
    return {}


def is_deterministic_field(entry: TargetTypeRegistryEntry, field_name: str) -> bool:
    return field_name in entry.deterministic_fields


def split_deterministic_and_llm_fields(
    entry: TargetTypeRegistryEntry,
    fields: list[str],
) -> tuple[list[str], list[str]]:
    deterministic = [f for f in fields if is_deterministic_field(entry, f)]
    llm_fields = [f for f in fields if not is_deterministic_field(entry, f)]
    return deterministic, llm_fields


def write_to_overlay(
    obj: Any,
    field_name: str,
    value: Any,
    *,
    run_id: uuid.UUID | str | None = None,
    confidence: float | None = None,
    source: str = "llm_field_completion",
    meta_extra: dict[str, Any] | None = None,
) -> bool:
    """Write formal field to overlay JSONB (attributes or normalized_payload_json).

    Returns True if a writable JSONB/attributes column was updated.
    Uses flag_modified so SQLAlchemy persists JSONB mutations.
    """
    from sqlalchemy.orm.attributes import flag_modified

    now_iso = datetime.now(timezone.utc).isoformat()
    safe_value = to_jsonable(value)
    meta_entry: dict[str, Any] = {
        "source": source,
        "updated_at": now_iso,
    }
    if run_id is not None:
        meta_entry["run_id"] = str(run_id)
    if confidence is not None:
        meta_entry["confidence"] = to_jsonable(confidence)
    if meta_extra:
        meta_entry.update(to_jsonable(meta_extra))

    # Prefer dedicated attributes column when present
    attrs = get_attributes_dict(obj)
    if attrs is not None:
        overlay = dict(attrs.get("formal_field_overlay") or {})
        overlay_meta = dict(attrs.get("formal_field_overlay_meta") or {})
        overlay[field_name] = safe_value
        overlay_meta[field_name] = meta_entry
        new_attrs = dict(attrs)
        new_attrs["formal_field_overlay"] = overlay
        new_attrs["formal_field_overlay_meta"] = overlay_meta
        setattr(obj, "attributes", to_jsonable(new_attrs))
        flag_modified(obj, "attributes")
        return True

    for attr_name in ("normalized_payload_json", "raw_payload_json"):
        if not hasattr(obj, attr_name):
            continue
        payload = getattr(obj, attr_name, None)
        if not isinstance(payload, dict):
            payload = {}
        new_payload = dict(payload)
        overlay = dict(new_payload.get("formal_field_overlay") or {})
        overlay_meta = dict(new_payload.get("formal_field_overlay_meta") or {})
        overlay[field_name] = safe_value
        overlay_meta[field_name] = meta_entry
        new_payload["formal_field_overlay"] = overlay
        new_payload["formal_field_overlay_meta"] = overlay_meta
        setattr(obj, attr_name, to_jsonable(new_payload))
        flag_modified(obj, attr_name)
        return True
    return False


def get_field_value(obj: Any, field_name: str) -> Any:
    """Read a field value, checking direct ORM attribute first, then overlay."""
    val = getattr(obj, field_name, None)
    if val is not None and not is_empty_value(val):
        return val
    overlay_val = get_overlay_value(obj, field_name)
    if overlay_val is not None:
        return overlay_val
    return None


def object_to_json(obj: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for col in obj.__table__.columns:  # type: ignore[attr-defined]
        val = getattr(obj, col.name, None)
        data[col.name] = to_jsonable(val)
    return data
