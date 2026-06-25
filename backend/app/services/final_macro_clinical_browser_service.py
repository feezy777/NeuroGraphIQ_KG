"""Final macro_clinical browser / query service (Step 8.16, read-only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.final_kg import (
    FinalEvidenceRecord,
    FinalKgTriple,
    FinalRegionCircuit,
    FinalRegionFunction,
)
from app.models.final_macro_clinical import (
    FinalCircuitFunction,
    FinalCircuitProjectionMembership,
    FinalCircuitStep,
    FinalMacroClinicalPromotionRecord,
    FinalProjection,
    FinalProjectionFunction,
)
from app.schemas.final_macro_clinical_browser import (
    BROWSER_SEARCH_TARGET_TYPES,
    FinalBrowserSearchItem,
    FinalBrowserSearchResponse,
    FinalCircuitDetailResponse,
    FinalGraphEdge,
    FinalGraphNode,
    FinalGraphResponse,
    FinalObjectDetailResponse,
    FinalProjectionDetailResponse,
    FinalProvenancePayload,
    FinalRegionNeighborhoodResponse,
    OBJECT_DETAIL_TARGET_TYPES,
)
from app.services.final_macro_clinical_promotion_service import _row_json

MAX_GRAPH_DEPTH = 3
MAX_GRAPH_LIMIT = 1000


def normalize_search_query(query: str | None) -> str | None:
    if query is None:
        return None
    q = query.strip()
    return q if q else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _mirror_id_from_row(row: Any) -> uuid.UUID | None:
    for attr in (
        "source_mirror_id",
        "source_mirror_circuit_id",
        "source_mirror_function_id",
        "source_mirror_triple_id",
        "source_mirror_evidence_id",
    ):
        val = getattr(row, attr, None)
        if val is not None:
            return val
    return None


def _mirror_type_from_row(row: Any, default: str) -> str:
    return getattr(row, "source_mirror_type", None) or default


def make_final_label(target_type: str, row: Any) -> str:
    if target_type == "circuit":
        return getattr(row, "circuit_name", "") or str(row.id)
    if target_type == "circuit_step":
        return getattr(row, "step_name", "") or str(row.id)
    if target_type == "projection":
        return getattr(row, "projection_type", "") or str(row.id)
    if target_type in {"projection_function", "region_function", "circuit_function"}:
        return getattr(row, "function_term", "") or str(row.id)
    if target_type == "circuit_projection_membership":
        return getattr(row, "role_in_circuit", "") or str(row.id)
    if target_type == "triple":
        subj = getattr(row, "subject_label", "")
        pred = getattr(row, "predicate", "")
        obj = getattr(row, "object_label", "")
        return f"{subj} {pred} {obj}".strip() or str(row.id)
    if target_type == "evidence":
        return (getattr(row, "evidence_text", "") or "")[:120] or str(row.id)
    return str(row.id)


def make_final_summary(target_type: str, row: Any) -> str | None:
    if target_type == "circuit":
        parts = [getattr(row, "circuit_type", None), getattr(row, "description", None)]
    elif target_type == "circuit_step":
        parts = [getattr(row, "step_type", None), getattr(row, "role", None), getattr(row, "description", None)]
    elif target_type == "projection":
        parts = [
            getattr(row, "directionality", None),
            getattr(row, "strength", None),
            (getattr(row, "evidence_text", None) or "")[:200] or None,
        ]
    elif target_type in {"projection_function", "region_function", "circuit_function"}:
        parts = [getattr(row, "function_category", None), getattr(row, "relation_type", None)]
    elif target_type == "circuit_projection_membership":
        parts = [getattr(row, "verification_status", None), getattr(row, "source_method", None)]
    elif target_type == "triple":
        parts = [getattr(row, "triple_scope", None), getattr(row, "evidence_text", None)]
    elif target_type == "evidence":
        parts = [getattr(row, "evidence_type", None), getattr(row, "source_reference_text", None)]
    else:
        parts = []
    text = " · ".join(p for p in parts if p)
    return text or None


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _node_id(node_type: str, node_key: uuid.UUID | str) -> str:
    return f"{node_type}:{node_key}"


def _graph_node(
    node_type: str,
    *,
    label: str,
    final_id: uuid.UUID | None = None,
    source_mirror_id: uuid.UUID | None = None,
    node_key: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> FinalGraphNode:
    key = node_key if node_key is not None else (final_id or label)
    return FinalGraphNode(
        id=_node_id(node_type, key),
        type=node_type,
        label=label,
        final_id=final_id,
        source_mirror_id=source_mirror_id,
        metadata=metadata or {},
    )


def _graph_edge(
    edge_type: str,
    source: str,
    target: str,
    *,
    label: str | None = None,
    predicate: str | None = None,
    final_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> FinalGraphEdge:
    edge_key = final_id or f"{source}->{target}:{edge_type}"
    return FinalGraphEdge(
        id=f"edge:{edge_key}",
        type=edge_type,
        source=source,
        target=target,
        label=label,
        predicate=predicate,
        final_id=final_id,
        metadata=metadata or {},
    )


def _apply_status_filter(stmt, model, *, include_inactive: bool, final_status: str | None):
    if not hasattr(model, "final_status"):
        return stmt
    if final_status:
        return stmt.where(getattr(model, "final_status") == final_status)
    if not include_inactive:
        return stmt.where(getattr(model, "final_status") == "active")
    return stmt


def _apply_scope_filters(
    stmt,
    model,
    *,
    source_atlas: str | None,
    granularity_level: str | None,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
):
    if source_atlas and hasattr(model, "source_atlas"):
        stmt = stmt.where(model.source_atlas == source_atlas)
    if granularity_level and hasattr(model, "granularity_level"):
        stmt = stmt.where(model.granularity_level == granularity_level)
    if granularity_family and hasattr(model, "granularity_family"):
        stmt = stmt.where(model.granularity_family == granularity_family)
    if resource_id and hasattr(model, "resource_id"):
        stmt = stmt.where(model.resource_id == resource_id)
    if batch_id and hasattr(model, "batch_id"):
        stmt = stmt.where(model.batch_id == batch_id)
    return stmt


def _text_match(stmt, columns: list[Any], query: str):
    pattern = f"%{query}%"
    clauses = [cast(col, String).ilike(pattern) for col in columns if col is not None]
    if not clauses:
        return stmt
    return stmt.where(or_(*clauses))


SEARCH_MODELS: dict[str, tuple[type, list[Any], str]] = {
    "circuit": (
        FinalRegionCircuit,
        [
            FinalRegionCircuit.circuit_name,
            FinalRegionCircuit.circuit_type,
            FinalRegionCircuit.function_association,
            FinalRegionCircuit.description,
        ],
        "circuit",
    ),
    "circuit_step": (
        FinalCircuitStep,
        [
            FinalCircuitStep.step_name,
            FinalCircuitStep.step_type,
            FinalCircuitStep.role,
            FinalCircuitStep.description,
        ],
        "circuit_step",
    ),
    "projection": (
        FinalProjection,
        [FinalProjection.projection_type, FinalProjection.directionality, FinalProjection.evidence_text],
        "projection",
    ),
    "projection_function": (
        FinalProjectionFunction,
        [
            FinalProjectionFunction.function_term,
            FinalProjectionFunction.function_category,
            FinalProjectionFunction.relation_type,
        ],
        "projection_function",
    ),
    "circuit_projection_membership": (
        FinalCircuitProjectionMembership,
        [
            FinalCircuitProjectionMembership.role_in_circuit,
            FinalCircuitProjectionMembership.verification_status,
        ],
        "circuit_projection_membership",
    ),
    "region_function": (
        FinalRegionFunction,
        [
            FinalRegionFunction.function_term,
            FinalRegionFunction.function_category,
            FinalRegionFunction.relation_type,
        ],
        "region_function",
    ),
    "circuit_function": (
        FinalCircuitFunction,
        [
            FinalCircuitFunction.function_term,
            FinalCircuitFunction.function_category,
            FinalCircuitFunction.relation_type,
        ],
        "circuit_function",
    ),
    "triple": (
        FinalKgTriple,
        [FinalKgTriple.subject_label, FinalKgTriple.predicate, FinalKgTriple.object_label],
        "triple",
    ),
    "evidence": (
        FinalEvidenceRecord,
        [FinalEvidenceRecord.evidence_text, FinalEvidenceRecord.source_reference_text],
        "evidence",
    ),
}


def _apply_entity_filters(
    stmt,
    model,
    target_type: str,
    *,
    region_candidate_id: uuid.UUID | None,
    circuit_id: uuid.UUID | None,
    projection_id: uuid.UUID | None,
):
    if region_candidate_id:
        if target_type == "circuit_step" and hasattr(model, "region_candidate_id"):
            stmt = stmt.where(model.region_candidate_id == region_candidate_id)
        elif target_type == "region_function" and hasattr(model, "region_candidate_id"):
            stmt = stmt.where(model.region_candidate_id == region_candidate_id)
        elif target_type == "projection" and hasattr(model, "source_region_candidate_id"):
            stmt = stmt.where(
                or_(
                    model.source_region_candidate_id == region_candidate_id,
                    model.target_region_candidate_id == region_candidate_id,
                )
            )
    if circuit_id:
        if hasattr(model, "final_circuit_id"):
            stmt = stmt.where(model.final_circuit_id == circuit_id)
    if projection_id:
        if hasattr(model, "final_projection_id"):
            stmt = stmt.where(model.final_projection_id == projection_id)
    return stmt


def _to_search_item(target_type: str, row: Any, mirror_default: str) -> FinalBrowserSearchItem:
    conf = getattr(row, "confidence", None)
    return FinalBrowserSearchItem(
        target_type=target_type,
        final_id=row.id,
        final_uid=getattr(row, "final_uid", None),
        label=make_final_label(target_type, row),
        summary=make_final_summary(target_type, row),
        source_atlas=getattr(row, "source_atlas", None),
        granularity_level=getattr(row, "granularity_level", None),
        granularity_family=getattr(row, "granularity_family", None),
        confidence=float(conf) if conf is not None else None,
        final_status=getattr(row, "final_status", None),
        source_mirror_type=_mirror_type_from_row(row, mirror_default),
        source_mirror_id=_mirror_id_from_row(row),
        promotion_run_id=getattr(row, "promotion_run_id", None),
        created_at=getattr(row, "created_at", None),
    )


async def _query_search_type(
    session: AsyncSession,
    target_type: str,
    *,
    query: str | None,
    source_atlas: str | None,
    granularity_level: str | None,
    granularity_family: str | None,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    final_status: str | None,
    region_candidate_id: uuid.UUID | None,
    circuit_id: uuid.UUID | None,
    projection_id: uuid.UUID | None,
    include_inactive: bool,
) -> list[Any]:
    model, search_cols, mirror_default = SEARCH_MODELS[target_type]
    stmt = select(model)
    stmt = _apply_scope_filters(
        stmt,
        model,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        resource_id=resource_id,
        batch_id=batch_id,
    )
    stmt = _apply_status_filter(stmt, model, include_inactive=include_inactive, final_status=final_status)
    stmt = _apply_entity_filters(
        stmt,
        model,
        target_type,
        region_candidate_id=region_candidate_id,
        circuit_id=circuit_id,
        projection_id=projection_id,
    )
    if query:
        stmt = _text_match(stmt, search_cols, query)
    stmt = stmt.order_by(model.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def search_final_objects(
    session: AsyncSession,
    *,
    query: str | None = None,
    target_types: list[str] | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    final_status: str | None = None,
    region_candidate_id: uuid.UUID | None = None,
    circuit_id: uuid.UUID | None = None,
    projection_id: uuid.UUID | None = None,
    include_inactive: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> FinalBrowserSearchResponse:
    q = normalize_search_query(query)
    types = target_types or [t.value for t in BROWSER_SEARCH_TARGET_TYPES]
    invalid = [t for t in types if t not in SEARCH_MODELS]
    if invalid:
        raise ValueError(f"invalid target_types: {invalid}")

    merged: list[FinalBrowserSearchItem] = []
    for tt in types:
        rows = await _query_search_type(
            session,
            tt,
            query=q,
            source_atlas=source_atlas,
            granularity_level=granularity_level,
            granularity_family=granularity_family,
            resource_id=resource_id,
            batch_id=batch_id,
            final_status=final_status,
            region_candidate_id=region_candidate_id,
            circuit_id=circuit_id,
            projection_id=projection_id,
            include_inactive=include_inactive,
        )
        _, _, mirror_default = SEARCH_MODELS[tt]
        merged.extend(_to_search_item(tt, row, mirror_default) for row in rows)

    merged.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
    total = len(merged)
    page = merged[offset : offset + limit]
    return FinalBrowserSearchResponse(items=page, total=total, limit=limit, offset=offset, warnings=[])


async def _region_label(session: AsyncSession, region_candidate_id: uuid.UUID) -> tuple[str | None, str | None, str | None]:
    row = await session.get(CandidateBrainRegion, region_candidate_id)
    if row is None:
        return None, None, None
    label = row.std_name or row.en_name or row.raw_name
    return label, row.source_atlas, row.granularity_level


async def _regions_map(session: AsyncSession, region_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    if not region_ids:
        return {}
    rows = list(
        (await session.execute(select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(region_ids)))).scalars().all()
    )
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for r in rows:
        out[r.id] = {
            "region_candidate_id": r.id,
            "label": r.std_name or r.en_name or r.raw_name,
            "source_atlas": r.source_atlas,
            "granularity_level": r.granularity_level,
            "granularity_family": r.granularity_family,
        }
    return out


async def collect_final_triples(
    session: AsyncSession,
    *,
    object_ids: dict[str, set[uuid.UUID]],
    region_candidate_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses = []
    type_map = {
        "circuit": "circuit",
        "projection": "projection",
        "region": "region",
        "region_function": "region_function",
        "circuit_step": "circuit_step",
    }
    for obj_type, ids in object_ids.items():
        mapped = type_map.get(obj_type, obj_type)
        if ids:
            clauses.append(
                or_(
                    (FinalKgTriple.subject_type == mapped) & FinalKgTriple.subject_id.in_(ids),
                    (FinalKgTriple.object_type == mapped) & FinalKgTriple.object_id.in_(ids),
                )
            )
    if region_candidate_id:
        clauses.append(
            or_(
                (FinalKgTriple.subject_type == "region") & (FinalKgTriple.subject_id == region_candidate_id),
                (FinalKgTriple.object_type == "region") & (FinalKgTriple.object_id == region_candidate_id),
            )
        )
    if not clauses:
        return []
    stmt = select(FinalKgTriple).where(or_(*clauses)).order_by(FinalKgTriple.created_at.desc()).limit(limit)
    return [_row_json(r) for r in (await session.execute(stmt)).scalars().all()]


async def collect_final_evidence(
    session: AsyncSession,
    *,
    targets: list[tuple[str, uuid.UUID]],
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not targets:
        return []
    clauses = [
        (FinalEvidenceRecord.evidence_target_type == t) & (FinalEvidenceRecord.evidence_target_id == i)
        for t, i in targets
    ]
    stmt = (
        select(FinalEvidenceRecord)
        .where(or_(*clauses))
        .order_by(FinalEvidenceRecord.created_at.desc())
        .limit(limit)
    )
    return [_row_json(r) for r in (await session.execute(stmt)).scalars().all()]


async def build_provenance_payload(session: AsyncSession, row: Any, mirror_default: str) -> FinalProvenancePayload:
    promotion_record_id = getattr(row, "promotion_record_id", None)
    promotion_record = None
    if promotion_record_id:
        rec = await session.get(FinalMacroClinicalPromotionRecord, promotion_record_id)
        if rec:
            promotion_record = _row_json(rec)

    source_mirror_id = _mirror_id_from_row(row)
    mirror_link_available = source_mirror_id is not None

    return FinalProvenancePayload(
        source_mirror_type=_mirror_type_from_row(row, mirror_default),
        source_mirror_id=source_mirror_id,
        promotion_run_id=getattr(row, "promotion_run_id", None),
        promotion_record_id=promotion_record_id,
        promotion_record=promotion_record,
        validation_summary_json=getattr(row, "validation_summary_json", None) or {},
        review_summary_json=getattr(row, "review_summary_json", None) or {},
        cross_validation_summary_json=getattr(row, "cross_validation_summary_json", None) or {},
        dual_model_summary_json=getattr(row, "dual_model_summary_json", None) or {},
        provenance_json=getattr(row, "provenance_json", None) or {},
        final_status=getattr(row, "final_status", None),
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
        mirror_link_available=mirror_link_available,
    )


def build_region_graph(
    *,
    region_candidate_id: uuid.UUID,
    region_label: str | None,
    region_functions: list[dict[str, Any]],
    circuits: list[dict[str, Any]],
    circuit_steps: list[dict[str, Any]],
    outgoing_projections: list[dict[str, Any]],
    incoming_projections: list[dict[str, Any]],
    undirected_projections: list[dict[str, Any]],
    projection_functions: list[dict[str, Any]],
    region_map: dict[uuid.UUID, dict[str, Any]],
) -> FinalGraphResponse:
    nodes: dict[str, FinalGraphNode] = {}
    edges: list[FinalGraphEdge] = []
    center = _graph_node(
        "region",
        label=region_label or str(region_candidate_id),
        node_key=region_candidate_id,
    )
    nodes[center.id] = center

    for rf in region_functions:
        nid = _graph_node(
            "region_function",
            label=rf.get("function_term") or str(rf.get("id")),
            final_id=rf.get("id"),
            source_mirror_id=rf.get("source_mirror_function_id"),
        )
        nodes[nid.id] = nid
        edges.append(_graph_edge("has_function", center.id, nid.id, label="has_function", final_id=rf.get("id")))

    circuit_nodes: dict[uuid.UUID, str] = {}
    for c in circuits:
        cid = c.get("id")
        cn = _graph_node(
            "circuit",
            label=c.get("circuit_name") or str(cid),
            final_id=cid,
            source_mirror_id=c.get("source_mirror_circuit_id"),
        )
        nodes[cn.id] = cn
        circuit_nodes[cid] = cn.id
        edges.append(_graph_edge("participates_in", center.id, cn.id, label="participates_in"))

    for step in circuit_steps:
        cid = step.get("final_circuit_id")
        if cid in circuit_nodes:
            sn = _graph_node(
                "circuit_step",
                label=step.get("step_name") or str(step.get("id")),
                final_id=step.get("id"),
                source_mirror_id=step.get("source_mirror_id"),
            )
            nodes[sn.id] = sn
            edges.append(_graph_edge("contains_step", circuit_nodes[cid], sn.id, label="step", final_id=step.get("id")))
            edges.append(_graph_edge("step_region", sn.id, center.id, label="at_region"))

    all_projections = outgoing_projections + incoming_projections + undirected_projections
    proj_nodes: dict[uuid.UUID, str] = {}
    for p in all_projections:
        pid = p.get("id")
        pn = _graph_node(
            "projection",
            label=p.get("projection_type") or str(pid),
            final_id=pid,
            source_mirror_id=p.get("source_mirror_id"),
        )
        nodes[pn.id] = pn
        proj_nodes[pid] = pn.id
        src = p.get("source_region_candidate_id")
        tgt = p.get("target_region_candidate_id")
        if src:
            src_info = region_map.get(src, {})
            src_node = _graph_node("region", label=src_info.get("label") or str(src), node_key=src)
            nodes[src_node.id] = src_node
            edges.append(_graph_edge("projection_source", src_node.id, pn.id, label="source"))
        if tgt:
            tgt_info = region_map.get(tgt, {})
            tgt_node = _graph_node("region", label=tgt_info.get("label") or str(tgt), node_key=tgt)
            nodes[tgt_node.id] = tgt_node
            edges.append(_graph_edge("projection_target", pn.id, tgt_node.id, label="target"))
        for cid, cnode in circuit_nodes.items():
            edges.append(_graph_edge("circuit_contains_projection", cnode, pn.id, label="contains"))

    for pf in projection_functions:
        proj_id = pf.get("final_projection_id")
        if proj_id in proj_nodes:
            fn = _graph_node(
                "projection_function",
                label=pf.get("function_term") or str(pf.get("id")),
                final_id=pf.get("id"),
                source_mirror_id=pf.get("source_mirror_id"),
            )
            nodes[fn.id] = fn
            edges.append(
                _graph_edge("has_function", proj_nodes[proj_id], fn.id, label="function", final_id=pf.get("id"))
            )

    return FinalGraphResponse(nodes=list(nodes.values()), edges=edges, center_node_id=center.id)


async def get_final_region_neighborhood(
    session: AsyncSession,
    region_candidate_id: uuid.UUID,
) -> FinalRegionNeighborhoodResponse:
    region_label, source_atlas, granularity_level = await _region_label(session, region_candidate_id)

    region_functions = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalRegionFunction)
                .where(FinalRegionFunction.region_candidate_id == region_candidate_id)
                .order_by(FinalRegionFunction.created_at.desc())
            )
        ).scalars().all()
    ]

    circuit_steps = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalCircuitStep)
                .where(FinalCircuitStep.region_candidate_id == region_candidate_id)
                .order_by(FinalCircuitStep.step_order.asc())
            )
        ).scalars().all()
    ]

    outgoing = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalProjection)
                .where(
                    FinalProjection.source_region_candidate_id == region_candidate_id,
                    FinalProjection.directionality != "undirected",
                )
                .order_by(FinalProjection.created_at.desc())
            )
        ).scalars().all()
    ]
    incoming = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalProjection)
                .where(
                    FinalProjection.target_region_candidate_id == region_candidate_id,
                    FinalProjection.directionality != "undirected",
                )
                .order_by(FinalProjection.created_at.desc())
            )
        ).scalars().all()
    ]
    undirected = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalProjection)
                .where(
                    FinalProjection.directionality == "undirected",
                    or_(
                        FinalProjection.source_region_candidate_id == region_candidate_id,
                        FinalProjection.target_region_candidate_id == region_candidate_id,
                    ),
                )
                .order_by(FinalProjection.created_at.desc())
            )
        ).scalars().all()
    ]

    circuit_ids: set[uuid.UUID] = {s["final_circuit_id"] for s in circuit_steps if s.get("final_circuit_id")}
    projection_ids = {p["id"] for p in outgoing + incoming + undirected}

    if projection_ids:
        memberships = list(
            (
                await session.execute(
                    select(FinalCircuitProjectionMembership).where(
                        FinalCircuitProjectionMembership.final_projection_id.in_(projection_ids)
                    )
                )
            ).scalars().all()
        )
        circuit_ids.update(m.final_circuit_id for m in memberships)

    triples_raw = await collect_final_triples(
        session,
        object_ids={"circuit": circuit_ids, "projection": projection_ids},
        region_candidate_id=region_candidate_id,
    )
    for t in triples_raw:
        if t.get("predicate") == "has_participant_region" and t.get("object_id") == str(region_candidate_id):
            sid = t.get("subject_id")
            if sid and t.get("subject_type") == "circuit":
                circuit_ids.add(uuid.UUID(str(sid)))

    circuits = []
    if circuit_ids:
        circuits = [
            _row_json(r)
            for r in (
                await session.execute(
                    select(FinalRegionCircuit).where(FinalRegionCircuit.id.in_(circuit_ids))
                )
            ).scalars().all()
        ]

    projection_functions = []
    if projection_ids:
        projection_functions = [
            _row_json(r)
            for r in (
                await session.execute(
                    select(FinalProjectionFunction).where(
                        FinalProjectionFunction.final_projection_id.in_(projection_ids)
                    )
                )
            ).scalars().all()
        ]

    region_ids: set[uuid.UUID] = {region_candidate_id}
    for p in outgoing + incoming + undirected:
        if p.get("source_region_candidate_id"):
            region_ids.add(uuid.UUID(str(p["source_region_candidate_id"])))
        if p.get("target_region_candidate_id"):
            region_ids.add(uuid.UUID(str(p["target_region_candidate_id"])))
    region_map = await _regions_map(session, region_ids)

    evidence_targets: list[tuple[str, uuid.UUID]] = [("region", region_candidate_id)]
    for rf in region_functions:
        evidence_targets.append(("region_function", uuid.UUID(str(rf["id"]))))
    for c in circuits:
        evidence_targets.append(("circuit", uuid.UUID(str(c["id"]))))
    for s in circuit_steps:
        evidence_targets.append(("circuit_step", uuid.UUID(str(s["id"]))))
    for p in outgoing + incoming + undirected:
        evidence_targets.append(("projection", uuid.UUID(str(p["id"]))))
    evidence = await collect_final_evidence(session, targets=evidence_targets)

    graph = build_region_graph(
        region_candidate_id=region_candidate_id,
        region_label=region_label,
        region_functions=region_functions,
        circuits=circuits,
        circuit_steps=circuit_steps,
        outgoing_projections=outgoing,
        incoming_projections=incoming,
        undirected_projections=undirected,
        projection_functions=projection_functions,
        region_map=region_map,
    )

    return FinalRegionNeighborhoodResponse(
        region_candidate_id=region_candidate_id,
        region_label=region_label,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        region_functions=region_functions,
        circuits=circuits,
        circuit_steps=circuit_steps,
        outgoing_projections=outgoing,
        incoming_projections=incoming,
        undirected_projections=undirected,
        projection_functions=projection_functions,
        triples=triples_raw,
        evidence=evidence,
        graph=graph,
    )


def build_circuit_graph(
    *,
    circuit: dict[str, Any],
    steps: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    projections: list[dict[str, Any]],
    participant_regions: list[dict[str, Any]],
    circuit_functions: list[dict[str, Any]],
    projection_functions: list[dict[str, Any]],
) -> FinalGraphResponse:
    nodes: dict[str, FinalGraphNode] = {}
    edges: list[FinalGraphEdge] = []
    cid = circuit.get("id")
    center = _graph_node(
        "circuit",
        label=circuit.get("circuit_name") or str(cid),
        final_id=cid,
        source_mirror_id=circuit.get("source_mirror_circuit_id"),
    )
    nodes[center.id] = center

    region_nodes: dict[uuid.UUID, str] = {}
    for pr in participant_regions:
        rid = _as_uuid(pr.get("region_candidate_id"))
        if not rid:
            continue
        rn = _graph_node("region", label=pr.get("label") or str(rid), node_key=rid)
        nodes[rn.id] = rn
        region_nodes[rid] = rn.id

    for step in steps:
        sn = _graph_node(
            "circuit_step",
            label=step.get("step_name") or str(step.get("id")),
            final_id=_as_uuid(step.get("id")),
            source_mirror_id=_as_uuid(step.get("source_mirror_id")),
        )
        nodes[sn.id] = sn
        edges.append(_graph_edge("contains_step", center.id, sn.id, label="step", final_id=_as_uuid(step.get("id"))))
        rid = _as_uuid(step.get("region_candidate_id"))
        if rid and rid in region_nodes:
            edges.append(_graph_edge("step_region", sn.id, region_nodes[rid], label="at_region"))

    proj_nodes: dict[uuid.UUID, str] = {}
    for p in projections:
        pid = _as_uuid(p.get("id"))
        pn = _graph_node(
            "projection",
            label=p.get("projection_type") or str(p.get("id")),
            final_id=pid,
            source_mirror_id=_as_uuid(p.get("source_mirror_id")),
        )
        nodes[pn.id] = pn
        if pid:
            proj_nodes[pid] = pn.id
        edges.append(_graph_edge("contains_projection", center.id, pn.id, label="projection", final_id=pid))
        src = _as_uuid(p.get("source_region_candidate_id"))
        tgt = _as_uuid(p.get("target_region_candidate_id"))
        if src and src in region_nodes:
            edges.append(_graph_edge("projection_source", region_nodes[src], pn.id, label="source"))
        if tgt and tgt in region_nodes:
            edges.append(_graph_edge("projection_target", pn.id, region_nodes[tgt], label="target"))

    for pf in projection_functions:
        pid = _as_uuid(pf.get("final_projection_id"))
        if pid in proj_nodes:
            fn = _graph_node(
                "projection_function",
                label=pf.get("function_term") or str(pf.get("id")),
                final_id=pf.get("id"),
                source_mirror_id=pf.get("source_mirror_id"),
            )
            nodes[fn.id] = fn
            edges.append(_graph_edge("has_function", proj_nodes[pid], fn.id, final_id=pf.get("id")))

    for cf in circuit_functions:
        fn = _graph_node(
            "circuit_function",
            label=cf.get("function_term") or str(cf.get("id")),
            final_id=cf.get("id"),
            source_mirror_id=cf.get("source_mirror_id"),
        )
        nodes[fn.id] = fn
        edges.append(_graph_edge("has_function", center.id, fn.id, final_id=cf.get("id")))

    return FinalGraphResponse(nodes=list(nodes.values()), edges=edges, center_node_id=center.id)


async def get_final_circuit_detail(
    session: AsyncSession,
    final_circuit_id: uuid.UUID,
) -> FinalCircuitDetailResponse | None:
    circuit_row = await session.get(FinalRegionCircuit, final_circuit_id)
    if circuit_row is None:
        return None
    circuit = _row_json(circuit_row)

    steps = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalCircuitStep)
                .where(FinalCircuitStep.final_circuit_id == final_circuit_id)
                .order_by(FinalCircuitStep.step_order.asc())
            )
        ).scalars().all()
    ]

    memberships = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalCircuitProjectionMembership).where(
                    FinalCircuitProjectionMembership.final_circuit_id == final_circuit_id
                )
            )
        ).scalars().all()
    ]

    projection_ids = {m["final_projection_id"] for m in memberships if m.get("final_projection_id")}
    projections = []
    if projection_ids:
        projections = [
            _row_json(r)
            for r in (
                await session.execute(select(FinalProjection).where(FinalProjection.id.in_(projection_ids)))
            ).scalars().all()
        ]

    circuit_functions = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalCircuitFunction).where(FinalCircuitFunction.final_circuit_id == final_circuit_id)
            )
        ).scalars().all()
    ]

    projection_functions_summary = []
    if projection_ids:
        projection_functions_summary = [
            _row_json(r)
            for r in (
                await session.execute(
                    select(FinalProjectionFunction).where(
                        FinalProjectionFunction.final_projection_id.in_(projection_ids)
                    )
                )
            ).scalars().all()
        ]

    region_ids: set[uuid.UUID] = set()
    for s in steps:
        if s.get("region_candidate_id"):
            region_ids.add(uuid.UUID(str(s["region_candidate_id"])))
    for p in projections:
        if p.get("source_region_candidate_id"):
            region_ids.add(uuid.UUID(str(p["source_region_candidate_id"])))
        if p.get("target_region_candidate_id"):
            region_ids.add(uuid.UUID(str(p["target_region_candidate_id"])))

    triples = await collect_final_triples(
        session,
        object_ids={"circuit": {final_circuit_id}, "projection": projection_ids},
        limit=200,
    )
    for t in triples:
        if t.get("predicate") == "has_participant_region" and t.get("subject_id") == str(final_circuit_id):
            oid = t.get("object_id")
            if oid:
                region_ids.add(uuid.UUID(str(oid)))

    region_map = await _regions_map(session, region_ids)
    participant_regions = list(region_map.values())

    evidence_targets = [("circuit", final_circuit_id)]
    for s in steps:
        evidence_targets.append(("circuit_step", uuid.UUID(str(s["id"]))))
    for p in projections:
        evidence_targets.append(("projection", uuid.UUID(str(p["id"]))))
    evidence = await collect_final_evidence(session, targets=evidence_targets)

    provenance = await build_provenance_payload(session, circuit_row, "circuit")
    graph = build_circuit_graph(
        circuit=circuit,
        steps=steps,
        memberships=memberships,
        projections=projections,
        participant_regions=participant_regions,
        circuit_functions=circuit_functions,
        projection_functions=projection_functions_summary,
    )

    return FinalCircuitDetailResponse(
        circuit=circuit,
        steps=steps,
        memberships=memberships,
        projections=projections,
        participant_regions=participant_regions,
        circuit_functions=circuit_functions,
        projection_functions_summary=projection_functions_summary,
        triples=triples,
        evidence=evidence,
        provenance=provenance,
        graph=graph,
    )


def build_projection_graph(
    *,
    projection: dict[str, Any],
    source_region: dict[str, Any] | None,
    target_region: dict[str, Any] | None,
    circuits: list[dict[str, Any]],
    projection_functions: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
) -> FinalGraphResponse:
    nodes: dict[str, FinalGraphNode] = {}
    edges: list[FinalGraphEdge] = []
    pid = projection.get("id")
    center = _graph_node(
        "projection",
        label=projection.get("projection_type") or str(pid),
        final_id=pid,
        source_mirror_id=projection.get("source_mirror_id"),
    )
    nodes[center.id] = center

    if source_region:
        src = _graph_node(
            "region",
            label=source_region.get("label") or str(source_region.get("region_candidate_id")),
            node_key=source_region.get("region_candidate_id"),
        )
        nodes[src.id] = src
        edges.append(_graph_edge("projection_source", src.id, center.id, label="source"))

    if target_region:
        tgt = _graph_node(
            "region",
            label=target_region.get("label") or str(target_region.get("region_candidate_id")),
            node_key=target_region.get("region_candidate_id"),
        )
        nodes[tgt.id] = tgt
        edges.append(_graph_edge("projection_target", center.id, tgt.id, label="target"))

    for c in circuits:
        cn = _graph_node(
            "circuit",
            label=c.get("circuit_name") or str(c.get("id")),
            final_id=c.get("id"),
            source_mirror_id=c.get("source_mirror_circuit_id"),
        )
        nodes[cn.id] = cn
        edges.append(_graph_edge("circuit_contains", cn.id, center.id, label="membership"))

    for pf in projection_functions:
        fn = _graph_node(
            "projection_function",
            label=pf.get("function_term") or str(pf.get("id")),
            final_id=pf.get("id"),
            source_mirror_id=pf.get("source_mirror_id"),
        )
        nodes[fn.id] = fn
        edges.append(_graph_edge("has_function", center.id, fn.id, final_id=pf.get("id")))

    if evidence:
        for ev in evidence[:5]:
            en = _graph_node("evidence", label=(ev.get("evidence_text") or "")[:60], final_id=ev.get("id"))
            nodes[en.id] = en
            edges.append(_graph_edge("has_evidence", center.id, en.id, final_id=ev.get("id")))

    return FinalGraphResponse(nodes=list(nodes.values()), edges=edges, center_node_id=center.id)


async def get_final_projection_detail(
    session: AsyncSession,
    final_projection_id: uuid.UUID,
) -> FinalProjectionDetailResponse | None:
    projection_row = await session.get(FinalProjection, final_projection_id)
    if projection_row is None:
        return None
    projection = _row_json(projection_row)

    region_ids: set[uuid.UUID] = set()
    if projection_row.source_region_candidate_id:
        region_ids.add(projection_row.source_region_candidate_id)
    if projection_row.target_region_candidate_id:
        region_ids.add(projection_row.target_region_candidate_id)
    region_map = await _regions_map(session, region_ids)
    source_region = region_map.get(projection_row.source_region_candidate_id) if projection_row.source_region_candidate_id else None
    target_region = region_map.get(projection_row.target_region_candidate_id) if projection_row.target_region_candidate_id else None

    memberships = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalCircuitProjectionMembership).where(
                    FinalCircuitProjectionMembership.final_projection_id == final_projection_id
                )
            )
        ).scalars().all()
    ]

    circuit_ids = {m["final_circuit_id"] for m in memberships if m.get("final_circuit_id")}
    circuits = []
    if circuit_ids:
        circuits = [
            _row_json(r)
            for r in (
                await session.execute(select(FinalRegionCircuit).where(FinalRegionCircuit.id.in_(circuit_ids)))
            ).scalars().all()
        ]

    projection_functions = [
        _row_json(r)
        for r in (
            await session.execute(
                select(FinalProjectionFunction).where(
                    FinalProjectionFunction.final_projection_id == final_projection_id
                )
            )
        ).scalars().all()
    ]

    triples = await collect_final_triples(
        session,
        object_ids={"projection": {final_projection_id}, "circuit": circuit_ids},
        limit=200,
    )
    evidence = await collect_final_evidence(
        session,
        targets=[("projection", final_projection_id)],
    )

    provenance = await build_provenance_payload(session, projection_row, "projection")
    graph = build_projection_graph(
        projection=projection,
        source_region=source_region,
        target_region=target_region,
        circuits=circuits,
        projection_functions=projection_functions,
        evidence=evidence,
    )

    return FinalProjectionDetailResponse(
        projection=projection,
        source_region=source_region,
        target_region=target_region,
        memberships=memberships,
        circuits=circuits,
        projection_functions=projection_functions,
        triples=triples,
        evidence=evidence,
        provenance=provenance,
        graph=graph,
    )


DETAIL_MODEL_MAP: dict[str, tuple[type, str]] = {
    "circuit": (FinalRegionCircuit, "circuit"),
    "circuit_step": (FinalCircuitStep, "circuit_step"),
    "projection": (FinalProjection, "projection"),
    "projection_function": (FinalProjectionFunction, "projection_function"),
    "circuit_projection_membership": (FinalCircuitProjectionMembership, "circuit_projection_membership"),
    "region_function": (FinalRegionFunction, "region_function"),
    "circuit_function": (FinalCircuitFunction, "circuit_function"),
    "triple": (FinalKgTriple, "triple"),
    "evidence": (FinalEvidenceRecord, "evidence"),
}


async def get_final_object_detail(
    session: AsyncSession,
    target_type: str,
    final_id: uuid.UUID,
) -> FinalObjectDetailResponse | None:
    if target_type not in {t.value for t in OBJECT_DETAIL_TARGET_TYPES}:
        raise ValueError(f"unsupported target_type: {target_type}")

    model, mirror_default = DETAIL_MODEL_MAP[target_type]
    row = await session.get(model, final_id)
    if row is None:
        return None

    obj = _row_json(row)
    related_objects: list[dict[str, Any]] = []
    warnings: list[str] = []

    if target_type == "circuit_step":
        cid = getattr(row, "final_circuit_id", None)
        if cid:
            c = await session.get(FinalRegionCircuit, cid)
            if c:
                related_objects.append({"target_type": "circuit", **_row_json(c)})
    elif target_type == "projection_function":
        pid = getattr(row, "final_projection_id", None)
        if pid:
            p = await session.get(FinalProjection, pid)
            if p:
                related_objects.append({"target_type": "projection", **_row_json(p)})
    elif target_type == "circuit_projection_membership":
        cid = getattr(row, "final_circuit_id", None)
        pid = getattr(row, "final_projection_id", None)
        if cid:
            c = await session.get(FinalRegionCircuit, cid)
            if c:
                related_objects.append({"target_type": "circuit", **_row_json(c)})
        if pid:
            p = await session.get(FinalProjection, pid)
            if p:
                related_objects.append({"target_type": "projection", **_row_json(p)})
    elif target_type == "circuit_function":
        cid = getattr(row, "final_circuit_id", None)
        if cid:
            c = await session.get(FinalRegionCircuit, cid)
            if c:
                related_objects.append({"target_type": "circuit", **_row_json(c)})
    elif target_type == "region_function":
        rid = getattr(row, "region_candidate_id", None)
        if rid:
            info = await _regions_map(session, {rid})
            if rid in info:
                related_objects.append({"target_type": "region", **info[rid]})

    object_ids: dict[str, set[uuid.UUID]] = {target_type: {final_id}}
    triples = await collect_final_triples(session, object_ids=object_ids, limit=100)
    evidence = await collect_final_evidence(session, targets=[(target_type, final_id)])
    provenance = await build_provenance_payload(session, row, mirror_default)

    return FinalObjectDetailResponse(
        target_type=target_type,
        final_id=final_id,
        object=obj,
        related_objects=related_objects,
        triples=triples,
        evidence=evidence,
        provenance=provenance,
        promotion_record=provenance.promotion_record,
        warnings=warnings,
    )


async def list_final_regions_for_browser(
    session: AsyncSession,
    *,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Distinct region_candidate_ids referenced by final macro_clinical objects."""
    region_ids: set[uuid.UUID] = set()
    for stmt_model in (
        select(FinalCircuitStep.region_candidate_id).where(FinalCircuitStep.region_candidate_id.isnot(None)),
        select(FinalRegionFunction.region_candidate_id).where(FinalRegionFunction.region_candidate_id.isnot(None)),
        select(FinalProjection.source_region_candidate_id).where(FinalProjection.source_region_candidate_id.isnot(None)),
        select(FinalProjection.target_region_candidate_id).where(FinalProjection.target_region_candidate_id.isnot(None)),
    ):
        rows = (await session.execute(stmt_model)).scalars().all()
        region_ids.update(r for r in rows if r)

    region_map = await _regions_map(session, region_ids)
    items = list(region_map.values())
    if source_atlas:
        items = [i for i in items if i.get("source_atlas") == source_atlas]
    if granularity_level:
        items = [i for i in items if i.get("granularity_level") == granularity_level]
    return items[offset : offset + limit]


async def get_final_graph(
    session: AsyncSession,
    *,
    center_type: str,
    center_id: uuid.UUID,
    depth: int = 1,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    include_functions: bool = True,
    include_evidence: bool = False,
    include_triples: bool = True,
    limit: int = 200,
) -> FinalGraphResponse:
    depth = min(max(depth, 1), MAX_GRAPH_DEPTH)
    limit = min(max(limit, 1), MAX_GRAPH_LIMIT)
    warnings: list[str] = []

    if center_type == "region":
        nb = await get_final_region_neighborhood(session, center_id)
        graph = nb.graph
    elif center_type == "circuit":
        detail = await get_final_circuit_detail(session, center_id)
        if detail is None:
            return FinalGraphResponse(warnings=["circuit not found"])
        graph = detail.graph
    elif center_type == "projection":
        detail = await get_final_projection_detail(session, center_id)
        if detail is None:
            return FinalGraphResponse(warnings=["projection not found"])
        graph = detail.graph
    elif center_type == "circuit_step":
        step = await session.get(FinalCircuitStep, center_id)
        if step is None:
            return FinalGraphResponse(warnings=["circuit_step not found"])
        if step.final_circuit_id:
            detail = await get_final_circuit_detail(session, step.final_circuit_id)
            graph = detail.graph if detail else FinalGraphResponse()
        else:
            graph = FinalGraphResponse()
    elif center_type == "projection_function":
        pf = await session.get(FinalProjectionFunction, center_id)
        if pf is None:
            return FinalGraphResponse(warnings=["projection_function not found"])
        if pf.final_projection_id:
            detail = await get_final_projection_detail(session, pf.final_projection_id)
            graph = detail.graph if detail else FinalGraphResponse()
        else:
            graph = FinalGraphResponse()
    else:
        raise ValueError(f"unsupported center_type: {center_type}")

    if source_atlas or granularity_level:
        filtered_nodes = []
        for n in graph.nodes:
            meta_atlas = n.metadata.get("source_atlas")
            meta_gran = n.metadata.get("granularity_level")
            if source_atlas and meta_atlas and meta_atlas != source_atlas:
                continue
            if granularity_level and meta_gran and meta_gran != granularity_level:
                continue
            filtered_nodes.append(n)
        if len(filtered_nodes) < len(graph.nodes):
            graph = FinalGraphResponse(
                nodes=filtered_nodes,
                edges=[e for e in graph.edges if e.source in {n.id for n in filtered_nodes} and e.target in {n.id for n in filtered_nodes}],
                center_node_id=graph.center_node_id,
                warnings=graph.warnings,
            )

    if not include_functions:
        fn_types = {"region_function", "circuit_function", "projection_function"}
        fn_ids = {n.id for n in graph.nodes if n.type in fn_types}
        graph = FinalGraphResponse(
            nodes=[n for n in graph.nodes if n.type not in fn_types],
            edges=[e for e in graph.edges if e.source not in fn_ids and e.target not in fn_ids],
            center_node_id=graph.center_node_id,
            warnings=graph.warnings,
        )

    if not include_evidence:
        ev_ids = {n.id for n in graph.nodes if n.type == "evidence"}
        graph = FinalGraphResponse(
            nodes=[n for n in graph.nodes if n.type != "evidence"],
            edges=[e for e in graph.edges if e.source not in ev_ids and e.target not in ev_ids],
            center_node_id=graph.center_node_id,
            warnings=graph.warnings,
        )

    if len(graph.nodes) > limit:
        warnings.append(f"graph truncated to {limit} nodes")
        graph = FinalGraphResponse(
            nodes=graph.nodes[:limit],
            edges=graph.edges,
            center_node_id=graph.center_node_id,
            warnings=[*graph.warnings, *warnings],
        )
    elif warnings:
        graph = FinalGraphResponse(
            nodes=graph.nodes,
            edges=graph.edges,
            center_node_id=graph.center_node_id,
            warnings=[*graph.warnings, *warnings],
        )

    if depth > 1 and center_type in {"circuit", "projection", "region"}:
        warnings.append("depth>1 expansion uses direct neighborhood only in this MVP")
        graph = FinalGraphResponse(
            nodes=graph.nodes,
            edges=graph.edges,
            center_node_id=graph.center_node_id,
            warnings=[*graph.warnings, *warnings],
        )

    return graph
