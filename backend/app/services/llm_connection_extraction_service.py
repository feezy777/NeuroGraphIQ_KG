"""Same-granularity connection extraction — LLM run/item + Mirror KG (Step 3).

Writes mirror_region_connections, mirror_kg_triples, mirror_evidence_records.
Does NOT write final_* / kg_*; does NOT auto approve/promote.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import MirrorEvidenceRecord, MirrorKgTriple, MirrorRegionConnection
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
    TripleScope,
    TripleSubjectType,
)
from app.services.llm_extraction_service import (
    CandidateNotFoundError,
    ProviderNotConfiguredServiceError,
)
from app.services.llm_extraction_prompt_engineering import (
    DEFAULT_PAIRS_PER_PACK,
    ConnectionExecutionAudit,
    build_compact_pair_records,
    build_connection_prompt_preview,
    finalize_connection_extraction_status,
    make_pair_id,
    normalize_connection_extraction_payload,
    normalize_projection_extraction_response,
    pack_pair_records,
    prompt_display_name,
)
from app.services.llm_json_utils import (
    LlmJsonParseError,
    parse_connection_completion_response,
    raw_response_preview,
)
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services import mirror_kg_service
from app.services.llm_workflow_artifact_tagging import tag_raw_payload
from app.services.llm_workflow_cancel_registry import is_cancelling
from app.services.llm_workflow_event_log import safe_append_workflow_event
from app.services.llm_connection_parse_diagnostics import (
    FAIL_FAST_DEFAULT_ENABLED,
    FAIL_FAST_DEFAULT_REASON,
    FAIL_FAST_DEFAULT_THRESHOLD,
    RAW_TEXT_MISSING_CODE,
    build_debug_execution_extra,
    build_execution_summary,
    build_initial_pack_summary,
    finalize_pack_trace,
    prompt_preview,
    reassign_jsonb,
    should_trigger_parse_fail_fast,
    upsert_pack_trace,
)
from app.services.llm_status_utils import (
    apply_persistent_run_status,
    is_semantic_failure,
    is_semantic_no_edges,
)
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config

# No hard cap on candidate count or pair count — large selections produce warnings only.
LARGE_PAIR_COUNT_WARNING_THRESHOLD = 200
DEFAULT_MAX_CANDIDATE_PAIRS = 200  # retained for request compatibility; not used as a blocker
CONNECTION_TEMPLATE_KEY = "same_granularity_connection_completion_v1"
logger = logging.getLogger(__name__)

ConnectionProgressCallback = Callable[
    ["LlmExtractionRun", ConnectionExecutionAudit, dict[str, Any] | None],
    Awaitable[None],
]

DEFAULT_ALLOWED_CONNECTION_TYPES = frozenset({
    ConnectionType.structural_connection,
    ConnectionType.functional_connectivity,
    ConnectionType.effective_connectivity,
    ConnectionType.projection,
    ConnectionType.association,
    ConnectionType.coactivation,
    ConnectionType.uncertain_connection,
})

VALID_DIRECTIONALITIES = frozenset({
    Directionality.directed,
    Directionality.undirected,
    Directionality.bidirectional,
    Directionality.unknown,
})

CONNECTION_TO_PREDICATE: dict[str, str] = {
    ConnectionType.functional_connectivity: "functionally_connects_to",
    ConnectionType.structural_connection: "structurally_connects_to",
    ConnectionType.effective_connectivity: "effectively_connects_to",
    ConnectionType.projection: "projects_to",
    ConnectionType.association: "associated_with",
    ConnectionType.coactivation: "coactivates_with",
    ConnectionType.uncertain_connection: "possibly_connects_to",
    ConnectionType.unknown: "related_to",
}


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


class TooManyCandidatePairsError(Exception):
    def __init__(self, pair_count: int, max_candidate_pairs: int):
        self.pair_count = pair_count
        self.max_candidate_pairs = max_candidate_pairs
        super().__init__("too many candidate pairs")


class InvalidPairStrategyError(Exception):
    pass


class CenterCandidateRequiredError(Exception):
    pass


class CenterCandidateNotInSelectionError(Exception):
    pass


@dataclass
class ConnectionExtractionResult:
    run_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    task_type: str = LlmTaskType.same_granularity_connection_completion
    provider: str | None = None
    model_name: str | None = None
    status: str | None = None
    candidate_count: int = 0
    pair_count: int = 0
    connection_count: int = 0
    mirror_connection_created_count: int = 0
    mirror_connection_skipped_duplicate_count: int = 0
    triple_created_count: int = 0
    evidence_created_count: int = 0
    dry_run: bool = False
    system_prompt: str | None = None
    user_prompt: str | None = None
    prompt_preview: dict[str, Any] | None = None
    pack_count: int = 0
    processed_pair_count: int = 0
    unprocessed_pair_count: int = 0
    no_connection_count: int = 0
    created_connection_ids: list[uuid.UUID] = field(default_factory=list)
    execution_summary: dict[str, Any] | None = None
    provider_call_count: int = 0
    provider_success_count: int = 0
    provider_error_count: int = 0
    provider_empty_response_count: int = 0
    warnings: list[str] = field(default_factory=list)
    outcome: str | None = None
    display_status: str | None = None
    persistent_status: str | None = None


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES[CONNECTION_TEMPLATE_KEY]
    return tpl


def _region_label(c: CandidateBrainRegion) -> str:
    return c.en_name or c.cn_name or c.std_name or c.raw_name


def compute_pairs(
    candidate_ids: list[uuid.UUID],
    *,
    pair_strategy: str,
    center_candidate_id: uuid.UUID | None,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    ids = list(candidate_ids)
    if pair_strategy == "all_pairs":
        pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.append((ids[i], ids[j]))
        return pairs
    if pair_strategy == "region_centered":
        if center_candidate_id is None:
            raise CenterCandidateRequiredError()
        if center_candidate_id not in ids:
            raise CenterCandidateNotInSelectionError()
        return [(center_candidate_id, other) for other in ids if other != center_candidate_id]
    raise InvalidPairStrategyError(pair_strategy)


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


def build_connection_completion_prompt(
    candidates: list[CandidateBrainRegion],
    pair_records: list[dict[str, Any]],
    template_key: str = CONNECTION_TEMPLATE_KEY,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    first = candidates[0]
    pairs_json = json.dumps(pair_records, ensure_ascii=False, indent=2)

    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family or "",
        "pairs_json": pairs_json,
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "prompt_display_name": prompt_display_name(tpl.template_key),
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "pairs_json": pairs_json,
        "pair_count": len(pair_records),
    }
    return tpl.system_prompt, user_prompt, prompt_json


def _pack_max_tokens(pack_size: int, default_max_tokens: int) -> int:
    """Scale output budget for large packs to reduce truncation parse failures."""
    estimated = 200 + pack_size * 300
    return max(default_max_tokens, min(16000, estimated))


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_connection_candidates(
    parsed: dict[str, Any],
    *,
    allowed_candidate_ids: set[uuid.UUID],
    allowed_connection_types: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    allowed_types = allowed_connection_types or DEFAULT_ALLOWED_CONNECTION_TYPES
    warnings: list[str] = []
    raw_connections = parsed.get("connections")
    if raw_connections is None:
        return [], ["connections array missing; treating as empty"]
    if not isinstance(raw_connections, list):
        raise ValueError("connections must be an array")

    normalized: list[dict[str, Any]] = []
    for idx, conn in enumerate(raw_connections):
        if not isinstance(conn, dict):
            warnings.append(f"connection[{idx}] skipped: not an object")
            continue
        try:
            src = uuid.UUID(str(conn.get("source_candidate_id")))
            tgt = uuid.UUID(str(conn.get("target_candidate_id")))
        except (ValueError, TypeError, AttributeError):
            warnings.append(f"connection[{idx}] skipped: invalid candidate ids")
            continue
        if src == tgt:
            warnings.append(f"connection[{idx}] skipped: self-loop")
            continue
        if src not in allowed_candidate_ids or tgt not in allowed_candidate_ids:
            warnings.append(f"connection[{idx}] skipped: candidate not in input set")
            continue

        conn_type = str(conn.get("connection_type") or ConnectionType.unknown)
        if conn_type not in allowed_types and conn_type != ConnectionType.unknown:
            conn_type = ConnectionType.uncertain_connection
            warnings.append(f"connection[{idx}] connection_type coerced to uncertain_connection")

        directionality = str(conn.get("directionality") or Directionality.unknown)
        if directionality not in VALID_DIRECTIONALITIES:
            directionality = Directionality.unknown

        normalized.append({
            "source_candidate_id": str(src),
            "target_candidate_id": str(tgt),
            "connection_type": conn_type,
            "directionality": directionality,
            "strength": conn.get("strength"),
            "modality": conn.get("modality"),
            "confidence": _clamp_confidence(conn.get("confidence")),
            "evidence_text": conn.get("evidence_text"),
            "uncertainty_reason": conn.get("uncertainty_reason"),
            "suggested_triples": conn.get("suggested_triples") or [],
            "raw": conn,
        })
    return normalized, warnings


def canonical_pair_key(
    src: uuid.UUID,
    tgt: uuid.UUID,
    connection_type: str,
    directionality: str,
) -> tuple[str, str, str, str]:
    if directionality == Directionality.undirected:
        a, b = sorted((str(src), str(tgt)))
        return a, b, connection_type, directionality
    return str(src), str(tgt), connection_type, directionality


async def _connection_exists(
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
) -> bool:
    a, b, ctype, direc = canonical_pair_key(src, tgt, connection_type, directionality)
    blocked = {MirrorPromotionStatus.failed, MirrorPromotionStatus.blocked}

    base = select(MirrorRegionConnection.id).where(
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
    row = (await session.execute(q.limit(1))).scalar_one_or_none()
    return row is not None


async def persist_connection_mirror_records(
    session: AsyncSession,
    *,
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    connections: list[dict[str, Any]],
    candidate_map: dict[uuid.UUID, CandidateBrainRegion],
    create_triples: bool,
    create_evidence: bool,
    session_seen: set[tuple[str, str, str, str]] | None = None,
    composite_workflow_run_id: uuid.UUID | None = None,
    workflow_step_key: str | None = None,
) -> tuple[int, int, int, int, list[str], list[uuid.UUID]]:
    created = skipped = triples = evidence = 0
    warnings: list[str] = []
    created_ids: list[uuid.UUID] = []
    seen = session_seen or set()

    for conn in connections:
        if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
            warnings.append("Mirror persist skipped — workflow cancelled")
            break
        src = uuid.UUID(conn["source_candidate_id"])
        tgt = uuid.UUID(conn["target_candidate_id"])
        conn_type = conn["connection_type"]
        directionality = conn["directionality"]
        key = canonical_pair_key(src, tgt, conn_type, directionality)
        if key in seen:
            skipped += 1
            continue

        raw_payload = conn.get("raw") or conn
        normalized_payload = conn
        if composite_workflow_run_id:
            raw_payload = tag_raw_payload(
                raw_payload if isinstance(raw_payload, dict) else {"connection": raw_payload},
                workflow_run_id=composite_workflow_run_id,
                step_key=workflow_step_key,
            )
            normalized_payload = tag_raw_payload(
                conn if isinstance(conn, dict) else {"connection": conn},
                workflow_run_id=composite_workflow_run_id,
                step_key=workflow_step_key,
            )
        payload = MirrorRegionConnectionCreate(
            source_region_candidate_id=src,
            target_region_candidate_id=tgt,
            resource_id=run.resource_id,
            batch_id=run.batch_id,
            llm_run_id=run.id,
            llm_item_id=item.id,
            granularity_level=run.granularity_level or "",
            granularity_family=run.granularity_family,
            source_atlas=run.source_atlas or "",
            source_version=run.source_version,
            connection_type=conn_type,
            directionality=directionality,
            strength=conn.get("strength"),
            modality=conn.get("modality"),
            confidence=conn.get("confidence"),
            evidence_text=conn.get("evidence_text"),
            uncertainty_reason=conn.get("uncertainty_reason"),
            raw_payload_json=raw_payload,
            normalized_payload_json=normalized_payload,
        )
        mirror_conn = await mirror_kg_service.create_mirror_connection(session, payload)
        # Determine action from provenance merge_history (dedup-aware)
        prov = (mirror_conn.raw_payload_json or {}).get("provenance", {})
        merge_history = prov.get("merge_history", [])
        last_action = merge_history[-1].get("action") if merge_history else "created"
        if last_action == "updated":
            created += 1  # still counts as a successful addition
        elif last_action == "skipped":
            skipped += 1
        else:
            created += 1  # "created"
        created_ids.append(mirror_conn.id)
        seen.add(key)

        if create_triples:
            src_c = candidate_map[src]
            tgt_c = candidate_map[tgt]
            predicate = CONNECTION_TO_PREDICATE.get(conn_type, "related_to")
            triple_payload = MirrorKgTripleCreate(
                subject_type=TripleSubjectType.region_candidate,
                subject_id=src,
                subject_label=_region_label(src_c),
                predicate=predicate,
                object_type=TripleSubjectType.region_candidate,
                object_id=tgt,
                object_label=_region_label(tgt_c),
                triple_scope=TripleScope.same_granularity,
                resource_id=run.resource_id,
                batch_id=run.batch_id,
                llm_run_id=run.id,
                llm_item_id=item.id,
                source_mirror_connection_id=mirror_conn.id,
                granularity_level=run.granularity_level or "",
                granularity_family=run.granularity_family,
                source_atlas=run.source_atlas or "",
                source_version=run.source_version,
                confidence=conn.get("confidence"),
                evidence_text=conn.get("evidence_text"),
                uncertainty_reason=conn.get("uncertainty_reason"),
                raw_payload_json={"connection": conn},
                normalized_payload_json={"predicate": predicate, "connection_type": conn_type},
            )
            await mirror_kg_service.create_mirror_triple(session, triple_payload)
            triples += 1

        if create_evidence and conn.get("evidence_text"):
            ev_payload = MirrorEvidenceRecordCreate(
                evidence_target_type=EvidenceTargetType.mirror_connection,
                evidence_target_id=mirror_conn.id,
                resource_id=run.resource_id,
                batch_id=run.batch_id,
                llm_run_id=run.id,
                llm_item_id=item.id,
                evidence_type=EvidenceType.llm_explanation,
                evidence_text=str(conn["evidence_text"]),
                confidence=conn.get("confidence"),
                uncertainty_reason=conn.get("uncertainty_reason"),
            )
            await mirror_kg_service.create_mirror_evidence(session, ev_payload)
            evidence += 1

    return created, skipped, triples, evidence, warnings, created_ids


async def _load_candidates_batch(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
) -> list[CandidateBrainRegion]:
    """Load all candidates in one query (avoid N sequential session.get round-trips)."""
    stmt = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(candidate_ids))
    result = await session.execute(stmt)
    scalars_result = result.scalars() if hasattr(result, "scalars") else result
    rows = list(scalars_result.all())
    by_id = {c.id: c for c in rows}
    for cid in candidate_ids:
        if cid not in by_id:
            raise CandidateNotFoundError(str(cid))
    return [by_id[cid] for cid in candidate_ids]


def _lightweight_connection_preview(
    *,
    prompt_key: str,
    pair_count: int,
    pack_count: int,
) -> dict[str, Any]:
    return {
        "prompt_key": prompt_key,
        "prompt_display_name": prompt_display_name(prompt_key),
        "pair_count": pair_count,
        "pack_count": pack_count,
        "model_call_count": pack_count,
    }


async def run_same_granularity_connection_extraction(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    candidate_ids: list[uuid.UUID],
    scope_resource_id: uuid.UUID | None = None,
    scope_batch_id: uuid.UUID | None = None,
    prompt_template_key: str = CONNECTION_TEMPLATE_KEY,
    temperature: float = 0.2,
    # 40 pairs/pack with the full projection schema can exceed 4000 output tokens
    # and truncate the JSON mid-array (the dominant cause of parse failures).
    max_tokens: int = 12000,
    dry_run: bool = False,
    max_candidate_pairs: int = DEFAULT_MAX_CANDIDATE_PAIRS,
    pair_strategy: str = "all_pairs",
    center_candidate_id: uuid.UUID | None = None,
    allowed_connection_types: list[str] | None = None,
    create_mirror_records: bool = True,
    create_triples: bool = True,
    create_evidence: bool = True,
    on_progress: ConnectionProgressCallback | None = None,
    commit_progress: bool = False,
    composite_workflow_run_id: uuid.UUID | None = None,
    workflow_step_key: str | None = None,
    debug_max_packs: int | None = None,
    debug_single_pack: bool = False,
    parse_error_fail_fast_enabled: bool = FAIL_FAST_DEFAULT_ENABLED,
    parse_error_fail_fast_threshold: int = FAIL_FAST_DEFAULT_THRESHOLD,
) -> ConnectionExtractionResult:
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

    logger.info(
        "[connection-extraction] start dry_run=%s candidate_count=%s provider=%s",
        dry_run,
        len(candidate_ids),
        provider_key,
    )

    candidates = await _load_candidates_batch(session, candidate_ids)
    logger.info("[connection-extraction] candidates loaded count=%s", len(candidates))

    validate_candidates_homogeneous(
        candidates,
        scope_resource_id=scope_resource_id,
        scope_batch_id=scope_batch_id,
    )

    pairs = compute_pairs(
        [c.id for c in candidates],
        pair_strategy=pair_strategy,
        center_candidate_id=center_candidate_id,
    )
    pair_records = build_compact_pair_records(candidates, pairs)
    packs = pack_pair_records(pair_records, pairs_per_pack=DEFAULT_PAIRS_PER_PACK)
    original_pack_count = len(packs)
    resolved_debug_max_packs = debug_max_packs
    if debug_single_pack:
        resolved_debug_max_packs = 1
    if resolved_debug_max_packs is not None and resolved_debug_max_packs >= 0:
        packs = packs[: max(0, resolved_debug_max_packs)]
    executed_pack_count = len(packs)
    debug_mode = debug_single_pack or resolved_debug_max_packs is not None
    debug_extra = build_debug_execution_extra(
        debug_mode=debug_mode,
        debug_single_pack=debug_single_pack,
        debug_max_packs=resolved_debug_max_packs,
        original_pack_count=original_pack_count,
        executed_pack_count=executed_pack_count,
    )
    allowed_types = frozenset(allowed_connection_types) if allowed_connection_types else DEFAULT_ALLOWED_CONNECTION_TYPES
    system_prompt, user_prompt, prompt_json = build_connection_completion_prompt(
        candidates, pair_records[: min(len(pair_records), DEFAULT_PAIRS_PER_PACK)], prompt_template_key
    )

    result = ConnectionExtractionResult(
        candidate_count=len(candidates),
        pair_count=len(pairs),
        pack_count=len(packs),
        dry_run=dry_run,
        provider=provider_key,
        model_name=resolved_model,
    )

    if len(pairs) > LARGE_PAIR_COUNT_WARNING_THRESHOLD:
        result.warnings.append(
            f"LARGE_CANDIDATE_PAIR_COUNT: pair_count={len(pairs)} may increase prompt size, cost, and runtime"
        )
    if len(pairs) > max_candidate_pairs:
        result.warnings.append(
            f"pair_count ({len(pairs)}) exceeds request max_candidate_pairs ({max_candidate_pairs}); continuing without truncation"
        )

    preview = build_connection_prompt_preview(
        prompt_key=prompt_template_key,
        pair_count=len(pairs),
        packs=packs,
        system_prompt=system_prompt,
        sample_user_prompt=_resolve_template(prompt_template_key).user_prompt_template,
        model_call_count=len(packs),
    ) if dry_run else _lightweight_connection_preview(
        prompt_key=prompt_template_key,
        pair_count=len(pairs),
        pack_count=len(packs),
    )
    result.prompt_preview = preview

    if dry_run:
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt
        result.unprocessed_pair_count = len(pairs)
        return result

    first = candidates[0]
    now = datetime.now(timezone.utc)
    run = LlmExtractionRun(
        task_type=LlmTaskType.same_granularity_connection_completion,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=prompt_template_key,
        prompt_version=_resolve_template(prompt_template_key).version,
        scope_type=LlmScopeType.manual_selection,
        scope_json={
            "candidate_ids": [str(c.id) for c in candidates],
            "pair_strategy": pair_strategy,
            "max_candidate_pairs": max_candidate_pairs,
            "center_candidate_id": str(center_candidate_id) if center_candidate_id else None,
            "pack_count": len(packs),
            **({"composite_workflow_run_id": str(composite_workflow_run_id)} if composite_workflow_run_id else {}),
        },
        resource_id=scope_resource_id or first.resource_id,
        batch_id=scope_batch_id or first.batch_id,
        granularity_level=first.granularity_level,
        granularity_family=first.granularity_family,
        source_atlas=first.source_atlas,
        source_version=first.source_version,
        status=LlmRunStatus.running,
        input_count=len(pairs),
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
        task_type=LlmTaskType.same_granularity_connection_completion,
        item_index=0,
        input_json={
            "candidate_ids": [str(c.id) for c in candidates],
            "pair_count": len(pairs),
            "pack_count": len(packs),
            "pair_strategy": pair_strategy,
        },
        prompt_json={**prompt_json, "prompt_preview": preview},
        status=LlmItemStatus.running,
    )
    session.add(item)
    await session.flush()
    logger.info(
        "[connection-extraction] run created run_id=%s pair_count=%s pack_count=%s",
        run.id,
        len(pairs),
        len(packs),
    )

    audit = ConnectionExecutionAudit(
        pair_count=len(pairs),
        pack_count=len(packs),
        model_call_count=len(packs),
        estimated_input_tokens=preview.get("estimated_input_tokens", 0),
        estimated_output_tokens=preview.get("estimated_output_tokens", 0),
    )
    pack_traces: list[dict[str, Any]] = []
    reassign_jsonb(
        run,
        "scope_json",
        {
            **(run.scope_json or {}),
            "execution_summary": build_execution_summary(
                audit,
                pack_traces,
                extra=debug_extra,
            ),
        },
    )
    async def _log_event(
        level: str,
        event: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        if not composite_workflow_run_id:
            return
        await safe_append_workflow_event(
            session,
            composite_workflow_run_id,
            step_key=workflow_step_key or "extract_connections",
            level=level,
            event=event,
            message=message,
            data=data,
            commit=commit_progress,
        )

    if on_progress:
        await on_progress(
            run,
            audit,
            build_execution_summary(
                audit,
                pack_traces,
                extra=debug_extra,
            ),
        )
    if commit_progress:
        await session.commit()

    await _log_event(
        "info",
        "pairs_generated",
        f"Generated {len(pairs)} candidate pairs from {len(candidates)} candidates",
        {"candidate_count": len(candidates), "pair_count": len(pairs)},
    )
    await _log_event(
        "info",
        "packs_built",
        f"Built {len(packs)} prompt packs (size={DEFAULT_PAIRS_PER_PACK})",
        {
            "pack_count": len(packs),
            "pack_size": DEFAULT_PAIRS_PER_PACK,
            "estimated_input_tokens_total": preview.get("estimated_input_tokens", 0),
        },
    )

    all_warnings: list[str] = []
    normalized_connections: list[dict[str, Any]] = []
    all_no_connections: list[dict[str, Any]] = []
    processed_pair_ids: set[str] = set()
    tpl = _resolve_template(prompt_template_key)
    display_name = prompt_display_name(prompt_template_key)

    async def _emit_progress(extra: dict[str, Any] | None = None) -> None:
        merged_extra = {**debug_extra, **(extra or {})}
        summary = build_execution_summary(audit, pack_traces, extra=merged_extra)
        provider_audit = summary.get("provider_audit") or {}
        reassign_jsonb(
            run,
            "scope_json",
            {
                **(run.scope_json or {}),
                "execution_summary": summary,
                "pack_summaries": summary.get("pack_summaries") or [],
                "provider_audit": provider_audit,
            },
        )
        reassign_jsonb(
            item,
            "prompt_json",
            {
                **(item.prompt_json or {}),
                "pack_traces": pack_traces,
                "execution_summary": summary,
            },
        )
        if on_progress:
            await on_progress(run, audit, summary)
        if commit_progress:
            try:
                await session.commit()
            except StaleDataError:
                # Cleanup of a cancelled workflow may have changed our rows. Ignore
                # the late write instead of raising to the user.
                if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
                    logger.warning(
                        "[connection-extraction] late progress commit ignored after cancel run=%s",
                        getattr(run, "id", None),
                    )
                    await session.rollback()
                else:
                    raise

    async def _persist_pack_trace(trace: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
        upsert_pack_trace(pack_traces, trace)
        await _emit_progress(extra)

    provider = get_llm_provider(provider_key)

    packs_completed_before_cancel = 0
    packs_cancelled = 0
    late_provider_response_ignored = 0
    consecutive_parse_failures = 0
    fail_fast_triggered = False
    remaining_pack_count_skipped = 0
    max_provider_attempts = 1 if debug_mode else 2

    for pack_index, pack in enumerate(packs):
        if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
            packs_cancelled = len(packs) - pack_index
            all_warnings.append("Workflow cancelled by user — stopping new provider packs")
            break
        pack_pair_ids = {str(r["pair_id"]) for r in pack}
        pair_id_to_endpoints = {
            str(r["pair_id"]): (
                uuid.UUID(str(r["source_region_candidate_id"])),
                uuid.UUID(str(r["target_region_candidate_id"])),
            )
            for r in pack
        }
        pack_system, pack_user, _ = build_connection_completion_prompt(
            candidates, pack, prompt_template_key
        )
        audit.prompt_built_count += 1
        await _log_event(
            "info",
            "prompt_built",
            f"Built prompt for pack {pack_index + 1}/{len(packs)}",
            {
                "pack_id": pack_index,
                "pack_index": pack_index + 1,
                "pack_count": len(packs),
                "pair_count": len(pack),
            },
        )
        if not pack_user.strip():
            all_warnings.append(f"pack[{pack_index}] empty prompt; skipped provider call")
            pack_traces.append({
                "pack_id": pack_index,
                "prompt_key": prompt_template_key,
                "prompt_display_name": display_name,
                "provider": provider_key,
                "model_name": resolved_model,
                "response_received": False,
                "response_char_count": 0,
                "parsed_projection_count": 0,
                "parsed_no_connection_count": 0,
                "provider_error": "empty prompt",
            })
            await _emit_progress()
            continue

        trace = build_initial_pack_summary(
            pack_id=pack_index,
            pack_index=pack_index + 1,
            pack_count=len(packs),
            pair_count=len(pack),
            provider=provider_key,
            model_name=resolved_model,
            prompt_key=prompt_template_key,
            prompt_display_name=display_name,
            prompt_preview_text=pack_user,
            json_mode_enabled=run.scope_json.get("json_mode_enabled") if run.scope_json else None,
        )
        trace["prompt_built"] = True
        pack_max_tokens = _pack_max_tokens(len(pack), max_tokens)
        parsed: dict[str, Any] | None = None
        raw_text = ""
        pack_persisted = False

        try:
            for attempt in range(max_provider_attempts):
                if attempt > 0:
                    trace["retry_count"] = attempt
                    audit.provider_call_count += 1
                    audit.prompt_sent_count += 1
                    await _log_event(
                        "warning",
                        "provider_call_retry",
                        f"Retrying provider call for pack {pack_index + 1} after parse failure",
                        {"pack_id": pack_index, "retry_count": attempt},
                    )

                if attempt == 0:
                    audit.provider_call_count += 1
                    audit.prompt_sent_count += 1
                    trace["prompt_sent"] = True
                    trace["provider_call_started"] = True
                    await _log_event(
                        "info",
                        "provider_call_start",
                        f"Starting provider call for pack {pack_index + 1}/{len(packs)}",
                        {
                            "pack_id": pack_index,
                            "pack_index": pack_index + 1,
                            "pack_count": len(packs),
                            "pair_count": len(pack),
                            "max_tokens": pack_max_tokens,
                        },
                    )
                    logger.info(
                        "[connection-extraction] calling provider pack=%s/%s pair_count=%s provider_call_count=%s",
                        pack_index + 1,
                        len(packs),
                        len(pack),
                        audit.provider_call_count,
                    )

                text_result = await provider.complete_text(
                    model=resolved_model,
                    system_prompt=pack_system,
                    user_prompt=pack_user,
                    temperature=temperature,
                    max_tokens=pack_max_tokens,
                    json_mode=True,
                )
                if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
                    late_provider_response_ignored += 1
                    trace["provider_error"] = "late_provider_response_ignored"
                    trace["status"] = "cancelled"
                    all_warnings.append(f"pack[{pack_index}] late provider response ignored after cancel")
                    await _log_event(
                        "warning",
                        "late_provider_response_ignored",
                        f"Ignored late provider response for pack {pack_index + 1} after cancel",
                        {"pack_id": pack_index},
                    )
                    parsed = None
                    break

                if attempt == 0 and pack_index == 0:
                    item.raw_response_text = text_result.raw_text or None
                    reassign_jsonb(run, "request_payload_redacted", text_result.request_payload_redacted)
                    reassign_jsonb(run, "usage_json", text_result.usage.as_dict() if text_result.usage else {})
                    json_mode = text_result.response_payload.get("json_mode_enabled")
                    if json_mode is not None:
                        reassign_jsonb(
                            run,
                            "scope_json",
                            {**(run.scope_json or {}), "json_mode_enabled": json_mode},
                        )

                trace["provider_call_finished"] = True
                raw_text = text_result.raw_text or ""
                trace["response_received"] = bool(raw_text.strip())
                trace["response_char_count"] = len(raw_text)
                trace["raw_text"] = raw_text[:2000] if raw_text else ""
                trace["raw_response_preview"] = text_result.raw_response_preview or raw_response_preview(raw_text)
                trace["finish_reason"] = text_result.finish_reason
                trace["json_mode_enabled"] = text_result.response_payload.get(
                    "json_mode_enabled",
                    trace.get("json_mode_enabled"),
                )
                if text_result.response_payload.get("fallback_raw_response_used"):
                    trace["fallback_raw_response_used"] = True
                await _persist_pack_trace(trace)
                pack_persisted = True

                if not text_result.transport_ok:
                    audit.provider_transport_error_count += 1
                    audit.provider_error_count += 1
                    trace["provider_error"] = text_result.error or "transport_error"
                    trace["parse_error_type"] = "transport_error"
                    trace["status"] = "transport_error"
                    all_warnings.append(
                        f"pack[{pack_index}] provider transport error: {text_result.error or 'transport_error'}"
                    )
                    await _log_event(
                        "error",
                        "provider_call_transport_error",
                        f"Provider transport error for pack {pack_index + 1}",
                        {
                            "pack_id": pack_index,
                            "error_type": "transport_error",
                            "message": text_result.error,
                        },
                    )
                    parsed = None
                    break

                if not raw_text.strip():
                    audit.provider_empty_response_count += 1
                    trace["provider_error"] = RAW_TEXT_MISSING_CODE
                    trace["parse_error_type"] = "empty_response"
                    trace["status"] = "empty_response"
                    all_warnings.append(
                        f"pack[{pack_index}] {RAW_TEXT_MISSING_CODE}: provider call finished without body"
                    )
                    await _log_event(
                        "warning",
                        "provider_call_empty_response",
                        f"Provider returned empty response for pack {pack_index + 1}",
                        {"pack_id": pack_index, "error_code": RAW_TEXT_MISSING_CODE},
                    )
                    parsed = None
                    break

                audit.provider_success_count += 1
                await _log_event(
                    "info",
                    "provider_call_success",
                    f"Provider returned content for pack {pack_index + 1}",
                    {
                        "pack_id": pack_index,
                        "response_char_count": len(raw_text),
                        "finish_reason": text_result.finish_reason,
                        "raw_response_preview": trace.get("raw_response_preview"),
                    },
                )

                try:
                    parsed = parse_connection_completion_response(raw_text)
                    trace["status"] = "parsed"
                    break
                except LlmJsonParseError as exc:
                    trace["parse_error"] = str(exc)
                    trace["parse_error_type"] = exc.error_type
                    trace["raw_response_preview"] = exc.preview or trace["raw_response_preview"]
                    if attempt >= 1:
                        all_warnings.append(f"pack[{pack_index}] parse error: {exc}")
                        await _log_event(
                            "error",
                            "provider_response_parse_error",
                            f"Parse error for pack {pack_index + 1}",
                            {
                                "pack_id": pack_index,
                                "parse_error": str(exc),
                                "parse_error_type": exc.error_type,
                                "raw_response_preview": trace.get("raw_response_preview"),
                                "response_char_count": len(raw_text),
                                "retry_count": attempt,
                            },
                        )
                    if attempt == 0:
                        continue
                except Exception as exc:  # noqa: BLE001
                    trace["parse_error"] = str(exc)
                    trace["parse_error_type"] = "json_decode_error"
                    if attempt >= 1:
                        all_warnings.append(f"pack[{pack_index}] parse error: {exc}")
                        await _log_event(
                            "error",
                            "provider_response_parse_error",
                            f"Parse error for pack {pack_index + 1}",
                            {
                                "pack_id": pack_index,
                                "parse_error": str(exc),
                                "raw_response_preview": trace.get("raw_response_preview"),
                                "retry_count": attempt,
                            },
                        )
                    if attempt == 0:
                        continue
        finally:
            if not pack_persisted:
                await _persist_pack_trace(trace)

        if parsed is None:
            if trace.get("parse_error_type") not in {"transport_error", "empty_response"}:
                audit.parse_error_count += 1
                consecutive_parse_failures += 1
                trace["status"] = "parse_error"
                await _persist_pack_trace(trace)
                if should_trigger_parse_fail_fast(
                    consecutive_parse_failures=consecutive_parse_failures,
                    parsed_projection_count=audit.parsed_projection_count,
                    parsed_no_connection_count=audit.parsed_no_connection_count,
                    enabled=parse_error_fail_fast_enabled and not debug_mode,
                    threshold=parse_error_fail_fast_threshold,
                ):
                    fail_fast_triggered = True
                    remaining_pack_count_skipped = len(packs) - pack_index - 1
                    all_warnings.append(
                        "First "
                        f"{consecutive_parse_failures} provider responses could not be parsed as JSON. "
                        "Stopping remaining packs to avoid token waste."
                    )
                    await _log_event(
                        "error",
                        "parse_fail_fast_triggered",
                        "Parse fail-fast triggered after consecutive parse errors",
                        {
                            "consecutive_parse_failures": consecutive_parse_failures,
                            "remaining_pack_count_skipped": remaining_pack_count_skipped,
                            "fail_fast_reason": FAIL_FAST_DEFAULT_REASON,
                            "raw_response_preview": trace.get("raw_response_preview"),
                        },
                    )
                    await _persist_pack_trace(
                        trace,
                        extra={
                            "fail_fast_triggered": True,
                            "remaining_pack_count_skipped": remaining_pack_count_skipped,
                            "fail_fast_reason": FAIL_FAST_DEFAULT_REASON,
                        },
                    )
                    break
            else:
                await _persist_pack_trace(trace)
            continue

        consecutive_parse_failures = 0

        # Normalize aliased payloads and recover pair_id from endpoints where missing.
        parsed = normalize_connection_extraction_payload(
            parsed,
            pair_id_to_endpoints=pair_id_to_endpoints,
        )

        try:
            pack_connections, pack_no, pack_warnings, handled = normalize_projection_extraction_response(
                parsed,
                allowed_pair_ids=pack_pair_ids,
                pair_id_to_endpoints=pair_id_to_endpoints,
                allowed_connection_types=allowed_types,
            )
        except ValueError as exc:
            # JSON parsed but did not match schema → schema error, not transport.
            audit.schema_error_count += 1
            trace["schema_error"] = str(exc)
            trace["parse_error"] = str(exc)
            trace["parse_error_type"] = "schema_error"
            all_warnings.append(f"pack[{pack_index}] schema error: {exc}")
            await _log_event(
                "warning",
                "provider_response_schema_error",
                f"Schema error for pack {pack_index + 1}",
                {"pack_id": pack_index, "parse_error": str(exc)},
            )
            trace["status"] = "schema_error"
            await _persist_pack_trace(trace)
            continue

        rejected_in_pack = sum(1 for w in pack_warnings if "rejected" in w)
        audit.rejected_item_count += rejected_in_pack
        audit.parsed_projection_count += len(pack_connections)
        audit.parsed_no_connection_count += len(pack_no)
        trace["parsed_projection_count"] = len(pack_connections)
        trace["parsed_no_connection_count"] = len(pack_no)
        trace["rejected_item_count"] = rejected_in_pack
        trace["unprocessed_pair_count"] = max(0, len(pack) - len(handled))
        trace["status"] = "succeeded"

        await _log_event(
            "info",
            "provider_response_parsed",
            f"Parsed pack {pack_index + 1}: {len(pack_connections)} projections, {len(pack_no)} no_connections",
            {
                "pack_id": pack_index,
                "parsed_projection_count": len(pack_connections),
                "parsed_no_connection_count": len(pack_no),
                "rejected_item_count": rejected_in_pack,
            },
        )

        all_warnings.extend(pack_warnings)
        normalized_connections.extend(pack_connections)
        all_no_connections.extend(pack_no)
        processed_pair_ids.update(handled)
        packs_completed_before_cancel += 1
        await _persist_pack_trace(trace)

    if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
        run.status = LlmRunStatus.cancelled
        item.status = LlmItemStatus.skipped
        result.status = LlmRunStatus.cancelled
        execution_summary = build_execution_summary(
            audit,
            pack_traces,
            extra={
                "cancelled": True,
                "packs_completed_before_cancel": packs_completed_before_cancel,
                "packs_cancelled": packs_cancelled,
                "late_provider_response_ignored": late_provider_response_ignored,
            },
        )
        result.execution_summary = execution_summary
        run.scope_json = {**(run.scope_json or {}), "execution_summary": execution_summary}
        run.finished_at = datetime.now(timezone.utc)
        result.warnings = all_warnings
        result.provider_call_count = audit.provider_call_count
        result.run_id = run.id
        result.item_id = item.id
        try:
            await session.commit()
        except StaleDataError:
            logger.warning(
                "[connection-extraction] late cancel commit ignored — cleanup already removed rows run=%s",
                getattr(run, "id", None),
            )
            await session.rollback()
        return result

    audit.pack_summaries = pack_traces
    logger.info(
        "[connection-extraction] provider_call_count=%s pair_count=%s pack_count=%s parsed_projections=%s",
        audit.provider_call_count,
        audit.pair_count,
        audit.pack_count,
        audit.parsed_projection_count,
    )

    unprocessed = len(pairs) - len(processed_pair_ids)
    result.processed_pair_count = len(processed_pair_ids)
    result.unprocessed_pair_count = max(0, unprocessed)
    result.no_connection_count = len(all_no_connections)
    result.provider_call_count = audit.provider_call_count
    result.provider_success_count = audit.provider_success_count
    result.provider_error_count = audit.provider_error_count
    result.provider_empty_response_count = audit.provider_empty_response_count

    created_connection_ids: list[uuid.UUID] = []
    mirror_created = 0
    mirror_updated = 0

    item.parsed_response_json = {
        "connections": normalized_connections,
        "no_connections": all_no_connections,
    }
    item.normalized_output_json = item.parsed_response_json
    confidences = [c["confidence"] for c in normalized_connections if c.get("confidence") is not None]
    if confidences:
        item.confidence = sum(confidences) / len(confidences)

    candidate_map = {c.id: c for c in candidates}
    if create_mirror_records and normalized_connections:
        if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
            all_warnings.append("Mirror persist skipped — workflow cancelled")
            normalized_connections = []
        try:
            mc, skip, tr, ev, pw, created_ids = await persist_connection_mirror_records(
                session,
                run=run,
                item=item,
                connections=normalized_connections,
                candidate_map=candidate_map,
                create_triples=create_triples,
                create_evidence=create_evidence,
                composite_workflow_run_id=composite_workflow_run_id,
                workflow_step_key=workflow_step_key,
            )
            mirror_created = mc
            created_connection_ids = created_ids
            audit.created_projection_count = mc
            result.mirror_connection_created_count = mc
            result.mirror_connection_skipped_duplicate_count = skip
            result.triple_created_count = tr
            result.evidence_created_count = ev
            all_warnings.extend(pw)
            await _log_event(
                "info",
                "projections_created",
                f"Mirror persist: created={mirror_created}, updated={mirror_updated}",
                {
                    "created_projection_count": mirror_created,
                    "updated_projection_count": mirror_updated,
                },
            )
        except Exception as exc:
            all_warnings.append(str(exc))
            run.error_message = f"mirror persist failed: {exc}"

    mirror_output_count = mirror_created + mirror_updated
    run.output_count = mirror_output_count

    final_status, status_warnings = finalize_connection_extraction_status(
        dry_run=False,
        audit=audit,
        processed_pair_count=result.processed_pair_count,
        unprocessed_pair_count=result.unprocessed_pair_count,
        connection_count=len(normalized_connections),
        no_connection_count=len(all_no_connections),
        mirror_output_count=mirror_output_count,
    )
    all_warnings.extend(status_warnings)
    semantic_outcome = final_status
    persistent_status, _ = apply_persistent_run_status(
        run,
        semantic_outcome,
        no_connection_count=result.no_connection_count,
        created_projection_count=mirror_created,
    )
    result.status = semantic_outcome
    result.outcome = semantic_outcome
    result.display_status = semantic_outcome
    result.persistent_status = persistent_status

    if semantic_outcome == LlmRunStatus.failed_provider_not_called:
        await _log_event(
            "error",
            "provider_not_called",
            "Provider was not called although dry_run=false and pair_count>0",
            {
                "pair_count": audit.pair_count,
                "pack_count": audit.pack_count,
                "provider_call_count": audit.provider_call_count,
            },
        )
    elif semantic_outcome in {
        LlmRunStatus.failed_parse_error,
        LlmRunStatus.failed_no_output,
        LlmRunStatus.failed_provider_error,
        LlmRunStatus.failed_provider_empty_response,
        LlmRunStatus.failed_empty_prompt,
    }:
        await _log_event(
            "error",
            "workflow_failed",
            f"Connection extraction finished with status={semantic_outcome}",
            {"status": semantic_outcome, "provider_call_count": audit.provider_call_count},
        )

    if is_semantic_failure(semantic_outcome):
        item.status = LlmItemStatus.failed
        item.error_message = status_warnings[0] if status_warnings else semantic_outcome
        run.error_count = max(int(run.error_count or 0), 1)
    elif is_semantic_no_edges(semantic_outcome):
        item.status = LlmItemStatus.needs_review
    elif normalized_connections:
        item.status = LlmItemStatus.succeeded
    else:
        item.status = LlmItemStatus.needs_review

    result.created_connection_ids = created_connection_ids
    execution_summary = build_execution_summary(
        audit,
        pack_traces,
        extra={
            **debug_extra,
            "processed_pair_count": result.processed_pair_count,
            "unprocessed_pair_count": result.unprocessed_pair_count,
            "no_connection_count": result.no_connection_count,
            "fail_fast_triggered": fail_fast_triggered,
            "fail_fast_reason": FAIL_FAST_DEFAULT_REASON if fail_fast_triggered else None,
            "remaining_pack_count_skipped": remaining_pack_count_skipped,
        },
    )
    result.execution_summary = execution_summary
    reassign_jsonb(
        run,
        "scope_json",
        {
            **(run.scope_json or {}),
            "execution_summary": execution_summary,
            "pack_summaries": execution_summary.get("pack_summaries") or [],
            "provider_audit": execution_summary.get("provider_audit") or {},
        },
    )
    reassign_jsonb(
        item,
        "prompt_json",
        {
            **(item.prompt_json or {}),
            "pack_traces": pack_traces,
            "execution_summary": execution_summary,
        },
    )

    if result.unprocessed_pair_count > 0:
        all_warnings.append(
            f"UNPROCESSED_PAIRS: {result.unprocessed_pair_count} pair(s) missing from provider output"
        )

    if debug_single_pack:
        if executed_pack_count != 1 or audit.provider_call_count > 1 or audit.prompt_sent_count > 1:
            all_warnings.append("DEBUG_SINGLE_PACK_NOT_ENFORCED")
        if executed_pack_count != 1:
            all_warnings.append(
                f"DEBUG_SINGLE_PACK_INVARIANT: expected executed_pack_count=1, got {executed_pack_count}"
            )
        if audit.provider_call_count > 1:
            all_warnings.append(
                f"DEBUG_SINGLE_PACK_INVARIANT: expected provider_call_count<=1, got {audit.provider_call_count}"
            )
        if audit.prompt_sent_count > 1:
            all_warnings.append(
                f"DEBUG_SINGLE_PACK_INVARIANT: expected prompt_sent_count<=1, got {audit.prompt_sent_count}"
            )

    preview = build_connection_prompt_preview(
        prompt_key=prompt_template_key,
        pair_count=len(pairs),
        packs=packs,
        system_prompt=system_prompt,
        sample_user_prompt=tpl.user_prompt_template,
        processed_pair_count=result.processed_pair_count,
        unprocessed_pair_count=result.unprocessed_pair_count,
        no_connection_count=result.no_connection_count,
        model_call_count=audit.provider_call_count,
        execution_summary=execution_summary,
    )
    result.prompt_preview = preview

    run.finished_at = datetime.now(timezone.utc)
    result.run_id = run.id
    result.item_id = item.id
    result.connection_count = len(normalized_connections)
    result.warnings = all_warnings

    try:
        await session.commit()
        await session.refresh(run)
        await session.refresh(item)
    except StaleDataError:
        if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
            logger.warning(
                "[connection-extraction] late final commit ignored after cancel run=%s",
                getattr(run, "id", None),
            )
            await session.rollback()
        else:
            raise
    return result
