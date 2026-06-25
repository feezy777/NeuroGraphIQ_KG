"""Dual-model verification execution — DeepSeek + Kimi independent calls (Step 8.12).

Each model verifies Mirror KG objects independently; backend compares deterministically.
Writes llm_extraction_runs/items (one per model) + mirror_dual_model_verification_*.
Does NOT modify verified object status; does NOT write final_*/kg_*.
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
from app.models.mirror_cross_validation import MirrorCircuitProjectionCrossValidationResult
from app.models.mirror_kg import MirrorKgTriple, MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import (
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorDualModelVerificationRun,
    MirrorProjectionFunction,
)
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_dual_model_verification import (
    VALID_DUAL_MODEL_OBJECT_TYPES,
    DualModelConsensusStatus,
    DualModelDecision,
    DualModelReviewPriority,
    DualModelVerificationObjectType,
)
from app.schemas.mirror_macro_clinical import MirrorDualModelRunStatus
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_json_utils import parse_llm_json_response
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

DUAL_MODEL_TEMPLATE_KEY = "dual_model_verification_v1"
MAX_OBJECT_IDS = 50
MAX_SCOPE_OBJECTS = 200
PREVIEW_LIMIT = 200

PRIORITY_RANK = {
    DualModelReviewPriority.low: 0,
    DualModelReviewPriority.normal: 1,
    DualModelReviewPriority.high: 2,
    DualModelReviewPriority.urgent: 3,
}

VALID_DECISIONS = frozenset({
    DualModelDecision.support,
    DualModelDecision.reject,
    DualModelDecision.uncertain,
    DualModelDecision.insufficient_information,
    DualModelDecision.unknown,
})

VALID_PRIORITIES = frozenset({
    DualModelReviewPriority.low,
    DualModelReviewPriority.normal,
    DualModelReviewPriority.high,
    DualModelReviewPriority.urgent,
})


class InvalidObjectTypeError(ValueError):
    pass


class EmptyObjectsError(ValueError):
    pass


class TooManyObjectsError(ValueError):
    def __init__(self, count: int, maximum: int):
        self.count = count
        self.maximum = maximum
        super().__init__(f"object count {count} exceeds max {maximum}")


class ObjectNotFoundError(Exception):
    def __init__(self, object_type: str, object_id: uuid.UUID):
        self.object_type = object_type
        self.object_id = object_id
        super().__init__(f"{object_type} not found: {object_id}")


class CrossAtlasObjectError(Exception):
    def __init__(self, atlases: list[str]):
        self.atlases = atlases
        super().__init__("objects span multiple source_atlas values")


class CrossGranularityObjectError(Exception):
    def __init__(self, values: list[str]):
        self.values = values
        super().__init__("objects span multiple granularity_level values")


class SameProviderError(ValueError):
    pass


@dataclass
class VerificationScope:
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None


@dataclass
class VerificationObject:
    object_type: str
    object_id: uuid.UUID
    resource_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    source_atlas: str
    source_version: str | None
    granularity_level: str
    granularity_family: str | None
    label: str
    payload: dict[str, Any]


@dataclass
class ModelDecision:
    object_id: uuid.UUID
    decision: str
    confidence: float | None
    evidence_text: str | None
    uncertainty_reason: str | None
    risk_flags: list[str]
    recommended_review_priority: str
    raw: dict[str, Any]


@dataclass
class DualModelVerificationOutcome:
    run_id: uuid.UUID | None
    object_type: str
    object_count: int
    model_a_provider: str | None
    model_a_run_id: uuid.UUID | None
    model_b_provider: str | None
    model_b_run_id: uuid.UUID | None
    consensus_supported_count: int
    consensus_rejected_count: int
    model_conflict_count: int
    insufficient_information_count: int
    needs_human_review_count: int
    result_count: int
    dry_run: bool
    model_a_system_prompt: str | None = None
    model_a_user_prompt: str | None = None
    model_b_system_prompt: str | None = None
    model_b_user_prompt: str | None = None
    results_preview: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[DUAL_MODEL_TEMPLATE_KEY]
    return tpl


def _resolve_provider_config(provider_name: str, model_name: str | None):
    key = provider_name.lower()
    if key == "deepseek":
        cfg = get_deepseek_runtime_config()
        return key, model_name or cfg.default_model, cfg
    if key == "kimi":
        cfg = get_kimi_runtime_config()
        return key, model_name or cfg.default_model, cfg
    raise UnknownProviderError(provider_name)


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _normalize_decision(raw: Any) -> str:
    if not isinstance(raw, str):
        return DualModelDecision.unknown
    d = raw.strip().lower()
    if d in VALID_DECISIONS:
        return d
    if d in ("supported", "approve", "yes"):
        return DualModelDecision.support
    if d in ("rejected", "deny", "no"):
        return DualModelDecision.reject
    return DualModelDecision.unknown


def _normalize_priority(raw: Any) -> str:
    if isinstance(raw, str) and raw in VALID_PRIORITIES:
        return raw
    return DualModelReviewPriority.normal


def _min_priority(a: str, b: str) -> str:
    return a if PRIORITY_RANK.get(a, 1) <= PRIORITY_RANK.get(b, 1) else b


def _max_priority(a: str, b: str) -> str:
    return a if PRIORITY_RANK.get(a, 1) >= PRIORITY_RANK.get(b, 1) else b


def validate_objects_homogeneous(objects: list[VerificationObject]) -> None:
    if not objects:
        raise EmptyObjectsError()
    atlases = {o.source_atlas for o in objects}
    if len(atlases) > 1:
        raise CrossAtlasObjectError(sorted(atlases))
    granularities = {o.granularity_level for o in objects}
    if len(granularities) > 1:
        raise CrossGranularityObjectError(sorted(granularities))


def _apply_scope_filters(stmt, model, scope: VerificationScope):
    if scope.resource_id and hasattr(model, "resource_id"):
        stmt = stmt.where(model.resource_id == scope.resource_id)
    if scope.batch_id and hasattr(model, "batch_id"):
        stmt = stmt.where(model.batch_id == scope.batch_id)
    if scope.source_atlas and hasattr(model, "source_atlas"):
        stmt = stmt.where(model.source_atlas == scope.source_atlas)
    if scope.source_version and hasattr(model, "source_version"):
        stmt = stmt.where(model.source_version == scope.source_version)
    if scope.granularity_level and hasattr(model, "granularity_level"):
        stmt = stmt.where(model.granularity_level == scope.granularity_level)
    if scope.granularity_family and hasattr(model, "granularity_family"):
        stmt = stmt.where(model.granularity_family == scope.granularity_family)
    return stmt


async def _region_label(session: AsyncSession, region_id: uuid.UUID | None) -> str | None:
    if not region_id:
        return None
    c = await session.get(CandidateBrainRegion, region_id)
    if c is None:
        return str(region_id)
    return c.en_name or c.raw_name or str(region_id)


async def build_object_payload(
    session: AsyncSession,
    obj: VerificationObject,
    *,
    include_cross_validation_context: bool,
    include_evidence_context: bool,
    include_review_context: bool,
) -> dict[str, Any]:
    payload = dict(obj.payload)
    if include_evidence_context and "evidence_text" not in payload:
        payload["evidence_text"] = None
    if include_review_context:
        payload["review_status"] = payload.get("review_status")
        payload["promotion_status"] = payload.get("promotion_status")
    if include_cross_validation_context and obj.object_type == DualModelVerificationObjectType.circuit_projection_membership:
        circuit_id = payload.get("circuit_id")
        projection_id = payload.get("projection_id")
        if circuit_id and projection_id:
            q = (
                select(MirrorCircuitProjectionCrossValidationResult)
                .where(
                    MirrorCircuitProjectionCrossValidationResult.circuit_id == uuid.UUID(circuit_id),
                    MirrorCircuitProjectionCrossValidationResult.projection_id == uuid.UUID(projection_id),
                )
                .order_by(MirrorCircuitProjectionCrossValidationResult.created_at.desc())
                .limit(3)
            )
            rows = (await session.execute(q)).scalars().all()
            payload["cross_validation_summary"] = [
                {
                    "validation_status": r.validation_status,
                    "support_level": r.support_level,
                    "agreement_score": float(r.agreement_score) if r.agreement_score is not None else None,
                    "conflict_reason": r.conflict_reason,
                }
                for r in rows
            ]
    return payload


def _circuit_payload(c: MirrorRegionCircuit) -> dict[str, Any]:
    return {
        "circuit_id": str(c.id),
        "circuit_name": c.circuit_name,
        "circuit_type": c.circuit_type,
        "function_association": c.function_association,
        "description": c.description,
        "confidence": float(c.confidence) if c.confidence is not None else None,
        "evidence_text": c.evidence_text,
        "source_atlas": c.source_atlas,
        "granularity_level": c.granularity_level,
        "granularity_family": c.granularity_family,
        "mirror_status": c.mirror_status,
        "review_status": c.review_status,
        "promotion_status": c.promotion_status,
    }


def _projection_payload(p: MirrorRegionConnection) -> dict[str, Any]:
    return {
        "projection_id": str(p.id),
        "source_region_candidate_id": str(p.source_region_candidate_id) if p.source_region_candidate_id else None,
        "target_region_candidate_id": str(p.target_region_candidate_id) if p.target_region_candidate_id else None,
        "connection_type": p.connection_type,
        "directionality": p.directionality,
        "strength": p.strength,
        "modality": p.modality,
        "confidence": float(p.confidence) if p.confidence is not None else None,
        "evidence_text": p.evidence_text,
        "source_atlas": p.source_atlas,
        "granularity_level": p.granularity_level,
        "mirror_status": p.mirror_status,
        "review_status": p.review_status,
    }


def _membership_payload(m: MirrorCircuitProjectionMembership) -> dict[str, Any]:
    return {
        "membership_id": str(m.id),
        "circuit_id": str(m.circuit_id),
        "projection_id": str(m.projection_id),
        "source_step_id": str(m.source_step_id) if m.source_step_id else None,
        "target_step_id": str(m.target_step_id) if m.target_step_id else None,
        "source_method": m.source_method,
        "verification_status": m.verification_status,
        "confidence": float(m.confidence) if m.confidence is not None else None,
        "evidence_text": m.evidence_text,
        "source_atlas": m.source_atlas,
        "granularity_level": m.granularity_level,
        "mirror_status": m.mirror_status,
        "review_status": m.review_status,
    }


def _projection_function_payload(pf: MirrorProjectionFunction) -> dict[str, Any]:
    return {
        "projection_function_id": str(pf.id),
        "projection_id": str(pf.projection_id),
        "function_term": pf.function_term,
        "function_category": pf.function_category,
        "relation_type": pf.relation_type,
        "confidence": float(pf.confidence) if pf.confidence is not None else None,
        "evidence_text": pf.evidence_text,
        "source_atlas": pf.source_atlas,
        "granularity_level": pf.granularity_level,
        "mirror_status": pf.mirror_status,
        "review_status": pf.review_status,
    }


def _circuit_step_payload(s: MirrorCircuitStep) -> dict[str, Any]:
    return {
        "step_id": str(s.id),
        "circuit_id": str(s.circuit_id),
        "step_order": s.step_order,
        "step_name": s.step_name,
        "step_type": s.step_type,
        "role": s.role,
        "region_candidate_id": str(s.region_candidate_id) if s.region_candidate_id else None,
        "confidence": float(s.confidence) if s.confidence is not None else None,
        "evidence_text": s.evidence_text,
        "source_atlas": s.source_atlas,
        "granularity_level": s.granularity_level,
        "mirror_status": s.mirror_status,
        "review_status": s.review_status,
    }


def _triple_payload(t: MirrorKgTriple) -> dict[str, Any]:
    return {
        "triple_id": str(t.id),
        "subject_type": t.subject_type,
        "subject_id": str(t.subject_id) if t.subject_id else None,
        "subject_label": t.subject_label,
        "predicate": t.predicate,
        "object_type": t.object_type,
        "object_id": str(t.object_id) if t.object_id else None,
        "object_label": t.object_label,
        "confidence": float(t.confidence) if t.confidence is not None else None,
        "evidence_text": t.evidence_text,
        "source_atlas": t.source_atlas,
        "granularity_level": t.granularity_level,
        "mirror_status": t.mirror_status,
        "review_status": t.review_status,
    }


def _wrap_object(object_type: str, row: Any, label: str) -> VerificationObject:
    builders = {
        DualModelVerificationObjectType.circuit: (_circuit_payload, "circuit_name"),
        DualModelVerificationObjectType.projection: (_projection_payload, "connection_type"),
        DualModelVerificationObjectType.circuit_projection_membership: (_membership_payload, "membership_id"),
        DualModelVerificationObjectType.projection_function: (_projection_function_payload, "function_term"),
        DualModelVerificationObjectType.circuit_step: (_circuit_step_payload, "step_name"),
        DualModelVerificationObjectType.triple: (_triple_payload, "predicate"),
    }
    fn, _ = builders[object_type]
    payload = fn(row)
    return VerificationObject(
        object_type=object_type,
        object_id=row.id,
        resource_id=getattr(row, "resource_id", None),
        batch_id=getattr(row, "batch_id", None),
        source_atlas=row.source_atlas,
        source_version=getattr(row, "source_version", None),
        granularity_level=row.granularity_level,
        granularity_family=getattr(row, "granularity_family", None),
        label=label,
        payload=payload,
    )


async def collect_verification_objects(
    session: AsyncSession,
    *,
    object_type: str,
    object_ids: list[uuid.UUID] | None,
    scope: VerificationScope,
    max_objects: int,
) -> list[VerificationObject]:
    if object_type not in VALID_DUAL_MODEL_OBJECT_TYPES:
        raise InvalidObjectTypeError(f"invalid object_type: {object_type}")

    model_map = {
        DualModelVerificationObjectType.circuit: MirrorRegionCircuit,
        DualModelVerificationObjectType.projection: MirrorRegionConnection,
        DualModelVerificationObjectType.circuit_projection_membership: MirrorCircuitProjectionMembership,
        DualModelVerificationObjectType.projection_function: MirrorProjectionFunction,
        DualModelVerificationObjectType.circuit_step: MirrorCircuitStep,
        DualModelVerificationObjectType.triple: MirrorKgTriple,
    }
    model = model_map[object_type]
    objects: list[VerificationObject] = []

    if object_ids:
        if len(object_ids) > MAX_OBJECT_IDS:
            raise TooManyObjectsError(len(object_ids), MAX_OBJECT_IDS)
        for oid in object_ids[:max_objects]:
            row = await session.get(model, oid)
            if row is None:
                raise ObjectNotFoundError(object_type, oid)
            label = getattr(row, "circuit_name", None) or getattr(row, "function_term", None) or str(oid)
            objects.append(_wrap_object(object_type, row, str(label)))
    else:
        limit = min(max_objects, MAX_SCOPE_OBJECTS)
        stmt = select(model).order_by(model.created_at.desc())  # type: ignore[attr-defined]
        stmt = _apply_scope_filters(stmt, model, scope)
        rows = (await session.execute(stmt.limit(limit))).scalars().all()
        for row in rows:
            label = getattr(row, "circuit_name", None) or getattr(row, "function_term", None) or str(row.id)
            objects.append(_wrap_object(object_type, row, str(label)))

    if not objects:
        raise EmptyObjectsError()
    validate_objects_homogeneous(objects)
    return objects


def build_dual_model_prompt(
    *,
    object_type: str,
    object_payloads: list[dict[str, Any]],
    template_key: str = DUAL_MODEL_TEMPLATE_KEY,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    verification_instructions = {
        "same_granularity_only": True,
        "mirror_only": True,
        "not_final": True,
        "do_not_approve": True,
        "do_not_promote": True,
    }
    user_prompt = render_user_prompt(
        tpl,
        {
            "object_type": object_type,
            "objects_json": json.dumps(object_payloads, ensure_ascii=False, indent=2),
            "verification_instructions_json": json.dumps(verification_instructions, ensure_ascii=False),
            "object_payload_json": json.dumps(object_payloads[0] if object_payloads else {}, ensure_ascii=False),
        },
    )
    prompt_json = {
        "system": tpl.system_prompt,
        "user": user_prompt,
        "template_key": template_key,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_model_verification_response(
    raw_text: str,
    expected_ids: set[uuid.UUID],
    warnings: list[str],
) -> dict[uuid.UUID, ModelDecision]:
    parsed = parse_llm_json_response(raw_text)
    items = parsed.get("verification")
    if not isinstance(items, list):
        raise ValueError("missing verification array")

    result: dict[uuid.UUID, ModelDecision] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        oid_raw = entry.get("object_id")
        if not oid_raw:
            continue
        try:
            oid = uuid.UUID(str(oid_raw))
        except ValueError:
            warnings.append(f"INVALID_OBJECT_ID:{oid_raw}")
            continue
        if oid not in expected_ids:
            warnings.append(f"UNKNOWN_OBJECT_ID:{oid}")
            continue
        if oid in result:
            warnings.append(f"DUPLICATE_OBJECT_ID:{oid}")
            continue
        decision = _normalize_decision(entry.get("decision"))
        conf = _clamp_confidence(entry.get("confidence"))
        if not entry.get("evidence_text"):
            warnings.append(f"MISSING_EVIDENCE_TEXT:{oid}")
        flags = entry.get("risk_flags")
        if not isinstance(flags, list):
            flags = []
        result[oid] = ModelDecision(
            object_id=oid,
            decision=decision,
            confidence=conf,
            evidence_text=entry.get("evidence_text"),
            uncertainty_reason=entry.get("uncertainty_reason"),
            risk_flags=flags,
            recommended_review_priority=_normalize_priority(entry.get("recommended_review_priority")),
            raw=entry,
        )
    return result


def compare_dual_model_outputs(
    obj: VerificationObject,
    model_a: ModelDecision | None,
    model_b: ModelDecision | None,
) -> dict[str, Any]:
    if model_a is None or model_b is None:
        missing = "model_a" if model_a is None else "model_b"
        if model_a is None and model_b is None:
            missing = "both models"
        return {
            "consensus_status": DualModelConsensusStatus.insufficient_information,
            "consensus_score": None,
            "conflict_summary": f"MODEL_OUTPUT_MISSING_OBJECT ({missing})",
            "recommended_review_priority": DualModelReviewPriority.high,
            "evidence_text": None,
            "uncertainty_reason": "model output missing for object",
            "model_a_decision": model_a.decision if model_a else DualModelDecision.unknown,
            "model_a_confidence": model_a.confidence if model_a else None,
            "model_b_decision": model_b.decision if model_b else DualModelDecision.unknown,
            "model_b_confidence": model_b.confidence if model_b else None,
        }

    da, db = model_a.decision, model_b.decision
    ca = model_a.confidence
    cb = model_b.confidence
    avg_conf = None
    if ca is not None and cb is not None:
        avg_conf = (ca + cb) / 2.0
    elif ca is not None:
        avg_conf = ca
    elif cb is not None:
        avg_conf = cb

    min_conf = min(x for x in (ca, cb) if x is not None) if (ca is not None or cb is not None) else None
    priority = _min_priority(model_a.recommended_review_priority, model_b.recommended_review_priority)
    evidence = model_a.evidence_text or model_b.evidence_text
    uncertainty = "; ".join(filter(None, [model_a.uncertainty_reason, model_b.uncertainty_reason])) or None

    if da == DualModelDecision.support and db == DualModelDecision.support:
        score = min(0.95, (avg_conf or 0.5) + 0.10)
        return {
            "consensus_status": DualModelConsensusStatus.consensus_supported,
            "consensus_score": round(score, 3),
            "conflict_summary": None,
            "recommended_review_priority": _min_priority(priority, DualModelReviewPriority.normal),
            "evidence_text": evidence,
            "uncertainty_reason": uncertainty,
            "model_a_decision": da,
            "model_a_confidence": ca,
            "model_b_decision": db,
            "model_b_confidence": cb,
        }

    if da == DualModelDecision.reject and db == DualModelDecision.reject:
        score = min(0.95, (avg_conf or 0.5) + 0.10)
        return {
            "consensus_status": DualModelConsensusStatus.consensus_rejected,
            "consensus_score": round(score, 3),
            "conflict_summary": None,
            "recommended_review_priority": DualModelReviewPriority.high,
            "evidence_text": evidence,
            "uncertainty_reason": uncertainty,
            "model_a_decision": da,
            "model_a_confidence": ca,
            "model_b_decision": db,
            "model_b_confidence": cb,
        }

    if (da == DualModelDecision.support and db == DualModelDecision.reject) or (
        da == DualModelDecision.reject and db == DualModelDecision.support
    ):
        return {
            "consensus_status": DualModelConsensusStatus.model_conflict,
            "consensus_score": round(min_conf, 3) if min_conf is not None else None,
            "conflict_summary": f"model_a={da} vs model_b={db}",
            "recommended_review_priority": _max_priority(priority, DualModelReviewPriority.high),
            "evidence_text": evidence,
            "uncertainty_reason": uncertainty,
            "model_a_decision": da,
            "model_a_confidence": ca,
            "model_b_decision": db,
            "model_b_confidence": cb,
        }

    if (da == DualModelDecision.support and db == DualModelDecision.uncertain) or (
        da == DualModelDecision.uncertain and db == DualModelDecision.support
    ):
        return {
            "consensus_status": DualModelConsensusStatus.needs_human_review,
            "consensus_score": round(avg_conf, 3) if avg_conf is not None else None,
            "conflict_summary": f"support vs uncertain: model_a={da}, model_b={db}",
            "recommended_review_priority": DualModelReviewPriority.high,
            "evidence_text": evidence,
            "uncertainty_reason": uncertainty,
            "model_a_decision": da,
            "model_a_confidence": ca,
            "model_b_decision": db,
            "model_b_confidence": cb,
        }

    if da in {DualModelDecision.uncertain, DualModelDecision.insufficient_information, DualModelDecision.unknown} and db in {
        DualModelDecision.uncertain,
        DualModelDecision.insufficient_information,
        DualModelDecision.unknown,
    }:
        return {
            "consensus_status": DualModelConsensusStatus.insufficient_information,
            "consensus_score": round(avg_conf, 3) if avg_conf is not None else None,
            "conflict_summary": None,
            "recommended_review_priority": DualModelReviewPriority.high,
            "evidence_text": evidence,
            "uncertainty_reason": uncertainty,
            "model_a_decision": da,
            "model_a_confidence": ca,
            "model_b_decision": db,
            "model_b_confidence": cb,
        }

    return {
        "consensus_status": DualModelConsensusStatus.needs_human_review,
        "consensus_score": round(avg_conf, 3) if avg_conf is not None else None,
        "conflict_summary": f"mixed decisions: model_a={da}, model_b={db}",
        "recommended_review_priority": DualModelReviewPriority.high,
        "evidence_text": evidence,
        "uncertainty_reason": uncertainty,
        "model_a_decision": da,
        "model_a_confidence": ca,
        "model_b_decision": db,
        "model_b_confidence": cb,
    }


async def call_model_provider(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str,
    model_role: str,
    object_type: str,
    objects: list[VerificationObject],
    object_payloads: list[dict[str, Any]],
    prompt_template_key: str,
    temperature: float,
    max_tokens: int,
    scope_meta: dict[str, Any],
) -> tuple[LlmExtractionRun, LlmExtractionItem, dict[uuid.UUID, ModelDecision], list[str]]:
    warnings: list[str] = []
    system_prompt, user_prompt, prompt_json = build_dual_model_prompt(
        object_type=object_type,
        object_payloads=object_payloads,
        template_key=prompt_template_key,
    )
    tpl = _resolve_template(prompt_template_key)
    now = datetime.now(timezone.utc)
    first = objects[0]
    run = LlmExtractionRun(
        task_type=LlmTaskType.dual_model_verification,
        provider=provider_name,
        model_name=model_name,
        prompt_template_key=prompt_template_key,
        prompt_version=tpl.version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "object_type": object_type,
            "object_ids": [str(o.object_id) for o in objects],
            "model_role": model_role,
            **scope_meta,
        },
        resource_id=first.resource_id,
        batch_id=first.batch_id,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        source_atlas=first.source_atlas,
        source_version=first.source_version,
        status=LlmRunStatus.running,
        input_count=len(objects),
        output_count=0,
        error_count=0,
        temperature=temperature,
        max_tokens=max_tokens,
        request_payload_redacted={"provider": provider_name, "model": model_name, "model_role": model_role},
        started_at=now,
    )
    session.add(run)
    await session.flush()

    item = LlmExtractionItem(
        run_id=run.id,
        task_type=LlmTaskType.dual_model_verification,
        item_index=0,
        resource_id=first.resource_id,
        batch_id=first.batch_id,
        input_json={"object_type": object_type, "object_payloads": object_payloads, "model_role": model_role},
        prompt_json=prompt_json,
        status=LlmItemStatus.running,
    )
    session.add(item)
    await session.flush()

    expected_ids = {o.object_id for o in objects}
    decisions: dict[uuid.UUID, ModelDecision] = {}

    try:
        provider = get_llm_provider(provider_name)
        response = await provider.complete_json(
            model=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        item.raw_response_text = response.raw_text or None
        run.request_payload_redacted = response.request_payload_redacted
        run.usage_json = response.usage.as_dict() if response.usage else {}
        raw_for_parse = response.raw_text or ""
        if response.parsed_json and isinstance(response.parsed_json, dict):
            decisions = parse_model_verification_response(
                json.dumps(response.parsed_json), expected_ids, warnings
            )
        else:
            decisions = parse_model_verification_response(raw_for_parse, expected_ids, warnings)
        item.parsed_response_json = {"verification": [d.raw for d in decisions.values()]}
        item.normalized_output_json = {
            str(k): {
                "decision": v.decision,
                "confidence": v.confidence,
                "recommended_review_priority": v.recommended_review_priority,
            }
            for k, v in decisions.items()
        }
        item.status = LlmItemStatus.succeeded
        run.status = LlmRunStatus.succeeded
        run.output_count = len(decisions)
    except Exception as exc:
        item.status = LlmItemStatus.failed
        item.error_message = str(exc)
        run.status = LlmRunStatus.failed
        run.error_count = 1
        warnings.append(f"{model_role}_CALL_FAILED:{exc}")

    run.finished_at = datetime.now(timezone.utc)
    await session.flush()
    return run, item, decisions, warnings


async def persist_dual_model_run_and_results(
    session: AsyncSession,
    *,
    object_type: str,
    objects: list[VerificationObject],
    model_a_provider: str,
    model_a_name: str | None,
    model_a_run_id: uuid.UUID | None,
    model_b_provider: str,
    model_b_name: str | None,
    model_b_run_id: uuid.UUID | None,
    model_a_decisions: dict[uuid.UUID, ModelDecision],
    model_b_decisions: dict[uuid.UUID, ModelDecision],
    scope_json: dict[str, Any],
    dry_run: bool,
    create_results: bool,
) -> tuple[uuid.UUID, list[dict[str, Any]], dict[str, int]]:
    previews: list[dict[str, Any]] = []
    counts = {
        "consensus_supported_count": 0,
        "consensus_rejected_count": 0,
        "model_conflict_count": 0,
        "insufficient_information_count": 0,
        "needs_human_review_count": 0,
    }

    for obj in objects:
        cmp_result = compare_dual_model_outputs(
            obj,
            model_a_decisions.get(obj.object_id),
            model_b_decisions.get(obj.object_id),
        )
        status = cmp_result["consensus_status"]
        if status == DualModelConsensusStatus.consensus_supported:
            counts["consensus_supported_count"] += 1
        elif status == DualModelConsensusStatus.consensus_rejected:
            counts["consensus_rejected_count"] += 1
        elif status == DualModelConsensusStatus.model_conflict:
            counts["model_conflict_count"] += 1
        elif status == DualModelConsensusStatus.insufficient_information:
            counts["insufficient_information_count"] += 1
        elif status == DualModelConsensusStatus.needs_human_review:
            counts["needs_human_review_count"] += 1

        previews.append({
            "object_type": object_type,
            "object_id": obj.object_id,
            **cmp_result,
        })

    if not create_results:
        return None, previews, counts

    now = datetime.now(timezone.utc)
    first = objects[0]
    dual_status = MirrorDualModelRunStatus.succeeded
    if not model_a_run_id and not model_b_run_id:
        dual_status = MirrorDualModelRunStatus.failed
    elif (model_a_run_id and not model_a_decisions) or (model_b_run_id and not model_b_decisions):
        dual_status = MirrorDualModelRunStatus.partially_succeeded

    dual_run = MirrorDualModelVerificationRun(
        verification_task_type=object_type,
        model_a_provider=model_a_provider,
        model_a_name=model_a_name,
        model_a_run_id=model_a_run_id,
        model_b_provider=model_b_provider,
        model_b_name=model_b_name,
        model_b_run_id=model_b_run_id,
        scope_json=scope_json,
        resource_id=first.resource_id,
        batch_id=first.batch_id,
        source_atlas=first.source_atlas,
        source_version=first.source_version,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        status=dual_status,
        object_count=len(objects),
        consensus_supported_count=counts["consensus_supported_count"],
        consensus_rejected_count=counts["consensus_rejected_count"],
        model_conflict_count=counts["model_conflict_count"],
        insufficient_information_count=counts["insufficient_information_count"],
        needs_human_review_count=counts["needs_human_review_count"],
        dry_run=dry_run,
        started_at=now,
        finished_at=now,
    )
    session.add(dual_run)
    await session.flush()

    ma = model_a_decisions
    mb = model_b_decisions
    for obj in objects:
        cmp_result = compare_dual_model_outputs(obj, ma.get(obj.object_id), mb.get(obj.object_id))
        ma_d = ma.get(obj.object_id)
        mb_d = mb.get(obj.object_id)
        row = MirrorDualModelVerificationResult(
            run_id=dual_run.id,
            object_type=object_type,
            object_id=obj.object_id,
            model_a_provider=model_a_provider,
            model_a_decision=cmp_result["model_a_decision"],
            model_a_confidence=cmp_result["model_a_confidence"],
            model_a_payload_json=ma_d.raw if ma_d else {},
            model_b_provider=model_b_provider,
            model_b_decision=cmp_result["model_b_decision"],
            model_b_confidence=cmp_result["model_b_confidence"],
            model_b_payload_json=mb_d.raw if mb_d else {},
            consensus_status=cmp_result["consensus_status"],
            consensus_score=cmp_result["consensus_score"],
            conflict_summary=cmp_result["conflict_summary"],
            recommended_review_priority=cmp_result["recommended_review_priority"],
            evidence_text=cmp_result["evidence_text"],
            uncertainty_reason=cmp_result["uncertainty_reason"],
            resource_id=obj.resource_id,
            batch_id=obj.batch_id,
            source_atlas=obj.source_atlas,
            granularity_level=obj.granularity_level,
            granularity_family=obj.granularity_family,
        )
        session.add(row)

    await session.flush()
    return dual_run.id, previews, counts


async def run_dual_model_verification(
    session: AsyncSession,
    *,
    object_type: str,
    object_ids: list[uuid.UUID] | None = None,
    scope: VerificationScope | None = None,
    model_a_provider: str = "deepseek",
    model_a_name: str | None = None,
    model_b_provider: str = "kimi",
    model_b_name: str | None = None,
    prompt_template_key: str = DUAL_MODEL_TEMPLATE_KEY,
    temperature: float = 0.1,
    max_tokens: int = 3000,
    dry_run: bool = False,
    max_objects: int = 50,
    include_cross_validation_context: bool = True,
    include_evidence_context: bool = True,
    include_review_context: bool = False,
    create_results: bool = True,
) -> DualModelVerificationOutcome:
    scope = scope or VerificationScope()
    warnings: list[str] = []

    if model_a_provider.lower() == model_b_provider.lower():
        raise SameProviderError("model_a_provider and model_b_provider must differ")

    a_key, a_model, a_cfg = _resolve_provider_config(model_a_provider, model_a_name)
    b_key, b_model, b_cfg = _resolve_provider_config(model_b_provider, model_b_name)

    if not dry_run:
        if not a_cfg.api_key.strip():
            raise ProviderNotConfiguredServiceError(a_key, f"provider is not configured: {a_key}")
        if not b_cfg.api_key.strip():
            raise ProviderNotConfiguredServiceError(b_key, f"provider is not configured: {b_key}")

    objects = await collect_verification_objects(
        session,
        object_type=object_type,
        object_ids=object_ids,
        scope=scope,
        max_objects=max_objects,
    )

    object_payloads: list[dict[str, Any]] = []
    for obj in objects:
        payload = await build_object_payload(
            session,
            obj,
            include_cross_validation_context=include_cross_validation_context,
            include_evidence_context=include_evidence_context,
            include_review_context=include_review_context,
        )
        object_payloads.append(payload)

    sys_a, user_a, _ = build_dual_model_prompt(
        object_type=object_type,
        object_payloads=object_payloads,
        template_key=prompt_template_key,
    )
    sys_b, user_b, _ = build_dual_model_prompt(
        object_type=object_type,
        object_payloads=object_payloads,
        template_key=prompt_template_key,
    )

    outcome = DualModelVerificationOutcome(
        run_id=None,
        object_type=object_type,
        object_count=len(objects),
        model_a_provider=a_key,
        model_a_run_id=None,
        model_b_provider=b_key,
        model_b_run_id=None,
        consensus_supported_count=0,
        consensus_rejected_count=0,
        model_conflict_count=0,
        insufficient_information_count=0,
        needs_human_review_count=0,
        result_count=0,
        dry_run=dry_run,
        model_a_system_prompt=sys_a,
        model_a_user_prompt=user_a,
        model_b_system_prompt=sys_b,
        model_b_user_prompt=user_b,
        warnings=list(warnings),
    )

    if dry_run:
        for obj in objects:
            cmp_result = compare_dual_model_outputs(obj, None, None)
            outcome.results_preview.append({
                "object_type": object_type,
                "object_id": obj.object_id,
                **cmp_result,
            })
        outcome.insufficient_information_count = len(objects)
        return outcome

    scope_meta = {
        "resource_id": str(scope.resource_id) if scope.resource_id else None,
        "batch_id": str(scope.batch_id) if scope.batch_id else None,
        "source_atlas": scope.source_atlas,
        "granularity_level": scope.granularity_level,
    }

    model_a_run, _, model_a_decisions, w_a = await call_model_provider(
        session,
        provider_name=a_key,
        model_name=a_model,
        model_role="model_a",
        object_type=object_type,
        objects=objects,
        object_payloads=object_payloads,
        prompt_template_key=prompt_template_key,
        temperature=temperature,
        max_tokens=max_tokens,
        scope_meta=scope_meta,
    )
    warnings.extend(w_a)
    outcome.model_a_run_id = model_a_run.id

    model_b_run, _, model_b_decisions, w_b = await call_model_provider(
        session,
        provider_name=b_key,
        model_name=b_model,
        model_role="model_b",
        object_type=object_type,
        objects=objects,
        object_payloads=object_payloads,
        prompt_template_key=prompt_template_key,
        temperature=temperature,
        max_tokens=max_tokens,
        scope_meta=scope_meta,
    )
    warnings.extend(w_b)
    outcome.model_b_run_id = model_b_run.id

    scope_json = {
        "object_type": object_type,
        "object_ids": [str(o.object_id) for o in objects],
        "max_objects": max_objects,
        "include_cross_validation_context": include_cross_validation_context,
        "create_results": create_results,
    }

    dual_run_id, previews, counts = await persist_dual_model_run_and_results(
        session,
        object_type=object_type,
        objects=objects,
        model_a_provider=a_key,
        model_a_name=a_model,
        model_a_run_id=model_a_run.id,
        model_b_provider=b_key,
        model_b_name=b_model,
        model_b_run_id=model_b_run.id,
        model_a_decisions=model_a_decisions,
        model_b_decisions=model_b_decisions,
        scope_json=scope_json,
        dry_run=False,
        create_results=create_results,
    )

    await session.commit()

    outcome.run_id = dual_run_id if create_results else None
    outcome.consensus_supported_count = counts["consensus_supported_count"]
    outcome.consensus_rejected_count = counts["consensus_rejected_count"]
    outcome.model_conflict_count = counts["model_conflict_count"]
    outcome.insufficient_information_count = counts["insufficient_information_count"]
    outcome.needs_human_review_count = counts["needs_human_review_count"]
    outcome.result_count = len(previews)
    outcome.results_preview = previews[:PREVIEW_LIMIT]
    outcome.warnings = warnings
    return outcome
