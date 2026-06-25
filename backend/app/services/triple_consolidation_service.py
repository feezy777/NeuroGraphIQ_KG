"""Deterministic triple consolidation from Mirror KG sources (Step 6).

Reads mirror_region_connections, mirror_region_functions, mirror_region_circuits.
Writes mirror_kg_triples only. Does NOT call LLM; does NOT write final_* / kg_*.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.schemas.mirror_kg import (
    Directionality,
    MirrorKgTripleCreate,
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
    TripleObjectType,
    TripleScope,
    TripleSubjectType,
)
from app.services import mirror_kg_service

MAX_CONSOLIDATION_LIMIT = 5000
DEFAULT_CONSOLIDATION_LIMIT = 1000
PREVIEW_LIMIT = 100
CREATED_BY = "system:triple_consolidation"

VALID_SOURCE_TYPES = frozenset({"connection", "function", "circuit"})

DEFAULT_SKIP_MIRROR_STATUSES = frozenset({
    MirrorStatus.human_rejected,
    MirrorStatus.superseded,
    MirrorStatus.promoted_to_final,
})

DEFAULT_SKIP_PROMOTION_STATUSES = frozenset({
    MirrorPromotionStatus.failed,
    MirrorPromotionStatus.promoted,
})

CONNECTION_TO_PREDICATE: dict[str, str] = {
    "structural_connection": "structurally_connects_to",
    "functional_connectivity": "functionally_connects_to",
    "effective_connectivity": "effectively_connects_to",
    "projection": "projects_to",
    "association": "associated_with",
    "coactivation": "coactivates_with",
    "uncertain_connection": "possibly_connects_to",
    "unknown": "related_to",
}

RELATION_TO_PREDICATE: dict[str, str] = {
    "involved_in": "involved_in_function",
    "associated_with": "associated_with_function",
    "necessary_for": "necessary_for_function",
    "modulates": "modulates_function",
    "participates_in": "participates_in_function",
    "uncertain_association": "possibly_associated_with_function",
    "unknown": "associated_with_function",
}


class EmptySourceTypesError(Exception):
    pass


class InvalidSourceTypeError(Exception):
    def __init__(self, value: str):
        self.value = value
        super().__init__(f"invalid source_type: {value}")


class LimitExceededError(Exception):
    def __init__(self, limit: int, maximum: int):
        self.limit = limit
        self.maximum = maximum
        super().__init__(f"limit {limit} exceeds max {maximum}")


class ExplicitIdNotFoundError(Exception):
    def __init__(self, source_type: str, source_id: str):
        self.source_type = source_type
        self.source_id = source_id
        super().__init__(f"{source_type} not found: {source_id}")


class ScopeMismatchError(Exception):
    def __init__(self, source_type: str, source_id: str, field: str, expected: str):
        self.source_type = source_type
        self.source_id = source_id
        self.field = field
        self.expected = expected
        super().__init__(f"{source_type} {source_id} {field} mismatch")


class CrossScopeError(Exception):
    def __init__(self, field: str, values: list[str]):
        self.field = field
        self.values = values
        super().__init__(f"sources span multiple {field} values")


@dataclass
class ConsolidationScope:
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


@dataclass
class TripleCandidate:
    subject_type: str
    subject_id: uuid.UUID | None
    subject_label: str
    predicate: str
    object_type: str
    object_id: uuid.UUID | None
    object_label: str
    triple_scope: str = TripleScope.same_granularity
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    llm_run_id: uuid.UUID | None = None
    llm_item_id: uuid.UUID | None = None
    source_mirror_connection_id: uuid.UUID | None = None
    source_mirror_function_id: uuid.UUID | None = None
    source_mirror_circuit_id: uuid.UUID | None = None
    granularity_level: str = ""
    granularity_family: str | None = None
    source_atlas: str = ""
    source_version: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    uncertainty_reason: str | None = None
    mirror_status: str = MirrorStatus.llm_suggested
    review_status: str = MirrorReviewStatus.pending
    source_type: str = ""
    source_id: str = ""
    raw_payload_json: dict[str, Any] = field(default_factory=dict)
    duplicate: bool = False

    def canonical_key(self) -> tuple[Any, ...]:
        return normalize_triple_key(
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            subject_label=self.subject_label,
            predicate=self.predicate,
            object_type=self.object_type,
            object_id=self.object_id,
            object_label=self.object_label,
            triple_scope=self.triple_scope,
            source_atlas=self.source_atlas,
            granularity_level=self.granularity_level,
            granularity_family=self.granularity_family,
            resource_id=self.resource_id,
            batch_id=self.batch_id,
        )

    def to_create_payload(self) -> MirrorKgTripleCreate:
        key = self.canonical_key()
        return MirrorKgTripleCreate(
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            subject_label=self.subject_label,
            predicate=self.predicate,
            object_type=self.object_type,
            object_id=self.object_id,
            object_label=self.object_label,
            triple_scope=self.triple_scope,
            resource_id=self.resource_id,
            batch_id=self.batch_id,
            llm_run_id=self.llm_run_id,
            llm_item_id=self.llm_item_id,
            source_mirror_connection_id=self.source_mirror_connection_id,
            source_mirror_function_id=self.source_mirror_function_id,
            source_mirror_circuit_id=self.source_mirror_circuit_id,
            granularity_level=self.granularity_level,
            granularity_family=self.granularity_family,
            source_atlas=self.source_atlas,
            source_version=self.source_version,
            confidence=self.confidence,
            evidence_text=self.evidence_text,
            uncertainty_reason=self.uncertainty_reason,
            mirror_status=self.mirror_status,
            review_status=self.review_status,
            raw_payload_json=self.raw_payload_json,
            normalized_payload_json={"canonical_key": list(key), "generation_source": self.source_type},
            created_by=CREATED_BY,
        )


@dataclass
class ConsolidationResult:
    dry_run: bool
    source_counts: dict[str, int] = field(default_factory=dict)
    planned_triple_count: int = 0
    created_triple_count: int = 0
    skipped_duplicate_count: int = 0
    skipped_invalid_count: int = 0
    existing_triple_count: int = 0
    created_triple_ids: list[uuid.UUID] = field(default_factory=list)
    triples_preview: list[TripleCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm_label(label: str) -> str:
    return (label or "").lower().strip()


def normalize_triple_key(
    *,
    subject_type: str,
    subject_id: uuid.UUID | None,
    subject_label: str,
    predicate: str,
    object_type: str,
    object_id: uuid.UUID | None,
    object_label: str,
    triple_scope: str,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
) -> tuple[Any, ...]:
    subj = str(subject_id) if subject_id else _norm_label(subject_label)
    obj = str(object_id) if object_id else _norm_label(object_label)
    return (
        subject_type,
        subj,
        predicate,
        object_type,
        obj,
        triple_scope,
        source_atlas,
        granularity_level,
        granularity_family or "",
        str(resource_id) if resource_id else "",
        str(batch_id) if batch_id else "",
    )


def triple_row_key(row: MirrorKgTriple) -> tuple[Any, ...]:
    return normalize_triple_key(
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_label=row.subject_label,
        predicate=row.predicate,
        object_type=row.object_type,
        object_id=row.object_id,
        object_label=row.object_label,
        triple_scope=row.triple_scope,
        source_atlas=row.source_atlas,
        granularity_level=row.granularity_level,
        granularity_family=row.granularity_family,
        resource_id=row.resource_id,
        batch_id=row.batch_id,
    )


def _region_label(c: CandidateBrainRegion | None, fallback_id: uuid.UUID | None) -> str:
    if c is None:
        return str(fallback_id)[:8] if fallback_id else "unknown"
    return c.en_name or c.cn_name or c.std_name or c.raw_name or str(c.id)[:8]


def _validate_source_scope(
    obj: MirrorRegionConnection | MirrorRegionFunction | MirrorRegionCircuit,
    scope: ConsolidationScope,
    source_type: str,
) -> None:
    obj_id = str(obj.id)
    if scope.resource_id and obj.resource_id != scope.resource_id:
        raise ScopeMismatchError(source_type, obj_id, "resource_id", str(scope.resource_id))
    if scope.batch_id and obj.batch_id != scope.batch_id:
        raise ScopeMismatchError(source_type, obj_id, "batch_id", str(scope.batch_id))
    if scope.source_atlas and obj.source_atlas != scope.source_atlas:
        raise ScopeMismatchError(source_type, obj_id, "source_atlas", scope.source_atlas)
    if scope.granularity_level and obj.granularity_level != scope.granularity_level:
        raise ScopeMismatchError(source_type, obj_id, "granularity_level", scope.granularity_level)
    if scope.granularity_family and obj.granularity_family != scope.granularity_family:
        raise ScopeMismatchError(source_type, obj_id, "granularity_family", scope.granularity_family)


def _source_passes_filters(
    obj: MirrorRegionConnection | MirrorRegionFunction | MirrorRegionCircuit,
    *,
    mirror_statuses: list[str] | None,
    review_statuses: list[str] | None,
    promotion_statuses: list[str] | None,
    explicit: bool,
) -> bool:
    if obj.promotion_status in {MirrorPromotionStatus.promoted}:
        return False
    if mirror_statuses is not None:
        if obj.mirror_status not in mirror_statuses:
            return False
    elif not explicit and obj.mirror_status in DEFAULT_SKIP_MIRROR_STATUSES:
        return False
    if review_statuses is not None:
        if obj.review_status not in review_statuses:
            return False
    elif not explicit and obj.review_status == MirrorReviewStatus.rejected:
        return False
    if promotion_statuses is not None:
        if obj.promotion_status not in promotion_statuses:
            return False
    elif not explicit and obj.promotion_status in DEFAULT_SKIP_PROMOTION_STATUSES:
        return False
    return True


def _apply_scope_to_query(q, model, scope: ConsolidationScope):
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
    return q


async def collect_source_connections(
    session: AsyncSession,
    *,
    scope: ConsolidationScope,
    connection_ids: list[uuid.UUID] | None,
    mirror_statuses: list[str] | None,
    review_statuses: list[str] | None,
    promotion_statuses: list[str] | None,
    limit: int,
) -> list[MirrorRegionConnection]:
    if connection_ids:
        rows: list[MirrorRegionConnection] = []
        for cid in connection_ids:
            row = await session.get(MirrorRegionConnection, cid)
            if row is None:
                raise ExplicitIdNotFoundError("connection", str(cid))
            _validate_source_scope(row, scope, "connection")
            rows.append(row)
        return rows

    q = _apply_scope_to_query(select(MirrorRegionConnection), MirrorRegionConnection, scope)
    q = q.limit(limit)
    all_rows = list((await session.execute(q)).scalars().all())
    return [
        r for r in all_rows
        if _source_passes_filters(
            r,
            mirror_statuses=mirror_statuses,
            review_statuses=review_statuses,
            promotion_statuses=promotion_statuses,
            explicit=False,
        )
    ]


async def collect_source_functions(
    session: AsyncSession,
    *,
    scope: ConsolidationScope,
    function_ids: list[uuid.UUID] | None,
    mirror_statuses: list[str] | None,
    review_statuses: list[str] | None,
    promotion_statuses: list[str] | None,
    limit: int,
) -> list[MirrorRegionFunction]:
    if function_ids:
        rows: list[MirrorRegionFunction] = []
        for fid in function_ids:
            row = await session.get(MirrorRegionFunction, fid)
            if row is None:
                raise ExplicitIdNotFoundError("function", str(fid))
            _validate_source_scope(row, scope, "function")
            rows.append(row)
        return rows

    q = _apply_scope_to_query(select(MirrorRegionFunction), MirrorRegionFunction, scope)
    q = q.limit(limit)
    all_rows = list((await session.execute(q)).scalars().all())
    return [
        r for r in all_rows
        if _source_passes_filters(
            r,
            mirror_statuses=mirror_statuses,
            review_statuses=review_statuses,
            promotion_statuses=promotion_statuses,
            explicit=False,
        )
    ]


async def collect_source_circuits(
    session: AsyncSession,
    *,
    scope: ConsolidationScope,
    circuit_ids: list[uuid.UUID] | None,
    mirror_statuses: list[str] | None,
    review_statuses: list[str] | None,
    promotion_statuses: list[str] | None,
    limit: int,
) -> tuple[list[MirrorRegionCircuit], list[MirrorCircuitRegion]]:
    if circuit_ids:
        circuits: list[MirrorRegionCircuit] = []
        all_regions: list[MirrorCircuitRegion] = []
        for cid in circuit_ids:
            row = await session.get(MirrorRegionCircuit, cid)
            if row is None:
                raise ExplicitIdNotFoundError("circuit", str(cid))
            _validate_source_scope(row, scope, "circuit")
            circuits.append(row)
            regions = list(
                (await session.execute(
                    select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == cid)
                )).scalars().all()
            )
            all_regions.extend(regions)
        return circuits, all_regions

    q = _apply_scope_to_query(select(MirrorRegionCircuit), MirrorRegionCircuit, scope)
    q = q.limit(limit)
    circuits = [
        r for r in (await session.execute(q)).scalars().all()
        if _source_passes_filters(
            r,
            mirror_statuses=mirror_statuses,
            review_statuses=review_statuses,
            promotion_statuses=promotion_statuses,
            explicit=False,
        )
    ]
    if not circuits:
        return [], []
    circuit_id_list = [c.id for c in circuits]
    regions = list(
        (await session.execute(
            select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id.in_(circuit_id_list))
        )).scalars().all()
    )
    return circuits, regions


async def _load_candidate_map(
    session: AsyncSession,
    candidate_ids: set[uuid.UUID],
) -> dict[uuid.UUID, CandidateBrainRegion]:
    if not candidate_ids:
        return {}
    rows = (
        await session.execute(
            select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(candidate_ids))
        )
    ).scalars().all()
    return {r.id: r for r in rows}


def build_connection_triple_candidates(
    connections: list[MirrorRegionConnection],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    warnings: list[str],
) -> tuple[list[TripleCandidate], int]:
    candidates: list[TripleCandidate] = []
    skipped_invalid = 0
    for conn in connections:
        src = conn.source_region_candidate_id
        tgt = conn.target_region_candidate_id
        if not src or not tgt:
            skipped_invalid += 1
            warnings.append(f"connection {conn.id} skipped: missing region candidate ids")
            continue
        predicate = CONNECTION_TO_PREDICATE.get(conn.connection_type, "related_to")
        if conn.directionality == Directionality.bidirectional:
            predicate = "bidirectionally_connects_to"
        src_c = candidate_map.get(src)
        tgt_c = candidate_map.get(tgt)
        if src_c is None or tgt_c is None:
            warnings.append(f"connection {conn.id}: region label fallback used")
        candidates.append(TripleCandidate(
            subject_type=TripleSubjectType.region_candidate,
            subject_id=src,
            subject_label=_region_label(src_c, src),
            predicate=predicate,
            object_type=TripleSubjectType.region_candidate,
            object_id=tgt,
            object_label=_region_label(tgt_c, tgt),
            resource_id=conn.resource_id,
            batch_id=conn.batch_id,
            llm_run_id=conn.llm_run_id,
            llm_item_id=conn.llm_item_id,
            source_mirror_connection_id=conn.id,
            granularity_level=conn.granularity_level,
            granularity_family=conn.granularity_family,
            source_atlas=conn.source_atlas,
            source_version=conn.source_version,
            confidence=float(conn.confidence) if conn.confidence is not None else None,
            evidence_text=conn.evidence_text,
            uncertainty_reason=conn.uncertainty_reason,
            mirror_status=conn.mirror_status,
            review_status=conn.review_status,
            source_type="connection",
            source_id=str(conn.id),
            raw_payload_json={"source": "connection", "connection_id": str(conn.id)},
        ))
    return candidates, skipped_invalid


def build_function_triple_candidates(
    functions: list[MirrorRegionFunction],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    warnings: list[str],
) -> tuple[list[TripleCandidate], int]:
    candidates: list[TripleCandidate] = []
    skipped_invalid = 0
    for fn in functions:
        region_id = fn.region_candidate_id
        term = (fn.function_term or "").strip()
        if not region_id:
            skipped_invalid += 1
            warnings.append(f"function {fn.id} skipped: missing region_candidate_id")
            continue
        if not term:
            skipped_invalid += 1
            warnings.append(f"function {fn.id} skipped: empty function_term")
            continue
        region_c = candidate_map.get(region_id)
        if region_c is None:
            warnings.append(f"function {fn.id}: region label fallback used")
        predicate = RELATION_TO_PREDICATE.get(fn.relation_type, "associated_with_function")
        candidates.append(TripleCandidate(
            subject_type=TripleSubjectType.region_candidate,
            subject_id=region_id,
            subject_label=_region_label(region_c, region_id),
            predicate=predicate,
            object_type=TripleObjectType.function,
            object_id=None,
            object_label=term,
            resource_id=fn.resource_id,
            batch_id=fn.batch_id,
            llm_run_id=fn.llm_run_id,
            llm_item_id=fn.llm_item_id,
            source_mirror_function_id=fn.id,
            granularity_level=fn.granularity_level,
            granularity_family=fn.granularity_family,
            source_atlas=fn.source_atlas,
            source_version=fn.source_version,
            confidence=float(fn.confidence) if fn.confidence is not None else None,
            evidence_text=fn.evidence_text,
            uncertainty_reason=fn.uncertainty_reason,
            mirror_status=fn.mirror_status,
            review_status=fn.review_status,
            source_type="function",
            source_id=str(fn.id),
            raw_payload_json={"source": "function", "function_id": str(fn.id)},
        ))
    return candidates, skipped_invalid


def build_circuit_triple_candidates(
    circuits: list[MirrorRegionCircuit],
    circuit_regions: list[MirrorCircuitRegion],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    warnings: list[str],
) -> tuple[list[TripleCandidate], int]:
    candidates: list[TripleCandidate] = []
    skipped_invalid = 0
    regions_by_circuit: dict[uuid.UUID, list[MirrorCircuitRegion]] = {}
    for cr in circuit_regions:
        regions_by_circuit.setdefault(cr.circuit_id, []).append(cr)

    for circuit in circuits:
        name = (circuit.circuit_name or "").strip()
        if not name:
            skipped_invalid += 1
            warnings.append(f"circuit {circuit.id} skipped: empty circuit_name")
            continue
        regions = regions_by_circuit.get(circuit.id, [])
        if not regions:
            warnings.append(f"circuit {circuit.id}: no circuit_regions; function triple only if association set")

        for cr in regions:
            rid = cr.region_candidate_id
            if not rid:
                skipped_invalid += 1
                warnings.append(f"circuit_region {cr.id} skipped: missing region_candidate_id")
                continue
            region_c = candidate_map.get(rid)
            candidates.append(TripleCandidate(
                subject_type=TripleSubjectType.circuit,
                subject_id=circuit.id,
                subject_label=name,
                predicate="has_participant_region",
                object_type=TripleObjectType.region_candidate,
                object_id=rid,
                object_label=_region_label(region_c, rid),
                resource_id=circuit.resource_id,
                batch_id=circuit.batch_id,
                llm_run_id=circuit.llm_run_id,
                llm_item_id=circuit.llm_item_id,
                source_mirror_circuit_id=circuit.id,
                granularity_level=circuit.granularity_level,
                granularity_family=circuit.granularity_family,
                source_atlas=circuit.source_atlas,
                source_version=circuit.source_version,
                confidence=float(circuit.confidence) if circuit.confidence is not None else None,
                evidence_text=circuit.evidence_text,
                uncertainty_reason=circuit.uncertainty_reason,
                mirror_status=circuit.mirror_status,
                review_status=circuit.review_status,
                source_type="circuit",
                source_id=str(circuit.id),
                raw_payload_json={"source": "circuit", "circuit_id": str(circuit.id), "circuit_region_id": str(cr.id)},
            ))

        func_assoc = (circuit.function_association or "").strip()
        if func_assoc:
            candidates.append(TripleCandidate(
                subject_type=TripleSubjectType.circuit,
                subject_id=circuit.id,
                subject_label=name,
                predicate="associated_with_function",
                object_type=TripleObjectType.function,
                object_id=None,
                object_label=func_assoc,
                resource_id=circuit.resource_id,
                batch_id=circuit.batch_id,
                llm_run_id=circuit.llm_run_id,
                llm_item_id=circuit.llm_item_id,
                source_mirror_circuit_id=circuit.id,
                granularity_level=circuit.granularity_level,
                granularity_family=circuit.granularity_family,
                source_atlas=circuit.source_atlas,
                source_version=circuit.source_version,
                confidence=float(circuit.confidence) if circuit.confidence is not None else None,
                evidence_text=circuit.evidence_text,
                uncertainty_reason=circuit.uncertainty_reason,
                mirror_status=circuit.mirror_status,
                review_status=circuit.review_status,
                source_type="circuit",
                source_id=str(circuit.id),
                raw_payload_json={"source": "circuit", "circuit_id": str(circuit.id), "function_association": func_assoc},
            ))
    return candidates, skipped_invalid


async def find_existing_triple_keys(
    session: AsyncSession,
    scope: ConsolidationScope,
) -> set[tuple[Any, ...]]:
    q = _apply_scope_to_query(select(MirrorKgTriple), MirrorKgTriple, scope)
    rows = list((await session.execute(q.limit(10000))).scalars().all())
    return {triple_row_key(r) for r in rows}


async def persist_triple_candidates(
    session: AsyncSession,
    candidates: list[TripleCandidate],
) -> list[uuid.UUID]:
    created_ids: list[uuid.UUID] = []
    for cand in candidates:
        if cand.duplicate:
            continue
        row = await mirror_kg_service.create_mirror_triple(session, cand.to_create_payload())
        created_ids.append(row.id)
    return created_ids


async def consolidate_mirror_triples(
    session: AsyncSession,
    *,
    source_types: list[str] | None = None,
    scope: ConsolidationScope | None = None,
    mirror_statuses: list[str] | None = None,
    review_statuses: list[str] | None = None,
    promotion_statuses: list[str] | None = None,
    connection_ids: list[uuid.UUID] | None = None,
    function_ids: list[uuid.UUID] | None = None,
    circuit_ids: list[uuid.UUID] | None = None,
    include_existing: bool = False,
    dry_run: bool = True,
    limit: int = DEFAULT_CONSOLIDATION_LIMIT,
) -> ConsolidationResult:
    if source_types is None:
        types = ["connection", "function", "circuit"]
    elif not source_types:
        raise EmptySourceTypesError()
    else:
        types = source_types
    for t in types:
        if t not in VALID_SOURCE_TYPES:
            raise InvalidSourceTypeError(t)
    if limit > MAX_CONSOLIDATION_LIMIT:
        raise LimitExceededError(limit, MAX_CONSOLIDATION_LIMIT)

    sc = scope or ConsolidationScope()
    warnings: list[str] = []
    result = ConsolidationResult(dry_run=dry_run)

    connections: list[MirrorRegionConnection] = []
    functions: list[MirrorRegionFunction] = []
    circuits: list[MirrorRegionCircuit] = []
    circuit_regions: list[MirrorCircuitRegion] = []

    if "connection" in types:
        connections = await collect_source_connections(
            session,
            scope=sc,
            connection_ids=connection_ids,
            mirror_statuses=mirror_statuses,
            review_statuses=review_statuses,
            promotion_statuses=promotion_statuses,
            limit=limit,
        )
    if "function" in types:
        functions = await collect_source_functions(
            session,
            scope=sc,
            function_ids=function_ids,
            mirror_statuses=mirror_statuses,
            review_statuses=review_statuses,
            promotion_statuses=promotion_statuses,
            limit=limit,
        )
    if "circuit" in types:
        circuits, circuit_regions = await collect_source_circuits(
            session,
            scope=sc,
            circuit_ids=circuit_ids,
            mirror_statuses=mirror_statuses,
            review_statuses=review_statuses,
            promotion_statuses=promotion_statuses,
            limit=limit,
        )

    result.source_counts = {
        "connections": len(connections),
        "functions": len(functions),
        "circuits": len(circuits),
        "circuit_regions": len(circuit_regions),
    }

    candidate_ids: set[uuid.UUID] = set()
    for c in connections:
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

    candidate_map = await _load_candidate_map(session, candidate_ids)

    all_candidates: list[TripleCandidate] = []
    skipped_invalid = 0

    if connections:
        conn_cands, skip = build_connection_triple_candidates(connections, candidate_map, warnings)
        all_candidates.extend(conn_cands)
        skipped_invalid += skip
    if functions:
        fn_cands, skip = build_function_triple_candidates(functions, candidate_map, warnings)
        all_candidates.extend(fn_cands)
        skipped_invalid += skip
    if circuits:
        circ_cands, skip = build_circuit_triple_candidates(circuits, circuit_regions, candidate_map, warnings)
        all_candidates.extend(circ_cands)
        skipped_invalid += skip

    result.skipped_invalid_count = skipped_invalid

    existing_keys = await find_existing_triple_keys(session, sc)
    if include_existing:
        result.existing_triple_count = len(existing_keys)

    session_seen: set[tuple[Any, ...]] = set()
    skipped_dup = 0
    for cand in all_candidates[:limit]:
        key = cand.canonical_key()
        if key in session_seen or key in existing_keys:
            cand.duplicate = True
            skipped_dup += 1
            continue
        session_seen.add(key)

    result.planned_triple_count = len(all_candidates[:limit])
    result.skipped_duplicate_count = skipped_dup
    result.triples_preview = all_candidates[:PREVIEW_LIMIT]
    result.warnings = warnings

    if dry_run:
        return result

    to_create = [c for c in all_candidates[:limit] if not c.duplicate]
    created_ids = await persist_triple_candidates(session, to_create)
    result.created_triple_count = len(created_ids)
    result.created_triple_ids = created_ids
    await session.commit()
    return result
