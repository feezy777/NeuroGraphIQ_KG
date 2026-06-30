"""Same-granularity circuit extraction — LLM run/item + Mirror KG (Step 5).

Writes mirror_region_circuits, mirror_circuit_regions, mirror_kg_triples, mirror_evidence_records.
Does NOT write final_* / kg_*; does NOT auto approve/promote.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorCircuitRegion, MirrorRegionCircuit, MirrorRegionConnection, MirrorRegionFunction
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import (
    CircuitRegionRole,
    CircuitType,
    EvidenceTargetType,
    EvidenceType,
    MirrorCircuitRegionCreate,
    MirrorEvidenceRecordCreate,
    MirrorKgTripleCreate,
    MirrorPromotionStatus,
    MirrorRegionCircuitCreate,
    MirrorReviewStatus,
    MirrorStatus,
    TripleObjectType,
    TripleScope,
    TripleSubjectType,
)
from app.services import mirror_kg_service
from app.services.llm_extraction_service import (
    CandidateNotFoundError,
    ProviderNotConfiguredServiceError,
)
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

# No hard cap on candidate count — large selections produce warnings only.
LARGE_CANDIDATE_WARNING_THRESHOLD = 50
DEFAULT_MAX_CIRCUITS = 10
DEFAULT_MIN_REGIONS_PER_CIRCUIT = 2
DEFAULT_MAX_REGIONS_PER_CIRCUIT = 12
CIRCUIT_TEMPLATE_KEY = "same_granularity_circuit_completion_v1"
CONTEXT_LOAD_LIMIT = 200

DEFAULT_ALLOWED_CIRCUIT_TYPES = frozenset({
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

VALID_REGION_ROLES = frozenset({
    CircuitRegionRole.participant,
    CircuitRegionRole.source,
    CircuitRegionRole.target,
    CircuitRegionRole.hub,
    CircuitRegionRole.relay,
    CircuitRegionRole.modulator,
    CircuitRegionRole.unknown,
})


class TooFewCandidatesError(Exception):
    pass


class TooManyCandidatesError(Exception):
    def __init__(self, count: int, maximum: int):
        self.count = count
        self.maximum = maximum
        super().__init__(f"candidate count {count} exceeds max {maximum}")


class CrossAtlasError(Exception):
    def __init__(self, atlases: list[str], candidate_ids: list[str]):
        self.atlases = atlases
        self.candidate_ids = candidate_ids
        super().__init__("candidates span multiple source_atlas values")


class CrossGranularityError(Exception):
    def __init__(self, field: str, values: list[str], candidate_ids: list[str]):
        self.field = field
        self.values = values
        self.candidate_ids = candidate_ids
        super().__init__(f"candidates span multiple {field} values")


class ScopeMismatchError(Exception):
    def __init__(self, field: str, expected: str, candidate_id: str):
        self.field = field
        self.expected = expected
        self.candidate_id = candidate_id
        super().__init__(f"candidate {candidate_id} {field} mismatch")


class InvalidConnectionContextError(Exception):
    def __init__(self, connection_id: str, reason: str):
        self.connection_id = connection_id
        self.reason = reason
        super().__init__(f"invalid connection context {connection_id}: {reason}")


class InvalidFunctionContextError(Exception):
    def __init__(self, function_id: str, reason: str):
        self.function_id = function_id
        self.reason = reason
        super().__init__(f"invalid function context {function_id}: {reason}")


@dataclass
class CircuitExtractionResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.same_granularity_circuit_completion
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    candidate_count: int = 0
    connection_context_count: int = 0
    function_context_count: int = 0
    circuit_count: int = 0
    mirror_circuit_created_count: int = 0
    mirror_circuit_skipped_duplicate_count: int = 0
    circuit_region_created_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool = False
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[CIRCUIT_TEMPLATE_KEY]
    return tpl


def _region_label(c: CandidateBrainRegion) -> str:
    return c.en_name or c.cn_name or c.std_name or c.raw_name


def validate_candidates_homogeneous(
    candidates: list[CandidateBrainRegion],
    *,
    scope_resource_id: uuid.UUID | None = None,
    scope_batch_id: uuid.UUID | None = None,
) -> None:
    if len(candidates) < 2:
        raise TooFewCandidatesError()

    atlases = {c.source_atlas for c in candidates}
    if len(atlases) > 1:
        raise CrossAtlasError(
            sorted(atlases),
            [str(c.id) for c in candidates if c.source_atlas != candidates[0].source_atlas][:5],
        )

    levels = {c.granularity_level for c in candidates}
    if len(levels) > 1:
        raise CrossGranularityError(
            "granularity_level",
            sorted(levels),
            [str(c.id) for c in candidates if c.granularity_level != candidates[0].granularity_level][:5],
        )

    families = {c.granularity_family for c in candidates}
    if len(families) > 1:
        raise CrossGranularityError(
            "granularity_family",
            sorted(families),
            [str(c.id) for c in candidates if c.granularity_family != candidates[0].granularity_family][:5],
        )

    for c in candidates:
        if scope_batch_id and c.batch_id != scope_batch_id:
            raise ScopeMismatchError("batch_id", str(scope_batch_id), str(c.id))
        if scope_resource_id and c.resource_id != scope_resource_id:
            raise ScopeMismatchError("resource_id", str(scope_resource_id), str(c.id))


def _connection_matches_scope(
    conn: MirrorRegionConnection,
    *,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
) -> bool:
    if conn.source_atlas != source_atlas:
        return False
    if conn.granularity_level != granularity_level:
        return False
    if granularity_family and conn.granularity_family != granularity_family:
        return False
    if resource_id and conn.resource_id != resource_id:
        return False
    if batch_id and conn.batch_id != batch_id:
        return False
    if conn.review_status == MirrorReviewStatus.rejected:
        return False
    if conn.promotion_status == MirrorPromotionStatus.failed:
        return False
    if conn.mirror_status == MirrorStatus.human_rejected:
        return False
    return True


def _function_matches_scope(
    fn: MirrorRegionFunction,
    *,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
) -> bool:
    if fn.source_atlas != source_atlas:
        return False
    if fn.granularity_level != granularity_level:
        return False
    if granularity_family and fn.granularity_family != granularity_family:
        return False
    if resource_id and fn.resource_id != resource_id:
        return False
    if batch_id and fn.batch_id != batch_id:
        return False
    if fn.review_status == MirrorReviewStatus.rejected:
        return False
    if fn.promotion_status == MirrorPromotionStatus.failed:
        return False
    if fn.mirror_status == MirrorStatus.human_rejected:
        return False
    return True


def _validate_connection_context(
    conn: MirrorRegionConnection,
    *,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    strict: bool,
) -> None:
    if not _connection_matches_scope(
        conn,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        resource_id=resource_id,
        batch_id=batch_id,
    ):
        reason = "scope/atlas/granularity/review mismatch"
        if strict:
            raise InvalidConnectionContextError(str(conn.id), reason)


def _validate_function_context(
    fn: MirrorRegionFunction,
    *,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    strict: bool,
) -> None:
    if not _function_matches_scope(
        fn,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        resource_id=resource_id,
        batch_id=batch_id,
    ):
        reason = "scope/atlas/granularity/review mismatch"
        if strict:
            raise InvalidFunctionContextError(str(fn.id), reason)


async def load_connection_context(
    session: AsyncSession,
    *,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    connection_ids: list[uuid.UUID] | None,
    include: bool,
) -> tuple[list[MirrorRegionConnection], list[str]]:
    warnings: list[str] = []
    if not include:
        return [], warnings

    if connection_ids:
        rows: list[MirrorRegionConnection] = []
        for cid in connection_ids:
            conn = await session.get(MirrorRegionConnection, cid)
            if conn is None:
                raise InvalidConnectionContextError(str(cid), "not found")
            _validate_connection_context(
                conn,
                source_atlas=source_atlas,
                granularity_level=granularity_level,
                granularity_family=granularity_family,
                resource_id=resource_id,
                batch_id=batch_id,
                strict=True,
            )
            rows.append(conn)
        return rows, warnings

    all_rows, _ = await mirror_kg_service.list_mirror_connections(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        limit=CONTEXT_LOAD_LIMIT,
        offset=0,
    )
    filtered: list[MirrorRegionConnection] = []
    for conn in all_rows:
        if _connection_matches_scope(
            conn,
            source_atlas=source_atlas,
            granularity_level=granularity_level,
            granularity_family=granularity_family,
            resource_id=resource_id,
            batch_id=batch_id,
        ):
            filtered.append(conn)
        else:
            warnings.append(f"filtered connection {conn.id} from auto context")
    return filtered, warnings


async def load_function_context(
    session: AsyncSession,
    *,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    function_ids: list[uuid.UUID] | None,
    include: bool,
) -> tuple[list[MirrorRegionFunction], list[str]]:
    warnings: list[str] = []
    if not include:
        return [], warnings

    if function_ids:
        rows: list[MirrorRegionFunction] = []
        for fid in function_ids:
            fn = await session.get(MirrorRegionFunction, fid)
            if fn is None:
                raise InvalidFunctionContextError(str(fid), "not found")
            _validate_function_context(
                fn,
                source_atlas=source_atlas,
                granularity_level=granularity_level,
                granularity_family=granularity_family,
                resource_id=resource_id,
                batch_id=batch_id,
                strict=True,
            )
            rows.append(fn)
        return rows, warnings

    all_rows, _ = await mirror_kg_service.list_mirror_functions(
        session,
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        limit=CONTEXT_LOAD_LIMIT,
        offset=0,
    )
    filtered: list[MirrorRegionFunction] = []
    for fn in all_rows:
        if _function_matches_scope(
            fn,
            source_atlas=source_atlas,
            granularity_level=granularity_level,
            granularity_family=granularity_family,
            resource_id=resource_id,
            batch_id=batch_id,
        ):
            filtered.append(fn)
        else:
            warnings.append(f"filtered function {fn.id} from auto context")
    return filtered, warnings


def _serialize_connections(conns: list[MirrorRegionConnection]) -> str:
    return json.dumps(
        [
            {
                "connection_id": str(c.id),
                "source_region_candidate_id": str(c.source_region_candidate_id) if c.source_region_candidate_id else None,
                "target_region_candidate_id": str(c.target_region_candidate_id) if c.target_region_candidate_id else None,
                "connection_type": c.connection_type,
                "directionality": c.directionality,
                "confidence": float(c.confidence) if c.confidence is not None else None,
                "evidence_text": c.evidence_text,
            }
            for c in conns
        ],
        ensure_ascii=False,
        indent=2,
    )


def _serialize_functions(fns: list[MirrorRegionFunction]) -> str:
    return json.dumps(
        [
            {
                "function_id": str(f.id),
                "region_candidate_id": str(f.region_candidate_id) if f.region_candidate_id else None,
                "function_term": f.function_term,
                "function_category": f.function_category,
                "relation_type": f.relation_type,
                "confidence": float(f.confidence) if f.confidence is not None else None,
                "evidence_text": f.evidence_text,
            }
            for f in fns
        ],
        ensure_ascii=False,
        indent=2,
    )


def build_circuit_completion_prompt(
    candidates: list[CandidateBrainRegion],
    connections: list[MirrorRegionConnection],
    functions: list[MirrorRegionFunction],
    *,
    template_key: str = CIRCUIT_TEMPLATE_KEY,
    max_circuits: int = DEFAULT_MAX_CIRCUITS,
    min_regions_per_circuit: int = DEFAULT_MIN_REGIONS_PER_CIRCUIT,
    max_regions_per_circuit: int = DEFAULT_MAX_REGIONS_PER_CIRCUIT,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    first = candidates[0]
    regions_json = json.dumps(
        [
            {
                "candidate_id": str(c.id),
                "en_name": c.en_name,
                "cn_name": c.cn_name,
                "raw_name": c.raw_name,
                "laterality": c.laterality,
                "source_atlas": c.source_atlas,
                "granularity_level": c.granularity_level,
                "granularity_family": c.granularity_family,
            }
            for c in candidates
        ],
        ensure_ascii=False,
        indent=2,
    )
    connections_json = _serialize_connections(connections)
    functions_json = _serialize_functions(functions)
    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family or "",
        "regions_json": regions_json,
        "connections_json": connections_json,
        "functions_json": functions_json,
        "max_circuits": str(max_circuits),
        "min_regions_per_circuit": str(min_regions_per_circuit),
        "max_regions_per_circuit": str(max_regions_per_circuit),
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "regions_json": regions_json,
        "connections_json": connections_json,
        "functions_json": functions_json,
        "max_circuits": max_circuits,
        "min_regions_per_circuit": min_regions_per_circuit,
        "max_regions_per_circuit": max_regions_per_circuit,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_circuit_completion_response(raw_text: str) -> dict[str, Any]:
    return parse_llm_json_response(raw_text)


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_circuit_candidates(
    parsed: dict[str, Any],
    *,
    allowed_candidate_ids: set[uuid.UUID],
    max_circuits: int = DEFAULT_MAX_CIRCUITS,
    min_regions_per_circuit: int = DEFAULT_MIN_REGIONS_PER_CIRCUIT,
    max_regions_per_circuit: int = DEFAULT_MAX_REGIONS_PER_CIRCUIT,
    allowed_circuit_types: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    types = allowed_circuit_types or DEFAULT_ALLOWED_CIRCUIT_TYPES
    warnings: list[str] = []
    raw_circuits = parsed.get("circuits")
    if raw_circuits is None:
        return [], ["circuits array missing; treating as empty"]
    if not isinstance(raw_circuits, list):
        raise ValueError("circuits must be an array")

    normalized: list[dict[str, Any]] = []

    for idx, circ in enumerate(raw_circuits):
        if not isinstance(circ, dict):
            warnings.append(f"circuit[{idx}] skipped: not an object")
            continue

        circuit_name = str(circ.get("circuit_name") or "").strip()
        if not circuit_name:
            warnings.append(f"circuit[{idx}] skipped: empty circuit_name")
            continue

        circuit_type = str(circ.get("circuit_type") or CircuitType.unknown)
        if circuit_type not in types:
            circuit_type = CircuitType.unknown
            warnings.append(f"circuit[{idx}] circuit_type coerced to unknown")

        raw_region_ids = circ.get("involved_region_candidate_ids") or []
        if not isinstance(raw_region_ids, list):
            warnings.append(f"circuit[{idx}] skipped: involved_region_candidate_ids not array")
            continue

        region_ids: list[uuid.UUID] = []
        skipped_regions: list[str] = []
        for rid_raw in raw_region_ids:
            try:
                rid = uuid.UUID(str(rid_raw))
            except (ValueError, TypeError, AttributeError):
                skipped_regions.append(str(rid_raw))
                continue
            if rid not in allowed_candidate_ids:
                skipped_regions.append(str(rid))
                continue
            if rid not in region_ids:
                region_ids.append(rid)

        if skipped_regions:
            warnings.append(f"circuit[{idx}] skipped unknown region ids: {skipped_regions[:5]}")

        if len(region_ids) < min_regions_per_circuit:
            warnings.append(
                f"circuit[{idx}] skipped: {len(region_ids)} regions < min {min_regions_per_circuit}"
            )
            continue

        if len(region_ids) > max_regions_per_circuit:
            warnings.append(
                f"circuit[{idx}] note: {len(region_ids)} regions exceeds max_regions_per_circuit ({max_regions_per_circuit}); saving all regions"
            )

        role_map: dict[str, dict[str, Any]] = {}
        region_roles = circ.get("region_roles") or []
        if isinstance(region_roles, list):
            for ridx, rr in enumerate(region_roles):
                if not isinstance(rr, dict):
                    continue
                try:
                    rid = uuid.UUID(str(rr.get("region_candidate_id")))
                except (ValueError, TypeError, AttributeError):
                    warnings.append(f"circuit[{idx}] region_roles[{ridx}] skipped: invalid id")
                    continue
                if rid not in region_ids:
                    continue
                role = str(rr.get("role") or CircuitRegionRole.participant)
                if role not in VALID_REGION_ROLES:
                    role = CircuitRegionRole.unknown
                    warnings.append(f"circuit[{idx}] region role coerced to unknown")
                sort_order = rr.get("sort_order")
                if sort_order is None:
                    sort_order = region_ids.index(rid)
                role_map[str(rid)] = {"role": role, "sort_order": int(sort_order)}

        circuit_regions: list[dict[str, Any]] = []
        seen_roles: set[tuple[str, str]] = set()
        for order, rid in enumerate(region_ids):
            rid_str = str(rid)
            rm = role_map.get(rid_str, {"role": CircuitRegionRole.participant, "sort_order": order})
            key = (rid_str, rm["role"])
            if key in seen_roles:
                continue
            seen_roles.add(key)
            circuit_regions.append({
                "region_candidate_id": rid_str,
                "role": rm["role"],
                "sort_order": rm["sort_order"],
            })

        normalized.append({
            "circuit_name": circuit_name,
            "circuit_name_key": circuit_name.lower().strip(),
            "circuit_type": circuit_type,
            "involved_region_candidate_ids": [str(r) for r in region_ids],
            "region_set_key": sorted(str(r) for r in region_ids),
            "circuit_regions": circuit_regions,
            "function_association": circ.get("function_association"),
            "description": circ.get("description"),
            "confidence": _clamp_confidence(circ.get("confidence")),
            "evidence_text": circ.get("evidence_text"),
            "uncertainty_reason": circ.get("uncertainty_reason"),
            "suggested_triples": circ.get("suggested_triples") or [],
            "raw": circ,
        })

    return normalized, warnings


def circuit_dedup_key(
    circuit_name_key: str,
    circuit_type: str,
    region_set_key: list[str],
) -> tuple[str, str, tuple[str, ...]]:
    return circuit_name_key, circuit_type, tuple(sorted(region_set_key))


async def _circuit_exists(
    session: AsyncSession,
    *,
    circuit_name_key: str,
    circuit_type: str,
    region_set_key: list[str],
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
) -> bool:
    blocked_promo = {MirrorPromotionStatus.failed, MirrorPromotionStatus.blocked}
    q = select(MirrorRegionCircuit.id).where(
        MirrorRegionCircuit.circuit_type == circuit_type,
        MirrorRegionCircuit.source_atlas == source_atlas,
        MirrorRegionCircuit.granularity_level == granularity_level,
        MirrorRegionCircuit.promotion_status.notin_(blocked_promo),
        MirrorRegionCircuit.review_status != MirrorReviewStatus.rejected,
        MirrorRegionCircuit.mirror_status != MirrorStatus.superseded,
    )
    if resource_id:
        q = q.where(MirrorRegionCircuit.resource_id == resource_id)
    if batch_id:
        q = q.where(MirrorRegionCircuit.batch_id == batch_id)

    ids = (await session.execute(q)).scalars().all()
    if not ids:
        return False

    target_set = set(region_set_key)
    for cid in ids:
        circuit = await session.get(MirrorRegionCircuit, cid)
        if circuit is None:
            continue
        if (circuit.circuit_name or "").lower().strip() != circuit_name_key:
            continue
        norm = circuit.normalized_payload_json or {}
        region_ids_from_norm = norm.get("region_set_key") or norm.get("involved_region_candidate_ids")
        if region_ids_from_norm:
            existing_set = set(region_ids_from_norm)
        else:
            # Fallback: derive involved_region_candidate_ids from MirrorCircuitRegion children
            regions_q = select(MirrorCircuitRegion.region_candidate_id).where(
                MirrorCircuitRegion.circuit_id == circuit.id
            )
            region_rows = (await session.execute(regions_q)).scalars().all()
            existing_set = set(str(r) for r in region_rows if r is not None)
        if existing_set == target_set:
            return True
    return False


async def persist_circuit_mirror_records(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    circuits: list[dict[str, Any]],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    create_triples: bool,
    create_evidence: bool,
    session_seen: set[tuple[str, str, tuple[str, ...]]] | None = None,
) -> tuple[int, int, int, int, int, list[str]]:
    created = skipped = regions_created = triples = evidence = 0
    warnings: list[str] = []
    seen = session_seen or set()

    for circ in circuits:
        name_key = circ["circuit_name_key"]
        ctype = circ["circuit_type"]
        region_set = circ["region_set_key"]
        key = circuit_dedup_key(name_key, ctype, region_set)
        if key in seen:
            skipped += 1
            continue
        if await _circuit_exists(
            session,
            circuit_name_key=name_key,
            circuit_type=ctype,
            region_set_key=region_set,
            resource_id=run.resource_id,
            batch_id=run.batch_id,
            source_atlas=run.source_atlas or "",
            granularity_level=run.granularity_level or "",
        ):
            skipped += 1
            seen.add(key)
            continue

        region_payloads = [
            MirrorCircuitRegionCreate(
                region_candidate_id=uuid.UUID(cr["region_candidate_id"]),
                role=cr["role"],
                sort_order=cr["sort_order"],
            )
            for cr in circ["circuit_regions"]
        ]

        payload = MirrorRegionCircuitCreate(
            resource_id=run.resource_id,
            batch_id=run.batch_id,
            llm_run_id=run.id,
            llm_item_id=item.id,
            granularity_level=run.granularity_level or "",
            granularity_family=run.granularity_family,
            source_atlas=run.source_atlas or "",
            source_version=run.source_version,
            circuit_name=circ["circuit_name"],
            circuit_type=ctype,
            function_association=circ.get("function_association"),
            description=circ.get("description"),
            confidence=circ.get("confidence"),
            evidence_text=circ.get("evidence_text"),
            uncertainty_reason=circ.get("uncertainty_reason"),
            raw_payload_json=circ.get("raw") or circ,
            normalized_payload_json=circ,
            circuit_regions=region_payloads,
        )
        mirror_circuit = await mirror_kg_service.create_mirror_circuit(session, payload)
        created += 1
        regions_created += len(region_payloads)
        seen.add(key)

        if create_triples:
            for cr in circ["circuit_regions"]:
                rid = uuid.UUID(cr["region_candidate_id"])
                region_c = candidate_map.get(rid)
                triple_payload = MirrorKgTripleCreate(
                    subject_type=TripleSubjectType.circuit,
                    subject_id=mirror_circuit.id,
                    subject_label=circ["circuit_name"],
                    predicate="has_participant_region",
                    object_type=TripleObjectType.region_candidate,
                    object_id=rid,
                    object_label=_region_label(region_c) if region_c else cr["region_candidate_id"],
                    triple_scope=TripleScope.same_granularity,
                    resource_id=run.resource_id,
                    batch_id=run.batch_id,
                    llm_run_id=run.id,
                    llm_item_id=item.id,
                    source_mirror_circuit_id=mirror_circuit.id,
                    granularity_level=run.granularity_level or "",
                    granularity_family=run.granularity_family,
                    source_atlas=run.source_atlas or "",
                    source_version=run.source_version,
                    confidence=circ.get("confidence"),
                    evidence_text=circ.get("evidence_text"),
                    uncertainty_reason=circ.get("uncertainty_reason"),
                    raw_payload_json={"circuit_region": cr},
                    normalized_payload_json={"predicate": "has_participant_region"},
                )
                await mirror_kg_service.create_mirror_triple(session, triple_payload)
                triples += 1

            func_assoc = str(circ.get("function_association") or "").strip()
            if func_assoc:
                fn_triple = MirrorKgTripleCreate(
                    subject_type=TripleSubjectType.circuit,
                    subject_id=mirror_circuit.id,
                    subject_label=circ["circuit_name"],
                    predicate="associated_with_function",
                    object_type=TripleObjectType.function,
                    object_id=None,
                    object_label=func_assoc,
                    triple_scope=TripleScope.same_granularity,
                    resource_id=run.resource_id,
                    batch_id=run.batch_id,
                    llm_run_id=run.id,
                    llm_item_id=item.id,
                    source_mirror_circuit_id=mirror_circuit.id,
                    granularity_level=run.granularity_level or "",
                    granularity_family=run.granularity_family,
                    source_atlas=run.source_atlas or "",
                    source_version=run.source_version,
                    confidence=circ.get("confidence"),
                    evidence_text=circ.get("evidence_text"),
                    uncertainty_reason=circ.get("uncertainty_reason"),
                    raw_payload_json={"function_association": func_assoc},
                    normalized_payload_json={"predicate": "associated_with_function"},
                )
                await mirror_kg_service.create_mirror_triple(session, fn_triple)
                triples += 1

        if create_evidence and circ.get("evidence_text"):
            ev_payload = MirrorEvidenceRecordCreate(
                evidence_target_type=EvidenceTargetType.mirror_circuit,
                evidence_target_id=mirror_circuit.id,
                resource_id=run.resource_id,
                batch_id=run.batch_id,
                llm_run_id=run.id,
                llm_item_id=item.id,
                evidence_type=EvidenceType.llm_explanation,
                evidence_text=str(circ["evidence_text"]),
                confidence=circ.get("confidence"),
                uncertainty_reason=circ.get("uncertainty_reason"),
            )
            await mirror_kg_service.create_mirror_evidence(session, ev_payload)
            evidence += 1

    return created, skipped, regions_created, triples, evidence, warnings


async def run_same_granularity_circuit_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    candidate_ids: list[uuid.UUID],
    scope_resource_id: uuid.UUID | None = None,
    scope_batch_id: uuid.UUID | None = None,
    prompt_template_key: str = CIRCUIT_TEMPLATE_KEY,
    temperature: float = 0.2,
    max_tokens: int = 5000,
    dry_run: bool = False,
    max_circuits: int = DEFAULT_MAX_CIRCUITS,
    min_regions_per_circuit: int = DEFAULT_MIN_REGIONS_PER_CIRCUIT,
    max_regions_per_circuit: int = DEFAULT_MAX_REGIONS_PER_CIRCUIT,
    include_connection_context: bool = True,
    include_function_context: bool = True,
    connection_ids: list[uuid.UUID] | None = None,
    function_ids: list[uuid.UUID] | None = None,
    allowed_circuit_types: list[str] | None = None,
    create_mirror_records: bool = True,
    create_triples: bool = True,
    create_evidence: bool = True,
) -> CircuitExtractionResult:
    if len(candidate_ids) < 2:
        raise TooFewCandidatesError()

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

    candidates: list[CandidateBrainRegion] = []
    for cid in candidate_ids:
        cand = await session.get(CandidateBrainRegion, cid)
        if cand is None:
            raise CandidateNotFoundError(str(cid))
        candidates.append(cand)

    validate_candidates_homogeneous(
        candidates,
        scope_resource_id=scope_resource_id,
        scope_batch_id=scope_batch_id,
    )

    first = candidates[0]
    all_warnings: list[str] = []

    connections, conn_warnings = await load_connection_context(
        session,
        source_atlas=first.source_atlas,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        resource_id=scope_resource_id or first.resource_id,
        batch_id=scope_batch_id or first.batch_id,
        connection_ids=connection_ids,
        include=include_connection_context,
    )
    all_warnings.extend(conn_warnings)

    functions, fn_warnings = await load_function_context(
        session,
        source_atlas=first.source_atlas,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        resource_id=scope_resource_id or first.resource_id,
        batch_id=scope_batch_id or first.batch_id,
        function_ids=function_ids,
        include=include_function_context,
    )
    all_warnings.extend(fn_warnings)

    allowed_types = frozenset(allowed_circuit_types) if allowed_circuit_types else DEFAULT_ALLOWED_CIRCUIT_TYPES

    system_prompt, user_prompt, prompt_json = build_circuit_completion_prompt(
        candidates,
        connections,
        functions,
        template_key=prompt_template_key,
        max_circuits=max_circuits,
        min_regions_per_circuit=min_regions_per_circuit,
        max_regions_per_circuit=max_regions_per_circuit,
    )

    result = CircuitExtractionResult(
        candidate_count=len(candidates),
        connection_context_count=len(connections),
        function_context_count=len(functions),
        dry_run=dry_run,
        provider=provider_key,
        model_name=resolved_model,
        warnings=all_warnings,
    )

    if len(candidates) > LARGE_CANDIDATE_WARNING_THRESHOLD:
        result.warnings.append(
            f"LARGE_CANDIDATE_COUNT: candidate_count={len(candidates)} may increase prompt size, cost, and runtime"
        )

    if dry_run:
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt
        return result

    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.same_granularity_circuit_completion,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "candidate_ids": [str(c.id) for c in candidates],
            "connection_ids": [str(c.id) for c in connections],
            "function_ids": [str(f.id) for f in functions],
            "max_circuits": max_circuits,
            "min_regions_per_circuit": min_regions_per_circuit,
            "max_regions_per_circuit": max_regions_per_circuit,
            "include_connection_context": include_connection_context,
            "include_function_context": include_function_context,
        },
        resource_id=scope_resource_id or first.resource_id,
        batch_id=scope_batch_id or first.batch_id,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        source_atlas=first.source_atlas,
        source_version=first.source_version,
        status=LlmRunStatus.running,
        input_count=len(candidates),
        temperature=temperature,
        max_tokens=max_tokens,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    item = LlmExtractionItem(
        run_id=run.id,
        candidate_id=None,
        resource_id=run.resource_id,
        batch_id=run.batch_id,
        task_type=LlmTaskType.same_granularity_circuit_completion,
        item_index=0,
        input_json={
            "candidate_ids": [str(c.id) for c in candidates],
            "connection_context_count": len(connections),
            "function_context_count": len(functions),
            "max_circuits": max_circuits,
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

    normalized_circuits: list[dict[str, Any]] = []

    if response.error_message:
        item.status = LlmItemStatus.failed
        item.error_message = response.error_message
        run.status = LlmRunStatus.failed
        run.error_count = 1
    elif response.parsed_json is None:
        raw_text = response.raw_text or ""
        parsed = None
        last_error = None
        max_provider_attempts = 2
        for attempt in range(max_provider_attempts):
            try:
                parsed = parse_circuit_completion_response(raw_text)
                if parsed is not None:
                    break
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = str(exc)
                if attempt < max_provider_attempts - 1:
                    response = await provider.complete_json(
                        model=resolved_model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    raw_text = response.raw_text or ""
                    item.raw_response_text = raw_text
                    run.usage_json = response.usage.as_dict() if response.usage else {}
        if parsed is None:
            item.status = LlmItemStatus.failed
            item.error_message = f"failed to parse model JSON after {max_provider_attempts} attempts: {last_error}"
            run.status = LlmRunStatus.failed
            run.error_count = 1
        else:
            response.parsed_json = parsed

    if response.parsed_json is not None and item.status != LlmItemStatus.failed:
        item.parsed_response_json = response.parsed_json
        try:
            normalized_circuits, norm_warnings = normalize_circuit_candidates(
                response.parsed_json,
                allowed_candidate_ids={c.id for c in candidates},
                max_circuits=max_circuits,
                min_regions_per_circuit=min_regions_per_circuit,
                max_regions_per_circuit=max_regions_per_circuit,
                allowed_circuit_types=allowed_types,
            )
            all_warnings.extend(norm_warnings)
        except ValueError as exc:
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            run.status = LlmRunStatus.failed
            run.error_count = 1
            normalized_circuits = []

    if item.status != LlmItemStatus.failed:
        item.normalized_output_json = {"circuits": normalized_circuits}
        confidences = [c["confidence"] for c in normalized_circuits if c.get("confidence") is not None]
        if confidences:
            item.confidence = sum(confidences) / len(confidences)
        item.status = LlmItemStatus.succeeded if normalized_circuits else LlmItemStatus.needs_review
        run.output_count = len(normalized_circuits)
        run.status = LlmRunStatus.succeeded

        candidate_map = {c.id: c for c in candidates}
        if create_mirror_records and normalized_circuits:
            try:
                mc, skip, rc, tr, ev, pw = await persist_circuit_mirror_records(
                    session,
                    run=run,
                    item=item,
                    circuits=normalized_circuits,
                    candidate_map=candidate_map,
                    create_triples=create_triples,
                    create_evidence=create_evidence,
                )
                result.mirror_circuit_created_count = mc
                result.mirror_circuit_skipped_duplicate_count = skip
                result.circuit_region_created_count = rc
                result.triple_created_count = tr
                result.evidence_created_count = ev
                all_warnings.extend(pw)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                run.status = LlmRunStatus.partially_succeeded
                run.error_message = f"mirror persist failed: {exc}"
                all_warnings.append(str(exc))

    run.finished_at = datetime.now(timezone.utc)
    result.run_id = run.id
    result.item_id = item.id
    result.status = run.status
    result.circuit_count = len(normalized_circuits)
    result.warnings = all_warnings

    await session.commit()
    await session.refresh(run)
    await session.refresh(item)
    return result
