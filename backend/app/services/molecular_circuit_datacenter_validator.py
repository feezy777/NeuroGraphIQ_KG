"""Data Center Record Quality Gate for Molecular circuit relation records.

Per spec section 14, every circuit step written as a "datacenter relation record"
must pass a deterministic field-level quality gate before it can be persisted.

Checks enforce that:
    - IDs are non-null and properly formed.
    - Subject/object fields reference real 574 candidate regions.
    - Predicates are meaningful (not ``related_to`` or similar defaults).
    - All numeric ranges are valid (0-1 for confidence, non-negative for counts).
    - All status fields use existing project enums.
    - Provenance is complete and traceable (spec section 12.3 item 18).

**No-fabrication rule** (spec section 14, final paragraph):
Fields that cannot be reliably populated MUST be left as ``None`` and recorded
in ``missing_fields``.  Default "unknown" / "0.5" / placeholder values are
NOT permitted as substitutes for missing data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DatacenterFieldViolation:
    """A single field-level issue in a datacenter relation record.

    Attributes:
        field: Dot-notation field path (e.g. ``subject_id``, ``provenance.model``).
        issue: Human-readable description of the problem.
        severity: ``"error"`` (blocking) or ``"warning"`` (advisory).
    """

    field: str
    issue: str
    severity: str  # "error" | "warning"


@dataclass
class DatacenterRecordValidation:
    """Result of validating one datacenter relation record.

    Attributes:
        passed: ``True`` only when every error-level check passes.
        violations: All field-level issues found (errors + warnings).
        missing_fields: Fields that could not be populated but are nullable.
    """

    passed: bool = True
    violations: list[DatacenterFieldViolation] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Required provenance fields (spec section 12.3 item 18)
# ---------------------------------------------------------------------------

REQUIRED_PROVENANCE_FIELDS: list[str] = [
    "extraction_run_id",
    "workflow_type",
    "pack_id",
    "candidate_id",
    "circuit_id",
    "canonical_key",
    "step_order",
    "edge_id",
    "source_connection_record_id",
    "source_region_record_id",
    "target_region_record_id",
    "functional_modules",
    "topology_type",
    "anatomical_pattern",
    "graph_algorithm",
    "prompt_version",
    "model",
    "quality_gate_version",
    "raw_response_reference",
    "created_by",
]

# ---------------------------------------------------------------------------
# Banned predicates that are too vague for circuit-step relation records
# ---------------------------------------------------------------------------

BANNED_PREDICATES: set[str] = {
    "related_to",
    "associated_with",
    "connected_to",
    "unknown",
    "unspecified",
    "n/a",
    "",
}

# ---------------------------------------------------------------------------
# Valid status enumerations (mirrors app.schemas.mirror_kg)
# ---------------------------------------------------------------------------

VALID_MIRROR_STATUSES: set[str] = {
    "llm_suggested",
    "rule_checked",
    "human_review_pending",
    "human_approved",
    "human_rejected",
    "promoted_to_final",
    "superseded",
}

VALID_REVIEW_STATUSES: set[str] = {
    "pending",
    "approved",
    "rejected",
    "needs_revision",
    "not_required",
}

VALID_PROMOTION_STATUSES: set[str] = {
    "not_promoted",
    "promoted",
    "failed",
    "blocked",
}

VALID_VALIDATION_STATUSES: set[str] = {
    "passed",
    "failed",
    "pending",
    "not_validated",
}

VALID_MIRROR_CONFIDENCE_RANGE: tuple[float, float] = (0.0, 1.0)

DEFAULT_VALID_STATUSES: dict[str, set[str]] = {
    "mirror_status": VALID_MIRROR_STATUSES,
    "review_status": VALID_REVIEW_STATUSES,
    "promotion_status": VALID_PROMOTION_STATUSES,
    "validation_status": VALID_VALIDATION_STATUSES,
}


# ---------------------------------------------------------------------------
# Section 14 — Record-level validation
# ---------------------------------------------------------------------------


def validate_datacenter_record(
    record: dict[str, Any],
    valid_region_ids: set[str] | None = None,
    valid_predicates: set[str] | None = None,
    valid_statuses: dict[str, set[str]] | None = None,
) -> DatacenterRecordValidation:
    """Validate ALL field-level checks from spec section 14.

    Args:
        record: A single datacenter relation record dict.  Expected fields
            match the spec section 12.3 table (id, subject_type, subject_id,
            subject_label, predicate, object_type, object_id, object_label,
            confidence, evidence_count, created_at, mirror_status, review_status,
            validation_status, promotion_status, mirror_confidence,
            mirror_evidence_text, provenance, source, target, edge_id).
        valid_region_ids: Set of valid 574 region IDs (as strings).  When
            ``None``, region-ID existence is skipped.
        valid_predicates: Set of allowed predicate values.  When ``None``,
            only banned-predicate check runs.
        valid_statuses: ``{field_name: {valid_values}}``.  Defaults to
            :const:`DEFAULT_VALID_STATUSES`.

    Returns:
        A :class:`DatacenterRecordValidation` with error-level checks in
        ``violations`` and silently-missing nullable fields in ``missing_fields``.

    Note:
        This function does NOT raise exceptions.  Every issue is recorded as a
        violation or a missing-field entry.
    """
    violations: list[DatacenterFieldViolation] = []
    missing_fields: list[str] = []

    statuses = valid_statuses or DEFAULT_VALID_STATUSES

    # ── 1. id — non-null and valid UUID ────────────────────────────────
    raw_id = record.get("id")
    if raw_id is None:
        violations.append(_error("id", "id is null or missing."))
    elif not _is_valid_uuid(raw_id):
        violations.append(_error("id", f"'{raw_id}' is not a valid UUID."))

    # ── 2 + 3 + 4. subject_type / subject_id / subject_label ──────────
    _check_subject_object(
        record, "subject", valid_region_ids, violations, missing_fields
    )

    # ── 5. predicate — valid and not banned ─────────────────────────────
    predicate = record.get("predicate")
    if not predicate:
        violations.append(_error("predicate", "predicate is null or empty."))
    elif predicate in BANNED_PREDICATES:
        violations.append(
            _error("predicate", f"predicate '{predicate}' is banned (too vague).")
        )
    elif valid_predicates is not None and predicate not in valid_predicates:
        violations.append(
            _error(
                "predicate",
                f"predicate '{predicate}' is not in the valid set.",
            )
        )

    # ── 6 + 7. object_type / object_id / object_label ──────────────────
    _check_subject_object(
        record, "object", valid_region_ids, violations, missing_fields
    )

    # ── 8. confidence — null or 0..1 ───────────────────────────────────
    confidence = record.get("confidence")
    if confidence is not None:
        try:
            cf = float(confidence)
            if cf < 0.0 or cf > 1.0:
                violations.append(
                    _error("confidence", f"Value {cf} is outside [0.0, 1.0].")
                )
        except (TypeError, ValueError):
            violations.append(
                _error("confidence", f"'{confidence}' is not a valid number.")
            )

    # ── 9. evidence_count — non-negative int ────────────────────────────
    evidence_count = record.get("evidence_count")
    if evidence_count is not None:
        try:
            ec = int(evidence_count)
            if ec < 0:
                violations.append(
                    _error("evidence_count", f"Negative value {ec}.")
                )
        except (TypeError, ValueError):
            violations.append(
                _error("evidence_count", f"'{evidence_count}' is not a valid integer.")
            )

    # ── 10. created_at — valid datetime ────────────────────────────────
    created_at = record.get("created_at")
    if created_at is not None:
        if not isinstance(created_at, (datetime, str)):
            violations.append(
                _error("created_at", f"Unexpected type: {type(created_at).__name__}.")
            )
        elif isinstance(created_at, str):
            try:
                datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                violations.append(
                    _error("created_at", f"'{created_at}' is not a valid ISO datetime.")
                )

    # ── 11. mirror_status — valid enum ─────────────────────────────────
    _check_status("mirror_status", record, statuses, violations, missing_fields)

    # ── 12. review_status — valid enum ─────────────────────────────────
    _check_status("review_status", record, statuses, violations, missing_fields)

    # ── 13. validation_status — valid enum (when present) ──────────────
    _check_status("validation_status", record, statuses, violations, missing_fields)

    # ── 14. promotion_status — valid enum ──────────────────────────────
    _check_status("promotion_status", record, statuses, violations, missing_fields)

    # ── 15. mirror_confidence — 0..1 ──────────────────────────────────
    mirror_conf = record.get("mirror_confidence")
    if mirror_conf is not None:
        try:
            mc = float(mirror_conf)
            if mc < 0.0 or mc > 1.0:
                violations.append(
                    _error(
                        "mirror_confidence",
                        f"Value {mc} is outside [0.0, 1.0].",
                    )
                )
        except (TypeError, ValueError):
            violations.append(
                _error("mirror_confidence", f"'{mirror_conf}' is not a valid number.")
            )

    # ── 16. mirror_evidence_text — non-empty or explicitly marked ──────
    mirror_evidence = record.get("mirror_evidence_text")
    if mirror_evidence is not None and not mirror_evidence:
        violations.append(
            _warning(
                "mirror_evidence_text",
                "Field is present but empty. Use null if unavailable.",
            )
        )

    # ── 17. provenance — complete required fields ─────────────────────
    provenance = record.get("provenance")
    if provenance is None or not isinstance(provenance, dict):
        violations.append(
            _error("provenance", "provenance is missing or not a dict.")
        )
    else:
        for pf in REQUIRED_PROVENANCE_FIELDS:
            if pf not in provenance or provenance[pf] is None:
                violations.append(
                    _error(
                        f"provenance.{pf}",
                        f"Required provenance field '{pf}' is missing or null.",
                    )
                )

    # ── 18. source / target match original edge_id ────────────────────
    edge_id = record.get("edge_id")
    source = record.get("subject_id")
    target = record.get("object_id")
    record_source = record.get("source_region_id")
    record_target = record.get("target_region_id")

    # When edge-level source/target info is available, cross-check
    if record_source and source and str(record_source) != str(source):
        violations.append(
            _error(
                "source_region_id",
                f"Record source '{record_source}' does not match subject_id '{source}'.",
            )
        )
    if record_target and target and str(record_target) != str(target):
        violations.append(
            _error(
                "target_region_id",
                f"Record target '{record_target}' does not match object_id '{target}'.",
            )
        )

    return DatacenterRecordValidation(
        passed=len([v for v in violations if v.severity == "error"]) == 0,
        violations=violations,
        missing_fields=missing_fields,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_subject_object(
    record: dict[str, Any],
    prefix: str,  # "subject" or "object"
    valid_region_ids: set[str] | None,
    violations: list[DatacenterFieldViolation],
    missing_fields: list[str],
) -> None:
    """Validate subject_type, subject_id, subject_label (or object_*)."""
    type_field = f"{prefix}_type"
    id_field = f"{prefix}_id"
    label_field = f"{prefix}_label"

    # type (non-null, but not deeply validated here — enum check is separate)
    st = record.get(type_field)
    if not st:
        violations.append(_error(type_field, f"{type_field} is null or missing."))

    # id (must exist in valid_region_ids when provided)
    sid = record.get(id_field)
    if sid is None:
        violations.append(_error(id_field, f"{id_field} is null or missing."))
    elif valid_region_ids is not None:
        sid_str = str(sid)
        if sid_str not in valid_region_ids:
            violations.append(
                _error(
                    id_field,
                    f"{id_field} '{sid_str}' is not in the 574 valid region IDs.",
                )
            )

    # label (non-empty)
    label = record.get(label_field)
    if not label:
        violations.append(
            _error(label_field, f"{label_field} is null or empty.")
        )
    elif not isinstance(label, str) or not label.strip():
        violations.append(
            _error(label_field, f"{label_field} is present but blank.")
        )


def _check_status(
    field_name: str,
    record: dict[str, Any],
    valid_statuses: dict[str, set[str]],
    violations: list[DatacenterFieldViolation],
    missing_fields: list[str],
) -> None:
    """Validate a single status field against its allowed values."""
    allowed = valid_statuses.get(field_name)
    if allowed is None:
        return  # no validation configured for this field

    value = record.get(field_name)
    if value is None:
        missing_fields.append(field_name)
        return

    if value not in allowed:
        violations.append(
            _error(
                field_name,
                f"'{value}' is not a valid {field_name}. Allowed: {sorted(allowed)}.",
            )
        )


def _error(field: str, issue: str) -> DatacenterFieldViolation:
    return DatacenterFieldViolation(field=field, issue=issue, severity="error")


def _warning(field: str, issue: str) -> DatacenterFieldViolation:
    return DatacenterFieldViolation(field=field, issue=issue, severity="warning")


def _is_valid_uuid(value: Any) -> bool:
    """Check whether *value* is a valid UUID (string or ``uuid.UUID``)."""
    if isinstance(value, uuid.UUID):
        return True
    if isinstance(value, str):
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False
    return False


# ---------------------------------------------------------------------------
# Section 14 — Enum audit
# ---------------------------------------------------------------------------


def audit_existing_enums() -> dict[str, set[str]]:
    """Return all valid status enum values as a dictionary.

    Reads from the canonical string-constant classes in ``app.schemas.mirror_kg``.
    Falls back to hardcoded sets when the import is unavailable (e.g. during
    unit testing without the full application stack).

    Returns:
        ``{field_name: {valid_value, ...}}`` mirroring the shape expected by
        :func:`validate_datacenter_record`'s ``valid_statuses`` parameter.
    """
    try:
        from app.schemas.mirror_kg import (
            MirrorPromotionStatus,
            MirrorReviewStatus,
            MirrorStatus,
        )

        return {
            "mirror_status": _extract_enum_values(MirrorStatus),
            "review_status": _extract_enum_values(MirrorReviewStatus),
            "promotion_status": _extract_enum_values(MirrorPromotionStatus),
            "validation_status": VALID_VALIDATION_STATUSES,
        }
    except ImportError:
        return dict(DEFAULT_VALID_STATUSES)


def _extract_enum_values(enum_class: type) -> set[str]:
    """Extract all string values from a string-constant "enum" class."""
    values: set[str] = set()
    for attr_name in dir(enum_class):
        if attr_name.startswith("_"):
            continue
        val = getattr(enum_class, attr_name)
        if isinstance(val, str):
            values.add(val)
    return values
