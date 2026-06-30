"""Same-granularity function extraction — LLM run/item + Mirror KG (Step 4).

Writes mirror_region_functions, mirror_kg_triples, mirror_evidence_records.
Does NOT write final_* / kg_*; does NOT auto approve/promote.
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
from app.models.mirror_kg import MirrorRegionFunction
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus, LlmScopeType, LlmTaskType
from app.schemas.mirror_kg import (
    EvidenceTargetType,
    EvidenceType,
    FunctionCategory,
    FunctionRelationType,
    MirrorEvidenceRecordCreate,
    MirrorKgTripleCreate,
    MirrorPromotionStatus,
    MirrorRegionFunctionCreate,
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
DEFAULT_MAX_FUNCTIONS_PER_REGION = 5
FUNCTION_TEMPLATE_KEY = "same_granularity_function_completion_v1"

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

RELATION_TO_PREDICATE: dict[str, str] = {
    FunctionRelationType.involved_in: "involved_in_function",
    FunctionRelationType.associated_with: "associated_with_function",
    FunctionRelationType.necessary_for: "necessary_for_function",
    FunctionRelationType.modulates: "modulates_function",
    FunctionRelationType.participates_in: "participates_in_function",
    FunctionRelationType.uncertain_association: "possibly_associated_with_function",
    FunctionRelationType.unknown: "associated_with_function",
}


class EmptyCandidatesError(Exception):
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


@dataclass
class FunctionExtractionResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.same_granularity_function_completion
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    candidate_count: int = 0
    function_count: int = 0
    mirror_function_created_count: int = 0
    mirror_function_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool = False
    system_prompt: str | None = None
    user_prompt: str | None = None
    warnings: list[str] = field(default_factory=list)


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[FUNCTION_TEMPLATE_KEY]
    return tpl


def _region_label(c: CandidateBrainRegion) -> str:
    return c.en_name or c.cn_name or c.std_name or c.raw_name


def validate_candidates_homogeneous(
    candidates: list[CandidateBrainRegion],
    *,
    scope_resource_id: uuid.UUID | None = None,
    scope_batch_id: uuid.UUID | None = None,
) -> None:
    if not candidates:
        raise EmptyCandidatesError()

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


def build_function_completion_prompt(
    candidates: list[CandidateBrainRegion],
    *,
    template_key: str = FUNCTION_TEMPLATE_KEY,
    max_functions_per_region: int = DEFAULT_MAX_FUNCTIONS_PER_REGION,
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
    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family,
        "regions_json": regions_json,
        "max_functions_per_region": str(max_functions_per_region),
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "regions_json": regions_json,
        "max_functions_per_region": max_functions_per_region,
    }
    return tpl.system_prompt, user_prompt, prompt_json


def parse_function_completion_response(raw_text: str) -> dict[str, Any]:
    return parse_llm_json_response(raw_text)


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_function_candidates(
    parsed: dict[str, Any],
    *,
    allowed_candidate_ids: set[uuid.UUID],
    max_functions_per_region: int = DEFAULT_MAX_FUNCTIONS_PER_REGION,
    allowed_categories: frozenset[str] | None = None,
    allowed_relation_types: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    categories = allowed_categories or DEFAULT_ALLOWED_FUNCTION_CATEGORIES
    relations = allowed_relation_types or DEFAULT_ALLOWED_RELATION_TYPES
    warnings: list[str] = []
    raw_functions = parsed.get("functions")
    if raw_functions is None:
        return [], ["functions array missing; treating as empty"]
    if not isinstance(raw_functions, list):
        raise ValueError("functions must be an array")

    per_region_count: dict[str, int] = defaultdict(int)
    normalized: list[dict[str, Any]] = []

    for idx, fn in enumerate(raw_functions):
        if not isinstance(fn, dict):
            warnings.append(f"function[{idx}] skipped: not an object")
            continue
        try:
            region_id = uuid.UUID(str(fn.get("region_candidate_id")))
        except (ValueError, TypeError, AttributeError):
            warnings.append(f"function[{idx}] skipped: invalid region_candidate_id")
            continue
        if region_id not in allowed_candidate_ids:
            warnings.append(f"function[{idx}] skipped: candidate not in input set")
            continue

        function_term = str(fn.get("function_term") or "").strip()
        if not function_term:
            warnings.append(f"function[{idx}] skipped: empty function_term")
            continue

        if per_region_count[str(region_id)] >= max_functions_per_region:
            warnings.append(
                f"function[{idx}] note: per-region count exceeds max_functions_per_region ({max_functions_per_region}); still saving"
            )

        category = str(fn.get("function_category") or FunctionCategory.unknown)
        if category not in categories:
            category = FunctionCategory.unknown
            warnings.append(f"function[{idx}] function_category coerced to unknown")

        relation = str(fn.get("relation_type") or FunctionRelationType.unknown)
        if relation not in relations:
            relation = FunctionRelationType.unknown
            warnings.append(f"function[{idx}] relation_type coerced to unknown")

        per_region_count[str(region_id)] += 1
        normalized.append({
            "region_candidate_id": str(region_id),
            "function_term": function_term,
            "function_term_key": function_term.lower().strip(),
            "function_category": category,
            "relation_type": relation,
            "confidence": _clamp_confidence(fn.get("confidence")),
            "evidence_text": fn.get("evidence_text"),
            "uncertainty_reason": fn.get("uncertainty_reason"),
            "suggested_triples": fn.get("suggested_triples") or [],
            "raw": fn,
        })
    return normalized, warnings


def function_dedup_key(
    region_id: uuid.UUID,
    function_term_key: str,
    function_category: str,
    relation_type: str,
) -> tuple[str, str, str, str]:
    return str(region_id), function_term_key, function_category, relation_type


async def _function_exists(
    session: AsyncSession,
    *,
    region_id: uuid.UUID,
    function_term_key: str,
    function_category: str,
    relation_type: str,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
) -> bool:
    blocked = {MirrorPromotionStatus.failed, MirrorPromotionStatus.blocked}
    q = select(MirrorRegionFunction.id).where(
        MirrorRegionFunction.region_candidate_id == region_id,
        MirrorRegionFunction.function_category == function_category,
        MirrorRegionFunction.relation_type == relation_type,
        MirrorRegionFunction.source_atlas == source_atlas,
        MirrorRegionFunction.granularity_level == granularity_level,
        MirrorRegionFunction.promotion_status.notin_(blocked),
        MirrorRegionFunction.review_status != MirrorReviewStatus.rejected,
        MirrorRegionFunction.mirror_status != MirrorStatus.superseded,
    )
    if resource_id:
        q = q.where(MirrorRegionFunction.resource_id == resource_id)
    if batch_id:
        q = q.where(MirrorRegionFunction.batch_id == batch_id)

    rows = (await session.execute(q)).scalars().all()
    if not rows:
        return False
    existing = (
        await session.execute(
            select(MirrorRegionFunction).where(MirrorRegionFunction.id.in_(rows))
        )
    ).scalars().all()
    for row in existing:
        if (row.function_term or "").lower().strip() == function_term_key:
            return True
    return False


async def persist_function_mirror_records(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    functions: list[dict[str, Any]],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    create_triples: bool,
    create_evidence: bool,
    session_seen: set[tuple[str, str, str, str]] | None = None,
) -> tuple[int, int, int, int, list[str]]:
    created = skipped = triples = evidence = 0
    warnings: list[str] = []
    seen = session_seen or set()

    for fn in functions:
        region_id = uuid.UUID(fn["region_candidate_id"])
        term_key = fn["function_term_key"]
        category = fn["function_category"]
        relation = fn["relation_type"]
        key = function_dedup_key(region_id, term_key, category, relation)
        if key in seen:
            skipped += 1
            continue
        if await _function_exists(
            session,
            region_id=region_id,
            function_term_key=term_key,
            function_category=category,
            relation_type=relation,
            resource_id=run.resource_id,
            batch_id=run.batch_id,
            source_atlas=run.source_atlas or "",
            granularity_level=run.granularity_level or "",
        ):
            skipped += 1
            seen.add(key)
            continue

        region_c = candidate_map[region_id]
        payload = MirrorRegionFunctionCreate(
            region_candidate_id=region_id,
            region_name_cn=getattr(region_c, 'cn_name', None) or None,
            region_name_en=getattr(region_c, 'en_name', None) or getattr(region_c, 'std_name', None) or None,
            resource_id=run.resource_id,
            batch_id=run.batch_id,
            llm_run_id=run.id,
            llm_item_id=item.id,
            granularity_level=run.granularity_level or "",
            granularity_family=run.granularity_family,
            source_atlas=run.source_atlas or "",
            source_version=run.source_version,
            function_term=fn["function_term"],
            function_category=category,
            relation_type=relation,
            confidence=fn.get("confidence"),
            evidence_text=fn.get("evidence_text"),
            uncertainty_reason=fn.get("uncertainty_reason"),
            raw_payload_json=fn.get("raw") or fn,
            normalized_payload_json=fn,
        )
        mirror_fn = await mirror_kg_service.create_mirror_function(session, payload)
        created += 1
        seen.add(key)

        if create_triples:
            predicate = RELATION_TO_PREDICATE.get(relation, "associated_with_function")
            triple_payload = MirrorKgTripleCreate(
                subject_type=TripleSubjectType.region_candidate,
                subject_id=region_id,
                subject_label=_region_label(region_c),
                predicate=predicate,
                object_type=TripleObjectType.function,
                object_id=None,
                object_label=fn["function_term"],
                triple_scope=TripleScope.same_granularity,
                resource_id=run.resource_id,
                batch_id=run.batch_id,
                llm_run_id=run.id,
                llm_item_id=item.id,
                source_mirror_function_id=mirror_fn.id,
                granularity_level=run.granularity_level or "",
                granularity_family=run.granularity_family,
                source_atlas=run.source_atlas or "",
                source_version=run.source_version,
                confidence=fn.get("confidence"),
                evidence_text=fn.get("evidence_text"),
                uncertainty_reason=fn.get("uncertainty_reason"),
                raw_payload_json={"function": fn},
                normalized_payload_json={"predicate": predicate, "function_term": fn["function_term"]},
            )
            await mirror_kg_service.create_mirror_triple(session, triple_payload)
            triples += 1

        if create_evidence and fn.get("evidence_text"):
            ev_payload = MirrorEvidenceRecordCreate(
                evidence_target_type=EvidenceTargetType.mirror_function,
                evidence_target_id=mirror_fn.id,
                resource_id=run.resource_id,
                batch_id=run.batch_id,
                llm_run_id=run.id,
                llm_item_id=item.id,
                evidence_type=EvidenceType.llm_explanation,
                evidence_text=str(fn["evidence_text"]),
                confidence=fn.get("confidence"),
                uncertainty_reason=fn.get("uncertainty_reason"),
            )
            await mirror_kg_service.create_mirror_evidence(session, ev_payload)
            evidence += 1

    return created, skipped, triples, evidence, warnings


async def run_same_granularity_function_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    candidate_ids: list[uuid.UUID],
    scope_resource_id: uuid.UUID | None = None,
    scope_batch_id: uuid.UUID | None = None,
    prompt_template_key: str = FUNCTION_TEMPLATE_KEY,
    temperature: float = 0.2,
    max_tokens: int = 8192,
    dry_run: bool = False,
    max_functions_per_region: int = DEFAULT_MAX_FUNCTIONS_PER_REGION,
    allowed_function_categories: list[str] | None = None,
    allowed_relation_types: list[str] | None = None,
    create_mirror_records: bool = True,
    create_triples: bool = True,
    create_evidence: bool = True,
) -> FunctionExtractionResult:
    if not candidate_ids:
        raise EmptyCandidatesError()

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

    allowed_cats = frozenset(allowed_function_categories) if allowed_function_categories else DEFAULT_ALLOWED_FUNCTION_CATEGORIES
    allowed_rels = frozenset(allowed_relation_types) if allowed_relation_types else DEFAULT_ALLOWED_RELATION_TYPES

    system_prompt, user_prompt, prompt_json = build_function_completion_prompt(
        candidates,
        template_key=FUNCTION_TEMPLATE_KEY,
        max_functions_per_region=max_functions_per_region,
    )

    result = FunctionExtractionResult(
        candidate_count=len(candidates),
        dry_run=dry_run,
        provider=provider_key,
        model_name=resolved_model,
    )

    if len(candidates) > LARGE_CANDIDATE_WARNING_THRESHOLD:
        result.warnings.append(
            f"LARGE_CANDIDATE_COUNT: candidate_count={len(candidates)} may increase prompt size, cost, and runtime"
        )

    if dry_run:
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt
        return result

    first = candidates[0]
    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.same_granularity_function_completion,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=FUNCTION_TEMPLATE_KEY,
        prompt_version=_resolve_template(FUNCTION_TEMPLATE_KEY).version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "candidate_ids": [str(c.id) for c in candidates],
            "max_functions_per_region": max_functions_per_region,
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
        task_type=LlmTaskType.same_granularity_function_completion,
        item_index=0,
        input_json={
            "candidate_ids": [str(c.id) for c in candidates],
            "max_functions_per_region": max_functions_per_region,
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

    all_warnings: list[str] = []
    normalized_functions: list[dict[str, Any]] = []

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
                parsed = parse_function_completion_response(raw_text)
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
            normalized_functions, norm_warnings = normalize_function_candidates(
                response.parsed_json,
                allowed_candidate_ids={c.id for c in candidates},
                max_functions_per_region=max_functions_per_region,
                allowed_categories=allowed_cats,
                allowed_relation_types=allowed_rels,
            )
            all_warnings.extend(norm_warnings)
        except ValueError as exc:
            item.status = LlmItemStatus.failed
            item.error_message = str(exc)
            run.status = LlmRunStatus.failed
            run.error_count = 1
            normalized_functions = []

    if item.status != LlmItemStatus.failed:
        item.normalized_output_json = {"functions": normalized_functions}
        confidences = [f["confidence"] for f in normalized_functions if f.get("confidence") is not None]
        if confidences:
            item.confidence = sum(confidences) / len(confidences)
        item.status = LlmItemStatus.succeeded if normalized_functions else LlmItemStatus.needs_review
        run.output_count = len(normalized_functions)
        run.status = LlmRunStatus.succeeded

        candidate_map = {c.id: c for c in candidates}
        if create_mirror_records and normalized_functions:
            try:
                mf, skip, tr, ev, pw = await persist_function_mirror_records(
                    session,
                    run=run,
                    item=item,
                    functions=normalized_functions,
                    candidate_map=candidate_map,
                    create_triples=create_triples,
                    create_evidence=create_evidence,
                )
                result.mirror_function_created_count = mf
                result.mirror_function_skipped_duplicate_count = skip
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
    result.function_count = len(normalized_functions)
    result.warnings = all_warnings

    await session.commit()
    await session.refresh(run)
    await session.refresh(item)
    return result
