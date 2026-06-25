"""LLM Extraction business logic — DeepSeek candidate-side field completion.

Boundaries (guide §LLM/Agent validation layer, §Candidate/Final DB):
  - Reads candidate_brain_regions; writes the LLM side ONLY (candidate_llm_extractions).
  - Output is ADVISORY: never written to final_* / kg_*, never auto-approved or
    promoted, and does NOT mutate candidate_brain_regions.candidate_status here.
  - Single extraction and small batch (<= MAX_BATCH_SIZE) only, to prevent accidental
    large-scale paid API calls. Full lineage is copied from the candidate onto each row.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_deepseek_runtime_config
from app.models.candidate import CandidateBrainRegion
from datetime import datetime, timezone

from app.models.llm_extraction import (
    CandidateLlmExtraction,
    LlmExtractionItem,
    LlmExtractionRun,
)
from app.schemas.llm_extraction import (
    IMPLEMENTED_TASK_TYPES,
    MAX_BATCH_SIZE,
    PROMPT_VERSION,
    LlmExtractionStatus,
    LlmItemStatus,
    LlmProviderInfo,
    LlmRunStatus,
    LlmScopeType,
    LlmTaskType,
    LlmTaskTypeInfo,
)
from app.services.llm_json_utils import (
    normalize_region_field_completion_output,
    normalized_to_legacy_structured,
    parse_llm_json_response,
)
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES, render_user_prompt
from app.services.llm_providers import ProviderNotConfiguredError, UnknownProviderError, get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config, get_kimi_runtime_config, load_runtime_settings
from app.services.deepseek_client import (
    DeepSeekCallError,
    DeepSeekConfigError,
    chat_completion,
)

logger = logging.getLogger(__name__)


class CandidateNotFoundError(Exception):
    pass


class BatchTooLargeError(Exception):
    def __init__(self, requested: int):
        self.requested = requested
        super().__init__(f"batch size {requested} exceeds max {MAX_BATCH_SIZE}")


_SYSTEM_PROMPT = (
    "You are a neuroanatomy knowledge assistant helping curate brain-atlas region "
    "candidates. You are given ONE candidate region's raw and parsed fields. Suggest "
    "completed/translated/explanatory fields. These are SUGGESTIONS for human review, "
    "NOT final facts. Be conservative: if unsure, lower the confidence and set "
    "needs_human_review=true. Respond with a SINGLE JSON object and nothing else, "
    "matching exactly this shape:\n"
    "{\n"
    '  "candidate_id": string,\n'
    '  "suggested_cn_name": string,\n'
    '  "suggested_en_name": string,\n'
    '  "suggested_aliases": [string],\n'
    '  "suggested_description": string,\n'
    '  "suggested_region_base_name": string,\n'
    '  "suggested_laterality": "left|right|bilateral|midline|unknown",\n'
    '  "confidence": number between 0 and 1,\n'
    '  "evidence_summary": string,\n'
    '  "risk_flags": [string],\n'
    '  "needs_human_review": boolean\n'
    "}"
)


def _build_user_prompt(candidate: CandidateBrainRegion) -> str:
    fields = {
        "candidate_id": str(candidate.id),
        "source_atlas": candidate.source_atlas,
        "source_version": candidate.source_version,
        "source_label_id": candidate.source_label_id,
        "label_value": candidate.label_value,
        "raw_name": candidate.raw_name,
        "std_name": candidate.std_name,
        "en_name": candidate.en_name,
        "cn_name": candidate.cn_name,
        "laterality": candidate.laterality,
        "region_base_name": candidate.region_base_name,
        "granularity_level": candidate.granularity_level,
        "granularity_family": candidate.granularity_family,
    }
    return (
        "Candidate region fields (some may be missing):\n"
        + json.dumps(fields, ensure_ascii=False, indent=2)
        + "\n\nReturn the JSON object described in the system prompt."
    )


def _parse_structured(raw: str) -> dict:
    """Best-effort parse of the model's JSON. Tolerates code fences / surrounding text."""
    text = raw.strip()
    if text.startswith("```"):
        # strip a leading ```json / ``` fence and trailing fence
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def _persist_extraction(
    session: AsyncSession,
    candidate: CandidateBrainRegion,
    *,
    run_id: uuid.UUID,
    model: str,
    status: str,
    raw_response: str | None,
    structured_result: dict | None,
    error_message: str | None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: int | None = None,
) -> CandidateLlmExtraction:
    row = CandidateLlmExtraction(
        candidate_id=candidate.id,
        batch_id=candidate.batch_id,
        resource_id=candidate.resource_id,
        generation_run_id=candidate.generation_run_id,
        parse_run_id=candidate.parse_run_id,
        run_id=run_id,
        provider="deepseek",
        model=model,
        prompt_version=PROMPT_VERSION,
        status=status,
        raw_response=raw_response,
        structured_result=structured_result,
        error_message=error_message,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )
    session.add(row)
    await session.flush()
    return row


async def extract_one(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    run_id: uuid.UUID | None = None,
) -> CandidateLlmExtraction:
    """Run DeepSeek extraction for a single candidate; always persists a row.

    A DeepSeek config/call failure is recorded as a status='failed' row (with the
    error message) rather than raising, so the workbench can surface it per-candidate.
    Raises CandidateNotFoundError only when the candidate id does not exist.
    """
    candidate = await session.get(CandidateBrainRegion, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError(str(candidate_id))

    run = run_id or uuid.uuid4()
    default_model = get_deepseek_runtime_config().default_model

    try:
        result = await chat_completion(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(candidate),
        )
    except (DeepSeekConfigError, DeepSeekCallError) as exc:
        logger.warning(
            "event_type=llm_extraction result=failed candidate_id=%s error=%s",
            candidate_id,
            exc,
        )
        row = await _persist_extraction(
            session,
            candidate,
            run_id=run,
            model=default_model,
            status=LlmExtractionStatus.failed,
            raw_response=None,
            structured_result=None,
            error_message=str(exc),
        )
        await session.commit()
        await session.refresh(row)
        return row

    structured: dict | None
    error: str | None
    try:
        structured = _parse_structured(result.content)
        status = LlmExtractionStatus.succeeded
        error = None
    except (json.JSONDecodeError, ValueError) as exc:
        structured = None
        status = LlmExtractionStatus.failed
        error = f"failed to parse model JSON: {exc}"

    row = await _persist_extraction(
        session,
        candidate,
        run_id=run,
        model=result.model,
        status=status,
        raw_response=result.content,
        structured_result=structured,
        error_message=error,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms,
    )
    await session.commit()
    await session.refresh(row)
    logger.info(
        "event_type=llm_extraction result=%s candidate_id=%s run_id=%s",
        status,
        candidate_id,
        run,
    )
    return row


async def extract_batch(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
) -> tuple[uuid.UUID, list[CandidateLlmExtraction]]:
    """Run extraction for a small batch of candidates (<= MAX_BATCH_SIZE).

    Candidates are processed sequentially under one shared run_id. A missing candidate
    id raises CandidateNotFoundError before any call; per-candidate LLM failures are
    captured as failed rows.
    """
    if len(candidate_ids) > MAX_BATCH_SIZE:
        raise BatchTooLargeError(len(candidate_ids))

    run = uuid.uuid4()
    rows: list[CandidateLlmExtraction] = []
    for cid in candidate_ids:
        rows.append(await extract_one(session, cid, run_id=run))
    return run, rows


async def list_extractions(
    session: AsyncSession,
    *,
    candidate_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateLlmExtraction], int]:
    base = select(CandidateLlmExtraction)
    count_q = select(func.count()).select_from(CandidateLlmExtraction)
    filters = []
    if candidate_id:
        filters.append(CandidateLlmExtraction.candidate_id == candidate_id)
    if batch_id:
        filters.append(CandidateLlmExtraction.batch_id == batch_id)
    if resource_id:
        filters.append(CandidateLlmExtraction.resource_id == resource_id)
    if run_id:
        filters.append(CandidateLlmExtraction.run_id == run_id)
    if status:
        filters.append(CandidateLlmExtraction.status == status)
    for f in filters:
        base = base.where(f)
        count_q = count_q.where(f)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(CandidateLlmExtraction.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_latest_for_candidate(
    session: AsyncSession, candidate_id: uuid.UUID
) -> CandidateLlmExtraction | None:
    row = (
        await session.execute(
            select(CandidateLlmExtraction)
            .where(CandidateLlmExtraction.candidate_id == candidate_id)
            .order_by(CandidateLlmExtraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


# ---------------------------------------------------------------------------
# Infrastructure (Step 1) — providers, runs, items
# ---------------------------------------------------------------------------


class LlmTaskNotImplementedError(Exception):
    def __init__(self, task_type: str):
        self.task_type = task_type
        super().__init__(task_type)


class ProviderNotConfiguredServiceError(Exception):
    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(message)


_TASK_TYPE_LABELS: dict[str, tuple[str, str]] = {
    LlmTaskType.region_field_completion: ("Region field completion", "Candidate-side region field advisory completion"),
    LlmTaskType.region_alias_completion: ("Region alias completion", "Planned"),
    LlmTaskType.region_description_completion: ("Region description completion", "Planned"),
    LlmTaskType.same_granularity_connection_completion: (
        "Same-granularity connections",
        "LLM advisory connection completion to Mirror KG (Step 3)",
    ),
    LlmTaskType.same_granularity_function_completion: (
        "Same-granularity functions",
        "Extract function candidates per region into Mirror KG",
    ),
    LlmTaskType.same_granularity_circuit_completion: (
        "Same-granularity circuits",
        "Extract circuit candidates with optional connection/function context into Mirror KG",
    ),
    LlmTaskType.triple_candidate_generation: ("Triple candidate generation", "Planned — Step 6"),
    LlmTaskType.translation: ("Translation", "Planned"),
    LlmTaskType.evidence_explanation: ("Evidence explanation", "Planned"),
    LlmTaskType.uncertainty_flagging: ("Uncertainty flagging", "Planned"),
    LlmTaskType.regions_to_circuits: (
        "Regions to circuits (macro_clinical)",
        "Planned Step 8.5 — region pool → circuit candidates",
    ),
    LlmTaskType.circuit_to_steps: (
        "Circuit to steps (macro_clinical)",
        "Decompose mirror circuit into ordered mirror_circuit_steps (Step 8.7)",
    ),
    LlmTaskType.circuit_steps_to_projections: (
        "Circuit steps to projections (macro_clinical)",
        "Derive mirror projections + circuit-projection memberships from ordered steps (Step 8.8)",
    ),
    LlmTaskType.projections_to_circuits: (
        "Projections to circuits (macro_clinical)",
        "Step 8.10 — reverse infer circuits from projection graph",
    ),
    LlmTaskType.circuit_projection_cross_validation: (
        "Circuit projection cross validation (macro_clinical)",
        "Planned Step 8.5b — compare circuit→projection vs projection→circuit",
    ),
    LlmTaskType.dual_model_verification: (
        "Dual model verification (macro_clinical)",
        "Step 8.12 — DeepSeek/Kimi independent verification with deterministic consensus",
    ),
    LlmTaskType.region_to_functions: (
        "Region to functions (macro_clinical)",
        "Planned Step 8.5 — region_function candidates",
    ),
    LlmTaskType.circuit_to_functions: (
        "Circuit to functions (macro_clinical)",
        "Extract mirror_circuit_functions from mirror_region_circuits (Step 10.6.3)",
    ),
    LlmTaskType.projection_to_functions: (
        "Projection to functions (macro_clinical)",
        "Step 8.9 — projection_function candidates from mirror_region_connections",
    ),
    LlmTaskType.macro_clinical_triple_generation: (
        "Macro clinical triple generation",
        "Planned Step 8.5 — LLM-assisted triple view (prefer deterministic consolidation)",
    ),
    LlmTaskType.evidence_uncertainty_review: (
        "Evidence uncertainty review",
        "Planned Step 8.5 — evidence quality and risk flags",
    ),
}


def list_llm_task_types() -> list[LlmTaskTypeInfo]:
    return [
        LlmTaskTypeInfo(
            task_type=key,
            label=label,
            implemented=key in IMPLEMENTED_TASK_TYPES,
            description=desc,
        )
        for key, (label, desc) in _TASK_TYPE_LABELS.items()
    ]


def list_llm_providers() -> list[LlmProviderInfo]:
    runtime = load_runtime_settings().api_providers
    deepseek = get_deepseek_runtime_config()
    kimi = get_kimi_runtime_config()
    return [
        LlmProviderInfo(
            name="deepseek",
            configured=bool(runtime.deepseek.api_key.strip()),
            default_model=deepseek.default_model,
            enabled=deepseek.enabled,
        ),
        LlmProviderInfo(
            name="kimi",
            configured=bool(runtime.kimi.api_key.strip()),
            default_model=kimi.default_model,
            enabled=kimi.enabled,
        ),
    ]


def _resolve_template(template_key: str):
    tpl = DEFAULT_TEMPLATES.get(template_key)
    if tpl is None:
        tpl = DEFAULT_TEMPLATES["region_field_completion_v1"]
    return tpl


def build_region_field_prompt(candidate: CandidateBrainRegion, template_key: str) -> tuple[str, str, dict]:
    tpl = _resolve_template(template_key)
    values = {
        "candidate_id": str(candidate.id),
        "source_atlas": candidate.source_atlas or "",
        "granularity_level": candidate.granularity_level or "",
        "granularity_family": candidate.granularity_family or "",
        "en_name": candidate.en_name or "",
        "cn_name": candidate.cn_name or "",
        "laterality": candidate.laterality or "",
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
    }
    return tpl.system_prompt, user_prompt, prompt_json


async def _sync_legacy_extraction(
    session: AsyncSession,
    candidate: CandidateBrainRegion,
    *,
    run_id: uuid.UUID,
    provider: str,
    model: str,
    status: str,
    raw_response: str | None,
    structured_result: dict | None,
    error_message: str | None,
    usage: dict | None = None,
    latency_ms: int | None = None,
) -> CandidateLlmExtraction:
    usage = usage or {}
    row = await _persist_extraction(
        session,
        candidate,
        run_id=run_id,
        model=model,
        status=status,
        raw_response=raw_response,
        structured_result=structured_result,
        error_message=error_message,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        latency_ms=latency_ms,
    )
    row.provider = provider
    return row


async def run_region_field_completion(
    session: AsyncSession,
    *,
    provider_name: str,
    model_name: str | None,
    candidate_ids: list[uuid.UUID],
    prompt_template_key: str,
    temperature: float,
    max_tokens: int,
    dry_run: bool,
) -> tuple[LlmExtractionRun, list[LlmExtractionItem], list[CandidateLlmExtraction]]:
    if len(candidate_ids) > MAX_BATCH_SIZE:
        raise BatchTooLargeError(len(candidate_ids))

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

    tpl = _resolve_template(prompt_template_key)
    now = datetime.now(timezone.utc)
    scope_type = (
        LlmScopeType.single_candidate if len(candidates) == 1 else LlmScopeType.candidate_batch
    )
    first = candidates[0]
    run = LlmExtractionRun(
        task_type=LlmTaskType.region_field_completion,
        provider=provider_key,
        model_name=resolved_model,
        prompt_template_key=tpl.template_key,
        prompt_version=tpl.version,
        scope_type=scope_type,
        scope_json={"candidate_ids": [str(c.id) for c in candidates]},
        resource_id=first.resource_id,
        batch_id=first.batch_id,
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

    items: list[LlmExtractionItem] = []
    legacy_rows: list[CandidateLlmExtraction] = []
    succeeded = 0
    failed = 0
    total_usage: dict[str, int] = {}

    provider = None if dry_run else get_llm_provider(provider_key)

    for index, candidate in enumerate(candidates):
        system_prompt, user_prompt, prompt_json = build_region_field_prompt(
            candidate, prompt_template_key
        )
        item = LlmExtractionItem(
            run_id=run.id,
            candidate_id=candidate.id,
            resource_id=candidate.resource_id,
            batch_id=candidate.batch_id,
            task_type=LlmTaskType.region_field_completion,
            item_index=index,
            input_json={
                "candidate_id": str(candidate.id),
                "source_atlas": candidate.source_atlas,
                "granularity_level": candidate.granularity_level,
                "granularity_family": candidate.granularity_family,
                "en_name": candidate.en_name,
                "cn_name": candidate.cn_name,
                "laterality": candidate.laterality,
            },
            prompt_json=prompt_json,
            status=LlmItemStatus.running if not dry_run else LlmItemStatus.created,
        )
        session.add(item)
        await session.flush()

        if dry_run:
            item.status = LlmItemStatus.succeeded
            item.normalized_output_json = {"dry_run": True}
            succeeded += 1
            items.append(item)
            continue

        assert provider is not None
        response = await provider.complete_json(
            model=resolved_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        item.raw_response_text = response.raw_text or None
        run.request_payload_redacted = response.request_payload_redacted

        if response.error_message:
            item.status = LlmItemStatus.failed
            item.error_message = response.error_message
            failed += 1
        elif response.parsed_json is None:
            item.status = LlmItemStatus.failed
            item.error_message = "failed to parse model JSON"
            failed += 1
        else:
            item.parsed_response_json = response.parsed_json
            normalized = normalize_region_field_completion_output(response.parsed_json)
            item.normalized_output_json = normalized
            item.confidence = normalized.get("confidence")
            item.evidence_text = normalized.get("evidence_text")
            item.uncertainty_reason = normalized.get("uncertainty_reason")
            item.status = LlmItemStatus.succeeded
            succeeded += 1

            legacy = await _sync_legacy_extraction(
                session,
                candidate,
                run_id=run.id,
                provider=provider_key,
                model=response.model,
                status=LlmExtractionStatus.succeeded,
                raw_response=response.raw_text,
                structured_result=normalized_to_legacy_structured(
                    normalized, str(candidate.id)
                ),
                error_message=None,
                usage=response.usage.as_dict(),
                latency_ms=response.latency_ms,
            )
            legacy_rows.append(legacy)

        for key, val in response.usage.as_dict().items():
            if val is not None:
                total_usage[key] = total_usage.get(key, 0) + int(val)
        items.append(item)

    run.output_count = succeeded
    run.error_count = failed
    run.usage_json = total_usage
    run.finished_at = datetime.now(timezone.utc)
    if failed == 0 and succeeded > 0:
        run.status = LlmRunStatus.succeeded
    elif succeeded > 0:
        run.status = LlmRunStatus.partially_succeeded
    else:
        run.status = LlmRunStatus.failed

    await session.commit()
    await session.refresh(run)
    for item in items:
        await session.refresh(item)
    return run, items, legacy_rows


async def list_extraction_runs(
    session: AsyncSession,
    *,
    task_type: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LlmExtractionRun], int]:
    base = select(LlmExtractionRun)
    count_q = select(func.count()).select_from(LlmExtractionRun)
    if task_type:
        base = base.where(LlmExtractionRun.task_type == task_type)
        count_q = count_q.where(LlmExtractionRun.task_type == task_type)
    if provider:
        base = base.where(LlmExtractionRun.provider == provider)
        count_q = count_q.where(LlmExtractionRun.provider == provider)
    if status:
        base = base.where(LlmExtractionRun.status == status)
        count_q = count_q.where(LlmExtractionRun.status == status)
    if resource_id:
        base = base.where(LlmExtractionRun.resource_id == resource_id)
        count_q = count_q.where(LlmExtractionRun.resource_id == resource_id)
    if batch_id:
        base = base.where(LlmExtractionRun.batch_id == batch_id)
        count_q = count_q.where(LlmExtractionRun.batch_id == batch_id)
    if candidate_id:
        subq = select(LlmExtractionItem.run_id).where(
            LlmExtractionItem.candidate_id == candidate_id
        )
        base = base.where(LlmExtractionRun.id.in_(subq))
        count_q = count_q.where(LlmExtractionRun.id.in_(subq))

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(LlmExtractionRun.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_extraction_run(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[LlmExtractionRun | None, list[LlmExtractionItem]]:
    run = await session.get(LlmExtractionRun, run_id)
    if run is None:
        return None, []
    items = (
        await session.execute(
            select(LlmExtractionItem)
            .where(LlmExtractionItem.run_id == run_id)
            .order_by(LlmExtractionItem.item_index.asc())
        )
    ).scalars().all()
    return run, list(items)


async def list_extraction_items(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    task_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LlmExtractionItem], int]:
    base = select(LlmExtractionItem)
    count_q = select(func.count()).select_from(LlmExtractionItem)
    if run_id:
        base = base.where(LlmExtractionItem.run_id == run_id)
        count_q = count_q.where(LlmExtractionItem.run_id == run_id)
    if candidate_id:
        base = base.where(LlmExtractionItem.candidate_id == candidate_id)
        count_q = count_q.where(LlmExtractionItem.candidate_id == candidate_id)
    if task_type:
        base = base.where(LlmExtractionItem.task_type == task_type)
        count_q = count_q.where(LlmExtractionItem.task_type == task_type)
    if status:
        base = base.where(LlmExtractionItem.status == status)
        count_q = count_q.where(LlmExtractionItem.status == status)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(LlmExtractionItem.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total
