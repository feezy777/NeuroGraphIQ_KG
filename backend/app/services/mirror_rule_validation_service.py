"""Mirror KG Rule Validation — deterministic checks over mirror objects (Step 7).

Reads mirror_region_connections, mirror_region_functions, mirror_region_circuits,
mirror_circuit_regions, mirror_kg_triples. Writes mirror_rule_validation_runs/results
and optionally updates mirror_status to rule_checked. Does NOT call LLM; does NOT
write final_* / kg_*; does NOT approve or promote.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_validation import MirrorRuleValidationResult, MirrorRuleValidationRun
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.schemas.mirror_kg import (
    CircuitRegionRole,
    CircuitType,
    ConnectionType,
    Directionality,
    FunctionCategory,
    FunctionRelationType,
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
    TripleObjectType,
    TripleScope,
    TripleSubjectType,
)
from app.schemas.mirror_validation import (
    MirrorValidationResultStatus,
    MirrorValidationRunStatus,
    MirrorValidationSeverity,
    VALID_MIRROR_VALIDATION_TARGET_TYPES,
)
from app.services.mirror_rule_validation_helpers import (
    ValidationCheck,
    build_validation_result,
    float_confidence as _float_confidence,
    norm_label as _norm_label,
    validate_common_fields,
    VALID_CONNECTION_TYPES,
    VALID_DIRECTIONALITIES,
    VALID_FUNCTION_CATEGORIES,
    VALID_MIRROR_STATUSES,
    VALID_PROMOTION_STATUSES,
    VALID_RELATION_TYPES,
    VALID_REVIEW_STATUSES,
)
from app.services import mirror_rule_validation_macro_clinical as mc_rules
from app.services.triple_consolidation_service import normalize_triple_key

MAX_VALIDATION_LIMIT = 5000
DEFAULT_VALIDATION_LIMIT = 1000
PREVIEW_LIMIT = 200

VALID_TARGET_TYPES = VALID_MIRROR_VALIDATION_TARGET_TYPES

# Re-export for tests and backward compatibility

VALID_CIRCUIT_TYPES = frozenset({
    CircuitType.sensory_circuit,
    CircuitType.motor_circuit,
    CircuitType.limbic_circuit,
    CircuitType.cognitive_control_circuit,
    CircuitType.default_mode_related,
    CircuitType.salience_related,
    CircuitType.memory_related,
    CircuitType.reward_related,
    CircuitType.language_related,
    CircuitType.attention_related,
    CircuitType.uncertain_circuit,
    CircuitType.unknown,
})

VALID_CIRCUIT_ROLES = frozenset({
    CircuitRegionRole.participant,
    CircuitRegionRole.source,
    CircuitRegionRole.target,
    CircuitRegionRole.hub,
    CircuitRegionRole.relay,
    CircuitRegionRole.modulator,
    CircuitRegionRole.unknown,
})

VALID_TRIPLE_SCOPES = frozenset({
    TripleScope.same_granularity,
    TripleScope.cross_granularity_mapping,
    TripleScope.evidence_link,
    TripleScope.unknown,
})

VALID_SUBJECT_TYPES = frozenset({
    TripleSubjectType.region_candidate,
    TripleSubjectType.region_final,
    TripleSubjectType.connection,
    TripleSubjectType.circuit,
    TripleSubjectType.function,
    TripleSubjectType.term,
    TripleSubjectType.literal,
    TripleSubjectType.unknown,
})

VALID_OBJECT_TYPES = frozenset({
    TripleObjectType.region_candidate,
    TripleObjectType.region_final,
    TripleObjectType.connection,
    TripleObjectType.circuit,
    TripleObjectType.function,
    TripleObjectType.term,
    TripleObjectType.literal,
    TripleObjectType.unknown,
})

RULE_CHECK_ELIGIBLE_MIRROR_STATUSES = frozenset({
    MirrorStatus.llm_suggested,
    MirrorStatus.human_review_pending,
    MirrorStatus.rule_checked,
})


class EmptyTargetTypesError(Exception):
    pass


class InvalidTargetTypeError(Exception):
    def __init__(self, value: str):
        self.value = value
        super().__init__(f"invalid target_type: {value}")


class LimitExceededError(Exception):
    def __init__(self, limit: int, maximum: int):
        super().__init__(f"limit {limit} exceeds max {maximum}")


class ExplicitIdNotFoundError(Exception):
    def __init__(self, target_type: str, target_id: str):
        self.target_type = target_type
        self.target_id = target_id
        super().__init__(f"{target_type} not found: {target_id}")


class ScopeMismatchError(Exception):
    def __init__(self, target_type: str, target_id: str, field: str):
        self.target_type = target_type
        self.target_id = target_id
        self.field = field
        super().__init__(f"{target_type} {target_id} scope mismatch on {field}")


class MirrorValidationRunNotFoundError(Exception):
    pass


@dataclass
class ValidationFilters:
    circuit_id: uuid.UUID | None = None
    projection_id: uuid.UUID | None = None
    object_type: str | None = None
    validation_status: str | None = None
    consensus_status: str | None = None
    verification_status: str | None = None


@dataclass
class ValidationScope:
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_statuses: list[str] | None = None
    review_statuses: list[str] | None = None
    promotion_statuses: list[str] | None = None


@dataclass
class ValidationOutcome:
    target_type: str
    target_id: uuid.UUID
    checks: list[ValidationCheck] = field(default_factory=list)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    mirror_status: str | None = None

    def has_blocker_or_error(self) -> bool:
        return any(
            c.severity in (MirrorValidationSeverity.blocker, MirrorValidationSeverity.error)
            for c in self.checks
        )

    def worst_status(self) -> str:
        if any(c.status == MirrorValidationResultStatus.blocked for c in self.checks):
            return MirrorValidationResultStatus.blocked
        if any(c.status == MirrorValidationResultStatus.failed for c in self.checks):
            return MirrorValidationResultStatus.failed
        if any(c.status == MirrorValidationResultStatus.warning for c in self.checks):
            return MirrorValidationResultStatus.warning
        return MirrorValidationResultStatus.passed


@dataclass
class ValidationRunResult:
    dry_run: bool = True
    run_id: uuid.UUID | None = None
    target_counts: dict[str, int] = field(default_factory=dict)
    passed_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    high_review_priority_count: int = 0
    result_count: int = 0
    status_updates: dict[str, int] = field(default_factory=dict)
    results_preview: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    outcomes: list[ValidationOutcome] = field(default_factory=list)
    run_status: str = MirrorValidationRunStatus.succeeded


def _connection_pair_key(conn: MirrorRegionConnection) -> tuple[Any, ...]:
    src = conn.source_region_candidate_id
    tgt = conn.target_region_candidate_id
    if conn.directionality in (Directionality.undirected, Directionality.bidirectional):
        pair = tuple(sorted([str(src), str(tgt)]))
    else:
        pair = (str(src), str(tgt))
    return (
        str(conn.resource_id),
        str(conn.batch_id),
        conn.source_atlas,
        conn.granularity_level,
        conn.granularity_family or "",
        pair,
        conn.connection_type,
        conn.directionality,
    )


def validate_connection(
    conn: MirrorRegionConnection,
    *,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_common_fields(conn)

    has_src = bool(conn.source_region_candidate_id or conn.source_region_final_id)
    has_tgt = bool(conn.target_region_candidate_id or conn.target_region_final_id)
    if not has_src:
        checks.append(build_validation_result(
            "RULE_CONNECTION_SOURCE_REGION_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="source region is missing",
        ))
    if not has_tgt:
        checks.append(build_validation_result(
            "RULE_CONNECTION_TARGET_REGION_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="target region is missing",
        ))

    if (
        conn.source_region_candidate_id
        and conn.target_region_candidate_id
        and conn.source_region_candidate_id == conn.target_region_candidate_id
    ):
        checks.append(build_validation_result(
            "RULE_CONNECTION_NO_SELF_LOOP",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="self-loop connection detected",
        ))

    for label, cid in (("source", conn.source_region_candidate_id), ("target", conn.target_region_candidate_id)):
        if cid is None:
            continue
        cand = candidate_map.get(cid)
        if cand is None:
            checks.append(build_validation_result(
                "RULE_CONNECTION_REGION_EXISTS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"{label} region candidate {cid} not found",
                details={"region_candidate_id": str(cid), "endpoint": label},
            ))
            continue
        if cand.source_atlas != conn.source_atlas:
            checks.append(build_validation_result(
                "RULE_CONNECTION_SAME_ATLAS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"{label} candidate atlas mismatch",
                details={"expected": conn.source_atlas, "actual": cand.source_atlas},
            ))
        if cand.granularity_level != conn.granularity_level or cand.granularity_family != conn.granularity_family:
            checks.append(build_validation_result(
                "RULE_CONNECTION_SAME_GRANULARITY",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"{label} candidate granularity mismatch",
            ))

    if conn.connection_type not in VALID_CONNECTION_TYPES:
        checks.append(build_validation_result(
            "RULE_CONNECTION_TYPE_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid connection_type: {conn.connection_type}",
        ))
    if conn.directionality not in VALID_DIRECTIONALITIES:
        checks.append(build_validation_result(
            "RULE_CONNECTION_DIRECTIONALITY_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid directionality: {conn.directionality}",
        ))

    if conn.source_region_candidate_id and conn.target_region_candidate_id:
        key = _connection_pair_key(conn)
        other = duplicate_keys.get(key)
        if other and other != conn.id:
            checks.append(build_validation_result(
                "RULE_CONNECTION_DUPLICATE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="Duplicate connection candidate detected.",
                details={"duplicate_of": str(other)},
            ))
        else:
            duplicate_keys.setdefault(key, conn.id)

    return checks


def validate_function(
    fn: MirrorRegionFunction,
    *,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_common_fields(fn)

    if not fn.region_candidate_id and not fn.region_final_id:
        checks.append(build_validation_result(
            "RULE_FUNCTION_REGION_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="region is missing",
        ))

    if fn.region_candidate_id:
        cand = candidate_map.get(fn.region_candidate_id)
        if cand is None:
            checks.append(build_validation_result(
                "RULE_FUNCTION_REGION_EXISTS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"region candidate {fn.region_candidate_id} not found",
            ))
        else:
            if cand.source_atlas != fn.source_atlas:
                checks.append(build_validation_result(
                    "RULE_FUNCTION_SAME_ATLAS",
                    severity=MirrorValidationSeverity.blocker,
                    status=MirrorValidationResultStatus.blocked,
                    message="region candidate atlas mismatch",
                ))
            if cand.granularity_level != fn.granularity_level or cand.granularity_family != fn.granularity_family:
                checks.append(build_validation_result(
                    "RULE_FUNCTION_SAME_GRANULARITY",
                    severity=MirrorValidationSeverity.blocker,
                    status=MirrorValidationResultStatus.blocked,
                    message="region candidate granularity mismatch",
                ))

    term = (fn.function_term or "").strip()
    if not term:
        checks.append(build_validation_result(
            "RULE_FUNCTION_TERM_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="function_term is required",
        ))

    if fn.function_category not in VALID_FUNCTION_CATEGORIES:
        checks.append(build_validation_result(
            "RULE_FUNCTION_CATEGORY_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid function_category: {fn.function_category}",
        ))
    if fn.relation_type not in VALID_RELATION_TYPES:
        checks.append(build_validation_result(
            "RULE_FUNCTION_RELATION_TYPE_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid relation_type: {fn.relation_type}",
        ))

    if fn.region_candidate_id and term:
        key = (
            str(fn.resource_id),
            str(fn.batch_id),
            fn.source_atlas,
            fn.granularity_level,
            fn.granularity_family or "",
            str(fn.region_candidate_id),
            _norm_label(term),
            fn.function_category,
            fn.relation_type,
        )
        other = duplicate_keys.get(key)
        if other and other != fn.id:
            checks.append(build_validation_result(
                "RULE_FUNCTION_DUPLICATE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="Duplicate function candidate detected.",
                details={"duplicate_of": str(other)},
            ))
        else:
            duplicate_keys.setdefault(key, fn.id)

    return checks


def validate_circuit(
    circuit: MirrorRegionCircuit,
    *,
    circuit_regions: list[MirrorCircuitRegion],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_common_fields(circuit)

    name = (circuit.circuit_name or "").strip()
    if not name:
        checks.append(build_validation_result(
            "RULE_CIRCUIT_NAME_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="circuit_name is required",
        ))

    if circuit.circuit_type not in VALID_CIRCUIT_TYPES:
        checks.append(build_validation_result(
            "RULE_CIRCUIT_TYPE_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid circuit_type: {circuit.circuit_type}",
        ))

    valid_regions = [cr for cr in circuit_regions if cr.region_candidate_id]
    if len(valid_regions) < 2:
        checks.append(build_validation_result(
            "RULE_CIRCUIT_REGIONS_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"circuit requires at least 2 regions, found {len(valid_regions)}",
        ))

    region_ids: set[uuid.UUID] = set()
    for cr in circuit_regions:
        if not cr.region_candidate_id:
            continue
        region_ids.add(cr.region_candidate_id)
        cand = candidate_map.get(cr.region_candidate_id)
        if cand is None:
            checks.append(build_validation_result(
                "RULE_CIRCUIT_REGION_EXISTS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message=f"region candidate {cr.region_candidate_id} not found",
            ))
        else:
            if cand.source_atlas != circuit.source_atlas:
                checks.append(build_validation_result(
                    "RULE_CIRCUIT_REGION_SAME_ATLAS",
                    severity=MirrorValidationSeverity.blocker,
                    status=MirrorValidationResultStatus.blocked,
                    message="circuit region atlas mismatch",
                ))
            if cand.granularity_level != circuit.granularity_level or cand.granularity_family != circuit.granularity_family:
                checks.append(build_validation_result(
                    "RULE_CIRCUIT_REGION_SAME_GRANULARITY",
                    severity=MirrorValidationSeverity.blocker,
                    status=MirrorValidationResultStatus.blocked,
                    message="circuit region granularity mismatch",
                ))
        if cr.role not in VALID_CIRCUIT_ROLES:
            checks.append(build_validation_result(
                "RULE_CIRCUIT_ROLE_VALID",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message=f"invalid circuit region role: {cr.role}",
            ))

    if name and len(region_ids) >= 2:
        key = (
            str(circuit.resource_id),
            str(circuit.batch_id),
            circuit.source_atlas,
            circuit.granularity_level,
            circuit.granularity_family or "",
            _norm_label(name),
            circuit.circuit_type,
            tuple(sorted(str(r) for r in region_ids)),
        )
        other = duplicate_keys.get(key)
        if other and other != circuit.id:
            checks.append(build_validation_result(
                "RULE_CIRCUIT_DUPLICATE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="Duplicate circuit candidate detected.",
                details={"duplicate_of": str(other)},
            ))
        else:
            duplicate_keys.setdefault(key, circuit.id)

    if not (circuit.function_association or "").strip():
        checks.append(build_validation_result(
            "RULE_CIRCUIT_FUNCTION_ASSOCIATION_EMPTY",
            severity=MirrorValidationSeverity.info,
            status=MirrorValidationResultStatus.passed,
            message="function_association is empty (informational)",
        ))

    return checks


def validate_triple(
    triple: MirrorKgTriple,
    *,
    connection_map: dict[uuid.UUID, MirrorRegionConnection],
    function_map: dict[uuid.UUID, MirrorRegionFunction],
    circuit_map: dict[uuid.UUID, MirrorRegionCircuit],
    duplicate_keys: dict[tuple[Any, ...], uuid.UUID],
) -> list[ValidationCheck]:
    checks = validate_common_fields(triple)

    if not (triple.subject_label or "").strip() and not triple.subject_id:
        checks.append(build_validation_result(
            "RULE_TRIPLE_SUBJECT_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="subject is missing",
        ))
    if not (triple.object_label or "").strip() and not triple.object_id:
        checks.append(build_validation_result(
            "RULE_TRIPLE_OBJECT_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="object is missing",
        ))
    if not (triple.predicate or "").strip():
        checks.append(build_validation_result(
            "RULE_TRIPLE_PREDICATE_REQUIRED",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message="predicate is required",
        ))
    if triple.triple_scope not in VALID_TRIPLE_SCOPES:
        checks.append(build_validation_result(
            "RULE_TRIPLE_SCOPE_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid triple_scope: {triple.triple_scope}",
        ))
    if triple.subject_type not in VALID_SUBJECT_TYPES:
        checks.append(build_validation_result(
            "RULE_TRIPLE_SUBJECT_TYPE_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid subject_type: {triple.subject_type}",
        ))
    if triple.object_type not in VALID_OBJECT_TYPES:
        checks.append(build_validation_result(
            "RULE_TRIPLE_OBJECT_TYPE_VALID",
            severity=MirrorValidationSeverity.blocker,
            status=MirrorValidationResultStatus.blocked,
            message=f"invalid object_type: {triple.object_type}",
        ))

    has_source = bool(
        triple.source_mirror_connection_id
        or triple.source_mirror_function_id
        or triple.source_mirror_circuit_id
    )
    if not has_source:
        checks.append(build_validation_result(
            "RULE_TRIPLE_SOURCE_LINK_REQUIRED",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="triple has no source mirror object link",
        ))

    source_obj: MirrorRegionConnection | MirrorRegionFunction | MirrorRegionCircuit | None = None
    if triple.source_mirror_connection_id:
        source_obj = connection_map.get(triple.source_mirror_connection_id)
        if source_obj is None:
            checks.append(build_validation_result(
                "RULE_TRIPLE_SOURCE_LINK_EXISTS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="source_mirror_connection_id not found",
            ))
    if triple.source_mirror_function_id:
        source_obj = function_map.get(triple.source_mirror_function_id)
        if source_obj is None:
            checks.append(build_validation_result(
                "RULE_TRIPLE_SOURCE_LINK_EXISTS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="source_mirror_function_id not found",
            ))
    if triple.source_mirror_circuit_id:
        source_obj = circuit_map.get(triple.source_mirror_circuit_id)
        if source_obj is None:
            checks.append(build_validation_result(
                "RULE_TRIPLE_SOURCE_LINK_EXISTS",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="source_mirror_circuit_id not found",
            ))

    if source_obj is not None:
        if source_obj.source_atlas != triple.source_atlas:
            checks.append(build_validation_result(
                "RULE_TRIPLE_SAME_SCOPE_WITH_SOURCE",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="triple source_atlas differs from source mirror object",
            ))
        if (
            source_obj.granularity_level != triple.granularity_level
            or source_obj.granularity_family != triple.granularity_family
        ):
            checks.append(build_validation_result(
                "RULE_TRIPLE_SAME_SCOPE_WITH_SOURCE",
                severity=MirrorValidationSeverity.blocker,
                status=MirrorValidationResultStatus.blocked,
                message="triple granularity differs from source mirror object",
            ))
        if source_obj.resource_id and triple.resource_id and source_obj.resource_id != triple.resource_id:
            checks.append(build_validation_result(
                "RULE_TRIPLE_SAME_SCOPE_WITH_SOURCE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="triple resource_id differs from source mirror object",
            ))
        if source_obj.batch_id and triple.batch_id and source_obj.batch_id != triple.batch_id:
            checks.append(build_validation_result(
                "RULE_TRIPLE_SAME_SCOPE_WITH_SOURCE",
                severity=MirrorValidationSeverity.warning,
                status=MirrorValidationResultStatus.warning,
                message="triple batch_id differs from source mirror object",
            ))

    key = normalize_triple_key(
        subject_type=triple.subject_type,
        subject_id=triple.subject_id,
        subject_label=triple.subject_label,
        predicate=triple.predicate,
        object_type=triple.object_type,
        object_id=triple.object_id,
        object_label=triple.object_label,
        triple_scope=triple.triple_scope,
        source_atlas=triple.source_atlas,
        granularity_level=triple.granularity_level,
        granularity_family=triple.granularity_family,
        resource_id=triple.resource_id,
        batch_id=triple.batch_id,
    )
    other = duplicate_keys.get(key)
    if other and other != triple.id:
        checks.append(build_validation_result(
            "RULE_TRIPLE_DUPLICATE",
            severity=MirrorValidationSeverity.warning,
            status=MirrorValidationResultStatus.warning,
            message="Duplicate triple candidate detected.",
            details={"duplicate_of": str(other)},
        ))
    else:
        duplicate_keys.setdefault(key, triple.id)

    return checks


def summarize_validation_results(outcomes: list[ValidationOutcome]) -> tuple[int, int, int, int, int]:
    """Return passed, warning, failed, blocked target counts, result_count."""
    passed = warning = failed = blocked = 0
    result_count = 0
    for o in outcomes:
        result_count += len(o.checks)
        worst = o.worst_status()
        if worst == MirrorValidationResultStatus.blocked:
            blocked += 1
        elif worst == MirrorValidationResultStatus.failed:
            failed += 1
        elif worst == MirrorValidationResultStatus.warning:
            warning += 1
        else:
            passed += 1
    return passed, warning, failed, blocked, result_count


def _apply_scope_to_query(q, model, scope: ValidationScope):
    if scope.resource_id:
        q = q.where(model.resource_id == scope.resource_id)
    if scope.batch_id:
        q = q.where(model.batch_id == scope.batch_id)
    if scope.source_atlas:
        q = q.where(model.source_atlas == scope.source_atlas)
    if scope.granularity_level:
        q = q.where(model.granularity_level == scope.granularity_level)
    if scope.granularity_family:
        q = q.where(model.granularity_family == scope.granularity_family)
    if scope.mirror_statuses:
        q = q.where(model.mirror_status.in_(scope.mirror_statuses))
    if scope.review_statuses:
        q = q.where(model.review_status.in_(scope.review_statuses))
    if scope.promotion_statuses:
        q = q.where(model.promotion_status.in_(scope.promotion_statuses))
    return q


def _validate_source_scope(
    row: MirrorRegionConnection | MirrorRegionFunction | MirrorRegionCircuit | MirrorKgTriple,
    scope: ValidationScope,
    target_type: str,
) -> None:
    checks = [
        ("resource_id", scope.resource_id, row.resource_id),
        ("batch_id", scope.batch_id, row.batch_id),
        ("source_atlas", scope.source_atlas, row.source_atlas),
        ("granularity_level", scope.granularity_level, row.granularity_level),
        ("granularity_family", scope.granularity_family, row.granularity_family),
    ]
    for field, expected, actual in checks:
        if expected is not None and actual != expected:
            raise ScopeMismatchError(target_type, str(row.id), field)


def _apply_extra_filters(model, q, filters: ValidationFilters | None):
    if filters is None:
        return q
    if filters.circuit_id and hasattr(model, "circuit_id"):
        q = q.where(model.circuit_id == filters.circuit_id)
    if filters.projection_id and hasattr(model, "projection_id"):
        q = q.where(model.projection_id == filters.projection_id)
    if filters.object_type and hasattr(model, "object_type"):
        q = q.where(model.object_type == filters.object_type)
    if filters.validation_status and hasattr(model, "validation_status"):
        q = q.where(model.validation_status == filters.validation_status)
    if filters.consensus_status and hasattr(model, "consensus_status"):
        q = q.where(model.consensus_status == filters.consensus_status)
    if filters.verification_status and hasattr(model, "verification_status"):
        q = q.where(model.verification_status == filters.verification_status)
    return q


async def collect_validation_targets(
    session: AsyncSession,
    *,
    target_types: list[str],
    scope: ValidationScope,
    filters: ValidationFilters | None,
    connection_ids: list[uuid.UUID] | None,
    function_ids: list[uuid.UUID] | None,
    circuit_ids: list[uuid.UUID] | None,
    triple_ids: list[uuid.UUID] | None,
    projection_ids: list[uuid.UUID] | None,
    circuit_step_ids: list[uuid.UUID] | None,
    projection_function_ids: list[uuid.UUID] | None,
    membership_ids: list[uuid.UUID] | None,
    cross_validation_result_ids: list[uuid.UUID] | None,
    dual_model_result_ids: list[uuid.UUID] | None,
    limit: int,
) -> dict[str, list[Any]]:
    """Collect mirror objects to validate, keyed by target_type."""
    out: dict[str, list[Any]] = {t: [] for t in target_types}

    if "connection" in target_types:
        if connection_ids:
            for cid in connection_ids:
                row = await session.get(MirrorRegionConnection, cid)
                if row is None:
                    raise ExplicitIdNotFoundError("connection", str(cid))
                _validate_source_scope(row, scope, "connection")
                out["connection"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorRegionConnection), MirrorRegionConnection, scope)
            out["connection"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "function" in target_types:
        if function_ids:
            for fid in function_ids:
                row = await session.get(MirrorRegionFunction, fid)
                if row is None:
                    raise ExplicitIdNotFoundError("function", str(fid))
                _validate_source_scope(row, scope, "function")
                out["function"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorRegionFunction), MirrorRegionFunction, scope)
            out["function"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "circuit" in target_types:
        if circuit_ids:
            for cid in circuit_ids:
                row = await session.get(MirrorRegionCircuit, cid)
                if row is None:
                    raise ExplicitIdNotFoundError("circuit", str(cid))
                _validate_source_scope(row, scope, "circuit")
                out["circuit"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorRegionCircuit), MirrorRegionCircuit, scope)
            q = _apply_extra_filters(MirrorRegionCircuit, q, filters)
            out["circuit"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "triple" in target_types:
        if triple_ids:
            for tid in triple_ids:
                row = await session.get(MirrorKgTriple, tid)
                if row is None:
                    raise ExplicitIdNotFoundError("triple", str(tid))
                _validate_source_scope(row, scope, "triple")
                out["triple"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorKgTriple), MirrorKgTriple, scope)
            out["triple"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "projection" in target_types:
        if projection_ids:
            for pid in projection_ids:
                row = await session.get(MirrorRegionConnection, pid)
                if row is None:
                    raise ExplicitIdNotFoundError("projection", str(pid))
                _validate_source_scope(row, scope, "projection")
                out["projection"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorRegionConnection), MirrorRegionConnection, scope)
            q = _apply_extra_filters(MirrorRegionConnection, q, filters)
            out["projection"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "circuit_step" in target_types:
        if circuit_step_ids:
            for sid in circuit_step_ids:
                row = await session.get(MirrorCircuitStep, sid)
                if row is None:
                    raise ExplicitIdNotFoundError("circuit_step", str(sid))
                out["circuit_step"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorCircuitStep), MirrorCircuitStep, scope)
            q = _apply_extra_filters(MirrorCircuitStep, q, filters)
            out["circuit_step"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "projection_function" in target_types:
        if projection_function_ids:
            for pfid in projection_function_ids:
                row = await session.get(MirrorProjectionFunction, pfid)
                if row is None:
                    raise ExplicitIdNotFoundError("projection_function", str(pfid))
                out["projection_function"].append(row)
        else:
            q = _apply_scope_to_query(select(MirrorProjectionFunction), MirrorProjectionFunction, scope)
            q = _apply_extra_filters(MirrorProjectionFunction, q, filters)
            out["projection_function"] = list((await session.execute(q.limit(limit))).scalars().all())

    if "circuit_projection_membership" in target_types:
        if membership_ids:
            for mid in membership_ids:
                row = await session.get(MirrorCircuitProjectionMembership, mid)
                if row is None:
                    raise ExplicitIdNotFoundError("circuit_projection_membership", str(mid))
                out["circuit_projection_membership"].append(row)
        else:
            q = _apply_scope_to_query(
                select(MirrorCircuitProjectionMembership), MirrorCircuitProjectionMembership, scope
            )
            q = _apply_extra_filters(MirrorCircuitProjectionMembership, q, filters)
            out["circuit_projection_membership"] = list(
                (await session.execute(q.limit(limit))).scalars().all()
            )

    if "circuit_projection_cross_validation_result" in target_types:
        if cross_validation_result_ids:
            for rid in cross_validation_result_ids:
                row = await session.get(MirrorCircuitProjectionCrossValidationResult, rid)
                if row is None:
                    raise ExplicitIdNotFoundError("circuit_projection_cross_validation_result", str(rid))
                out["circuit_projection_cross_validation_result"].append(row)
        else:
            q = _apply_scope_to_query(
                select(MirrorCircuitProjectionCrossValidationResult),
                MirrorCircuitProjectionCrossValidationResult,
                scope,
            )
            q = _apply_extra_filters(MirrorCircuitProjectionCrossValidationResult, q, filters)
            out["circuit_projection_cross_validation_result"] = list(
                (await session.execute(q.limit(limit))).scalars().all()
            )

    if "dual_model_verification_result" in target_types:
        if dual_model_result_ids:
            for did in dual_model_result_ids:
                row = await session.get(MirrorDualModelVerificationResult, did)
                if row is None:
                    raise ExplicitIdNotFoundError("dual_model_verification_result", str(did))
                out["dual_model_verification_result"].append(row)
        else:
            q = _apply_scope_to_query(
                select(MirrorDualModelVerificationResult),
                MirrorDualModelVerificationResult,
                scope,
            )
            q = _apply_extra_filters(MirrorDualModelVerificationResult, q, filters)
            out["dual_model_verification_result"] = list(
                (await session.execute(q.limit(limit))).scalars().all()
            )

    return out


async def _load_candidate_map(
    session: AsyncSession,
    candidate_ids: set[uuid.UUID],
) -> dict[uuid.UUID, CandidateBrainRegion]:
    if not candidate_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(candidate_ids))
            )
        ).scalars().all()
    )
    return {r.id: r for r in rows}


async def _load_source_maps(
    session: AsyncSession,
    triples: list[MirrorKgTriple],
) -> tuple[
    dict[uuid.UUID, MirrorRegionConnection],
    dict[uuid.UUID, MirrorRegionFunction],
    dict[uuid.UUID, MirrorRegionCircuit],
]:
    conn_ids = {t.source_mirror_connection_id for t in triples if t.source_mirror_connection_id}
    fn_ids = {t.source_mirror_function_id for t in triples if t.source_mirror_function_id}
    circ_ids = {t.source_mirror_circuit_id for t in triples if t.source_mirror_circuit_id}
    conn_map: dict[uuid.UUID, MirrorRegionConnection] = {}
    fn_map: dict[uuid.UUID, MirrorRegionFunction] = {}
    circ_map: dict[uuid.UUID, MirrorRegionCircuit] = {}
    if conn_ids:
        rows = list(
            (await session.execute(
                select(MirrorRegionConnection).where(MirrorRegionConnection.id.in_(conn_ids))
            )).scalars().all()
        )
        conn_map = {r.id: r for r in rows}
    if fn_ids:
        rows = list(
            (await session.execute(
                select(MirrorRegionFunction).where(MirrorRegionFunction.id.in_(fn_ids))
            )).scalars().all()
        )
        fn_map = {r.id: r for r in rows}
    if circ_ids:
        rows = list(
            (await session.execute(
                select(MirrorRegionCircuit).where(MirrorRegionCircuit.id.in_(circ_ids))
            )).scalars().all()
        )
        circ_map = {r.id: r for r in rows}
    return conn_map, fn_map, circ_map


async def _load_circuit_map(
    session: AsyncSession,
    circuit_ids: set[uuid.UUID],
) -> dict[uuid.UUID, MirrorRegionCircuit]:
    if not circuit_ids:
        return {}
    rows = list(
        (await session.execute(
            select(MirrorRegionCircuit).where(MirrorRegionCircuit.id.in_(circuit_ids))
        )).scalars().all()
    )
    return {r.id: r for r in rows}


async def _load_projection_map(
    session: AsyncSession,
    projection_ids: set[uuid.UUID],
) -> dict[uuid.UUID, MirrorRegionConnection]:
    if not projection_ids:
        return {}
    rows = list(
        (await session.execute(
            select(MirrorRegionConnection).where(MirrorRegionConnection.id.in_(projection_ids))
        )).scalars().all()
    )
    return {r.id: r for r in rows}


async def _load_step_map(
    session: AsyncSession,
    step_ids: set[uuid.UUID],
) -> dict[uuid.UUID, MirrorCircuitStep]:
    if not step_ids:
        return {}
    rows = list(
        (await session.execute(
            select(MirrorCircuitStep).where(MirrorCircuitStep.id.in_(step_ids))
        )).scalars().all()
    )
    return {r.id: r for r in rows}


async def _load_cross_results_for_memberships(
    session: AsyncSession,
    memberships: list[MirrorCircuitProjectionMembership],
) -> dict[tuple[uuid.UUID, uuid.UUID], list[MirrorCircuitProjectionCrossValidationResult]]:
    if not memberships:
        return {}
    pairs = {(m.circuit_id, m.projection_id) for m in memberships}
    circuit_ids = {p[0] for p in pairs}
    projection_ids = {p[1] for p in pairs}
    rows = list(
        (await session.execute(
            select(MirrorCircuitProjectionCrossValidationResult).where(
                MirrorCircuitProjectionCrossValidationResult.circuit_id.in_(circuit_ids),
                MirrorCircuitProjectionCrossValidationResult.projection_id.in_(projection_ids),
            )
        )).scalars().all()
    )
    out: dict[tuple[uuid.UUID, uuid.UUID], list[MirrorCircuitProjectionCrossValidationResult]] = {}
    for r in rows:
        out.setdefault((r.circuit_id, r.projection_id), []).append(r)
    return out


async def _count_memberships_by_projection(
    session: AsyncSession,
    projection_ids: set[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not projection_ids:
        return {}
    rows = list(
        (await session.execute(
            select(
                MirrorCircuitProjectionMembership.projection_id,
                func.count(),
            ).where(
                MirrorCircuitProjectionMembership.projection_id.in_(projection_ids)
            ).group_by(MirrorCircuitProjectionMembership.projection_id)
        )).all()
    )
    return {pid: int(cnt) for pid, cnt in rows}


async def _count_steps_by_circuit(
    session: AsyncSession,
    circuit_ids: set[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not circuit_ids:
        return {}
    rows = list(
        (await session.execute(
            select(MirrorCircuitStep.circuit_id, func.count()).where(
                MirrorCircuitStep.circuit_id.in_(circuit_ids)
            ).group_by(MirrorCircuitStep.circuit_id)
        )).all()
    )
    return {cid: int(cnt) for cid, cnt in rows}


async def _count_memberships_by_circuit(
    session: AsyncSession,
    circuit_ids: set[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not circuit_ids:
        return {}
    rows = list(
        (await session.execute(
            select(MirrorCircuitProjectionMembership.circuit_id, func.count()).where(
                MirrorCircuitProjectionMembership.circuit_id.in_(circuit_ids)
            ).group_by(MirrorCircuitProjectionMembership.circuit_id)
        )).all()
    )
    return {cid: int(cnt) for cid, cnt in rows}


async def _count_cross_conflicts_by_circuit(
    session: AsyncSession,
    circuit_ids: set[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not circuit_ids:
        return {}
    rows = list(
        (await session.execute(
            select(
                MirrorCircuitProjectionCrossValidationResult.circuit_id,
                func.count(),
            ).where(
                MirrorCircuitProjectionCrossValidationResult.circuit_id.in_(circuit_ids),
                MirrorCircuitProjectionCrossValidationResult.validation_status == "conflict",
            ).group_by(MirrorCircuitProjectionCrossValidationResult.circuit_id)
        )).all()
    )
    return {cid: int(cnt) for cid, cnt in rows}


async def _count_dual_conflicts_for_object(
    session: AsyncSession,
    object_type: str,
    object_ids: set[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not object_ids:
        return {}
    rows = list(
        (await session.execute(
            select(MirrorDualModelVerificationResult.object_id, func.count()).where(
                MirrorDualModelVerificationResult.object_type == object_type,
                MirrorDualModelVerificationResult.object_id.in_(object_ids),
                MirrorDualModelVerificationResult.consensus_status == "model_conflict",
            ).group_by(MirrorDualModelVerificationResult.object_id)
        )).all()
    )
    return {oid: int(cnt) for oid, cnt in rows}


async def _dual_object_exists(
    session: AsyncSession,
    object_type: str,
    object_id: uuid.UUID,
) -> bool:
    model_map = {
        "circuit": MirrorRegionCircuit,
        "projection": MirrorRegionConnection,
        "circuit_projection_membership": MirrorCircuitProjectionMembership,
        "projection_function": MirrorProjectionFunction,
        "circuit_step": MirrorCircuitStep,
        "triple": MirrorKgTriple,
    }
    model = model_map.get(object_type)
    if model is None:
        return False
    row = await session.get(model, object_id)
    return row is not None


def _count_high_review_checks(outcomes: list[ValidationOutcome]) -> int:
    count = 0
    for outcome in outcomes:
        for check in outcome.checks:
            if mc_rules.is_high_review_check(check):
                count += 1
    return count


async def apply_rule_checked_status_updates(
    session: AsyncSession,
    outcomes: list[ValidationOutcome],
    *,
    objects_by_type: dict[str, list[Any]],
) -> dict[str, int]:
    stats = {"eligible_rule_checked": 0, "skipped_blocked": 0, "skipped_existing_status": 0}
    obj_maps: dict[str, dict[uuid.UUID, Any]] = {}
    for tt, rows in objects_by_type.items():
        obj_maps[tt] = {r.id: r for r in rows}

    status_eligible_types = frozenset({
        "connection", "function", "circuit", "triple", "projection",
        "circuit_step", "projection_function", "circuit_projection_membership",
    })

    for outcome in outcomes:
        if outcome.target_type not in status_eligible_types:
            continue
        obj = obj_maps.get(outcome.target_type, {}).get(outcome.target_id)
        if obj is None:
            continue
        if not hasattr(obj, "mirror_status"):
            continue
        if getattr(obj, "promotion_status", None) == MirrorPromotionStatus.promoted:
            stats["skipped_existing_status"] += 1
            continue
        if outcome.has_blocker_or_error():
            stats["skipped_blocked"] += 1
            continue
        if obj.mirror_status not in RULE_CHECK_ELIGIBLE_MIRROR_STATUSES:
            stats["skipped_existing_status"] += 1
            continue
        obj.mirror_status = MirrorStatus.rule_checked
        stats["eligible_rule_checked"] += 1
    return stats


async def persist_validation_run_and_results(
    session: AsyncSession,
    *,
    target_types: list[str],
    scope: ValidationScope,
    dry_run: bool,
    apply_status_update: bool,
    outcomes: list[ValidationOutcome],
    passed_count: int,
    warning_count: int,
    failed_count: int,
    blocked_count: int,
    result_count: int,
    run_status: str,
) -> MirrorRuleValidationRun:
    now = datetime.now(timezone.utc)
    scope_json = {
        "resource_id": str(scope.resource_id) if scope.resource_id else None,
        "batch_id": str(scope.batch_id) if scope.batch_id else None,
        "source_atlas": scope.source_atlas,
        "source_version": scope.source_version,
        "granularity_level": scope.granularity_level,
        "granularity_family": scope.granularity_family,
        "mirror_status": scope.mirror_statuses,
        "review_status": scope.review_statuses,
        "promotion_status": scope.promotion_statuses,
    }
    run = MirrorRuleValidationRun(
        id=uuid.uuid4(),
        target_types=target_types,
        scope_json=scope_json,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        source_version=scope.source_version,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        status=run_status,
        object_count=len(outcomes),
        passed_count=passed_count,
        warning_count=warning_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
        result_count=result_count,
        dry_run=dry_run,
        apply_status_update=apply_status_update,
        started_at=now,
        finished_at=now,
    )
    session.add(run)
    await session.flush()
    for outcome in outcomes:
        for check in outcome.checks:
            session.add(MirrorRuleValidationResult(
                run_id=run.id,
                target_type=outcome.target_type,
                target_id=outcome.target_id,
                rule_code=check.rule_code,
                severity=check.severity,
                status=check.status,
                message=check.message,
                details_json=check.details_json,
                resource_id=outcome.resource_id,
                batch_id=outcome.batch_id,
                source_atlas=outcome.source_atlas,
                granularity_level=outcome.granularity_level,
                granularity_family=outcome.granularity_family,
            ))
    return run


async def run_mirror_rule_validation(
    session: AsyncSession,
    *,
    target_types: list[str] | None = None,
    scope: ValidationScope | None = None,
    filters: ValidationFilters | None = None,
    connection_ids: list[uuid.UUID] | None = None,
    function_ids: list[uuid.UUID] | None = None,
    circuit_ids: list[uuid.UUID] | None = None,
    triple_ids: list[uuid.UUID] | None = None,
    projection_ids: list[uuid.UUID] | None = None,
    circuit_step_ids: list[uuid.UUID] | None = None,
    projection_function_ids: list[uuid.UUID] | None = None,
    membership_ids: list[uuid.UUID] | None = None,
    cross_validation_result_ids: list[uuid.UUID] | None = None,
    dual_model_result_ids: list[uuid.UUID] | None = None,
    dry_run: bool = True,
    apply_status_update: bool = False,
    limit: int = DEFAULT_VALIDATION_LIMIT,
) -> ValidationRunResult:
    if target_types is None:
        types = ["connection", "function", "circuit", "triple"]
    elif not target_types:
        raise EmptyTargetTypesError()
    else:
        types = target_types

    for t in types:
        if t not in VALID_TARGET_TYPES:
            raise InvalidTargetTypeError(t)
    if limit > MAX_VALIDATION_LIMIT:
        raise LimitExceededError(limit, MAX_VALIDATION_LIMIT)

    sc = scope or ValidationScope()
    flt = filters or ValidationFilters()
    result = ValidationRunResult(dry_run=dry_run)

    collected = await collect_validation_targets(
        session,
        target_types=types,
        scope=sc,
        filters=flt,
        connection_ids=connection_ids,
        function_ids=function_ids,
        circuit_ids=circuit_ids,
        triple_ids=triple_ids,
        projection_ids=projection_ids,
        circuit_step_ids=circuit_step_ids,
        projection_function_ids=projection_function_ids,
        membership_ids=membership_ids,
        cross_validation_result_ids=cross_validation_result_ids,
        dual_model_result_ids=dual_model_result_ids,
        limit=limit,
    )

    connections = collected.get("connection", [])
    functions = collected.get("function", [])
    circuits = collected.get("circuit", [])
    triples = collected.get("triple", [])
    projections = collected.get("projection", [])
    circuit_steps = collected.get("circuit_step", [])
    projection_functions = collected.get("projection_function", [])
    memberships = collected.get("circuit_projection_membership", [])
    cross_results = collected.get("circuit_projection_cross_validation_result", [])
    dual_results = collected.get("dual_model_verification_result", [])

    result.target_counts = {t: len(collected.get(t, [])) for t in types}

    circuit_regions: list[MirrorCircuitRegion] = []
    if circuits:
        cids = [c.id for c in circuits]
        cr_q = select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id.in_(cids))
        circuit_regions = list((await session.execute(cr_q)).scalars().all())

    candidate_ids: set[uuid.UUID] = set()
    for c in connections + projections:
        if c.source_region_candidate_id:
            candidate_ids.add(c.source_region_candidate_id)
        if c.target_region_candidate_id:
            candidate_ids.add(c.target_region_candidate_id)
    for f in functions:
        if f.region_candidate_id:
            candidate_ids.add(f.region_candidate_id)
    for cr in circuit_regions:
        if cr.region_candidate_id:
            candidate_ids.add(cr.region_candidate_id)
    for step in circuit_steps:
        if step.region_candidate_id:
            candidate_ids.add(step.region_candidate_id)

    circuit_id_set = {s.circuit_id for s in circuit_steps} | {c.id for c in circuits} | {m.circuit_id for m in memberships} | {r.circuit_id for r in cross_results}
    projection_id_set = {pf.projection_id for pf in projection_functions} | {p.id for p in projections} | {m.projection_id for m in memberships} | {r.projection_id for r in cross_results}
    step_id_set: set[uuid.UUID] = set()
    for m in memberships:
        if m.source_step_id:
            step_id_set.add(m.source_step_id)
        if m.target_step_id:
            step_id_set.add(m.target_step_id)

    candidate_map = await _load_candidate_map(session, candidate_ids)
    circuit_map = await _load_circuit_map(session, circuit_id_set)
    projection_map = await _load_projection_map(session, projection_id_set)
    step_map = await _load_step_map(session, step_id_set | {s.id for s in circuit_steps})
    conn_map, fn_map, circ_map = await _load_source_maps(session, triples)
    circ_map.update(circuit_map)

    cross_by_membership = await _load_cross_results_for_memberships(session, memberships)
    membership_count_by_projection = await _count_memberships_by_projection(
        session, {p.id for p in projections}
    )
    step_count_by_circuit = await _count_steps_by_circuit(session, {c.id for c in circuits})
    membership_count_by_circuit = await _count_memberships_by_circuit(session, {c.id for c in circuits})
    cross_conflicts_by_circuit = await _count_cross_conflicts_by_circuit(session, {c.id for c in circuits})
    dual_conflicts_by_circuit = await _count_dual_conflicts_for_object(
        session, "circuit", {c.id for c in circuits}
    )

    regions_by_circuit: dict[uuid.UUID, list[MirrorCircuitRegion]] = {}
    for cr in circuit_regions:
        regions_by_circuit.setdefault(cr.circuit_id, []).append(cr)

    conn_dup: dict[tuple[Any, ...], uuid.UUID] = {}
    fn_dup: dict[tuple[Any, ...], uuid.UUID] = {}
    circ_dup: dict[tuple[Any, ...], uuid.UUID] = {}
    triple_dup: dict[tuple[Any, ...], uuid.UUID] = {}
    proj_dup: dict[tuple[Any, ...], uuid.UUID] = {}
    step_order_dup: dict[tuple[uuid.UUID, int], uuid.UUID] = {}
    pf_dup: dict[tuple[Any, ...], uuid.UUID] = {}
    mem_dup: dict[tuple[Any, ...], uuid.UUID] = {}

    outcomes: list[ValidationOutcome] = []

    for conn in connections:
        checks = validate_connection(conn, candidate_map=candidate_map, duplicate_keys=conn_dup)
        outcomes.append(ValidationOutcome(
            target_type="connection", target_id=conn.id, checks=checks,
            resource_id=conn.resource_id, batch_id=conn.batch_id,
            source_atlas=conn.source_atlas, granularity_level=conn.granularity_level,
            granularity_family=conn.granularity_family, mirror_status=conn.mirror_status,
        ))

    for fn in functions:
        checks = validate_function(fn, candidate_map=candidate_map, duplicate_keys=fn_dup)
        outcomes.append(ValidationOutcome(
            target_type="function", target_id=fn.id, checks=checks,
            resource_id=fn.resource_id, batch_id=fn.batch_id,
            source_atlas=fn.source_atlas, granularity_level=fn.granularity_level,
            granularity_family=fn.granularity_family, mirror_status=fn.mirror_status,
        ))

    for circuit in circuits:
        crs = regions_by_circuit.get(circuit.id, [])
        checks = validate_circuit(
            circuit, circuit_regions=crs, candidate_map=candidate_map, duplicate_keys=circ_dup,
        )
        checks.extend(mc_rules.supplement_circuit_macro_clinical(
            circuit,
            step_count=step_count_by_circuit.get(circuit.id, 0),
            membership_count=membership_count_by_circuit.get(circuit.id, 0),
            cross_conflicts=cross_conflicts_by_circuit.get(circuit.id, 0),
            dual_conflicts=dual_conflicts_by_circuit.get(circuit.id, 0),
        ))
        outcomes.append(ValidationOutcome(
            target_type="circuit", target_id=circuit.id, checks=checks,
            resource_id=circuit.resource_id, batch_id=circuit.batch_id,
            source_atlas=circuit.source_atlas, granularity_level=circuit.granularity_level,
            granularity_family=circuit.granularity_family, mirror_status=circuit.mirror_status,
        ))

    for triple in triples:
        checks = validate_triple(
            triple, connection_map=conn_map, function_map=fn_map, circuit_map=circ_map,
            duplicate_keys=triple_dup,
        )
        checks.extend(mc_rules.supplement_triple_macro_clinical(triple))
        outcomes.append(ValidationOutcome(
            target_type="triple", target_id=triple.id, checks=checks,
            resource_id=triple.resource_id, batch_id=triple.batch_id,
            source_atlas=triple.source_atlas, granularity_level=triple.granularity_level,
            granularity_family=triple.granularity_family, mirror_status=triple.mirror_status,
        ))

    for proj in projections:
        checks = mc_rules.validate_projection_macro(
            proj,
            candidate_map=candidate_map,
            membership_count=membership_count_by_projection.get(proj.id, 0),
            duplicate_keys=proj_dup,
        )
        outcomes.append(ValidationOutcome(
            target_type="projection", target_id=proj.id, checks=checks,
            resource_id=proj.resource_id, batch_id=proj.batch_id,
            source_atlas=proj.source_atlas, granularity_level=proj.granularity_level,
            granularity_family=proj.granularity_family, mirror_status=proj.mirror_status,
        ))

    for step in circuit_steps:
        checks = mc_rules.validate_circuit_step(
            step,
            circuit=circuit_map.get(step.circuit_id),
            candidate_map=candidate_map,
            order_dup=step_order_dup,
        )
        outcomes.append(ValidationOutcome(
            target_type="circuit_step", target_id=step.id, checks=checks,
            resource_id=step.resource_id, batch_id=step.batch_id,
            source_atlas=step.source_atlas, granularity_level=step.granularity_level,
            granularity_family=step.granularity_family, mirror_status=step.mirror_status,
        ))

    for pf in projection_functions:
        checks = mc_rules.validate_projection_function(
            pf, projection=projection_map.get(pf.projection_id), duplicate_keys=pf_dup,
        )
        outcomes.append(ValidationOutcome(
            target_type="projection_function", target_id=pf.id, checks=checks,
            resource_id=pf.resource_id, batch_id=pf.batch_id,
            source_atlas=pf.source_atlas, granularity_level=pf.granularity_level,
            granularity_family=pf.granularity_family, mirror_status=pf.mirror_status,
        ))

    for m in memberships:
        cross_list = cross_by_membership.get((m.circuit_id, m.projection_id), [])
        checks = mc_rules.validate_circuit_projection_membership(
            m,
            circuit=circuit_map.get(m.circuit_id),
            projection=projection_map.get(m.projection_id),
            step_map=step_map,
            cross_results=cross_list,
            duplicate_keys=mem_dup,
        )
        outcomes.append(ValidationOutcome(
            target_type="circuit_projection_membership", target_id=m.id, checks=checks,
            resource_id=m.resource_id, batch_id=m.batch_id,
            source_atlas=m.source_atlas, granularity_level=m.granularity_level,
            granularity_family=m.granularity_family, mirror_status=m.mirror_status,
        ))

    for cr in cross_results:
        checks = mc_rules.validate_cross_validation_result(
            cr,
            circuit=circuit_map.get(cr.circuit_id),
            projection=projection_map.get(cr.projection_id),
        )
        outcomes.append(ValidationOutcome(
            target_type="circuit_projection_cross_validation_result", target_id=cr.id, checks=checks,
            resource_id=cr.resource_id, batch_id=cr.batch_id,
            source_atlas=cr.source_atlas, granularity_level=cr.granularity_level,
            granularity_family=cr.granularity_family,
        ))

    for dr in dual_results:
        exists = await _dual_object_exists(session, dr.object_type, dr.object_id)
        checks = mc_rules.validate_dual_model_verification_result(dr, object_exists=exists)
        outcomes.append(ValidationOutcome(
            target_type="dual_model_verification_result", target_id=dr.id, checks=checks,
            resource_id=dr.resource_id, batch_id=dr.batch_id,
            source_atlas=dr.source_atlas, granularity_level=dr.granularity_level,
            granularity_family=dr.granularity_family,
        ))

    result.outcomes = outcomes
    passed, warning, failed, blocked, result_count = summarize_validation_results(outcomes)
    result.passed_count = passed
    result.warning_count = warning
    result.failed_count = failed
    result.blocked_count = blocked
    result.high_review_priority_count = _count_high_review_checks(outcomes)
    result.result_count = result_count

    if blocked > 0 or failed > 0:
        result.run_status = MirrorValidationRunStatus.partially_succeeded
    else:
        result.run_status = MirrorValidationRunStatus.succeeded

    preview_items: list[dict[str, Any]] = []
    for outcome in outcomes:
        for check in outcome.checks:
            preview_items.append({
                "target_type": outcome.target_type,
                "target_id": outcome.target_id,
                "rule_code": check.rule_code,
                "severity": check.severity,
                "status": check.status,
                "message": check.message,
                "details_json": check.details_json,
            })
    result.results_preview = preview_items[:PREVIEW_LIMIT]

    objects_by_type = {
        "connection": connections,
        "function": functions,
        "circuit": circuits,
        "triple": triples,
        "projection": projections,
        "circuit_step": circuit_steps,
        "projection_function": projection_functions,
        "circuit_projection_membership": memberships,
    }

    status_updates = {"eligible_rule_checked": 0, "skipped_blocked": 0, "skipped_existing_status": 0}
    if apply_status_update and not dry_run:
        status_updates = await apply_rule_checked_status_updates(
            session, outcomes, objects_by_type=objects_by_type,
        )
    elif apply_status_update:
        for outcome in outcomes:
            if outcome.target_type not in {
                "connection", "function", "circuit", "triple", "projection",
                "circuit_step", "projection_function", "circuit_projection_membership",
            }:
                continue
            if outcome.has_blocker_or_error():
                status_updates["skipped_blocked"] += 1
            elif outcome.mirror_status not in RULE_CHECK_ELIGIBLE_MIRROR_STATUSES:
                status_updates["skipped_existing_status"] += 1
            else:
                status_updates["eligible_rule_checked"] += 1
    result.status_updates = status_updates

    if not dry_run:
        run = await persist_validation_run_and_results(
            session,
            target_types=types,
            scope=sc,
            dry_run=False,
            apply_status_update=apply_status_update,
            outcomes=outcomes,
            passed_count=passed,
            warning_count=warning,
            failed_count=failed,
            blocked_count=blocked,
            result_count=result_count,
            run_status=result.run_status,
        )
        result.run_id = run.id
        await session.commit()

    return result


async def list_validation_runs(
    session: AsyncSession,
    *,
    target_type: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorRuleValidationRun], int]:
    q = select(MirrorRuleValidationRun)
    count_q = select(func.count()).select_from(MirrorRuleValidationRun)
    if status:
        q = q.where(MirrorRuleValidationRun.status == status)
        count_q = count_q.where(MirrorRuleValidationRun.status == status)
    if resource_id:
        q = q.where(MirrorRuleValidationRun.resource_id == resource_id)
        count_q = count_q.where(MirrorRuleValidationRun.resource_id == resource_id)
    if batch_id:
        q = q.where(MirrorRuleValidationRun.batch_id == batch_id)
        count_q = count_q.where(MirrorRuleValidationRun.batch_id == batch_id)
    if source_atlas:
        q = q.where(MirrorRuleValidationRun.source_atlas == source_atlas)
        count_q = count_q.where(MirrorRuleValidationRun.source_atlas == source_atlas)
    if granularity_level:
        q = q.where(MirrorRuleValidationRun.granularity_level == granularity_level)
        count_q = count_q.where(MirrorRuleValidationRun.granularity_level == granularity_level)
    if target_type:
        q = q.where(MirrorRuleValidationRun.target_types.contains([target_type]))
        count_q = count_q.where(MirrorRuleValidationRun.target_types.contains([target_type]))
    total = int((await session.execute(count_q)).scalar_one())
    rows = list(
        (await session.execute(
            q.order_by(MirrorRuleValidationRun.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return rows, total


async def get_validation_run(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> MirrorRuleValidationRun:
    row = await session.get(MirrorRuleValidationRun, run_id)
    if row is None:
        raise MirrorValidationRunNotFoundError()
    return row


async def list_validation_results(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule_code: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[MirrorRuleValidationResult], int]:
    q = select(MirrorRuleValidationResult)
    count_q = select(func.count()).select_from(MirrorRuleValidationResult)
    filters = []
    if run_id:
        filters.append(MirrorRuleValidationResult.run_id == run_id)
    if target_type:
        filters.append(MirrorRuleValidationResult.target_type == target_type)
    if target_id:
        filters.append(MirrorRuleValidationResult.target_id == target_id)
    if severity:
        filters.append(MirrorRuleValidationResult.severity == severity)
    if status:
        filters.append(MirrorRuleValidationResult.status == status)
    if rule_code:
        filters.append(MirrorRuleValidationResult.rule_code == rule_code)
    if resource_id:
        filters.append(MirrorRuleValidationResult.resource_id == resource_id)
    if batch_id:
        filters.append(MirrorRuleValidationResult.batch_id == batch_id)
    for f in filters:
        q = q.where(f)
        count_q = count_q.where(f)
    total = int((await session.execute(count_q)).scalar_one())
    rows = list(
        (await session.execute(
            q.order_by(MirrorRuleValidationResult.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return rows, total
