"""Macro clinical human review helpers (Step 8.14).

Detail builders, queue enrichment, gating, and priority for macro_clinical objects
and verification signal objects. No LLM; no final_*/kg_*.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorProjectionFunction,
)
from app.models.mirror_review import MirrorHumanReviewRecord
from app.schemas.mirror_review import MirrorReviewAction

DOMAIN_TARGET_TYPES = frozenset({
    "connection", "function", "region_function", "circuit", "triple",
    "projection", "circuit_step", "projection_function", "circuit_projection_membership",
})

SIGNAL_TARGET_TYPES = frozenset({
    "circuit_projection_cross_validation_result",
    "dual_model_verification_result",
})

VALID_MACRO_REVIEW_TARGET_TYPES = DOMAIN_TARGET_TYPES | SIGNAL_TARGET_TYPES

TARGET_TYPE_ALIASES = {"region_function": "function", "projection": "connection"}

SIGNAL_ACTIONS = frozenset({
    MirrorReviewAction.accept_signal, MirrorReviewAction.dismiss_signal,
    MirrorReviewAction.comment, MirrorReviewAction.flag_for_followup,
})

DOMAIN_ACTIONS = frozenset({
    MirrorReviewAction.approve, MirrorReviewAction.reject, MirrorReviewAction.needs_revision,
    MirrorReviewAction.edit, MirrorReviewAction.comment, MirrorReviewAction.flag_for_followup,
})

EDITABLE_FIELDS: dict[str, frozenset[str]] = {
    "connection": frozenset({"connection_type", "directionality", "strength", "modality", "confidence", "evidence_text", "uncertainty_reason"}),
    "projection": frozenset({"connection_type", "directionality", "strength", "modality", "confidence", "evidence_text", "uncertainty_reason"}),
    "function": frozenset({"function_term", "function_category", "relation_type", "confidence", "evidence_text", "uncertainty_reason"}),
    "region_function": frozenset({"function_term", "function_category", "relation_type", "confidence", "evidence_text", "uncertainty_reason"}),
    "circuit": frozenset({"circuit_name", "circuit_type", "function_association", "description", "confidence", "evidence_text", "uncertainty_reason"}),
    "circuit_step": frozenset({"step_order", "step_name", "step_type", "role", "description", "confidence", "evidence_text", "uncertainty_reason"}),
    "projection_function": frozenset({"function_term", "function_category", "relation_type", "confidence", "evidence_text", "uncertainty_reason"}),
    "circuit_projection_membership": frozenset({"role_in_circuit", "verification_status", "confidence", "evidence_text", "uncertainty_reason"}),
    "triple": frozenset({"predicate", "confidence", "evidence_text", "uncertainty_reason"}),
}

TARGET_TYPE_META = [
    {"target_type": "connection", "label": "Connection", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror region connection"},
    {"target_type": "function", "label": "Region Function", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror region function"},
    {"target_type": "region_function", "label": "Region Function", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Alias for function"},
    {"target_type": "projection", "label": "Projection", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror projection (region connection)"},
    {"target_type": "circuit", "label": "Circuit", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror region circuit"},
    {"target_type": "circuit_step", "label": "Circuit Step", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror circuit step"},
    {"target_type": "projection_function", "label": "Projection Function", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror projection function"},
    {"target_type": "circuit_projection_membership", "label": "Membership", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Circuit-projection membership"},
    {"target_type": "triple", "label": "Triple", "category": "domain_object", "supported_actions": sorted(DOMAIN_ACTIONS), "description": "Mirror KG triple"},
    {"target_type": "circuit_projection_cross_validation_result", "label": "Cross Validation", "category": "signal_object", "supported_actions": sorted(SIGNAL_ACTIONS), "description": "Cross validation signal"},
    {"target_type": "dual_model_verification_result", "label": "Dual-Model Result", "category": "signal_object", "supported_actions": sorted(SIGNAL_ACTIONS), "description": "Dual-model verification signal"},
]

PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}

MODEL_MAP = {
    "connection": MirrorRegionConnection,
    "projection": MirrorRegionConnection,
    "function": MirrorRegionFunction,
    "region_function": MirrorRegionFunction,
    "circuit": MirrorRegionCircuit,
    "triple": MirrorKgTriple,
    "circuit_step": MirrorCircuitStep,
    "projection_function": MirrorProjectionFunction,
    "circuit_projection_membership": MirrorCircuitProjectionMembership,
    "circuit_projection_cross_validation_result": MirrorCircuitProjectionCrossValidationResult,
    "dual_model_verification_result": MirrorDualModelVerificationResult,
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def row_to_json(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    return {col.name: _json_safe(getattr(obj, col.name)) for col in obj.__table__.columns}


def is_signal_target(target_type: str) -> bool:
    return target_type in SIGNAL_TARGET_TYPES


def normalize_target_type(target_type: str) -> str:
    return TARGET_TYPE_ALIASES.get(target_type, target_type)


def display_label(target_type: str, obj: Any) -> str:
    tt = normalize_target_type(target_type)
    if tt == "connection" or target_type == "projection":
        return f"{getattr(obj, 'connection_type', 'projection')}: {obj.source_region_candidate_id} → {obj.target_region_candidate_id}"
    if tt == "function":
        return f"{obj.function_term} ({obj.relation_type})"
    if tt == "circuit":
        return obj.circuit_name or "(unnamed circuit)"
    if target_type == "circuit_step":
        return f"step {obj.step_order}: {obj.step_name}"
    if target_type == "projection_function":
        return f"{obj.function_term} @ {obj.projection_id}"
    if target_type == "circuit_projection_membership":
        return f"membership {obj.circuit_id} ↔ {obj.projection_id}"
    if target_type == "circuit_projection_cross_validation_result":
        return f"cross {obj.validation_status}"
    if target_type == "dual_model_verification_result":
        return f"dual {obj.consensus_status}"
    return f"{obj.subject_label} {obj.predicate} {obj.object_label}"


def summary_text(target_type: str, obj: Any) -> str:
    parts = [getattr(obj, "source_atlas", None), getattr(obj, "granularity_level", None)]
    if target_type in ("connection", "projection"):
        parts.extend([getattr(obj, "directionality", None), getattr(obj, "connection_type", None)])
    elif target_type in ("function", "region_function"):
        parts.append(getattr(obj, "function_category", None))
    elif target_type == "circuit":
        parts.append(getattr(obj, "circuit_type", None))
    elif target_type == "circuit_projection_membership":
        parts.extend([getattr(obj, "source_method", None), getattr(obj, "verification_status", None)])
    elif target_type == "circuit_projection_cross_validation_result":
        parts.append(getattr(obj, "validation_status", None))
    elif target_type == "dual_model_verification_result":
        parts.append(getattr(obj, "consensus_status", None))
    return " / ".join(str(p) for p in parts if p)


async def get_signal_status(session: AsyncSession, target_type: str, target_id: uuid.UUID) -> dict[str, str]:
    rows = list(
        (await session.execute(
            select(MirrorHumanReviewRecord)
            .where(MirrorHumanReviewRecord.target_type == target_type, MirrorHumanReviewRecord.target_id == target_id)
            .order_by(MirrorHumanReviewRecord.created_at.desc()).limit(1)
        )).scalars().all()
    )
    if not rows:
        return {"mirror_status": "signal_pending", "review_status": "pending", "promotion_status": "not_applicable"}
    act = rows[0].action
    if act == MirrorReviewAction.accept_signal:
        return {"mirror_status": "signal_accepted", "review_status": "accepted", "promotion_status": "not_applicable"}
    if act == MirrorReviewAction.dismiss_signal:
        return {"mirror_status": "signal_dismissed", "review_status": "dismissed", "promotion_status": "not_applicable"}
    return {"mirror_status": "signal_pending", "review_status": "pending", "promotion_status": "not_applicable"}


async def load_cross_results(session: AsyncSession, *, circuit_id=None, projection_id=None, limit=20) -> list[dict]:
    q = select(MirrorCircuitProjectionCrossValidationResult)
    if circuit_id:
        q = q.where(MirrorCircuitProjectionCrossValidationResult.circuit_id == circuit_id)
    if projection_id:
        q = q.where(MirrorCircuitProjectionCrossValidationResult.projection_id == projection_id)
    rows = list((await session.execute(q.order_by(MirrorCircuitProjectionCrossValidationResult.created_at.desc()).limit(limit))).scalars().all())
    return [row_to_json(r) for r in rows]


async def load_dual_results(session: AsyncSession, *, object_type=None, object_id=None, limit=20) -> list[dict]:
    q = select(MirrorDualModelVerificationResult)
    if object_type:
        q = q.where(MirrorDualModelVerificationResult.object_type == object_type)
    if object_id:
        q = q.where(MirrorDualModelVerificationResult.object_id == object_id)
    rows = list((await session.execute(q.order_by(MirrorDualModelVerificationResult.created_at.desc()).limit(limit))).scalars().all())
    return [row_to_json(r) for r in rows]


async def load_region_label(session: AsyncSession, region_id: uuid.UUID | None) -> str | None:
    if not region_id:
        return None
    c = await session.get(CandidateBrainRegion, region_id)
    return (c.en_name or c.raw_name or str(region_id)) if c else str(region_id)


def compute_review_priority(val_summary, *, cross_status=None, consensus_status=None, verification_status=None, evidence_empty=False, is_signal=False) -> str:
    if val_summary.get("has_blocker") or val_summary.get("has_error"):
        return "urgent"
    if cross_status == "conflict" or consensus_status == "model_conflict":
        return "urgent"
    if consensus_status == "consensus_rejected" or consensus_status in ("insufficient_information", "needs_human_review"):
        return "high"
    if verification_status in ("model_conflict", "circuit_supported", "projection_supported"):
        return "high"
    if evidence_empty or val_summary.get("has_warning"):
        return "high"
    if cross_status == "bidirectionally_supported" or consensus_status == "consensus_supported":
        return "low"
    return "normal"


def compute_gating(target_type: str, obj: Any, val_summary: dict, *, is_signal: bool) -> dict[str, Any]:
    if is_signal:
        return {"can_approve": False, "can_reject": False, "can_edit": False, "can_comment": True,
                "can_accept_signal": True, "can_dismiss_signal": True,
                "gating_reasons": ["signal object: use accept_signal or dismiss_signal"], "requires_reviewer_reason": False}
    reasons: list[str] = []
    requires_reason = False
    if val_summary.get("has_blocker"):
        reasons.append("blocker present")
    if val_summary.get("has_error"):
        reasons.append("error present")
    if val_summary.get("has_warning"):
        requires_reason = True
        reasons.append("warnings present")
    if not (getattr(obj, "evidence_text", None) or "").strip():
        requires_reason = True
        reasons.append("evidence empty")
    if target_type == "circuit_projection_membership" and getattr(obj, "verification_status", "") == "model_conflict":
        requires_reason = True
        reasons.append("membership model_conflict")
    can_approve = bool(val_summary.get("validated") and not val_summary.get("has_blocker") and not val_summary.get("has_error")
                       and getattr(obj, "promotion_status", None) != "promoted")
    return {"can_approve": can_approve, "can_reject": getattr(obj, "promotion_status", None) != "promoted",
            "can_edit": target_type in EDITABLE_FIELDS, "can_comment": True,
            "can_accept_signal": False, "can_dismiss_signal": False,
            "gating_reasons": reasons, "requires_reviewer_reason": requires_reason}


def queue_sort_key(item: dict) -> tuple:
    pr = PRIORITY_RANK.get(item.get("recommended_review_priority", "normal"), 2)
    val = item.get("latest_validation_summary") or {}
    score = int(val.get("blocker_count") or 0) * 10 + int(val.get("error_count") or 0) * 10
    if item.get("consensus_status") == "model_conflict" or item.get("cross_validation_status") == "conflict":
        score += 5
    ts = item.get("updated_at")
    ts_val = ts.timestamp() if ts and hasattr(ts, "timestamp") else 0.0
    return (pr, -score, -ts_val)


async def build_detail_context(session: AsyncSession, target_type: str, obj: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {"cross_validation_results": [], "dual_model_results": [], "related_objects": {}}
    if target_type in ("projection", "connection"):
        pid = obj.id
        mems = list((await session.execute(select(MirrorCircuitProjectionMembership).where(MirrorCircuitProjectionMembership.projection_id == pid).limit(50))).scalars().all())
        pfs = list((await session.execute(select(MirrorProjectionFunction).where(MirrorProjectionFunction.projection_id == pid).limit(50))).scalars().all())
        ctx["related_objects"] = {"memberships": [row_to_json(m) for m in mems], "projection_functions": [row_to_json(pf) for pf in pfs],
            "source_region_label": await load_region_label(session, obj.source_region_candidate_id),
            "target_region_label": await load_region_label(session, obj.target_region_candidate_id)}
        ctx["cross_validation_results"] = await load_cross_results(session, projection_id=pid)
        ctx["dual_model_results"] = await load_dual_results(session, object_type="projection", object_id=pid)
    elif target_type == "circuit":
        cid = obj.id
        steps = list((await session.execute(select(MirrorCircuitStep).where(MirrorCircuitStep.circuit_id == cid).order_by(MirrorCircuitStep.step_order))).scalars().all())
        mems = list((await session.execute(select(MirrorCircuitProjectionMembership).where(MirrorCircuitProjectionMembership.circuit_id == cid).limit(50))).scalars().all())
        regions = list((await session.execute(select(MirrorCircuitRegion).where(MirrorCircuitRegion.circuit_id == cid))).scalars().all())
        ctx["related_objects"] = {"circuit_steps": [row_to_json(s) for s in steps], "memberships": [row_to_json(m) for m in mems], "circuit_regions": [row_to_json(r) for r in regions]}
        ctx["cross_validation_results"] = await load_cross_results(session, circuit_id=cid)
        ctx["dual_model_results"] = await load_dual_results(session, object_type="circuit", object_id=cid)
    elif target_type == "circuit_step":
        circuit = await session.get(MirrorRegionCircuit, obj.circuit_id)
        mems = list((await session.execute(select(MirrorCircuitProjectionMembership).where(
            or_(MirrorCircuitProjectionMembership.source_step_id == obj.id, MirrorCircuitProjectionMembership.target_step_id == obj.id)).limit(20))).scalars().all())
        ctx["related_objects"] = {"circuit": row_to_json(circuit), "region_label": await load_region_label(session, obj.region_candidate_id), "memberships": [row_to_json(m) for m in mems]}
        ctx["dual_model_results"] = await load_dual_results(session, object_type="circuit_step", object_id=obj.id)
    elif target_type == "projection_function":
        proj = await session.get(MirrorRegionConnection, obj.projection_id)
        ctx["related_objects"] = {"projection": row_to_json(proj), "source_region_label": await load_region_label(session, proj.source_region_candidate_id if proj else None),
            "target_region_label": await load_region_label(session, proj.target_region_candidate_id if proj else None)}
        ctx["dual_model_results"] = await load_dual_results(session, object_type="projection_function", object_id=obj.id)
    elif target_type == "circuit_projection_membership":
        ctx["related_objects"] = {
            "circuit": row_to_json(await session.get(MirrorRegionCircuit, obj.circuit_id)),
            "projection": row_to_json(await session.get(MirrorRegionConnection, obj.projection_id)),
            "source_step": row_to_json(await session.get(MirrorCircuitStep, obj.source_step_id)) if obj.source_step_id else None,
            "target_step": row_to_json(await session.get(MirrorCircuitStep, obj.target_step_id)) if obj.target_step_id else None,
        }
        ctx["cross_validation_results"] = await load_cross_results(session, circuit_id=obj.circuit_id, projection_id=obj.projection_id)
        ctx["dual_model_results"] = await load_dual_results(session, object_type="circuit_projection_membership", object_id=obj.id)
    elif target_type == "circuit_projection_cross_validation_result":
        ctx["related_objects"] = {
            "circuit": row_to_json(await session.get(MirrorRegionCircuit, obj.circuit_id)),
            "projection": row_to_json(await session.get(MirrorRegionConnection, obj.projection_id)),
            "forward_membership": row_to_json(await session.get(MirrorCircuitProjectionMembership, obj.circuit_to_projection_membership_id)) if obj.circuit_to_projection_membership_id else None,
            "reverse_membership": row_to_json(await session.get(MirrorCircuitProjectionMembership, obj.projection_to_circuit_membership_id)) if obj.projection_to_circuit_membership_id else None,
        }
    elif target_type == "dual_model_verification_result":
        lm = MODEL_MAP.get(obj.object_type)
        linked = await session.get(lm, obj.object_id) if lm else None
        ctx["related_objects"] = {"linked_object_type": obj.object_type, "linked_object_id": str(obj.object_id), "linked_object": row_to_json(linked) if linked else None}
    return ctx
