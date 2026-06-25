"""Final KG export / sync preparation service (Step 8.17, read-only DB)."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
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
    FinalProjection,
    FinalProjectionFunction,
)
from app.schemas.final_kg_export import (
    DEFAULT_EXPORT_FORMATS,
    DEFAULT_EXPORT_TARGET_TYPES,
    EXPORT_SCHEMA_VERSION,
    FinalKgExportFileListResponse,
    FinalKgExportFileRead,
    FinalKgExportFormat,
    FinalKgExportManifest,
    FinalKgExportManifestBoundaries,
    FinalKgExportManifestCounts,
    FinalKgExportManifestListResponse,
    FinalKgExportManifestRead,
    FinalKgExportPreviewResponse,
    FinalKgExportRequest,
    FinalKgExportRunResponse,
    FinalKgExportScope,
)
from app.services.final_macro_clinical_promotion_service import _row_json

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXPORT_BASE_DIR = _BACKEND_ROOT / "data" / "exports" / "final_kg"

EXPORT_ID_PATTERN = re.compile(r"^EXP-[A-Za-z0-9_-]+$")
ALLOWED_FILENAMES = frozenset({
    "manifest.json",
    "nodes.jsonl",
    "edges.jsonl",
    "nodes.csv",
    "edges.csv",
    "neo4j_nodes.csv",
    "neo4j_relationships.csv",
    "evidence.jsonl",
    "provenance.jsonl",
    "README.md",
})

TYPE_TO_NODE_PREFIX: dict[str, str] = {
    "brain_region": "candidate_region",
    "region_function": "final:region_function",
    "circuit": "final:circuit",
    "circuit_step": "final:circuit_step",
    "circuit_function": "final:circuit_function",
    "projection": "final:projection",
    "projection_function": "final:projection_function",
    "circuit_projection_membership": "final:circuit_projection_membership",
    "triple": "final:triple",
    "evidence": "final:evidence",
}

TRIPLE_TYPE_MAP: dict[str, str] = {
    "region": "brain_region",
    "circuit": "circuit",
    "projection": "projection",
    "circuit_step": "circuit_step",
    "region_function": "region_function",
    "circuit_function": "circuit_function",
    "projection_function": "projection_function",
    "triple": "triple",
    "evidence": "evidence",
}


def get_export_base_dir() -> Path:
    return EXPORT_BASE_DIR


def sanitize_export_id(export_id: str) -> str:
    if not EXPORT_ID_PATTERN.match(export_id):
        raise ValueError("invalid export_id")
    return export_id


def ensure_export_path_safe(export_id: str, filename: str | None = None) -> Path:
    export_id = sanitize_export_id(export_id)
    base = get_export_base_dir().resolve()
    export_dir = (base / export_id).resolve()
    if not str(export_dir).startswith(str(base)):
        raise ValueError("path traversal rejected")
    if filename:
        if ".." in filename or filename.startswith("/") or "\\" in filename:
            raise ValueError("invalid filename")
        if filename not in ALLOWED_FILENAMES:
            raise ValueError("filename not allowed")
        target = (export_dir / filename).resolve()
        if not str(target).startswith(str(export_dir)):
            raise ValueError("path traversal rejected")
        return target
    return export_dir


def generate_export_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"EXP-{ts}-{suffix}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def final_node_id(target_type: str, final_id: uuid.UUID | str) -> str:
    return f"final:{target_type}:{final_id}"


def brain_region_node_id(region_candidate_id: uuid.UUID | str) -> str:
    return f"candidate_region:{region_candidate_id}"


def make_edge_id(edge_type: str, source: str, target: str, predicate_or_role: str = "") -> str:
    raw = f"edge:{edge_type}:{source}:{target}:{predicate_or_role}"
    if len(raw) > 200:
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"edge:{edge_type}:{digest}"
    return raw


def _provenance_from_row(row: Any, mirror_default: str) -> dict[str, Any]:
    mirror_id = None
    for attr in (
        "source_mirror_id",
        "source_mirror_circuit_id",
        "source_mirror_function_id",
        "source_mirror_triple_id",
        "source_mirror_evidence_id",
    ):
        val = getattr(row, attr, None)
        if val is not None:
            mirror_id = val
            break
    return {
        "source_mirror_type": getattr(row, "source_mirror_type", None) or mirror_default,
        "source_mirror_id": str(mirror_id) if mirror_id else None,
        "promotion_run_id": str(getattr(row, "promotion_run_id", None) or "") or None,
        "promotion_record_id": str(getattr(row, "promotion_record_id", None) or "") or None,
        "validation_summary_json": getattr(row, "validation_summary_json", None) or {},
        "review_summary_json": getattr(row, "review_summary_json", None) or {},
        "cross_validation_summary_json": getattr(row, "cross_validation_summary_json", None) or {},
        "dual_model_summary_json": getattr(row, "dual_model_summary_json", None) or {},
        "provenance_json": getattr(row, "provenance_json", None) or {},
    }


def _scope_filters(model, scope: FinalKgExportScope | None, *, default_active: bool = True):
    stmt = select(model)
    if scope is None:
        scope = FinalKgExportScope()
    if scope.source_atlas and hasattr(model, "source_atlas"):
        stmt = stmt.where(model.source_atlas == scope.source_atlas)
    if scope.source_version and hasattr(model, "source_version"):
        stmt = stmt.where(model.source_version == scope.source_version)
    if scope.granularity_level and hasattr(model, "granularity_level"):
        stmt = stmt.where(model.granularity_level == scope.granularity_level)
    if scope.granularity_family and hasattr(model, "granularity_family"):
        stmt = stmt.where(model.granularity_family == scope.granularity_family)
    if scope.resource_id and hasattr(model, "resource_id"):
        stmt = stmt.where(model.resource_id == scope.resource_id)
    if scope.batch_id and hasattr(model, "batch_id"):
        stmt = stmt.where(model.batch_id == scope.batch_id)
    if hasattr(model, "final_status"):
        if scope.final_status:
            stmt = stmt.where(model.final_status == scope.final_status)
        elif not scope.include_inactive and default_active:
            stmt = stmt.where(model.final_status == "active")
    if scope.final_ids and hasattr(model, "id"):
        stmt = stmt.where(model.id.in_(scope.final_ids))
    if scope.circuit_ids and hasattr(model, "final_circuit_id"):
        stmt = stmt.where(model.final_circuit_id.in_(scope.circuit_ids))
    if scope.projection_ids and hasattr(model, "final_projection_id"):
        stmt = stmt.where(model.final_projection_id.in_(scope.projection_ids))
    if scope.region_candidate_ids and hasattr(model, "region_candidate_id"):
        stmt = stmt.where(model.region_candidate_id.in_(scope.region_candidate_ids))
    return stmt


async def collect_final_export_objects(
    session: AsyncSession,
    request: FinalKgExportRequest,
) -> dict[str, list[Any]]:
    scope = request.scope or FinalKgExportScope()
    types = request.target_types or DEFAULT_EXPORT_TARGET_TYPES
    out: dict[str, list[Any]] = {}

    if "circuit" in types:
        out["circuit"] = list((await session.execute(_scope_filters(FinalRegionCircuit, scope))).scalars().all())
    if "circuit_step" in types:
        stmt = _scope_filters(FinalCircuitStep, scope)
        if scope.circuit_ids:
            stmt = stmt.where(FinalCircuitStep.final_circuit_id.in_(scope.circuit_ids))
        if scope.region_candidate_ids:
            stmt = stmt.where(FinalCircuitStep.region_candidate_id.in_(scope.region_candidate_ids))
        out["circuit_step"] = list((await session.execute(stmt)).scalars().all())
    if "projection" in types:
        stmt = _scope_filters(FinalProjection, scope)
        if scope.projection_ids:
            stmt = stmt.where(FinalProjection.id.in_(scope.projection_ids))
        if scope.region_candidate_ids:
            from sqlalchemy import or_
            stmt = stmt.where(
                or_(
                    FinalProjection.source_region_candidate_id.in_(scope.region_candidate_ids),
                    FinalProjection.target_region_candidate_id.in_(scope.region_candidate_ids),
                )
            )
        out["projection"] = list((await session.execute(stmt)).scalars().all())
    if "projection_function" in types:
        stmt = _scope_filters(FinalProjectionFunction, scope)
        if scope.projection_ids:
            stmt = stmt.where(FinalProjectionFunction.final_projection_id.in_(scope.projection_ids))
        out["projection_function"] = list((await session.execute(stmt)).scalars().all())
    if "circuit_projection_membership" in types:
        stmt = _scope_filters(FinalCircuitProjectionMembership, scope)
        if scope.circuit_ids:
            stmt = stmt.where(FinalCircuitProjectionMembership.final_circuit_id.in_(scope.circuit_ids))
        if scope.projection_ids:
            stmt = stmt.where(FinalCircuitProjectionMembership.final_projection_id.in_(scope.projection_ids))
        out["circuit_projection_membership"] = list((await session.execute(stmt)).scalars().all())
    if "region_function" in types:
        stmt = _scope_filters(FinalRegionFunction, scope)
        if scope.region_candidate_ids:
            stmt = stmt.where(FinalRegionFunction.region_candidate_id.in_(scope.region_candidate_ids))
        out["region_function"] = list((await session.execute(stmt)).scalars().all())
    if "circuit_function" in types:
        stmt = _scope_filters(FinalCircuitFunction, scope)
        if scope.circuit_ids:
            stmt = stmt.where(FinalCircuitFunction.final_circuit_id.in_(scope.circuit_ids))
        out["circuit_function"] = list((await session.execute(stmt)).scalars().all())
    if request.include_triples and "triple" in types:
        out["triple"] = list((await session.execute(_scope_filters(FinalKgTriple, scope))).scalars().all())
    if request.include_evidence and "evidence" in types:
        out["evidence"] = list((await session.execute(select(FinalEvidenceRecord))).scalars().all())

    return out


def build_brain_region_nodes(regions: dict[uuid.UUID, CandidateBrainRegion]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for rid, row in regions.items():
        nid = brain_region_node_id(rid)
        label = row.std_name or row.en_name or row.raw_name
        nodes[nid] = {
            "node_id": nid,
            "labels": ["BrainRegion"],
            "target_type": "brain_region",
            "final_id": None,
            "final_uid": None,
            "label": label,
            "properties": {
                "region_name": row.raw_name,
                "region_name_en": row.en_name,
                "region_name_zh": row.cn_name,
                "region_code": row.source_label_id,
                "source_atlas": row.source_atlas,
                "granularity_level": row.granularity_level,
                "granularity_family": row.granularity_family,
                "laterality": row.laterality,
            },
            "provenance": {},
        }
    return nodes


def _base_final_node(
    *,
    target_type: str,
    row: Any,
    label: str,
    labels: list[str],
    mirror_default: str,
    extra_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    props = {
        "source_atlas": getattr(row, "source_atlas", None),
        "source_version": getattr(row, "source_version", None),
        "granularity_level": getattr(row, "granularity_level", None),
        "granularity_family": getattr(row, "granularity_family", None),
        "confidence": _json_safe(getattr(row, "confidence", None)),
        "final_status": getattr(row, "final_status", "active"),
    }
    if extra_properties:
        props.update(extra_properties)
    conf = getattr(row, "confidence", None)
    return {
        "node_id": final_node_id(target_type, row.id),
        "labels": labels,
        "target_type": target_type,
        "final_id": str(row.id),
        "final_uid": getattr(row, "final_uid", None),
        "label": label,
        "properties": props,
        "provenance": _provenance_from_row(row, mirror_default),
        "created_at": _json_safe(getattr(row, "created_at", None)),
    }


def resolve_endpoint_node_id(subject_type: str, subject_id: uuid.UUID | None, node_index: dict[str, dict]) -> str | None:
    if subject_id is None:
        return None
    mapped = TRIPLE_TYPE_MAP.get(subject_type, subject_type)
    if mapped == "brain_region" or subject_type == "region":
        nid = brain_region_node_id(subject_id)
    else:
        nid = final_node_id(mapped if mapped != "brain_region" else subject_type, subject_id)
    if nid in node_index:
        return nid
    alt = final_node_id(subject_type, subject_id)
    if alt in node_index:
        return alt
    return None


def build_export_nodes_edges(
    objects: dict[str, list[Any]],
    regions: dict[uuid.UUID, CandidateBrainRegion],
    *,
    include_triples: bool = True,
    include_evidence: bool = True,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    provenance_records: list[dict[str, Any]] = []
    warnings: list[str] = []

    nodes.update(build_brain_region_nodes(regions))

    for row in objects.get("circuit", []):
        n = _base_final_node(
            target_type="circuit",
            row=row,
            label=row.circuit_name,
            labels=["Circuit", "FinalObject"],
            mirror_default="circuit",
            extra_properties={"circuit_name": row.circuit_name, "circuit_type": row.circuit_type},
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "circuit", "final_id": str(row.id), **n["provenance"]})

    for row in objects.get("circuit_step", []):
        n = _base_final_node(
            target_type="circuit_step",
            row=row,
            label=row.step_name,
            labels=["CircuitStep", "FinalObject"],
            mirror_default="circuit_step",
            extra_properties={"step_order": row.step_order, "step_type": row.step_type, "role": row.role},
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "circuit_step", "final_id": str(row.id), **n["provenance"]})
        cid = final_node_id("circuit", row.final_circuit_id)
        if cid in nodes:
            eid = make_edge_id("CIRCUIT_HAS_STEP", cid, n["node_id"], str(row.step_order))
            edges[eid] = {
                "edge_id": eid,
                "type": "CIRCUIT_HAS_STEP",
                "source": cid,
                "target": n["node_id"],
                "label": "has step",
                "properties": {"step_order": row.step_order, "source_atlas": row.source_atlas, "granularity_level": row.granularity_level},
                "provenance": n["provenance"],
            }
        if row.region_candidate_id:
            rid = brain_region_node_id(row.region_candidate_id)
            if rid in nodes:
                eid = make_edge_id("STEP_HAS_REGION", n["node_id"], rid, row.role)
                edges[eid] = {
                    "edge_id": eid,
                    "type": "STEP_HAS_REGION",
                    "source": n["node_id"],
                    "target": rid,
                    "label": "at region",
                    "properties": {"role": row.role},
                    "provenance": n["provenance"],
                }

    for row in objects.get("projection", []):
        n = _base_final_node(
            target_type="projection",
            row=row,
            label=row.projection_type,
            labels=["Projection", "FinalObject"],
            mirror_default="projection",
            extra_properties={"projection_type": row.projection_type, "directionality": row.directionality},
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "projection", "final_id": str(row.id), **n["provenance"]})
        if row.source_region_candidate_id:
            src = brain_region_node_id(row.source_region_candidate_id)
            if src in nodes:
                eid = make_edge_id("PROJECTION_SOURCE_REGION", src, n["node_id"], "source")
                edges[eid] = {
                    "edge_id": eid, "type": "PROJECTION_SOURCE_REGION", "source": src, "target": n["node_id"],
                    "label": "source region", "properties": {}, "provenance": n["provenance"],
                }
        if row.target_region_candidate_id:
            tgt = brain_region_node_id(row.target_region_candidate_id)
            if tgt in nodes:
                eid = make_edge_id("PROJECTION_TARGET_REGION", n["node_id"], tgt, "target")
                edges[eid] = {
                    "edge_id": eid, "type": "PROJECTION_TARGET_REGION", "source": n["node_id"], "target": tgt,
                    "label": "target region", "properties": {}, "provenance": n["provenance"],
                }

    for row in objects.get("projection_function", []):
        n = _base_final_node(
            target_type="projection_function",
            row=row,
            label=row.function_term,
            labels=["ProjectionFunction", "Function", "FinalObject"],
            mirror_default="projection_function",
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "projection_function", "final_id": str(row.id), **n["provenance"]})
        pid = final_node_id("projection", row.final_projection_id)
        if pid in nodes:
            eid = make_edge_id("PROJECTION_HAS_FUNCTION", pid, n["node_id"], row.function_term)
            edges[eid] = {
                "edge_id": eid, "type": "PROJECTION_HAS_FUNCTION", "source": pid, "target": n["node_id"],
                "label": "has function", "properties": {}, "provenance": n["provenance"],
            }

    for row in objects.get("circuit_projection_membership", []):
        n = _base_final_node(
            target_type="circuit_projection_membership",
            row=row,
            label=row.role_in_circuit,
            labels=["CircuitProjectionMembership", "FinalObject"],
            mirror_default="circuit_projection_membership",
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "circuit_projection_membership", "final_id": str(row.id), **n["provenance"]})
        cid = final_node_id("circuit", row.final_circuit_id)
        pid = final_node_id("projection", row.final_projection_id)
        if cid in nodes and pid in nodes:
            for etype, src, tgt, lbl in (
                ("CIRCUIT_CONTAINS_PROJECTION", cid, pid, "contains projection"),
                ("PROJECTION_BELONGS_TO_CIRCUIT", pid, cid, "belongs to circuit"),
            ):
                eid = make_edge_id(etype, src, tgt, lbl)
                edges[eid] = {"edge_id": eid, "type": etype, "source": src, "target": tgt, "label": lbl, "properties": {}, "provenance": n["provenance"]}
            eid = make_edge_id("CIRCUIT_HAS_MEMBERSHIP", cid, n["node_id"], "membership")
            edges[eid] = {"edge_id": eid, "type": "CIRCUIT_HAS_MEMBERSHIP", "source": cid, "target": n["node_id"], "label": "membership", "properties": {}, "provenance": n["provenance"]}
            eid = make_edge_id("MEMBERSHIP_HAS_PROJECTION", n["node_id"], pid, "projection")
            edges[eid] = {"edge_id": eid, "type": "MEMBERSHIP_HAS_PROJECTION", "source": n["node_id"], "target": pid, "label": "projection", "properties": {}, "provenance": n["provenance"]}
        if row.final_source_step_id:
            sid = final_node_id("circuit_step", row.final_source_step_id)
            if sid in nodes:
                eid = make_edge_id("MEMBERSHIP_SOURCE_STEP", n["node_id"], sid, "source_step")
                edges[eid] = {"edge_id": eid, "type": "MEMBERSHIP_SOURCE_STEP", "source": n["node_id"], "target": sid, "label": "source step", "properties": {}, "provenance": n["provenance"]}
        if row.final_target_step_id:
            tid = final_node_id("circuit_step", row.final_target_step_id)
            if tid in nodes:
                eid = make_edge_id("MEMBERSHIP_TARGET_STEP", n["node_id"], tid, "target_step")
                edges[eid] = {"edge_id": eid, "type": "MEMBERSHIP_TARGET_STEP", "source": n["node_id"], "target": tid, "label": "target step", "properties": {}, "provenance": n["provenance"]}

    for row in objects.get("region_function", []):
        n = _base_final_node(
            target_type="region_function",
            row=row,
            label=row.function_term,
            labels=["RegionFunction", "Function", "FinalObject"],
            mirror_default="region_function",
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "region_function", "final_id": str(row.id), **n["provenance"]})
        if row.region_candidate_id:
            rid = brain_region_node_id(row.region_candidate_id)
            if rid in nodes:
                eid = make_edge_id("REGION_HAS_FUNCTION", rid, n["node_id"], row.function_term)
                edges[eid] = {
                    "edge_id": eid, "type": "REGION_HAS_FUNCTION", "source": rid, "target": n["node_id"],
                    "label": "has function", "properties": {}, "provenance": n["provenance"],
                }

    for row in objects.get("circuit_function", []):
        n = _base_final_node(
            target_type="circuit_function",
            row=row,
            label=row.function_term,
            labels=["CircuitFunction", "Function", "FinalObject"],
            mirror_default="circuit_function",
        )
        nodes[n["node_id"]] = n
        provenance_records.append({"target_type": "circuit_function", "final_id": str(row.id), **n["provenance"]})
        cid = final_node_id("circuit", row.final_circuit_id)
        if cid in nodes:
            eid = make_edge_id("CIRCUIT_HAS_FUNCTION", cid, n["node_id"], row.function_term)
            edges[eid] = {
                "edge_id": eid, "type": "CIRCUIT_HAS_FUNCTION", "source": cid, "target": n["node_id"],
                "label": "has function", "properties": {}, "provenance": n["provenance"],
            }

    if include_triples:
        for row in objects.get("triple", []):
            label = f"{row.subject_label} {row.predicate} {row.object_label}".strip()
            n = _base_final_node(
                target_type="triple",
                row=row,
                label=label,
                labels=["Triple", "FinalObject"],
                mirror_default="triple",
                extra_properties={"predicate": row.predicate, "subject_label": row.subject_label, "object_label": row.object_label},
            )
            nodes[n["node_id"]] = n
            provenance_records.append({"target_type": "triple", "final_id": str(row.id), **n["provenance"]})
            subj_nid = resolve_endpoint_node_id(row.subject_type, row.subject_id, nodes)
            obj_nid = resolve_endpoint_node_id(row.object_type, row.object_id, nodes)
            if subj_nid:
                eid = make_edge_id("TRIPLE_SUBJECT", n["node_id"], subj_nid, row.predicate)
                edges[eid] = {"edge_id": eid, "type": "TRIPLE_SUBJECT", "source": n["node_id"], "target": subj_nid, "label": "subject", "predicate": row.predicate, "properties": {}, "provenance": n["provenance"]}
            if obj_nid:
                eid = make_edge_id("TRIPLE_OBJECT", n["node_id"], obj_nid, row.predicate)
                edges[eid] = {"edge_id": eid, "type": "TRIPLE_OBJECT", "source": n["node_id"], "target": obj_nid, "label": "object", "predicate": row.predicate, "properties": {}, "provenance": n["provenance"]}
            if not subj_nid or not obj_nid:
                warnings.append(f"UNRESOLVED_TRIPLE_ENDPOINT:triple:{row.id}")

    if include_evidence:
        for row in objects.get("evidence", []):
            n = {
                "node_id": final_node_id("evidence", row.id),
                "labels": ["Evidence", "FinalObject"],
                "target_type": "evidence",
                "final_id": str(row.id),
                "final_uid": getattr(row, "final_uid", None),
                "label": (row.evidence_text or "")[:120],
                "properties": {"evidence_type": row.evidence_type, "evidence_target_type": row.evidence_target_type},
                "provenance": _provenance_from_row(row, "evidence"),
                "created_at": _json_safe(row.created_at),
            }
            nodes[n["node_id"]] = n
            provenance_records.append({"target_type": "evidence", "final_id": str(row.id), **n["provenance"]})
            target_type = row.evidence_target_type
            mapped = TRIPLE_TYPE_MAP.get(target_type, target_type)
            if mapped == "brain_region" or target_type == "region":
                tgt_nid = brain_region_node_id(row.evidence_target_id)
            else:
                tgt_nid = final_node_id(mapped, row.evidence_target_id)
            if tgt_nid in nodes:
                eid = make_edge_id("OBJECT_HAS_EVIDENCE", tgt_nid, n["node_id"], row.evidence_type)
                edges[eid] = {
                    "edge_id": eid, "type": "OBJECT_HAS_EVIDENCE", "source": tgt_nid, "target": n["node_id"],
                    "label": "has evidence", "properties": {}, "provenance": n["provenance"],
                }

    # region participates in circuit via steps
    for row in objects.get("circuit_step", []):
        if row.region_candidate_id:
            rid = brain_region_node_id(row.region_candidate_id)
            cid = final_node_id("circuit", row.final_circuit_id)
            if rid in nodes and cid in nodes:
                eid = make_edge_id("REGION_PARTICIPATES_IN_CIRCUIT", rid, cid, str(row.final_circuit_id))
                edges[eid] = {
                    "edge_id": eid, "type": "REGION_PARTICIPATES_IN_CIRCUIT", "source": rid, "target": cid,
                    "label": "participates in circuit", "properties": {}, "provenance": {},
                }

    return nodes, edges, provenance_records, warnings


async def _collect_referenced_regions(
    session: AsyncSession,
    objects: dict[str, list[Any]],
) -> dict[uuid.UUID, CandidateBrainRegion]:
    region_ids: set[uuid.UUID] = set()
    for row in objects.get("circuit_step", []):
        if row.region_candidate_id:
            region_ids.add(row.region_candidate_id)
    for row in objects.get("projection", []):
        if row.source_region_candidate_id:
            region_ids.add(row.source_region_candidate_id)
        if row.target_region_candidate_id:
            region_ids.add(row.target_region_candidate_id)
    for row in objects.get("region_function", []):
        if row.region_candidate_id:
            region_ids.add(row.region_candidate_id)
    scope = objects.get("_region_candidate_ids")
    if scope:
        region_ids.update(scope)
    if not region_ids:
        return {}
    rows = list(
        (await session.execute(select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(region_ids)))).scalars().all()
    )
    return {r.id: r for r in rows}


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def write_csv(path: Path, columns: list[str], records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow({k: (json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v) for k, v in rec.items()})


def _nodes_to_csv_rows(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for n in nodes.values():
        p = n.get("properties") or {}
        prov = n.get("provenance") or {}
        rows.append({
            "node_id": n["node_id"],
            "labels": "|".join(n.get("labels") or []),
            "target_type": n.get("target_type"),
            "final_id": n.get("final_id"),
            "final_uid": n.get("final_uid"),
            "label": n.get("label"),
            "source_atlas": p.get("source_atlas"),
            "source_version": p.get("source_version"),
            "granularity_level": p.get("granularity_level"),
            "granularity_family": p.get("granularity_family"),
            "confidence": p.get("confidence"),
            "final_status": p.get("final_status"),
            "source_mirror_type": prov.get("source_mirror_type"),
            "source_mirror_id": prov.get("source_mirror_id"),
            "promotion_run_id": prov.get("promotion_run_id"),
            "created_at": n.get("created_at"),
            "properties_json": p,
            "provenance_json": prov,
        })
    return rows


def _edges_to_csv_rows(edges: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for e in edges.values():
        p = e.get("properties") or {}
        prov = e.get("provenance") or {}
        rows.append({
            "edge_id": e["edge_id"],
            "type": e["type"],
            "source": e["source"],
            "target": e["target"],
            "label": e.get("label"),
            "source_atlas": p.get("source_atlas"),
            "source_version": p.get("source_version"),
            "granularity_level": p.get("granularity_level"),
            "granularity_family": p.get("granularity_family"),
            "confidence": p.get("confidence"),
            "source_mirror_type": prov.get("source_mirror_type"),
            "source_mirror_id": prov.get("source_mirror_id"),
            "promotion_run_id": prov.get("promotion_run_id"),
            "properties_json": p,
            "provenance_json": prov,
        })
    return rows


def write_neo4j_csv(nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]], export_dir: Path) -> None:
    node_rows = []
    for n in nodes.values():
        p = n.get("properties") or {}
        prov = n.get("provenance") or {}
        node_rows.append({
            ":ID": n["node_id"],
            ":LABEL": ";".join(n.get("labels") or []),
            "name": n.get("label"),
            "target_type": n.get("target_type"),
            "final_id": n.get("final_id"),
            "final_uid": n.get("final_uid"),
            "source_atlas": p.get("source_atlas"),
            "source_version": p.get("source_version"),
            "granularity_level": p.get("granularity_level"),
            "granularity_family": p.get("granularity_family"),
            "confidence:float": p.get("confidence"),
            "final_status": p.get("final_status"),
            "source_mirror_type": prov.get("source_mirror_type"),
            "source_mirror_id": prov.get("source_mirror_id"),
            "promotion_run_id": prov.get("promotion_run_id"),
            "properties_json": json.dumps(p, ensure_ascii=False, default=str),
        })
    edge_rows = []
    for e in edges.values():
        p = e.get("properties") or {}
        prov = e.get("provenance") or {}
        edge_rows.append({
            ":START_ID": e["source"],
            ":END_ID": e["target"],
            ":TYPE": e["type"],
            "edge_id": e["edge_id"],
            "label": e.get("label"),
            "source_atlas": p.get("source_atlas"),
            "source_version": p.get("source_version"),
            "granularity_level": p.get("granularity_level"),
            "granularity_family": p.get("granularity_family"),
            "confidence:float": p.get("confidence"),
            "source_mirror_type": prov.get("source_mirror_type"),
            "source_mirror_id": prov.get("source_mirror_id"),
            "promotion_run_id": prov.get("promotion_run_id"),
            "properties_json": json.dumps(p, ensure_ascii=False, default=str),
        })
    write_csv(export_dir / "neo4j_nodes.csv", list(node_rows[0].keys()) if node_rows else [":ID", ":LABEL", "name"], node_rows)
    write_csv(
        export_dir / "neo4j_relationships.csv",
        list(edge_rows[0].keys()) if edge_rows else [":START_ID", ":END_ID", ":TYPE", "edge_id"],
        edge_rows,
    )


def write_readme(manifest: FinalKgExportManifest, export_dir: Path) -> None:
    lines = [
        f"# Final KG Export — {manifest.export_id}",
        "",
        f"- **Created at**: {manifest.created_at}",
        f"- **Export label**: {manifest.export_label or '(none)'}",
        f"- **Schema version**: {manifest.schema_version}",
        "",
        "## Scope",
        "```json",
        json.dumps(manifest.scope, indent=2, ensure_ascii=False, default=str),
        "```",
        "",
        f"**Target types**: {', '.join(manifest.target_types)}",
        f"**Formats**: {', '.join(manifest.formats)}",
        "",
        "## Files",
        "",
    ]
    for key, fname in manifest.files.items():
        lines.append(f"- `{fname}` — {key}")
    lines.extend([
        "",
        "## Node labels",
        "BrainRegion, Circuit, CircuitStep, CircuitFunction, Projection, ProjectionFunction,",
        "CircuitProjectionMembership, RegionFunction, Triple, Evidence, FinalObject",
        "",
        "## Edge types",
        "REGION_HAS_FUNCTION, REGION_PARTICIPATES_IN_CIRCUIT, CIRCUIT_HAS_STEP, STEP_HAS_REGION,",
        "CIRCUIT_CONTAINS_PROJECTION, PROJECTION_BELONGS_TO_CIRCUIT, PROJECTION_SOURCE_REGION,",
        "PROJECTION_TARGET_REGION, PROJECTION_HAS_FUNCTION, CIRCUIT_HAS_FUNCTION, OBJECT_HAS_EVIDENCE,",
        "TRIPLE_SUBJECT, TRIPLE_OBJECT",
        "",
        "## Neo4j CSV import (manual only)",
        "",
        "This export was **NOT** imported into Neo4j automatically.",
        "",
        "Example (user must review paths and run manually):",
        "```bash",
        "neo4j-admin database import full \\",
        "  --nodes=neo4j_nodes.csv \\",
        "  --relationships=neo4j_relationships.csv \\",
        "  --delimiter=, \\",
        "  --array-delimiter=;",
        "```",
        "",
        "## Boundaries",
        "",
        "- This export did **NOT** write to Neo4j.",
        "- This export did **NOT** write to kg_* tables.",
        "- This export did **NOT** sync to external NeuroGraphIQ_KG_V3 formal database.",
        "- User must manually review and import.",
        "",
    ])
    (export_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _estimate_file_count(formats: list[str], include_evidence: bool, include_provenance: bool, include_readme: bool) -> int:
    count = 1  # manifest
    if "jsonl" in formats:
        count += 2
    if "csv" in formats:
        count += 2
    if "neo4j_csv" in formats:
        count += 2
    if include_evidence:
        count += 1
    if include_provenance:
        count += 1
    if include_readme:
        count += 1
    return count


async def preview_final_kg_export(
    session: AsyncSession,
    request: FinalKgExportRequest,
) -> FinalKgExportPreviewResponse:
    _validate_request_limits(request)
    scope = request.scope or FinalKgExportScope()
    objects = await collect_final_export_objects(session, request)
    if "brain_region" in (request.target_types or DEFAULT_EXPORT_TARGET_TYPES):
        if scope.region_candidate_ids:
            objects["_region_candidate_ids"] = scope.region_candidate_ids
    regions = await _collect_referenced_regions(session, objects)
    if "brain_region" in (request.target_types or DEFAULT_EXPORT_TARGET_TYPES) and scope.region_candidate_ids:
        extra = list(
            (await session.execute(select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(scope.region_candidate_ids)))).scalars().all()
        )
        for r in extra:
            regions[r.id] = r

    nodes, edges, prov_records, warnings = build_export_nodes_edges(
        objects,
        regions,
        include_triples=request.include_triples,
        include_evidence=request.include_evidence,
    )

    if len(nodes) > request.max_nodes:
        raise ValueError(f"node count {len(nodes)} exceeds max_nodes {request.max_nodes}")
    if len(edges) > request.max_edges:
        raise ValueError(f"edge count {len(edges)} exceeds max_edges {request.max_edges}")

    candidate_counts = {k: len(v) for k, v in objects.items() if not k.startswith("_")}
    node_list = list(nodes.values())
    edge_list = list(edges.values())

    return FinalKgExportPreviewResponse(
        dry_run=True,
        candidate_counts=candidate_counts,
        estimated_node_count=len(nodes),
        estimated_edge_count=len(edges),
        estimated_file_count=_estimate_file_count(
            request.formats or DEFAULT_EXPORT_FORMATS,
            request.include_evidence,
            request.include_provenance,
            request.include_readme,
        ),
        warnings=warnings,
        sample_nodes=node_list[:10],
        sample_edges=edge_list[:10],
    )


def _validate_request_limits(request: FinalKgExportRequest) -> None:
    invalid_types = [t for t in (request.target_types or []) if t not in DEFAULT_EXPORT_TARGET_TYPES]
    if invalid_types:
        raise ValueError(f"invalid target_types: {invalid_types}")
    valid_formats = {f.value for f in FinalKgExportFormat}
    invalid_formats = [f for f in (request.formats or []) if f not in valid_formats]
    if invalid_formats:
        raise ValueError(f"invalid formats: {invalid_formats}")


async def run_final_kg_export(
    session: AsyncSession,
    request: FinalKgExportRequest,
    *,
    app_version: str = "",
) -> FinalKgExportRunResponse | FinalKgExportPreviewResponse:
    _validate_request_limits(request)
    if request.dry_run:
        return await preview_final_kg_export(session, request)

    preview = await preview_final_kg_export(session, request)
    export_id = generate_export_id()
    export_dir = get_export_base_dir() / export_id
    if export_dir.exists():
        raise ValueError("export_id collision")
    export_dir.mkdir(parents=True, exist_ok=False)

    objects = await collect_final_export_objects(session, request)
    scope = request.scope or FinalKgExportScope()
    if scope.region_candidate_ids:
        objects["_region_candidate_ids"] = scope.region_candidate_ids
    regions = await _collect_referenced_regions(session, objects)
    if "brain_region" in (request.target_types or DEFAULT_EXPORT_TARGET_TYPES) and scope.region_candidate_ids:
        extra = list(
            (await session.execute(select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(scope.region_candidate_ids)))).scalars().all()
        )
        for r in extra:
            regions[r.id] = r

    nodes, edges, prov_records, warnings = build_export_nodes_edges(
        objects,
        regions,
        include_triples=request.include_triples,
        include_evidence=request.include_evidence,
    )
    warnings = list(dict.fromkeys([*preview.warnings, *warnings]))
    formats = request.formats or DEFAULT_EXPORT_FORMATS
    files_map: dict[str, str] = {}
    written: list[str] = []

    node_list = list(nodes.values())
    edge_list = list(edges.values())

    if "jsonl" in formats:
        write_jsonl(export_dir / "nodes.jsonl", node_list)
        write_jsonl(export_dir / "edges.jsonl", edge_list)
        files_map["nodes_jsonl"] = "nodes.jsonl"
        files_map["edges_jsonl"] = "edges.jsonl"
        written.extend(["nodes.jsonl", "edges.jsonl"])

    node_csv_cols = [
        "node_id", "labels", "target_type", "final_id", "final_uid", "label",
        "source_atlas", "source_version", "granularity_level", "granularity_family",
        "confidence", "final_status", "source_mirror_type", "source_mirror_id",
        "promotion_run_id", "created_at", "properties_json", "provenance_json",
    ]
    edge_csv_cols = [
        "edge_id", "type", "source", "target", "label",
        "source_atlas", "source_version", "granularity_level", "granularity_family",
        "confidence", "source_mirror_type", "source_mirror_id", "promotion_run_id",
        "properties_json", "provenance_json",
    ]
    if "csv" in formats:
        write_csv(export_dir / "nodes.csv", node_csv_cols, _nodes_to_csv_rows(nodes))
        write_csv(export_dir / "edges.csv", edge_csv_cols, _edges_to_csv_rows(edges))
        files_map["nodes_csv"] = "nodes.csv"
        files_map["edges_csv"] = "edges.csv"
        written.extend(["nodes.csv", "edges.csv"])

    if "neo4j_csv" in formats:
        write_neo4j_csv(nodes, edges, export_dir)
        files_map["neo4j_nodes_csv"] = "neo4j_nodes.csv"
        files_map["neo4j_relationships_csv"] = "neo4j_relationships.csv"
        written.extend(["neo4j_nodes.csv", "neo4j_relationships.csv"])

    evidence_count = 0
    if request.include_evidence:
        ev_records = [n for n in node_list if n.get("target_type") == "evidence"]
        write_jsonl(export_dir / "evidence.jsonl", ev_records)
        files_map["evidence_jsonl"] = "evidence.jsonl"
        written.append("evidence.jsonl")
        evidence_count = len(ev_records)

    provenance_count = 0
    if request.include_provenance:
        write_jsonl(export_dir / "provenance.jsonl", prov_records)
        files_map["provenance_jsonl"] = "provenance.jsonl"
        written.append("provenance.jsonl")
        provenance_count = len(prov_records)

    counts = FinalKgExportManifestCounts(
        nodes=len(nodes),
        edges=len(edges),
        evidence=evidence_count,
        provenance=provenance_count,
    )
    manifest = FinalKgExportManifest(
        export_id=export_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        export_label=request.export_label,
        scope=(request.scope.model_dump(mode="json") if request.scope else {}),
        formats=formats,
        target_types=request.target_types or DEFAULT_EXPORT_TARGET_TYPES,
        counts=counts,
        files=files_map,
        schema_version=EXPORT_SCHEMA_VERSION,
        app_version=app_version,
        warnings=warnings,
        boundaries=FinalKgExportManifestBoundaries(),
    )
    files_map["readme"] = "README.md"
    if request.include_readme:
        write_readme(manifest, export_dir)
        written.append("README.md")

    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    files_map["manifest"] = "manifest.json"
    written.insert(0, "manifest.json")

    return FinalKgExportRunResponse(
        dry_run=False,
        export_id=export_id,
        export_dir=f"data/exports/final_kg/{export_id}",
        manifest=manifest,
        files=written,
        counts=counts,
        warnings=warnings,
    )


def list_exports() -> FinalKgExportManifestListResponse:
    base = get_export_base_dir()
    if not base.exists():
        return FinalKgExportManifestListResponse(items=[], total=0)
    items: list[FinalKgExportManifestRead] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            items.append(
                FinalKgExportManifestRead(
                    export_id=data["export_id"],
                    created_at=data.get("created_at", ""),
                    scope=data.get("scope", {}),
                    formats=data.get("formats", []),
                    target_types=data.get("target_types", []),
                    counts=FinalKgExportManifestCounts(**data.get("counts", {})),
                    files=data.get("files", {}),
                    warnings=data.get("warnings", []),
                    export_label=data.get("export_label"),
                )
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return FinalKgExportManifestListResponse(items=items, total=len(items))


def get_export_manifest(export_id: str) -> FinalKgExportManifest:
    path = ensure_export_path_safe(export_id, "manifest.json")
    if not path.exists():
        raise FileNotFoundError("manifest not found")
    return FinalKgExportManifest.model_validate_json(path.read_text(encoding="utf-8"))


def list_export_files(export_id: str) -> FinalKgExportFileListResponse:
    manifest = get_export_manifest(export_id)
    export_dir = ensure_export_path_safe(export_id)
    files: list[FinalKgExportFileRead] = []
    allowed = set(manifest.files.values()) | {"manifest.json"}
    for fname in sorted(allowed):
        fpath = export_dir / fname
        if not fpath.exists():
            continue
        stat = fpath.stat()
        files.append(
            FinalKgExportFileRead(
                export_id=export_id,
                filename=fname,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                download_url=f"/api/final-macro-clinical/export/{export_id}/files/{fname}",
            )
        )
    return FinalKgExportFileListResponse(export_id=export_id, files=files)


def get_export_file_path(export_id: str, filename: str) -> Path:
    manifest = get_export_manifest(export_id)
    if filename not in manifest.files.values() and filename != "manifest.json":
        raise ValueError("filename not in manifest")
    path = ensure_export_path_safe(export_id, filename)
    if not path.exists():
        raise FileNotFoundError("file not found")
    return path
