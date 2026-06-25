"""Projections-to-circuits reverse extraction — LLM run/item + mirror circuits/steps/memberships (Step 8.10).

Infers mirror_region_circuits from mirror_region_connections projection graph.
Does NOT write final_*/kg_*; does NOT auto approve/promote; does NOT cross-validate.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership, MirrorCircuitStep
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import (
    CircuitType,
    EvidenceTargetType,
    EvidenceType,
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
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitProjectionMembershipCreate,
    MirrorCircuitProjectionRole,
    MirrorCircuitStepCreate,
    MirrorCircuitStepRole,
    MirrorCircuitStepType,
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
)
from app.services import mirror_kg_service, mirror_macro_clinical_service
from app.services.llm_circuit_extraction_service import circuit_dedup_key
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_projection_function_extraction_service import (
    CrossAtlasProjectionError,
    CrossGranularityProjectionError,
    InvalidProjectionError,
    ProjectionNotFoundError,
    _homogeneous_field,
    _region_label,
    load_region_map_for_projections,
)
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

PROJECTIONS_TO_CIRCUITS_TEMPLATE_KEY = "projections_to_circuits_v1"
MIN_PROJECTIONS = 2
MAX_PROJECTIONS = 100
DEFAULT_MAX_CIRCUITS = 10
DEFAULT_MAX_STEPS_PER_CIRCUIT = 20
REGION_REUSE_JACCARD_THRESHOLD = 0.8

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

VALID_STEP_ROLES = frozenset({
    MirrorCircuitStepRole.source,
    MirrorCircuitStepRole.target,
    MirrorCircuitStepRole.relay,
    MirrorCircuitStepRole.hub,
    MirrorCircuitStepRole.modulator,
    MirrorCircuitStepRole.participant,
    MirrorCircuitStepRole.unknown,
})


class EmptyProjectionsError(Exception):
    pass


class TooFewProjectionsError(Exception):
    pass


class TooManyProjectionsError(Exception):
    def __init__(self, count: int, maximum: int):
        self.count = count
        self.maximum = maximum
        super().__init__(f"projection count {count} exceeds max {maximum}")


class InvalidMembershipConfigError(Exception):
    pass


class MirrorPersistError(Exception):
    pass


@dataclass
class ProjectionsToCircuitsResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.projections_to_circuits
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    projection_count: int = 0
    existing_circuit_context_count: int = 0
    inferred_circuit_count: int = 0
    mirror_circuit_created_count: int = 0
    mirror_circuit_reused_count: int = 0
    mirror_circuit_skipped_duplicate_count: int = 0
    circuit_step_created_count: int = 0
    circuit_step_skipped_duplicate_count: int = 0
    membership_created_count: int = 0
    membership_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool = False
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[PROJECTIONS_TO_CIRCUITS_TEMPLATE_KEY]
    return tpl


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def validate_projections_for_circuit_inference(projections: list[MirrorRegionConnection]) -> None:
    if not projections:
        raise EmptyProjectionsError()
    if len(projections) < MIN_PROJECTIONS:
        raise TooFewProjectionsError()
    if len(projections) > MAX_PROJECTIONS:
        raise TooManyProjectionsError(len(projections), MAX_PROJECTIONS)
    for p in projections:
        if not p.source_atlas:
            raise InvalidProjectionError(f"projection {p.id} missing source_atlas")
        if not p.granularity_level:
            raise InvalidProjectionError(f"projection {p.id} missing granularity_level")
    atlases = {p.source_atlas for p in projections}
    if len(atlases) > 1:
        raise CrossAtlasProjectionError(sorted(atlases))
    levels = {p.granularity_level for p in projections}
    if len(levels) > 1:
        raise CrossGranularityProjectionError("granularity_level", sorted(levels))
    families = {p.granularity_family for p in projections}
    if len(families) > 1:
        raise CrossGranularityProjectionError("granularity_family", sorted(families))


def _serialize_projection_row(
    p: MirrorRegionConnection,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> dict[str, Any]:
    src_id = p.source_region_candidate_id
    tgt_id = p.target_region_candidate_id
    src_c = candidate_map.get(src_id) if src_id else None
    tgt_c = candidate_map.get(tgt_id) if tgt_id else None
    return {
        "projection_id": str(p.id),
        "source_region_candidate_id": str(src_id) if src_id else None,
        "source_region_en_name": src_c.en_name if src_c else None,
        "source_region_cn_name": src_c.cn_name if src_c else None,
        "target_region_candidate_id": str(tgt_id) if tgt_id else None,
        "target_region_en_name": tgt_c.en_name if tgt_c else None,
        "target_region_cn_name": tgt_c.cn_name if tgt_c else None,
        "connection_type": p.connection_type,
        "projection_type": p.connection_type,
        "directionality": p.directionality,
        "strength": p.strength,
        "modality": p.modality,
        "confidence": float(p.confidence) if p.confidence is not None else None,
        "evidence_text": p.evidence_text,
        "uncertainty_reason": p.uncertainty_reason,
        "source_atlas": p.source_atlas,
        "granularity_level": p.granularity_level,
        "granularity_family": p.granularity_family,
    }


def _union_find_components(region_ids: set[uuid.UUID], edges: list[tuple[uuid.UUID, uuid.UUID]]) -> list[list[str]]:
    parent = {r: r for r in region_ids}

    def find(x: uuid.UUID) -> uuid.UUID:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: uuid.UUID, b: uuid.UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in edges:
        if a in parent and b in parent:
            union(a, b)

    groups: dict[uuid.UUID, set[str]] = defaultdict(set)
    for r in region_ids:
        groups[find(r)].add(str(r))
    return [sorted(g) for g in groups.values()]


def build_projection_graph_summary(
    projections: list[MirrorRegionConnection],
) -> dict[str, Any]:
    region_ids: set[uuid.UUID] = set()
    directed_edges: list[dict[str, Any]] = []
    undirected_edges: list[dict[str, Any]] = []
    edge_pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
    hub_counts: dict[str, int] = defaultdict(int)

    for p in projections:
        src, tgt = p.source_region_candidate_id, p.target_region_candidate_id
        if src:
            region_ids.add(src)
        if tgt:
            region_ids.add(tgt)
        edge = {
            "projection_id": str(p.id),
            "source_region_candidate_id": str(src) if src else None,
            "target_region_candidate_id": str(tgt) if tgt else None,
            "directionality": p.directionality,
            "connection_type": p.connection_type,
        }
        if p.directionality in ("directed", "bidirectional"):
            directed_edges.append(edge)
        else:
            undirected_edges.append(edge)
        if src and tgt:
            edge_pairs.append((src, tgt))
            hub_counts[str(src)] += 1
            hub_counts[str(tgt)] += 1

    components = _union_find_components(region_ids, edge_pairs)
    repeated_hubs = [
        {"region_candidate_id": rid, "degree": deg}
        for rid, deg in sorted(hub_counts.items(), key=lambda x: -x[1])
        if deg >= 2
 ][:10]

    return {
        "node_count": len(region_ids),
        "edge_count": len(projections),
        "region_ids": sorted(str(r) for r in region_ids),
        "connected_components": components,
        "directed_edges": directed_edges,
        "undirected_edges": undirected_edges,
        "repeated_hubs": repeated_hubs,
        "possible_linear_paths": components,
        "possible_feedback_paths": [
            c for c in components if len(c) >= 3
        ],
    }


def _region_set_from_circuit(circuit: MirrorRegionCircuit) -> set[str]:
    norm = circuit.normalized_payload_json or {}
    ids = norm.get("involved_region_candidate_ids") or norm.get("region_set_key") or []
    return {str(x) for x in ids}


def _region_sets_similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    inter = len(a & b)
    union = len(a | b)
    return union > 0 and inter / union >= REGION_REUSE_JACCARD_THRESHOLD


def _serialize_existing_circuit(circuit: MirrorRegionCircuit) -> dict[str, Any]:
    norm = circuit.normalized_payload_json or {}
    return {
        "circuit_id": str(circuit.id),
        "circuit_name": circuit.circuit_name,
        "circuit_type": circuit.circuit_type,
        "involved_region_candidate_ids": norm.get("involved_region_candidate_ids") or list(_region_set_from_circuit(circuit)),
        "function_association": circuit.function_association,
        "description": circuit.description,
        "confidence": float(circuit.confidence) if circuit.confidence is not None else None,
        "source_atlas": circuit.source_atlas,
        "granularity_level": circuit.granularity_level,
    }


async def load_existing_circuits(
    session: AsyncSession,
    projections: list[MirrorRegionConnection],
) -> list[MirrorRegionCircuit]:
    first = projections[0]
    rows, _ = await mirror_kg_service.list_mirror_circuits(
        session,
        resource_id=first.resource_id,
        batch_id=first.batch_id,
        source_atlas=first.source_atlas,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        limit=100,
        offset=0,
    )
    return rows


def build_projections_to_circuits_prompt(
    projections: list[MirrorRegionConnection],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    graph_summary: dict[str, Any],
    existing_circuits: list[MirrorRegionCircuit],
    *,
    template_key: str = PROJECTIONS_TO_CIRCUITS_TEMPLATE_KEY,
    max_circuits: int = DEFAULT_MAX_CIRCUITS,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    first = projections[0]
    projections_json = json.dumps(
        [_serialize_projection_row(p, candidate_map) for p in projections],
        ensure_ascii=False,
        indent=2,
    )
    graph_summary_json = json.dumps(graph_summary, ensure_ascii=False, indent=2)
    existing_circuits_json = json.dumps(
        [_serialize_existing_circuit(c) for c in existing_circuits],
        ensure_ascii=False,
        indent=2,
    )
    regions_json = json.dumps(
        [
            {
                "region_candidate_id": str(rid),
                "en_name": c.en_name,
                "cn_name": c.cn_name,
            }
            for rid, c in candidate_map.items()
        ],
        ensure_ascii=False,
        indent=2,
    )
    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family or "",
        "max_circuits": str(max_circuits),
        "projections_json": projections_json,
        "projection_graph_summary_json": graph_summary_json,
        "regions_json": regions_json,
        "existing_circuits_json": existing_circuits_json,
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "projections_json": projections_json,
        "projection_graph_summary_json": graph_summary_json,
        "existing_circuits_json": existing_circuits_json,
        "max_circuits": max_circuits,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_projections_to_circuits_response(raw_text: str) -> dict[str, Any]:
    return parse_llm_json_response(raw_text)


def _projection_region_ids(projections: list[MirrorRegionConnection]) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    for p in projections:
        if p.source_region_candidate_id:
            out.add(p.source_region_candidate_id)
        if p.target_region_candidate_id:
            out.add(p.target_region_candidate_id)
    return out


def normalize_inferred_circuit_candidates(
    parsed: dict[str, Any],
    *,
    allowed_projection_ids: set[uuid.UUID],
    projection_map: dict[uuid.UUID, MirrorRegionConnection],
    allowed_region_ids: set[uuid.UUID],
    max_circuits: int = DEFAULT_MAX_CIRCUITS,
    max_steps_per_circuit: int = DEFAULT_MAX_STEPS_PER_CIRCUIT,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    raw_circuits = parsed.get("inferred_circuits")
    if raw_circuits is None:
        return [], ["inferred_circuits array missing; treating as empty"]
    if not isinstance(raw_circuits, list):
        raise ValueError("inferred_circuits must be an array")

    seen_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    normalized: list[dict[str, Any]] = []

    for idx, circ in enumerate(raw_circuits):
        if not isinstance(circ, dict):
            warnings.append(f"inferred_circuit[{idx}] skipped: not an object")
            continue

        circuit_name = str(circ.get("circuit_name") or "").strip()
        if not circuit_name:
            warnings.append(f"inferred_circuit[{idx}] skipped: empty circuit_name")
            continue

        supporting: list[uuid.UUID] = []
        for pid_raw in circ.get("supporting_projection_ids") or []:
            try:
                pid = uuid.UUID(str(pid_raw))
            except (ValueError, TypeError, AttributeError):
                warnings.append(f"inferred_circuit[{idx}] invalid supporting_projection_id: {pid_raw}")
                continue
            if pid not in allowed_projection_ids:
                warnings.append(f"inferred_circuit[{idx}] skipped projection_id not in input: {pid}")
                continue
            supporting.append(pid)
        if not supporting:
            warnings.append(f"inferred_circuit[{idx}] skipped: empty supporting_projection_ids")
            continue

        involved: list[uuid.UUID] = []
        for rid_raw in circ.get("involved_region_candidate_ids") or []:
            try:
                rid = uuid.UUID(str(rid_raw))
            except (ValueError, TypeError, AttributeError):
                continue
            if rid in allowed_region_ids:
                involved.append(rid)
        if not involved:
            derived: set[uuid.UUID] = set()
            for pid in supporting:
                proj = projection_map[pid]
                if proj.source_region_candidate_id:
                    derived.add(proj.source_region_candidate_id)
                if proj.target_region_candidate_id:
                    derived.add(proj.target_region_candidate_id)
            involved = sorted(derived, key=str)
            if not involved:
                warnings.append(f"inferred_circuit[{idx}] skipped: no involved regions")
                continue

        circuit_type = str(circ.get("circuit_type") or CircuitType.unknown)
        if circuit_type not in DEFAULT_ALLOWED_CIRCUIT_TYPES:
            circuit_type = CircuitType.unknown
            warnings.append(f"inferred_circuit[{idx}] circuit_type coerced to unknown")

        involved_set = {str(r) for r in involved}
        name_key = circuit_name.lower().strip()
        dedup_key = circuit_dedup_key(name_key, circuit_type, sorted(involved_set))
        if dedup_key in seen_keys:
            warnings.append(f"inferred_circuit[{idx}] skipped: duplicate circuit candidate")
            continue
        seen_keys.add(dedup_key)

        steps_out: list[dict[str, Any]] = []
        involved_uuid_set = set(involved)
        for sidx, step in enumerate(circ.get("possible_step_order") or []):
            if not isinstance(step, dict):
                continue
            try:
                rid = uuid.UUID(str(step.get("region_candidate_id")))
            except (ValueError, TypeError, AttributeError):
                warnings.append(f"inferred_circuit[{idx}] step[{sidx}] skipped: invalid region")
                continue
            if rid not in involved_uuid_set:
                warnings.append(f"inferred_circuit[{idx}] step[{sidx}] skipped: region not in involved set")
                continue
            step_order = step.get("step_order")
            if step_order is None:
                step_order = len(steps_out) + 1
                warnings.append(f"inferred_circuit[{idx}] step[{sidx}] step_order auto-assigned")
            role = str(step.get("role") or MirrorCircuitStepRole.unknown)
            if role not in VALID_STEP_ROLES:
                role = MirrorCircuitStepRole.unknown
            steps_out.append({
                "step_order": int(step_order),
                "region_candidate_id": str(rid),
                "step_name": str(step.get("step_name") or "").strip() or None,
                "role": role,
                "raw_step": step,
            })

        if not circ.get("evidence_text"):
            warnings.append(f"inferred_circuit[{idx}] warning: evidence_text empty")

        normalized.append({
            "circuit_name": circuit_name,
            "circuit_name_key": name_key,
            "circuit_type": circuit_type,
            "supporting_projection_ids": [str(x) for x in supporting],
            "involved_region_candidate_ids": sorted(involved_set),
            "region_set_key": sorted(involved_set),
            "possible_step_order": steps_out,
            "function_association": circ.get("function_association"),
            "description": circ.get("description"),
            "confidence": _clamp_confidence(circ.get("confidence")),
            "evidence_text": circ.get("evidence_text"),
            "uncertainty_reason": circ.get("uncertainty_reason"),
            "raw": circ,
        })

    return normalized, warnings


async def _find_reusable_circuit(
    session: AsyncSession,
    *,
    circuit_name_key: str,
    circuit_type: str,
    region_set: set[str],
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
) -> MirrorRegionCircuit | None:
    blocked = {MirrorPromotionStatus.failed, MirrorPromotionStatus.blocked}
    q = select(MirrorRegionCircuit).where(
        MirrorRegionCircuit.source_atlas == source_atlas,
        MirrorRegionCircuit.granularity_level == granularity_level,
        MirrorRegionCircuit.promotion_status.notin_(blocked),
        MirrorRegionCircuit.review_status != MirrorReviewStatus.rejected,
        MirrorRegionCircuit.mirror_status != MirrorStatus.superseded,
    )
    if resource_id:
        q = q.where(MirrorRegionCircuit.resource_id == resource_id)
    if batch_id:
        q = q.where(MirrorRegionCircuit.batch_id == batch_id)
    rows = (await session.execute(q.limit(50))).scalars().all()
    for circuit in rows:
        if (circuit.circuit_name or "").lower().strip() != circuit_name_key:
            continue
        existing_type = circuit.circuit_type or CircuitType.unknown
        if circuit_type != CircuitType.unknown and existing_type != CircuitType.unknown and circuit_type != existing_type:
            continue
        existing_regions = _region_set_from_circuit(circuit)
        if _region_sets_similar(region_set, existing_regions):
            return circuit
    return None


async def _circuit_exists_exact(
    session: AsyncSession,
    *,
    circuit_name_key: str,
    circuit_type: str,
    region_set_key: list[str],
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
) -> MirrorRegionCircuit | None:
    return await _find_reusable_circuit(
        session,
        circuit_name_key=circuit_name_key,
        circuit_type=circuit_type,
        region_set=set(region_set_key),
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
    )


def _projection_label(
    projection: MirrorRegionConnection,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> str:
    src_c = candidate_map.get(projection.source_region_candidate_id) if projection.source_region_candidate_id else None
    tgt_c = candidate_map.get(projection.target_region_candidate_id) if projection.target_region_candidate_id else None
    src_l = _region_label(src_c, str(projection.source_region_candidate_id))
    tgt_l = _region_label(tgt_c, str(projection.target_region_candidate_id))
    return f"{src_l} -> {tgt_l} ({projection.connection_type})"


async def create_inferred_circuit_triples(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    circuit: MirrorRegionCircuit,
    circ: dict[str, Any],
    projection_map: dict[uuid.UUID, MirrorRegionConnection],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> int:
    count = 0
    common = dict(
        triple_scope=TripleScope.same_granularity,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        llm_run_id=run.id,
        llm_item_id=item.id,
        source_mirror_circuit_id=circuit.id,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        source_atlas=circuit.source_atlas,
        source_version=circuit.source_version,
        confidence=circ.get("confidence"),
        evidence_text=circ.get("evidence_text"),
        uncertainty_reason=circ.get("uncertainty_reason"),
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    for rid_str in circ.get("involved_region_candidate_ids") or []:
        rid = uuid.UUID(rid_str)
        region_c = candidate_map.get(rid)
        tp = MirrorKgTripleCreate(
            subject_type=TripleSubjectType.circuit,
            subject_id=circuit.id,
            subject_label=circuit.circuit_name,
            predicate="has_participant_region",
            object_type=TripleObjectType.region_candidate,
            object_id=rid,
            object_label=_region_label(region_c, rid_str),
            raw_payload_json={"inferred_circuit": circ},
            normalized_payload_json={"predicate": "has_participant_region"},
            **common,
        )
        await mirror_kg_service.create_mirror_triple(session, tp)
        count += 1

    for pid_str in circ.get("supporting_projection_ids") or []:
        pid = uuid.UUID(pid_str)
        proj = projection_map.get(pid)
        if proj is None:
            continue
        label = _projection_label(proj, candidate_map)
        proj_common = {**common, "source_mirror_connection_id": proj.id}
        for subj_type, subj_id, subj_label, pred, obj_type, obj_id, obj_label in (
            (TripleSubjectType.circuit, circuit.id, circuit.circuit_name, "circuit_contains_projection",
             TripleObjectType.connection, proj.id, label),
            (TripleSubjectType.connection, proj.id, label, "projection_belongs_to_circuit",
             TripleObjectType.circuit, circuit.id, circuit.circuit_name),
        ):
            tp = MirrorKgTripleCreate(
                subject_type=subj_type,
                subject_id=subj_id,
                subject_label=subj_label,
                predicate=pred,
                object_type=obj_type,
                object_id=obj_id,
                object_label=obj_label,
                raw_payload_json={"inferred_circuit": circ, "projection_id": pid_str},
                normalized_payload_json={"predicate": pred},
                **proj_common,
            )
            await mirror_kg_service.create_mirror_triple(session, tp)
            count += 1

    func_assoc = str(circ.get("function_association") or "").strip()
    if func_assoc:
        tp = MirrorKgTripleCreate(
            subject_type=TripleSubjectType.circuit,
            subject_id=circuit.id,
            subject_label=circuit.circuit_name,
            predicate="associated_with_function",
            object_type=TripleObjectType.function,
            object_id=None,
            object_label=func_assoc,
            raw_payload_json={"function_association": func_assoc},
            normalized_payload_json={"predicate": "associated_with_function"},
            **common,
        )
        await mirror_kg_service.create_mirror_triple(session, tp)
        count += 1
    return count


async def create_inferred_circuit_evidence(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    circuit: MirrorRegionCircuit,
    circ: dict[str, Any],
) -> int:
    if not circ.get("evidence_text"):
        return 0
    ev = MirrorEvidenceRecordCreate(
        evidence_target_type=EvidenceTargetType.mirror_circuit,
        evidence_target_id=circuit.id,
        resource_id=run.resource_id,
        batch_id=run.batch_id,
        llm_run_id=run.id,
        llm_item_id=item.id,
        evidence_type=EvidenceType.llm_explanation,
        evidence_text=str(circ["evidence_text"]),
        confidence=circ.get("confidence"),
        uncertainty_reason=circ.get("uncertainty_reason"),
    )
    await mirror_kg_service.create_mirror_evidence(session, ev)
    return 1


async def _step_by_region(
    session: AsyncSession,
    circuit_id: uuid.UUID,
) -> dict[uuid.UUID, MirrorCircuitStep]:
    steps, _ = await mirror_macro_clinical_service.list_circuit_steps(
        session, circuit_id=circuit_id, limit=100, offset=0
    )
    out: dict[uuid.UUID, MirrorCircuitStep] = {}
    for s in steps:
        if s.region_candidate_id and s.region_candidate_id not in out:
            out[s.region_candidate_id] = s
    return out


async def persist_inferred_circuits_steps_memberships(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    circuits: list[dict[str, Any]],
    projections: list[MirrorRegionConnection],
    projection_map: dict[uuid.UUID, MirrorRegionConnection],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    first: MirrorRegionConnection,
    reuse_existing_circuits: bool,
    create_mirror_circuits: bool,
    create_circuit_steps: bool,
    create_memberships: bool,
    create_triples: bool,
    create_evidence: bool,
) -> tuple[int, int, int, int, int, int, int, int, int, list[str]]:
    created = reused = circ_skipped = steps_created = steps_skipped = 0
    mem_created = mem_skipped = triples = evidence = 0
    warnings: list[str] = []
    session_seen: set[tuple[str, str, tuple[str, ...]]] = set()

    if not create_mirror_circuits and not (create_memberships and reuse_existing_circuits):
        return 0, 0, 0, 0, 0, 0, 0, 0, 0, warnings

    for circ in circuits:
        name_key = circ["circuit_name_key"]
        ctype = circ["circuit_type"]
        region_set_key = circ["region_set_key"]
        key = circuit_dedup_key(name_key, ctype, region_set_key)
        if key in session_seen:
            circ_skipped += 1
            continue

        circuit_row: MirrorRegionCircuit | None = None
        if reuse_existing_circuits:
            circuit_row = await _find_reusable_circuit(
                session,
                circuit_name_key=name_key,
                circuit_type=ctype,
                region_set=set(region_set_key),
                resource_id=first.resource_id,
                batch_id=first.batch_id,
                source_atlas=first.source_atlas,
                granularity_level=first.granularity_level,
            )
            if circuit_row is not None:
                reused += 1
                session_seen.add(key)

        if circuit_row is None and create_mirror_circuits:
            existing = await _circuit_exists_exact(
                session,
                circuit_name_key=name_key,
                circuit_type=ctype,
                region_set_key=region_set_key,
                resource_id=first.resource_id,
                batch_id=first.batch_id,
                source_atlas=first.source_atlas,
                granularity_level=first.granularity_level,
            )
            if existing is not None:
                circuit_row = existing
                reused += 1
                session_seen.add(key)
            else:
                norm_payload = {
                    "macro_clinical_semantic_type": "circuit",
                    "source_method": MirrorMembershipSourceMethod.projection_to_circuit,
                    "supporting_projection_ids": circ["supporting_projection_ids"],
                    "involved_region_candidate_ids": circ["involved_region_candidate_ids"],
                    "region_set_key": region_set_key,
                }
                payload = MirrorRegionCircuitCreate(
                    resource_id=first.resource_id,
                    batch_id=first.batch_id,
                    llm_run_id=run.id,
                    llm_item_id=item.id,
                    granularity_level=first.granularity_level,
                    granularity_family=first.granularity_family,
                    source_atlas=first.source_atlas,
                    source_version=first.source_version,
                    circuit_name=circ["circuit_name"],
                    circuit_type=ctype,
                    function_association=circ.get("function_association"),
                    description=circ.get("description"),
                    confidence=circ.get("confidence"),
                    evidence_text=circ.get("evidence_text"),
                    uncertainty_reason=circ.get("uncertainty_reason"),
                    raw_payload_json=circ.get("raw") or circ,
                    normalized_payload_json=norm_payload,
                )
                try:
                    circuit_row = await mirror_kg_service.create_mirror_circuit(session, payload)
                    created += 1
                    session_seen.add(key)
                except Exception as exc:
                    raise MirrorPersistError(f"circuit persist failed: {exc}") from exc
        elif circuit_row is None:
            warnings.append(f"circuit {circ['circuit_name']} skipped: no circuit_id and create_mirror_circuits=false")
            continue

        if create_circuit_steps and circ.get("possible_step_order"):
            step_norm_base = {
                "source_method": MirrorMembershipSourceMethod.projection_to_circuit,
                "supporting_projection_ids": circ["supporting_projection_ids"],
            }
            for step in circ["possible_step_order"]:
                existing_step = (
                    await session.execute(
                        select(MirrorCircuitStep).where(
                            MirrorCircuitStep.circuit_id == circuit_row.id,
                            MirrorCircuitStep.step_order == step["step_order"],
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if existing_step is not None:
                    rid = uuid.UUID(step["region_candidate_id"]) if step.get("region_candidate_id") else None
                    if rid and existing_step.region_candidate_id and existing_step.region_candidate_id != rid:
                        warnings.append(
                            f"EXISTING_STEP_ORDER_DIFFERENT_REGION: step_order {step['step_order']}"
                        )
                    else:
                        steps_skipped += 1
                    continue
                region_id = uuid.UUID(step["region_candidate_id"])
                step_payload = MirrorCircuitStepCreate(
                    circuit_id=circuit_row.id,
                    region_candidate_id=region_id,
                    resource_id=circuit_row.resource_id,
                    batch_id=circuit_row.batch_id,
                    llm_run_id=run.id,
                    llm_item_id=item.id,
                    granularity_level=circuit_row.granularity_level,
                    granularity_family=circuit_row.granularity_family,
                    source_atlas=circuit_row.source_atlas,
                    source_version=circuit_row.source_version,
                    step_order=step["step_order"],
                    step_name=step.get("step_name") or _region_label(candidate_map.get(region_id), str(region_id)),
                    step_type=MirrorCircuitStepType.region,
                    role=step["role"],
                    confidence=circ.get("confidence"),
                    evidence_text=circ.get("evidence_text"),
                    uncertainty_reason=circ.get("uncertainty_reason"),
                    raw_payload_json=step.get("raw_step") or step,
                    normalized_payload_json={**step_norm_base, **step},
                )
                try:
                    await mirror_macro_clinical_service.create_circuit_step(session, step_payload)
                    steps_created += 1
                except mirror_macro_clinical_service.DuplicateStepOrderError:
                    steps_skipped += 1

        region_step_map = await _step_by_region(session, circuit_row.id)

        if create_memberships:
            for pid_str in circ.get("supporting_projection_ids") or []:
                pid = uuid.UUID(pid_str)
                proj = projection_map.get(pid)
                if proj is None:
                    continue
                source_step_id = target_step_id = None
                step_order_val = None
                if proj.source_region_candidate_id and proj.source_region_candidate_id in region_step_map:
                    source_step_id = region_step_map[proj.source_region_candidate_id].id
                    step_order_val = region_step_map[proj.source_region_candidate_id].step_order
                if proj.target_region_candidate_id and proj.target_region_candidate_id in region_step_map:
                    target_step_id = region_step_map[proj.target_region_candidate_id].id
                if proj.directionality == "undirected" and source_step_id and target_step_id:
                    s_step = region_step_map.get(proj.source_region_candidate_id)
                    t_step = region_step_map.get(proj.target_region_candidate_id)
                    if s_step and t_step and t_step.step_order < s_step.step_order:
                        source_step_id, target_step_id = t_step.id, s_step.id
                        step_order_val = t_step.step_order

                mem_payload = MirrorCircuitProjectionMembershipCreate(
                    circuit_id=circuit_row.id,
                    projection_id=pid,
                    source_step_id=source_step_id,
                    target_step_id=target_step_id,
                    resource_id=circuit_row.resource_id,
                    batch_id=circuit_row.batch_id,
                    llm_run_id=run.id,
                    llm_item_id=item.id,
                    granularity_level=circuit_row.granularity_level,
                    granularity_family=circuit_row.granularity_family,
                    source_atlas=circuit_row.source_atlas,
                    source_version=circuit_row.source_version,
                    step_order=step_order_val,
                    role_in_circuit=MirrorCircuitProjectionRole.unknown,
                    source_method=MirrorMembershipSourceMethod.projection_to_circuit,
                    verification_status=MirrorMembershipVerificationStatus.projection_supported,
                    confidence=circ.get("confidence"),
                    evidence_text=circ.get("evidence_text"),
                    uncertainty_reason=circ.get("uncertainty_reason"),
                    raw_payload_json=circ.get("raw") or circ,
                    normalized_payload_json={
                        "source_method": MirrorMembershipSourceMethod.projection_to_circuit,
                        "verification_status": MirrorMembershipVerificationStatus.projection_supported,
                        "supporting_projection_ids": circ["supporting_projection_ids"],
                    },
                )
                try:
                    await mirror_macro_clinical_service.create_circuit_projection_membership(
                        session, mem_payload
                    )
                    mem_created += 1
                    if create_evidence and circ.get("evidence_text"):
                        warnings.append("MEMBERSHIP_EVIDENCE_STORED_ON_OBJECT_ONLY")
                except mirror_macro_clinical_service.DuplicateMembershipError:
                    mem_skipped += 1

        if create_triples:
            triples += await create_inferred_circuit_triples(
                session,
                run=run,
                item=item,
                circuit=circuit_row,
                circ=circ,
                projection_map=projection_map,
                candidate_map=candidate_map,
            )
        if create_evidence:
            evidence += await create_inferred_circuit_evidence(
                session, run=run, item=item, circuit=circuit_row, circ=circ
            )

    return created, reused, circ_skipped, steps_created, steps_skipped, mem_created, mem_skipped, triples, evidence, warnings


async def run_projections_to_circuits_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    projection_ids: list[uuid.UUID],
    prompt_template_key: str = PROJECTIONS_TO_CIRCUITS_TEMPLATE_KEY,
    temperature: float = 0.2,
    max_tokens: int = 5000,
    dry_run: bool = False,
    max_circuits: int = DEFAULT_MAX_CIRCUITS,
    max_steps_per_circuit: int = DEFAULT_MAX_STEPS_PER_CIRCUIT,
    include_existing_circuits: bool = True,
    reuse_existing_circuits: bool = True,
    create_mirror_circuits: bool = True,
    create_circuit_steps: bool = True,
    create_memberships: bool = True,
    create_triples: bool = True,
    create_evidence: bool = True,
) -> ProjectionsToCircuitsResult:
    if not projection_ids:
        raise EmptyProjectionsError()
    if create_memberships and not create_mirror_circuits and not reuse_existing_circuits:
        raise InvalidMembershipConfigError(
            "create_memberships=true requires create_mirror_circuits=true or reuse_existing_circuits=true"
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

    projections: list[MirrorRegionConnection] = []
    for pid in projection_ids:
        proj = await session.get(MirrorRegionConnection, pid)
        if proj is None:
            raise ProjectionNotFoundError(str(pid))
        projections.append(proj)

    validate_projections_for_circuit_inference(projections)
    first = projections[0]
    projection_map = {p.id: p for p in projections}
    allowed_region_ids = _projection_region_ids(projections)

    all_warnings: list[str] = []
    for p in projections:
        if not p.source_region_candidate_id or not p.target_region_candidate_id:
            all_warnings.append(
                f"projection {p.id} missing source/target region; graph context may be incomplete"
            )

    candidate_map = await load_region_map_for_projections(session, projections)
    graph_summary = build_projection_graph_summary(projections)
    existing_circuits: list[MirrorRegionCircuit] = []
    if include_existing_circuits:
        existing_circuits = await load_existing_circuits(session, projections)

    system_prompt, user_prompt, prompt_json = build_projections_to_circuits_prompt(
        projections,
        candidate_map,
        graph_summary,
        existing_circuits,
        template_key=prompt_template_key,
        max_circuits=max_circuits,
    )

    result = ProjectionsToCircuitsResult(
        projection_count=len(projections),
        existing_circuit_context_count=len(existing_circuits),
        dry_run=dry_run,
        provider=provider_key,
        model_name=resolved_model,
        warnings=list(all_warnings),
    )

    if dry_run:
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt
        return result

    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.projections_to_circuits,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.projection_selection,
        scope_json={
            "projection_ids": [str(p.id) for p in projections],
            "max_circuits": max_circuits,
            "max_steps_per_circuit": max_steps_per_circuit,
            "create_mirror_circuits": create_mirror_circuits,
            "create_circuit_steps": create_circuit_steps,
            "create_memberships": create_memberships,
            "create_triples": create_triples,
            "create_evidence": create_evidence,
            "reuse_existing_circuits": reuse_existing_circuits,
        },
        resource_id=_homogeneous_field(projections, "resource_id"),
        batch_id=_homogeneous_field(projections, "batch_id"),
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        source_atlas=first.source_atlas,
        source_version=_homogeneous_field(projections, "source_version"),
        status=LlmRunStatus.running,
        input_count=len(projections),
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
        task_type=LlmTaskType.projections_to_circuits,
        item_index=0,
        input_json={
            "projections_json": prompt_json.get("projections_json"),
            "projection_graph_summary_json": prompt_json.get("projection_graph_summary_json"),
            "existing_circuits_json": prompt_json.get("existing_circuits_json"),
            "projection_ids": [str(p.id) for p in projections],
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
        try:
            parsed = parse_projections_to_circuits_response(response.raw_text or "")
        except Exception as exc:
            item.status = LlmItemStatus.failed
            item.error_message = f"failed to parse model JSON: {exc}"
            run.status = LlmRunStatus.failed
            run.error_count = 1
            parsed = None
        if parsed is not None:
            response.parsed_json = parsed

    if response.parsed_json is not None and item.status != LlmItemStatus.failed:
        item.parsed_response_json = response.parsed_json
        try:
            normalized_circuits, norm_warnings = normalize_inferred_circuit_candidates(
                response.parsed_json,
                allowed_projection_ids=set(projection_map.keys()),
                projection_map=projection_map,
                allowed_region_ids=allowed_region_ids,
                max_circuits=max_circuits,
                max_steps_per_circuit=max_steps_per_circuit,
            )
            all_warnings.extend(norm_warnings)
        except ValueError as exc:
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            run.status = LlmRunStatus.failed
            run.error_count = 1
            normalized_circuits = []

    if item.status != LlmItemStatus.failed:
        item.normalized_output_json = {"inferred_circuits": normalized_circuits}
        confidences = [c["confidence"] for c in normalized_circuits if c.get("confidence") is not None]
        if confidences:
            item.confidence = sum(confidences) / len(confidences)
        item.status = LlmItemStatus.succeeded if normalized_circuits else LlmItemStatus.needs_review
        run.output_count = len(normalized_circuits)
        run.status = LlmRunStatus.succeeded

        if normalized_circuits and (create_mirror_circuits or create_memberships):
            try:
                cc, ru, cs, sc, ss, mc, ms, tr, ev, pw = await persist_inferred_circuits_steps_memberships(
                    session,
                    run=run,
                    item=item,
                    circuits=normalized_circuits,
                    projections=projections,
                    projection_map=projection_map,
                    candidate_map=candidate_map,
                    first=first,
                    reuse_existing_circuits=reuse_existing_circuits,
                    create_mirror_circuits=create_mirror_circuits,
                    create_circuit_steps=create_circuit_steps,
                    create_memberships=create_memberships,
                    create_triples=create_triples,
                    create_evidence=create_evidence,
                )
                result.mirror_circuit_created_count = cc
                result.mirror_circuit_reused_count = ru
                result.mirror_circuit_skipped_duplicate_count = cs
                result.circuit_step_created_count = sc
                result.circuit_step_skipped_duplicate_count = ss
                result.membership_created_count = mc
                result.membership_skipped_duplicate_count = ms
                result.triple_created_count = tr
                result.evidence_created_count = ev
                all_warnings.extend(pw)
            except MirrorPersistError as exc:
                run.status = LlmRunStatus.partially_succeeded
                run.error_message = str(exc)
                all_warnings.append(str(exc))

    run.finished_at = datetime.now(timezone.utc)
    result.run_id = run.id
    result.item_id = item.id
    result.status = run.status
    result.inferred_circuit_count = len(normalized_circuits)
    result.warnings = all_warnings

    await session.commit()
    await session.refresh(run)
    await session.refresh(item)
    return result
