"""Circuit-steps-to-projections extraction — LLM run/item + mirror projections/memberships (Step 8.8).

Derives mirror_region_connections (projection semantics) and mirror_circuit_projection_memberships
from ordered mirror_circuit_steps. Does NOT write final_*/kg_*; does NOT auto approve/promote.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import MirrorCircuitStep
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import (
    ConnectionType,
    Directionality,
    EvidenceTargetType,
    EvidenceType,
    MirrorEvidenceRecordCreate,
    MirrorKgTripleCreate,
    MirrorPromotionStatus,
    MirrorRegionConnectionCreate,
    MirrorReviewStatus,
    MirrorStatus,
    TripleObjectType,
    TripleScope,
    TripleSubjectType,
)
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitProjectionMembershipCreate,
    MirrorCircuitProjectionRole,
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
)
from app.services import mirror_kg_service, mirror_macro_clinical_service
from app.services.llm_connection_extraction_service import canonical_pair_key
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

CIRCUIT_STEPS_TO_PROJECTIONS_TEMPLATE_KEY = "circuit_steps_to_projections_v1"
DEFAULT_MAX_PROJECTIONS = 20

VALID_PROJECTION_TYPES = frozenset({
    ConnectionType.structural_connection,
    ConnectionType.functional_connectivity,
    ConnectionType.effective_connectivity,
    ConnectionType.projection,
    ConnectionType.association,
    ConnectionType.coactivation,
    ConnectionType.uncertain_connection,
    ConnectionType.unknown,
})

VALID_DIRECTIONALITY = frozenset({
    Directionality.directed,
    Directionality.undirected,
    Directionality.bidirectional,
    Directionality.unknown,
})

VALID_ROLE_IN_CIRCUIT = frozenset({
    MirrorCircuitProjectionRole.main_path,
    MirrorCircuitProjectionRole.feedback,
    MirrorCircuitProjectionRole.feedforward,
    MirrorCircuitProjectionRole.modulatory,
    MirrorCircuitProjectionRole.relay,
    MirrorCircuitProjectionRole.parallel_branch,
    MirrorCircuitProjectionRole.unknown,
})


class MirrorCircuitNotFoundError(Exception):
    pass


class InvalidCircuitError(Exception):
    pass


class NoCircuitStepsError(Exception):
    pass


class InvalidStepIdsError(Exception):
    pass


class StepNotInCircuitError(Exception):
    pass


class CrossAtlasStepError(Exception):
    pass


class CrossGranularityStepError(Exception):
    pass


class InvalidMembershipConfigError(Exception):
    pass


class MirrorProjectionTableMissingError(Exception):
    pass


class MirrorMembershipTableMissingError(Exception):
    pass


class MirrorPersistError(Exception):
    pass


@dataclass
class CircuitStepsToProjectionsResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.circuit_steps_to_projections
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    circuit_id: uuid.UUID | None = None
    input_step_count: int = 0
    existing_projection_context_count: int = 0
    projection_count: int = 0
    mirror_projection_created_count: int = 0
    mirror_projection_skipped_duplicate_count: int = 0
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
        tpl = DEFAULT_TEMPLATES[CIRCUIT_STEPS_TO_PROJECTIONS_TEMPLATE_KEY]
    return tpl


def _region_label(c: CandidateBrainRegion | None, fallback: str = "") -> str:
    if c is None:
        return fallback
    return c.en_name or c.cn_name or c.std_name or c.raw_name or fallback


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


def _serialize_steps(
    steps: list[MirrorCircuitStep],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> str:
    rows = []
    for s in steps:
        cand = candidate_map.get(s.region_candidate_id) if s.region_candidate_id else None
        rows.append({
            "step_id": str(s.id),
            "step_order": s.step_order,
            "step_name": s.step_name,
            "step_type": s.step_type,
            "role": s.role,
            "region_candidate_id": str(s.region_candidate_id) if s.region_candidate_id else None,
            "en_name": cand.en_name if cand else None,
            "cn_name": cand.cn_name if cand else None,
            "description": s.description,
            "evidence_text": s.evidence_text,
            "confidence": float(s.confidence) if s.confidence is not None else None,
            "uncertainty_reason": s.uncertainty_reason,
        })
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _serialize_existing_projections(projections: list[MirrorRegionConnection]) -> str:
    return json.dumps(
        [
            {
                "projection_id": str(p.id),
                "source_region_candidate_id": str(p.source_region_candidate_id)
                if p.source_region_candidate_id
                else None,
                "target_region_candidate_id": str(p.target_region_candidate_id)
                if p.target_region_candidate_id
                else None,
                "connection_type": p.connection_type,
                "directionality": p.directionality,
                "confidence": float(p.confidence) if p.confidence is not None else None,
                "evidence_text": p.evidence_text,
            }
            for p in projections
        ],
        ensure_ascii=False,
        indent=2,
    )


async def load_circuit_steps(
    session: AsyncSession,
    circuit: MirrorRegionCircuit,
    *,
    step_ids: list[uuid.UUID] | None = None,
) -> tuple[list[MirrorCircuitStep], list[str]]:
    warnings: list[str] = []
    all_steps, _ = await mirror_macro_clinical_service.list_circuit_steps(
        session, circuit_id=circuit.id, limit=500, offset=0
    )
    if not all_steps:
        raise NoCircuitStepsError("circuit has no mirror_circuit_steps; run circuit-to-steps first")

    steps = sorted(all_steps, key=lambda s: s.step_order)
    if step_ids:
        id_set = set(step_ids)
        found = {s.id for s in steps}
        missing = id_set - found
        if missing:
            raise InvalidStepIdsError(f"step_ids not found for circuit: {sorted(str(x) for x in missing)}")
        steps = [s for s in steps if s.id in id_set]
        steps.sort(key=lambda s: s.step_order)

    for s in steps:
        if s.circuit_id != circuit.id:
            raise StepNotInCircuitError(f"step {s.id} does not belong to circuit {circuit.id}")
        if s.source_atlas != circuit.source_atlas:
            raise CrossAtlasStepError(f"step {s.id} source_atlas mismatch")
        if s.granularity_level != circuit.granularity_level:
            raise CrossGranularityStepError(f"step {s.id} granularity_level mismatch")
        if s.granularity_family != circuit.granularity_family:
            raise CrossGranularityStepError(f"step {s.id} granularity_family mismatch")

    return steps, warnings


async def load_candidate_map(
    session: AsyncSession,
    steps: list[MirrorCircuitStep],
) -> dict[uuid.UUID, CandidateBrainRegion]:
    out: dict[uuid.UUID, CandidateBrainRegion] = {}
    for s in steps:
        if s.region_candidate_id and s.region_candidate_id not in out:
            cand = await session.get(CandidateBrainRegion, s.region_candidate_id)
            if cand:
                out[s.region_candidate_id] = cand
    return out


async def load_existing_projections(
    session: AsyncSession,
    circuit: MirrorRegionCircuit,
) -> list[MirrorRegionConnection]:
    rows, _ = await mirror_kg_service.list_mirror_connections(
        session,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        source_atlas=circuit.source_atlas,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        limit=200,
        offset=0,
    )
    return rows


def build_circuit_steps_to_projections_prompt(
    circuit: MirrorRegionCircuit,
    steps: list[MirrorCircuitStep],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    existing_projections: list[MirrorRegionConnection],
    *,
    template_key: str = CIRCUIT_STEPS_TO_PROJECTIONS_TEMPLATE_KEY,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    circuit_json = _serialize_circuit(circuit)
    steps_json = _serialize_steps(steps, candidate_map)
    existing_json = _serialize_existing_projections(existing_projections)
    values = {
        "source_atlas": circuit.source_atlas,
        "granularity_level": circuit.granularity_level,
        "granularity_family": circuit.granularity_family or "",
        "circuit_json": circuit_json,
        "circuit_steps_json": steps_json,
        "existing_projections_json": existing_json,
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "circuit_json": circuit_json,
        "circuit_steps_json": steps_json,
        "existing_projections_json": existing_json,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_circuit_steps_to_projections_response(raw_text: str) -> dict[str, Any]:
    return parse_llm_json_response(raw_text)


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_projection_candidates(
    parsed: dict[str, Any],
    *,
    circuit: MirrorRegionCircuit,
    steps: list[MirrorCircuitStep],
    max_projections: int = DEFAULT_MAX_PROJECTIONS,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    step_by_order = {s.step_order: s for s in steps}
    raw_projections = parsed.get("projections")
    if raw_projections is None:
        return [], ["projections array missing; treating as empty"]
    if not isinstance(raw_projections, list):
        raise ValueError("projections must be an array")

    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, int, str, str]] = set()

    for idx, proj in enumerate(raw_projections):
        if not isinstance(proj, dict):
            warnings.append(f"projections[{idx}] skipped: not an object")
            continue

        try:
            src_order = int(proj.get("source_step_order"))
            tgt_order = int(proj.get("target_step_order"))
        except (TypeError, ValueError):
            warnings.append(f"projections[{idx}] skipped: invalid step_order")
            continue

        if src_order == tgt_order:
            warnings.append(f"projections[{idx}] skipped: source_step_order == target_step_order")
            continue

        src_step = step_by_order.get(src_order)
        tgt_step = step_by_order.get(tgt_order)
        if src_step is None or tgt_step is None:
            warnings.append(f"projections[{idx}] skipped: unknown source/target step_order")
            continue

        if not src_step.region_candidate_id:
            warnings.append(f"projections[{idx}] skipped: source step has no region_candidate_id")
            continue
        if not tgt_step.region_candidate_id:
            warnings.append(f"projections[{idx}] skipped: target step has no region_candidate_id")
            continue

        raw_src_rid = proj.get("source_region_candidate_id")
        raw_tgt_rid = proj.get("target_region_candidate_id")
        try:
            src_rid = uuid.UUID(str(raw_src_rid)) if raw_src_rid else src_step.region_candidate_id
            tgt_rid = uuid.UUID(str(raw_tgt_rid)) if raw_tgt_rid else tgt_step.region_candidate_id
        except (ValueError, TypeError, AttributeError):
            warnings.append(f"projections[{idx}] skipped: invalid region_candidate_id")
            continue

        if src_rid != src_step.region_candidate_id:
            warnings.append(f"projections[{idx}] skipped: source_region_candidate_id mismatch")
            continue
        if tgt_rid != tgt_step.region_candidate_id:
            warnings.append(f"projections[{idx}] skipped: target_region_candidate_id mismatch")
            continue

        proj_type = str(proj.get("projection_type") or ConnectionType.unknown)
        if proj_type not in VALID_PROJECTION_TYPES:
            proj_type = ConnectionType.unknown
            warnings.append(f"projections[{idx}] projection_type coerced to unknown")

        directionality = str(proj.get("directionality") or Directionality.unknown)
        if directionality not in VALID_DIRECTIONALITY:
            directionality = Directionality.unknown
            warnings.append(f"projections[{idx}] directionality coerced to unknown")

        role_in_circuit = str(proj.get("role_in_circuit") or MirrorCircuitProjectionRole.unknown)
        if role_in_circuit not in VALID_ROLE_IN_CIRCUIT:
            role_in_circuit = MirrorCircuitProjectionRole.unknown
            warnings.append(f"projections[{idx}] role_in_circuit coerced to unknown")

        dedupe_key = (src_order, tgt_order, proj_type, directionality)
        if dedupe_key in seen_keys:
            warnings.append(f"projections[{idx}] skipped: duplicate projection key")
            continue
        seen_keys.add(dedupe_key)

        if not proj.get("evidence_text"):
            warnings.append(f"projections[{idx}] missing evidence_text")

        membership = proj.get("circuit_membership") or {}
        membership_confidence = _clamp_confidence(
            membership.get("membership_confidence") if isinstance(membership, dict) else None
        )

        normalized.append({
            "source_step_order": src_order,
            "target_step_order": tgt_order,
            "source_step_id": str(src_step.id),
            "target_step_id": str(tgt_step.id),
            "source_region_candidate_id": str(src_rid),
            "target_region_candidate_id": str(tgt_rid),
            "projection_type": proj_type,
            "directionality": directionality,
            "strength": proj.get("strength"),
            "modality": proj.get("modality"),
            "role_in_circuit": role_in_circuit,
            "confidence": _clamp_confidence(proj.get("confidence")),
            "evidence_text": proj.get("evidence_text"),
            "uncertainty_reason": proj.get("uncertainty_reason"),
            "membership_confidence": membership_confidence,
            "raw": proj,
        })

    return normalized, warnings


async def _find_existing_connection(
    session: AsyncSession,
    *,
    src: uuid.UUID,
    tgt: uuid.UUID,
    connection_type: str,
    directionality: str,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
) -> MirrorRegionConnection | None:
    a, b, ctype, direc = canonical_pair_key(src, tgt, connection_type, directionality)
    blocked = {MirrorPromotionStatus.failed, MirrorPromotionStatus.blocked}

    base = select(MirrorRegionConnection).where(
        MirrorRegionConnection.connection_type == ctype,
        MirrorRegionConnection.directionality == direc,
        MirrorRegionConnection.source_atlas == source_atlas,
        MirrorRegionConnection.granularity_level == granularity_level,
        MirrorRegionConnection.promotion_status.notin_(blocked),
        MirrorRegionConnection.review_status != MirrorReviewStatus.rejected,
        MirrorRegionConnection.mirror_status != MirrorStatus.superseded,
    )
    if resource_id:
        base = base.where(MirrorRegionConnection.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorRegionConnection.batch_id == batch_id)

    if direc == Directionality.undirected:
        q = base.where(
            or_(
                (MirrorRegionConnection.source_region_candidate_id == uuid.UUID(a))
                & (MirrorRegionConnection.target_region_candidate_id == uuid.UUID(b)),
                (MirrorRegionConnection.source_region_candidate_id == uuid.UUID(b))
                & (MirrorRegionConnection.target_region_candidate_id == uuid.UUID(a)),
            )
        )
    else:
        q = base.where(
            MirrorRegionConnection.source_region_candidate_id == uuid.UUID(a),
            MirrorRegionConnection.target_region_candidate_id == uuid.UUID(b),
        )
    return (await session.execute(q.limit(1))).scalar_one_or_none()


def _projection_label(
    src_c: CandidateBrainRegion | None,
    tgt_c: CandidateBrainRegion | None,
    proj: dict[str, Any],
) -> str:
    src_l = _region_label(src_c, proj["source_region_candidate_id"])
    tgt_l = _region_label(tgt_c, proj["target_region_candidate_id"])
    return f"{src_l} -> {tgt_l} ({proj['projection_type']})"


async def create_projection_triples(
    session: AsyncSession,
    *,
    circuit: MirrorRegionCircuit,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    projection: MirrorRegionConnection,
    proj: dict[str, Any],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> int:
    src_rid = uuid.UUID(proj["source_region_candidate_id"])
    tgt_rid = uuid.UUID(proj["target_region_candidate_id"])
    src_c = candidate_map.get(src_rid)
    tgt_c = candidate_map.get(tgt_rid)
    label = _projection_label(src_c, tgt_c, proj)
    common = dict(
        triple_scope=TripleScope.same_granularity,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        llm_run_id=run.id,
        llm_item_id=item.id,
        source_mirror_connection_id=projection.id,
        source_mirror_circuit_id=circuit.id,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        source_atlas=circuit.source_atlas,
        source_version=circuit.source_version,
        confidence=proj.get("confidence"),
        evidence_text=proj.get("evidence_text"),
        uncertainty_reason=proj.get("uncertainty_reason"),
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
    )
    triples = [
        MirrorKgTripleCreate(
            subject_type=TripleSubjectType.connection,
            subject_id=projection.id,
            subject_label=label,
            predicate="projection_has_source_region",
            object_type=TripleObjectType.region_candidate,
            object_id=src_rid,
            object_label=_region_label(src_c, str(src_rid)),
            raw_payload_json={"projection": proj, "triple_kind": "source_region"},
            normalized_payload_json={"predicate": "projection_has_source_region"},
            **common,
        ),
        MirrorKgTripleCreate(
            subject_type=TripleSubjectType.connection,
            subject_id=projection.id,
            subject_label=label,
            predicate="projection_has_target_region",
            object_type=TripleObjectType.region_candidate,
            object_id=tgt_rid,
            object_label=_region_label(tgt_c, str(tgt_rid)),
            raw_payload_json={"projection": proj, "triple_kind": "target_region"},
            normalized_payload_json={"predicate": "projection_has_target_region"},
            **common,
        ),
        MirrorKgTripleCreate(
            subject_type=TripleSubjectType.circuit,
            subject_id=circuit.id,
            subject_label=circuit.circuit_name,
            predicate="circuit_contains_projection",
            object_type=TripleObjectType.connection,
            object_id=projection.id,
            object_label=label,
            raw_payload_json={"projection": proj, "triple_kind": "circuit_contains"},
            normalized_payload_json={"predicate": "circuit_contains_projection"},
            **common,
        ),
        MirrorKgTripleCreate(
            subject_type=TripleSubjectType.connection,
            subject_id=projection.id,
            subject_label=label,
            predicate="projection_belongs_to_circuit",
            object_type=TripleObjectType.circuit,
            object_id=circuit.id,
            object_label=circuit.circuit_name,
            raw_payload_json={"projection": proj, "triple_kind": "belongs_to_circuit"},
            normalized_payload_json={"predicate": "projection_belongs_to_circuit"},
            **common,
        ),
    ]
    for tp in triples:
        await mirror_kg_service.create_mirror_triple(session, tp)
    return len(triples)


async def create_projection_evidence(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    projection: MirrorRegionConnection,
    proj: dict[str, Any],
) -> int:
    if not proj.get("evidence_text"):
        return 0
    ev_payload = MirrorEvidenceRecordCreate(
        evidence_target_type=EvidenceTargetType.mirror_connection,
        evidence_target_id=projection.id,
        resource_id=run.resource_id,
        batch_id=run.batch_id,
        llm_run_id=run.id,
        llm_item_id=item.id,
        evidence_type=EvidenceType.llm_explanation,
        evidence_text=str(proj["evidence_text"]),
        confidence=proj.get("confidence"),
        uncertainty_reason=proj.get("uncertainty_reason"),
    )
    await mirror_kg_service.create_mirror_evidence(session, ev_payload)
    return 1


async def persist_projections_and_memberships(
    session: AsyncSession,
    *,
    circuit: MirrorRegionCircuit,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    projections: list[dict[str, Any]],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    create_mirror_records: bool,
    create_memberships: bool,
    create_triples: bool,
    create_evidence: bool,
) -> tuple[int, int, int, int, int, int, list[str]]:
    proj_created = proj_skipped = mem_created = mem_skipped = triples = evidence = 0
    warnings: list[str] = []

    if not create_mirror_records and not create_memberships:
        return 0, 0, 0, 0, 0, 0, warnings

    session_seen: set[tuple[str, str, str, str]] = set()

    for proj in projections:
        src = uuid.UUID(proj["source_region_candidate_id"])
        tgt = uuid.UUID(proj["target_region_candidate_id"])
        src_step_id = uuid.UUID(proj["source_step_id"])
        tgt_step_id = uuid.UUID(proj["target_step_id"])
        conn_type = proj["projection_type"]
        directionality = proj["directionality"]
        key = canonical_pair_key(src, tgt, conn_type, directionality)

        projection_row: MirrorRegionConnection | None = None
        projection_reused = False

        if create_mirror_records:
            if key in session_seen:
                proj_skipped += 1
                continue
            existing = await _find_existing_connection(
                session,
                src=src,
                tgt=tgt,
                connection_type=conn_type,
                directionality=directionality,
                resource_id=circuit.resource_id,
                batch_id=circuit.batch_id,
                source_atlas=circuit.source_atlas,
                granularity_level=circuit.granularity_level,
            )
            if existing is not None:
                projection_row = existing
                projection_reused = True
                proj_skipped += 1
                session_seen.add(key)
                warnings.append("EXISTING_PROJECTION_REUSED_FOR_MEMBERSHIP")
            else:
                norm_payload = {
                    **proj,
                    "macro_clinical_semantic_type": "projection",
                    "source_circuit_id": str(circuit.id),
                    "source_step_id": str(src_step_id),
                    "target_step_id": str(tgt_step_id),
                }
                payload = MirrorRegionConnectionCreate(
                    source_region_candidate_id=src,
                    target_region_candidate_id=tgt,
                    resource_id=circuit.resource_id,
                    batch_id=circuit.batch_id,
                    llm_run_id=run.id,
                    llm_item_id=item.id,
                    granularity_level=circuit.granularity_level,
                    granularity_family=circuit.granularity_family,
                    source_atlas=circuit.source_atlas,
                    source_version=circuit.source_version,
                    connection_type=conn_type,
                    directionality=directionality,
                    strength=proj.get("strength"),
                    modality=proj.get("modality"),
                    confidence=proj.get("confidence"),
                    evidence_text=proj.get("evidence_text"),
                    uncertainty_reason=proj.get("uncertainty_reason"),
                    raw_payload_json=proj.get("raw") or proj,
                    normalized_payload_json=norm_payload,
                )
                projection_row = await mirror_kg_service.create_mirror_connection(session, payload)
                proj_created += 1
                session_seen.add(key)

                if create_triples:
                    triples += await create_projection_triples(
                        session,
                        circuit=circuit,
                        run=run,
                        item=item,
                        projection=projection_row,
                        proj=proj,
                        candidate_map=candidate_map,
                    )
                if create_evidence:
                    evidence += await create_projection_evidence(
                        session, run=run, item=item, projection=projection_row, proj=proj
                    )
        elif create_memberships:
            raise InvalidMembershipConfigError(
                "create_memberships=true requires create_mirror_records=true to obtain projection_id"
            )

        if create_memberships and projection_row is not None:
            if not src_step_id or not tgt_step_id:
                warnings.append("membership skipped: missing source/target step_id")
                continue
            mem_confidence = proj.get("membership_confidence") or proj.get("confidence")
            mem_payload = MirrorCircuitProjectionMembershipCreate(
                circuit_id=circuit.id,
                projection_id=projection_row.id,
                source_step_id=src_step_id,
                target_step_id=tgt_step_id,
                resource_id=circuit.resource_id,
                batch_id=circuit.batch_id,
                llm_run_id=run.id,
                llm_item_id=item.id,
                granularity_level=circuit.granularity_level,
                granularity_family=circuit.granularity_family,
                source_atlas=circuit.source_atlas,
                source_version=circuit.source_version,
                step_order=proj["source_step_order"],
                role_in_circuit=proj["role_in_circuit"],
                source_method=MirrorMembershipSourceMethod.circuit_to_projection,
                verification_status=MirrorMembershipVerificationStatus.circuit_supported,
                confidence=mem_confidence,
                evidence_text=proj.get("evidence_text"),
                uncertainty_reason=proj.get("uncertainty_reason"),
                raw_payload_json=proj.get("raw") or proj,
                normalized_payload_json={
                    **proj,
                    "projection_reused": projection_reused,
                },
            )
            try:
                await mirror_macro_clinical_service.create_circuit_projection_membership(
                    session, mem_payload
                )
                mem_created += 1
            except mirror_macro_clinical_service.DuplicateMembershipError:
                mem_skipped += 1
                warnings.append(
                    f"duplicate membership for projection {projection_row.id} "
                    f"steps {src_step_id}/{tgt_step_id}"
                )
            except Exception as exc:
                raise MirrorPersistError(f"membership persist failed: {exc}") from exc

    if create_memberships and not create_mirror_records:
        warnings.append("MEMBERSHIP_EVIDENCE_STORED_ON_OBJECT_ONLY")

    return proj_created, proj_skipped, mem_created, mem_skipped, triples, evidence, warnings


async def run_circuit_steps_to_projections_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    circuit_id: uuid.UUID,
    prompt_template_key: str = CIRCUIT_STEPS_TO_PROJECTIONS_TEMPLATE_KEY,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    dry_run: bool = False,
    max_projections: int = DEFAULT_MAX_PROJECTIONS,
    step_ids: list[uuid.UUID] | None = None,
    include_existing_projections: bool = True,
    create_mirror_records: bool = True,
    create_memberships: bool = True,
    create_triples: bool = True,
    create_evidence: bool = True,
) -> CircuitStepsToProjectionsResult:
    if create_memberships and not create_mirror_records:
        raise InvalidMembershipConfigError(
            "create_memberships=true requires create_mirror_records=true"
        )

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

    steps, load_warnings = await load_circuit_steps(
        session, circuit, step_ids=step_ids or None
    )
    all_warnings = list(load_warnings)
    candidate_map = await load_candidate_map(session, steps)

    existing_projections: list[MirrorRegionConnection] = []
    if include_existing_projections:
        existing_projections = await load_existing_projections(session, circuit)

    system_prompt, user_prompt, prompt_json = build_circuit_steps_to_projections_prompt(
        circuit,
        steps,
        candidate_map,
        existing_projections,
        template_key=prompt_template_key,
    )

    result = CircuitStepsToProjectionsResult(
        circuit_id=circuit.id,
        input_step_count=len(steps),
        existing_projection_context_count=len(existing_projections),
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
        task_type=LlmTaskType.circuit_steps_to_projections,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.single_circuit,
        scope_json={
            "circuit_id": str(circuit.id),
            "step_ids": [str(s) for s in (step_ids or [])],
            "max_projections": max_projections,
            "include_existing_projections": include_existing_projections,
            "create_mirror_records": create_mirror_records,
            "create_memberships": create_memberships,
            "create_triples": create_triples,
            "create_evidence": create_evidence,
        },
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        source_atlas=circuit.source_atlas,
        source_version=circuit.source_version,
        status=LlmRunStatus.running,
        input_count=len(steps),
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
        task_type=LlmTaskType.circuit_steps_to_projections,
        item_index=0,
        input_json={
            "circuit_id": str(circuit.id),
            "circuit_json": json.loads(_serialize_circuit(circuit)),
            "steps_json": json.loads(_serialize_steps(steps, candidate_map)),
            "existing_projections_json": json.loads(_serialize_existing_projections(existing_projections)),
            "input_step_count": len(steps),
            "max_projections": max_projections,
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

    normalized_projections: list[dict[str, Any]] = []

    if response.error_message:
        item.status = LlmItemStatus.failed
        item.error_message = response.error_message
        run.status = LlmRunStatus.failed
        run.error_count = 1
    elif response.parsed_json is None:
        try:
            parsed = parse_circuit_steps_to_projections_response(response.raw_text or "")
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
            normalized_projections, norm_warnings = normalize_projection_candidates(
                response.parsed_json,
                circuit=circuit,
                steps=steps,
                max_projections=max_projections,
            )
            all_warnings.extend(norm_warnings)
        except ValueError as exc:
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            run.status = LlmRunStatus.failed
            run.error_count = 1
            normalized_projections = []

    if item.status != LlmItemStatus.failed:
        item.normalized_output_json = {"projections": normalized_projections}
        confidences = [p["confidence"] for p in normalized_projections if p.get("confidence") is not None]
        if confidences:
            item.confidence = sum(confidences) / len(confidences)
        evidences = [p.get("evidence_text") for p in normalized_projections if p.get("evidence_text")]
        if evidences:
            item.evidence_text = "; ".join(str(e) for e in evidences[:3])
        item.status = LlmItemStatus.succeeded if normalized_projections else LlmItemStatus.needs_review
        run.output_count = len(normalized_projections)
        run.status = LlmRunStatus.succeeded

        if normalized_projections and (create_mirror_records or create_memberships):
            try:
                pc, ps, mc, ms, tc, ec, pw = await persist_projections_and_memberships(
                    session,
                    circuit=circuit,
                    run=run,
                    item=item,
                    projections=normalized_projections,
                    candidate_map=candidate_map,
                    create_mirror_records=create_mirror_records,
                    create_memberships=create_memberships,
                    create_triples=create_triples,
                    create_evidence=create_evidence,
                )
                result.mirror_projection_created_count = pc
                result.mirror_projection_skipped_duplicate_count = ps
                result.membership_created_count = mc
                result.membership_skipped_duplicate_count = ms
                result.triple_created_count = tc
                result.evidence_created_count = ec
                all_warnings.extend(pw)
            except ProgrammingError as exc:
                await session.rollback()
                run.status = LlmRunStatus.failed
                run.error_message = f"mirror table missing or inaccessible: {exc}"
                item.status = LlmItemStatus.failed
                item.error_message = run.error_message
                raise MirrorProjectionTableMissingError(run.error_message) from exc
            except MirrorPersistError as exc:
                await session.rollback()
                run.status = LlmRunStatus.failed
                run.error_message = str(exc)
                item.status = LlmItemStatus.failed
                item.error_message = str(exc)
                raise
            except Exception as exc:
                await session.rollback()
                run.status = LlmRunStatus.failed
                run.error_message = f"mirror persist failed: {exc}"
                item.status = LlmItemStatus.failed
                item.error_message = str(exc)
                raise MirrorPersistError(str(exc)) from exc

    run.finished_at = datetime.now(timezone.utc)
    result.run_id = run.id
    result.item_id = item.id
    result.status = run.status
    result.projection_count = len(normalized_projections)
    result.warnings = all_warnings

    await session.commit()
    await session.refresh(run)
    await session.refresh(item)
    return result
