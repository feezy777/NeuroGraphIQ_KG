"""Projection-to-functions extraction — LLM run/item + mirror_projection_functions (Step 8.9).

Derives mirror_projection_functions from mirror_region_connections (projection semantics).
Does NOT write final_*/kg_*; does NOT auto approve/promote.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership, MirrorCircuitStep, MirrorProjectionFunction
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import (
    FunctionCategory,
    FunctionRelationType,
    MirrorKgTripleCreate,
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
    TripleObjectType,
    TripleScope,
    TripleSubjectType,
)
from app.schemas.mirror_macro_clinical import MirrorProjectionFunctionCreate
from app.services import mirror_kg_service, mirror_macro_clinical_service
from app.services.llm_extraction_prompt_engineering import prompt_display_name
from app.services.llm_extraction_service import ProviderNotConfiguredServiceError
from app.services.llm_function_extraction_service import RELATION_TO_PREDICATE
from app.services.llm_json_utils import (
    LlmJsonParseError,
    parse_llm_json_response,
    raw_response_preview,
)
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config
from app.services.llm_workflow_artifact_tagging import tag_raw_payload
from app.services.llm_status_utils import apply_persistent_run_status

PROJECTION_TO_FUNCTIONS_TEMPLATE_KEY = "projection_to_functions_v1"
MAX_PROJECTIONS = 20
DEFAULT_MAX_FUNCTIONS_PER_PROJECTION = 5

DEFAULT_ALLOWED_FUNCTION_CATEGORIES = frozenset({
    FunctionCategory.motor,
    FunctionCategory.sensory,
    FunctionCategory.visual,
    FunctionCategory.auditory,
    FunctionCategory.language,
    FunctionCategory.memory,
    FunctionCategory.emotion,
    FunctionCategory.executive_control,
    FunctionCategory.attention,
    FunctionCategory.autonomic,
    FunctionCategory.default_mode,
    FunctionCategory.salience,
    FunctionCategory.reward,
    FunctionCategory.cognitive,
    FunctionCategory.unknown,
})

DEFAULT_ALLOWED_RELATION_TYPES = frozenset({
    FunctionRelationType.involved_in,
    FunctionRelationType.associated_with,
    FunctionRelationType.necessary_for,
    FunctionRelationType.modulates,
    FunctionRelationType.participates_in,
    FunctionRelationType.uncertain_association,
    FunctionRelationType.unknown,
})


class EmptyProjectionsError(Exception):
    pass


class TooManyProjectionsError(Exception):
    def __init__(self, count: int, maximum: int):
        self.count = count
        self.maximum = maximum
        super().__init__(f"projection count {count} exceeds max {maximum}")


class ProjectionNotFoundError(Exception):
    def __init__(self, projection_id: str):
        self.projection_id = projection_id
        super().__init__(f"projection not found: {projection_id}")


class CrossAtlasProjectionError(Exception):
    def __init__(self, atlases: list[str]):
        self.atlases = atlases
        super().__init__("projections span multiple source_atlas values")


class CrossGranularityProjectionError(Exception):
    def __init__(self, field: str, values: list[str]):
        self.field = field
        self.values = values
        super().__init__(f"projections span multiple {field} values")


class InvalidProjectionError(Exception):
    pass


class MirrorProjectionFunctionTableMissingError(Exception):
    pass


class MirrorPersistError(Exception):
    pass


@dataclass
class ProjectionToFunctionsResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.projection_to_functions
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    projection_count: int = 0
    circuit_context_count: int = 0
    function_count: int = 0
    mirror_projection_function_created_count: int = 0
    mirror_projection_function_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool = False
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[PROJECTION_TO_FUNCTIONS_TEMPLATE_KEY]
    return tpl


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _region_label(c: CandidateBrainRegion | None, fallback_id: str | None = None) -> str:
    if c:
        return c.en_name or c.cn_name or c.std_name or c.raw_name or str(c.id)
    return fallback_id or "unknown"


def _homogeneous_field(projections: list[MirrorRegionConnection], attr: str) -> Any | None:
    values = {getattr(p, attr) for p in projections}
    if len(values) == 1:
        return next(iter(values))
    return None


def validate_projections_homogeneous(projections: list[MirrorRegionConnection]) -> None:
    if not projections:
        raise EmptyProjectionsError()

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


def _serialize_projection(
    p: MirrorRegionConnection,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    *,
    include_region_context: bool,
) -> dict[str, Any]:
    src_id = p.source_region_candidate_id
    tgt_id = p.target_region_candidate_id
    src_c = candidate_map.get(src_id) if src_id else None
    tgt_c = candidate_map.get(tgt_id) if tgt_id else None
    row: dict[str, Any] = {
        "projection_id": str(p.id),
        "source_region_candidate_id": str(src_id) if src_id else None,
        "target_region_candidate_id": str(tgt_id) if tgt_id else None,
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
    if include_region_context:
        row["source_region_en_name"] = src_c.en_name if src_c else None
        row["source_region_cn_name"] = src_c.cn_name if src_c else None
        row["target_region_en_name"] = tgt_c.en_name if tgt_c else None
        row["target_region_cn_name"] = tgt_c.cn_name if tgt_c else None
    return row


async def load_region_map_for_projections(
    session: AsyncSession,
    projections: list[MirrorRegionConnection],
) -> dict[uuid.UUID, CandidateBrainRegion]:
    out: dict[uuid.UUID, CandidateBrainRegion] = {}
    for p in projections:
        for rid in (p.source_region_candidate_id, p.target_region_candidate_id):
            if rid and rid not in out:
                cand = await session.get(CandidateBrainRegion, rid)
                if cand:
                    out[rid] = cand
    return out


async def load_circuit_context(
    session: AsyncSession,
    projections: list[MirrorRegionConnection],
) -> list[dict[str, Any]]:
    first = projections[0]
    context_rows: list[dict[str, Any]] = []
    for p in projections:
        memberships, _ = await mirror_macro_clinical_service.list_circuit_projection_memberships(
            session,
            projection_id=p.id,
            source_atlas=first.source_atlas,
            granularity_level=first.granularity_level,
            granularity_family=first.granularity_family,
            limit=50,
            offset=0,
        )
        for m in memberships:
            circuit = await session.get(MirrorRegionCircuit, m.circuit_id)
            source_step = await session.get(MirrorCircuitStep, m.source_step_id) if m.source_step_id else None
            target_step = await session.get(MirrorCircuitStep, m.target_step_id) if m.target_step_id else None
            context_rows.append({
                "membership_id": str(m.id),
                "projection_id": str(p.id),
                "circuit_id": str(m.circuit_id),
                "circuit_name": circuit.circuit_name if circuit else None,
                "circuit_type": circuit.circuit_type if circuit else None,
                "function_association": circuit.function_association if circuit else None,
                "source_step_id": str(m.source_step_id) if m.source_step_id else None,
                "target_step_id": str(m.target_step_id) if m.target_step_id else None,
                "source_step_order": source_step.step_order if source_step else None,
                "target_step_order": target_step.step_order if target_step else None,
                "role_in_circuit": m.role_in_circuit,
                "verification_status": m.verification_status,
                "membership_confidence": float(m.confidence) if m.confidence is not None else None,
            })
    return context_rows


def build_projection_to_functions_prompt(
    projections: list[MirrorRegionConnection],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    circuit_context: list[dict[str, Any]],
    *,
    template_key: str = PROJECTION_TO_FUNCTIONS_TEMPLATE_KEY,
    max_functions_per_projection: int = DEFAULT_MAX_FUNCTIONS_PER_PROJECTION,
    include_region_context: bool = True,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    first = projections[0]
    projections_payload = [
        _serialize_projection(p, candidate_map, include_region_context=include_region_context)
        for p in projections
    ]
    projections_json = json.dumps(projections_payload, ensure_ascii=False, indent=2)
    circuit_context_json = json.dumps(circuit_context, ensure_ascii=False, indent=2)
    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family or "",
        "max_functions_per_projection": str(max_functions_per_projection),
        "projections_json": projections_json,
        "circuit_context_json": circuit_context_json,
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "prompt_display_name": prompt_display_name(tpl.template_key),
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "projections_json": projections_json,
        "circuit_context_json": circuit_context_json,
        "max_functions_per_projection": max_functions_per_projection,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_projection_to_functions_response(raw_text: str) -> dict[str, Any]:
    return parse_llm_json_response(raw_text)


def normalize_projection_function_candidates(
    parsed: dict[str, Any],
    *,
    allowed_projection_ids: set[uuid.UUID],
    max_functions_per_projection: int = DEFAULT_MAX_FUNCTIONS_PER_PROJECTION,
    allowed_categories: frozenset[str] | None = None,
    allowed_relation_types: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    categories = allowed_categories or DEFAULT_ALLOWED_FUNCTION_CATEGORIES
    relations = allowed_relation_types or DEFAULT_ALLOWED_RELATION_TYPES
    warnings: list[str] = []
    raw_functions = parsed.get("projection_functions")
    if raw_functions is None:
        return [], ["projection_functions array missing; treating as empty"]
    if not isinstance(raw_functions, list):
        raise ValueError("projection_functions must be an array")

    per_projection_count: dict[str, int] = defaultdict(int)
    seen_keys: set[tuple[str, str, str, str]] = set()
    normalized: list[dict[str, Any]] = []

    for idx, fn in enumerate(raw_functions):
        if not isinstance(fn, dict):
            warnings.append(f"projection_function[{idx}] skipped: not an object")
            continue
        try:
            projection_id = uuid.UUID(str(fn.get("projection_id")))
        except (ValueError, TypeError, AttributeError):
            warnings.append(f"projection_function[{idx}] skipped: invalid projection_id")
            continue
        if projection_id not in allowed_projection_ids:
            warnings.append(f"projection_function[{idx}] skipped: projection not in input set")
            continue

        function_term = str(
            fn.get("function_term")
            or fn.get("function_term_en")
            or fn.get("function_term_cn")
            or ""
        ).strip()
        if not function_term:
            warnings.append(f"projection_function[{idx}] skipped: empty function_term")
            continue

        pid = str(projection_id)
        if per_projection_count[pid] >= max_functions_per_projection:
            warnings.append(
                f"projection_function[{idx}] note: exceeds max_functions_per_projection "
                f"({max_functions_per_projection}); still saving"
            )

        category = str(fn.get("function_category") or FunctionCategory.unknown)
        if category not in categories:
            category = FunctionCategory.unknown
            warnings.append(f"projection_function[{idx}] function_category coerced to unknown")

        relation = str(fn.get("relation_type") or FunctionRelationType.unknown)
        if relation not in relations:
            relation = FunctionRelationType.unknown
            warnings.append(f"projection_function[{idx}] relation_type coerced to unknown")

        term_key = function_term.lower().strip()
        dedup_key = (pid, term_key, category, relation)
        if dedup_key in seen_keys:
            warnings.append(f"projection_function[{idx}] skipped: duplicate within LLM output")
            continue
        seen_keys.add(dedup_key)

        evidence_text = fn.get("evidence_text")
        if not evidence_text:
            warnings.append(f"projection_function[{idx}] warning: evidence_text empty")

        per_projection_count[pid] += 1
        normalized.append({
            "projection_id": pid,
            "function_term": function_term,
            "function_term_key": term_key,
            "function_category": category,
            "relation_type": relation,
            "confidence": _clamp_confidence(fn.get("confidence")),
            "evidence_text": evidence_text,
            "uncertainty_reason": fn.get("uncertainty_reason"),
            "raw": fn,
            "normalized_payload_json": {
                "macro_clinical_semantic_type": "projection_function",
                "source_projection_id": pid,
            },
        })
    return normalized, warnings


def projection_function_dedup_key(
    projection_id: uuid.UUID,
    function_term_key: str,
    function_category: str,
    relation_type: str,
) -> tuple[str, str, str, str]:
    return str(projection_id), function_term_key, function_category, relation_type


async def _projection_function_exists(
    session: AsyncSession,
    *,
    projection_id: uuid.UUID,
    function_term_key: str,
    function_category: str,
    relation_type: str,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
) -> bool:
    blocked = {MirrorPromotionStatus.failed, MirrorPromotionStatus.blocked}
    q = select(MirrorProjectionFunction.id).where(
        MirrorProjectionFunction.projection_id == projection_id,
        MirrorProjectionFunction.function_category == function_category,
        MirrorProjectionFunction.relation_type == relation_type,
        MirrorProjectionFunction.source_atlas == source_atlas,
        MirrorProjectionFunction.granularity_level == granularity_level,
        MirrorProjectionFunction.promotion_status.notin_(blocked),
        MirrorProjectionFunction.review_status != MirrorReviewStatus.rejected,
        MirrorProjectionFunction.mirror_status != MirrorStatus.superseded,
        func.lower(MirrorProjectionFunction.function_term) == function_term_key,
    )
    if resource_id:
        q = q.where(MirrorProjectionFunction.resource_id == resource_id)
    if batch_id:
        q = q.where(MirrorProjectionFunction.batch_id == batch_id)
    return (await session.execute(q.limit(1))).scalar_one_or_none() is not None


def _projection_label(
    projection: MirrorRegionConnection,
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> str:
    src_c = candidate_map.get(projection.source_region_candidate_id) if projection.source_region_candidate_id else None
    tgt_c = candidate_map.get(projection.target_region_candidate_id) if projection.target_region_candidate_id else None
    src_l = _region_label(src_c, str(projection.source_region_candidate_id))
    tgt_l = _region_label(tgt_c, str(projection.target_region_candidate_id))
    return f"{src_l} -> {tgt_l} ({projection.connection_type})"


async def create_projection_function_triples(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    projection: MirrorRegionConnection,
    projection_function: MirrorProjectionFunction,
    fn: dict[str, Any],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
) -> int:
    relation = fn["relation_type"]
    predicate = RELATION_TO_PREDICATE.get(relation, "associated_with_function")
    label = _projection_label(projection, candidate_map)
    triple_payload = MirrorKgTripleCreate(
        subject_type=TripleSubjectType.connection,
        subject_id=projection.id,
        subject_label=label,
        predicate=predicate,
        object_type=TripleObjectType.function,
        object_id=None,
        object_label=fn["function_term"],
        triple_scope=TripleScope.same_granularity,
        resource_id=projection.resource_id,
        batch_id=projection.batch_id,
        llm_run_id=run.id,
        llm_item_id=item.id,
        source_mirror_connection_id=projection.id,
        granularity_level=projection.granularity_level,
        granularity_family=projection.granularity_family,
        source_atlas=projection.source_atlas,
        source_version=projection.source_version,
        confidence=fn.get("confidence"),
        evidence_text=fn.get("evidence_text"),
        uncertainty_reason=fn.get("uncertainty_reason"),
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status=MirrorPromotionStatus.not_promoted,
        raw_payload_json={"projection_function": fn},
        normalized_payload_json={"predicate": predicate, "function_term": fn["function_term"]},
    )
    await mirror_kg_service.create_mirror_triple(session, triple_payload)
    return 1


async def create_projection_function_evidence(
    *,
    create_evidence: bool,
    fn: dict[str, Any],
    warnings: list[str],
) -> int:
    if not create_evidence:
        return 0
    if fn.get("evidence_text"):
        warnings.append("PROJECTION_FUNCTION_EVIDENCE_STORED_ON_OBJECT_ONLY")
    return 0


async def persist_projection_functions(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    functions: list[dict[str, Any]],
    projection_map: dict[uuid.UUID, MirrorRegionConnection],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    create_triples: bool,
    create_evidence: bool,
    session_seen: set[tuple[str, str, str, str]] | None = None,
    composite_workflow_run_id: uuid.UUID | None = None,
    workflow_step_key: str | None = None,
) -> tuple[int, int, int, int, list[str]]:
    created = skipped = triples = evidence = 0
    warnings: list[str] = []
    seen = session_seen or set()

    for fn in functions:
        if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
            warnings.append("Mirror persist skipped — workflow cancelled")
            break
        projection_id = uuid.UUID(fn["projection_id"])
        projection = projection_map.get(projection_id)
        if projection is None:
            warnings.append(f"projection {projection_id} missing during persist; skipped")
            continue

        term_key = fn["function_term_key"]
        category = fn["function_category"]
        relation = fn["relation_type"]
        key = projection_function_dedup_key(projection_id, term_key, category, relation)
        if key in seen:
            skipped += 1
            warnings.append(f"EXISTING_PROJECTION_FUNCTION_SKIPPED: duplicate in session for {projection_id}")
            continue
        if await _projection_function_exists(
            session,
            projection_id=projection_id,
            function_term_key=term_key,
            function_category=category,
            relation_type=relation,
            resource_id=projection.resource_id,
            batch_id=projection.batch_id,
            source_atlas=projection.source_atlas,
            granularity_level=projection.granularity_level,
        ):
            skipped += 1
            seen.add(key)
            warnings.append(f"EXISTING_PROJECTION_FUNCTION_SKIPPED: {projection_id} / {fn['function_term']}")
            continue

        raw_payload = tag_raw_payload(
            fn.get("raw") or fn,
            workflow_run_id=composite_workflow_run_id,
            step_key=workflow_step_key,
        ) if composite_workflow_run_id else (fn.get("raw") or fn)
        normalized = fn.get("normalized_payload_json") or {
            "macro_clinical_semantic_type": "projection_function",
            "source_projection_id": str(projection_id),
        }
        if composite_workflow_run_id:
            normalized = tag_raw_payload(
                normalized,
                workflow_run_id=composite_workflow_run_id,
                step_key=workflow_step_key,
            )
        payload = MirrorProjectionFunctionCreate(
            projection_id=projection_id,
            resource_id=projection.resource_id,
            batch_id=projection.batch_id,
            llm_run_id=run.id,
            llm_item_id=item.id,
            granularity_level=projection.granularity_level,
            granularity_family=projection.granularity_family,
            source_atlas=projection.source_atlas,
            source_version=projection.source_version,
            function_term=fn["function_term"],
            function_category=category,
            relation_type=relation,
            confidence=fn.get("confidence"),
            evidence_text=fn.get("evidence_text"),
            uncertainty_reason=fn.get("uncertainty_reason"),
            raw_payload_json=raw_payload,
            normalized_payload_json=normalized,
        )
        try:
            mirror_fn = await mirror_macro_clinical_service.create_projection_function(session, payload)
        except Exception as exc:
            raise MirrorPersistError(f"projection_function persist failed: {exc}") from exc
        created += 1
        seen.add(key)

        if create_triples:
            triples += await create_projection_function_triples(
                session,
                run=run,
                item=item,
                projection=projection,
                projection_function=mirror_fn,
                fn=fn,
                candidate_map=candidate_map,
            )

        if create_evidence and fn.get("evidence_text"):
            evidence += await create_projection_function_evidence(
                create_evidence=create_evidence,
                fn=fn,
                warnings=warnings,
            )

    return created, skipped, triples, evidence, warnings


async def run_projection_to_functions_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    projection_ids: list[uuid.UUID],
    prompt_template_key: str = PROJECTION_TO_FUNCTIONS_TEMPLATE_KEY,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    dry_run: bool = False,
    max_functions_per_projection: int = DEFAULT_MAX_FUNCTIONS_PER_PROJECTION,
    include_circuit_context: bool = True,
    include_region_context: bool = True,
    create_mirror_records: bool = True,
    create_triples: bool = True,
    create_evidence: bool = True,
    composite_workflow_run_id: uuid.UUID | None = None,
    workflow_step_key: str | None = None,
) -> ProjectionToFunctionsResult:
    if not projection_ids:
        raise EmptyProjectionsError()
    if len(projection_ids) > MAX_PROJECTIONS:
        raise TooManyProjectionsError(len(projection_ids), MAX_PROJECTIONS)

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

    validate_projections_homogeneous(projections)

    all_warnings: list[str] = []
    for p in projections:
        if not p.source_region_candidate_id or not p.target_region_candidate_id:
            all_warnings.append(
                f"projection {p.id} missing source/target region; LLM context may be incomplete"
            )

    candidate_map: dict[uuid.UUID, CandidateBrainRegion] = {}
    if include_region_context:
        candidate_map = await load_region_map_for_projections(session, projections)

    circuit_context: list[dict[str, Any]] = []
    if include_circuit_context:
        circuit_context = await load_circuit_context(session, projections)

    system_prompt, user_prompt, prompt_json = build_projection_to_functions_prompt(
        projections,
        candidate_map,
        circuit_context,
        template_key=prompt_template_key,
        max_functions_per_projection=max_functions_per_projection,
        include_region_context=include_region_context,
    )

    result = ProjectionToFunctionsResult(
        projection_count=len(projections),
        circuit_context_count=len(circuit_context),
        dry_run=dry_run,
        provider=provider_key,
        model_name=resolved_model,
        warnings=list(all_warnings),
    )

    if dry_run:
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt
        return result

    first = projections[0]
    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.projection_to_functions,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "projection_ids": [str(p.id) for p in projections],
            "max_functions_per_projection": max_functions_per_projection,
            "create_mirror_records": create_mirror_records,
            "create_triples": create_triples,
            "create_evidence": create_evidence,
            "include_circuit_context": include_circuit_context,
            "include_region_context": include_region_context,
            **({"composite_workflow_run_id": str(composite_workflow_run_id)} if composite_workflow_run_id else {}),
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
        task_type=LlmTaskType.projection_to_functions,
        item_index=0,
        input_json={
            "projections_json": prompt_json.get("projections_json"),
            "circuit_context_json": prompt_json.get("circuit_context_json"),
            "projection_ids": [str(p.id) for p in projections],
        },
        prompt_json=prompt_json,
        status=LlmItemStatus.running,
    )
    session.add(item)
    await session.flush()

    if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
        run.status = LlmRunStatus.cancelled
        item.status = LlmItemStatus.skipped
        result.status = LlmRunStatus.cancelled
        result.run_id = run.id
        result.item_id = item.id
        result.warnings.append("Workflow cancelled before provider call")
        await session.commit()
        return result

    provider = get_llm_provider(provider_key)
    response = await provider.complete_json(
        model=resolved_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
        run.status = LlmRunStatus.cancelled
        item.status = LlmItemStatus.skipped
        result.status = LlmRunStatus.cancelled
        result.run_id = run.id
        result.item_id = item.id
        result.warnings.append("late_provider_response_ignored")
        await session.commit()
        return result

    item.raw_response_text = response.raw_text or None
    run.request_payload_redacted = response.request_payload_redacted
    run.usage_json = response.usage.as_dict() if response.usage else {}

    normalized_functions: list[dict[str, Any]] = []

    preview = raw_response_preview(response.raw_text or "")
    run.scope_json = {**(run.scope_json or {}), "raw_response_preview": preview}

    if response.error_message:
        # Transport-level failure (HTTP/timeout/network).
        item.status = LlmItemStatus.failed
        item.error_message = response.error_message
        apply_persistent_run_status(run, LlmRunStatus.failed_provider_error)
        run.error_count = 1
    elif response.parsed_json is None:
        try:
            parsed = parse_projection_to_functions_response(response.raw_text or "")
        except LlmJsonParseError as exc:
            item.status = LlmItemStatus.failed
            item.error_message = f"failed to parse model JSON: {exc}"
            apply_persistent_run_status(
                run,
                LlmRunStatus.failed_parse_error,
                extra_scope={"raw_response_preview": exc.preview or preview},
            )
            run.error_count = 1
            parsed = None
        except Exception as exc:  # noqa: BLE001 - any parser failure is a parse error, not transport
            item.status = LlmItemStatus.failed
            item.error_message = f"failed to parse model JSON: {exc}"
            apply_persistent_run_status(run, LlmRunStatus.failed_parse_error)
            run.error_count = 1
            parsed = None
        if parsed is not None:
            response.parsed_json = parsed

    if response.parsed_json is not None and item.status != LlmItemStatus.failed:
        item.parsed_response_json = response.parsed_json
        try:
            normalized_functions, norm_warnings = normalize_projection_function_candidates(
                response.parsed_json,
                allowed_projection_ids={p.id for p in projections},
                max_functions_per_projection=max_functions_per_projection,
            )
            all_warnings.extend(norm_warnings)
        except ValueError as exc:
            # JSON parsed but did not match schema → parse/schema error, not transport.
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            apply_persistent_run_status(run, LlmRunStatus.failed_parse_error)
            run.error_count = 1
            normalized_functions = []

    if item.status != LlmItemStatus.failed:
        item.normalized_output_json = {"projection_functions": normalized_functions}
        confidences = [f["confidence"] for f in normalized_functions if f.get("confidence") is not None]
        if confidences:
            item.confidence = sum(confidences) / len(confidences)
        evidence_parts = [str(f["evidence_text"]) for f in normalized_functions if f.get("evidence_text")]
        if evidence_parts:
            item.evidence_text = "; ".join(evidence_parts[:5])
        item.status = LlmItemStatus.succeeded if normalized_functions else LlmItemStatus.needs_review
        run.output_count = len(normalized_functions)
        apply_persistent_run_status(run, LlmRunStatus.succeeded)

        projection_map = {p.id: p for p in projections}
        if create_mirror_records and normalized_functions:
            if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
                all_warnings.append("Mirror persist skipped — workflow cancelled")
            else:
                try:
                    pf, skip, tr, ev, pw = await persist_projection_functions(
                        session,
                        run=run,
                        item=item,
                        functions=normalized_functions,
                        projection_map=projection_map,
                        candidate_map=candidate_map,
                        create_triples=create_triples,
                        create_evidence=create_evidence,
                        composite_workflow_run_id=composite_workflow_run_id,
                        workflow_step_key=workflow_step_key,
                    )
                    result.mirror_projection_function_created_count = pf
                    result.mirror_projection_function_skipped_duplicate_count = skip
                    result.triple_created_count = tr
                    result.evidence_created_count = ev
                    all_warnings.extend(pw)
                except MirrorPersistError as exc:
                    run.status = LlmRunStatus.partially_succeeded
                    run.error_message = str(exc)
                    all_warnings.append(str(exc))
        elif normalized_functions and not create_mirror_records:
            pass

    run.finished_at = datetime.now(timezone.utc)
    result.run_id = run.id
    result.item_id = item.id
    result.status = (run.scope_json or {}).get("outcome") or run.status
    result.function_count = len(normalized_functions)
    result.warnings = all_warnings

    await session.commit()
    await session.refresh(run)
    await session.refresh(item)
    return result
