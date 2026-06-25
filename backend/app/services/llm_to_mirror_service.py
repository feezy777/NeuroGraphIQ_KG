"""Convert llm_extraction_items into Mirror KG records (planned LLM output shapes).

Not auto-triggered in Step 2 — called explicitly by future extraction steps or tests.
Does NOT call LLM providers; does NOT write final_* / kg_*.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_extraction import LlmExtractionItem
from app.models.mirror_kg import (
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import (
    MirrorCircuitRegionCreate,
    MirrorKgTripleCreate,
    MirrorRegionCircuitCreate,
    MirrorRegionConnectionCreate,
    MirrorRegionFunctionCreate,
    TripleScope,
)
from app.services import mirror_kg_service


class LlmItemNotFoundError(Exception):
    pass


class LlmItemTaskTypeMismatchError(Exception):
    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected task_type={expected}, got {actual}")


class LlmItemNormalizedOutputError(Exception):
    pass


async def _load_item(session: AsyncSession, item_id: uuid.UUID) -> LlmExtractionItem:
    row = await session.get(LlmExtractionItem, item_id)
    if row is None:
        raise LlmItemNotFoundError(str(item_id))
    return row


def _require_dict(data: Any, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise LlmItemNormalizedOutputError(f"normalized_output_json.{field} must be an object")
    return data


def _parse_uuid(value: Any, field: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise LlmItemNormalizedOutputError(f"invalid UUID in {field}") from exc


async def create_mirror_connection_from_llm_item(
    session: AsyncSession,
    item_id: uuid.UUID,
) -> MirrorRegionConnection:
    item = await _load_item(session, item_id)
    if item.task_type != LlmTaskType.same_granularity_connection_completion:
        raise LlmItemTaskTypeMismatchError(
            LlmTaskType.same_granularity_connection_completion, item.task_type
        )
    norm = item.normalized_output_json or {}
    if not norm:
        raise LlmItemNormalizedOutputError("normalized_output_json is empty")

    payload = MirrorRegionConnectionCreate(
        source_region_candidate_id=_parse_uuid(
            norm.get("source_region_candidate_id"), "source_region_candidate_id"
        ),
        target_region_candidate_id=_parse_uuid(
            norm.get("target_region_candidate_id"), "target_region_candidate_id"
        ),
        resource_id=item.resource_id,
        batch_id=item.batch_id,
        llm_run_id=item.run_id,
        llm_item_id=item.id,
        granularity_level=str(norm.get("granularity_level") or norm.get("granularity") or ""),
        granularity_family=norm.get("granularity_family"),
        source_atlas=str(norm.get("source_atlas") or ""),
        source_version=norm.get("source_version"),
        connection_type=str(norm.get("connection_type") or "unknown"),
        directionality=str(norm.get("directionality") or "unknown"),
        strength=norm.get("strength"),
        modality=norm.get("modality"),
        confidence=norm.get("confidence") if norm.get("confidence") is not None else item.confidence,
        evidence_text=norm.get("evidence_text") or item.evidence_text,
        uncertainty_reason=norm.get("uncertainty_reason") or item.uncertainty_reason,
        raw_payload_json={"llm_item_id": str(item.id), "parsed": item.parsed_response_json},
        normalized_payload_json=norm,
    )
    if not payload.granularity_level or not payload.source_atlas:
        raise LlmItemNormalizedOutputError(
            "granularity_level and source_atlas are required in normalized_output_json"
        )
    return await mirror_kg_service.create_mirror_connection(session, payload)


async def create_mirror_function_from_llm_item(
    session: AsyncSession,
    item_id: uuid.UUID,
) -> MirrorRegionFunction:
    item = await _load_item(session, item_id)
    if item.task_type != LlmTaskType.same_granularity_function_completion:
        raise LlmItemTaskTypeMismatchError(
            LlmTaskType.same_granularity_function_completion, item.task_type
        )
    norm = item.normalized_output_json or {}
    if not norm:
        raise LlmItemNormalizedOutputError("normalized_output_json is empty")

    payload = MirrorRegionFunctionCreate(
        region_candidate_id=_parse_uuid(norm.get("region_candidate_id"), "region_candidate_id")
        or item.candidate_id,
        resource_id=item.resource_id,
        batch_id=item.batch_id,
        llm_run_id=item.run_id,
        llm_item_id=item.id,
        granularity_level=str(norm.get("granularity_level") or norm.get("granularity") or ""),
        granularity_family=norm.get("granularity_family"),
        source_atlas=str(norm.get("source_atlas") or ""),
        source_version=norm.get("source_version"),
        function_term=str(norm.get("function_term") or norm.get("function") or ""),
        function_category=str(norm.get("function_category") or "unknown"),
        relation_type=str(norm.get("relation_type") or "associated_with"),
        confidence=norm.get("confidence") if norm.get("confidence") is not None else item.confidence,
        evidence_text=norm.get("evidence_text") or item.evidence_text,
        uncertainty_reason=norm.get("uncertainty_reason") or item.uncertainty_reason,
        raw_payload_json={"llm_item_id": str(item.id), "parsed": item.parsed_response_json},
        normalized_payload_json=norm,
    )
    if not payload.function_term:
        raise LlmItemNormalizedOutputError("function_term is required in normalized_output_json")
    if not payload.granularity_level or not payload.source_atlas:
        raise LlmItemNormalizedOutputError(
            "granularity_level and source_atlas are required in normalized_output_json"
        )
    return await mirror_kg_service.create_mirror_function(session, payload)


async def create_mirror_circuit_from_llm_item(
    session: AsyncSession,
    item_id: uuid.UUID,
) -> MirrorRegionCircuit:
    item = await _load_item(session, item_id)
    if item.task_type != LlmTaskType.same_granularity_circuit_completion:
        raise LlmItemTaskTypeMismatchError(
            LlmTaskType.same_granularity_circuit_completion, item.task_type
        )
    norm = item.normalized_output_json or {}
    if not norm:
        raise LlmItemNormalizedOutputError("normalized_output_json is empty")

    circuit_regions: list[MirrorCircuitRegionCreate] = []
    for idx, pr in enumerate(norm.get("participant_regions") or norm.get("circuit_regions") or []):
        pr_dict = _require_dict(pr, "participant_regions[]")
        circuit_regions.append(
            MirrorCircuitRegionCreate(
                region_candidate_id=_parse_uuid(
                    pr_dict.get("region_candidate_id"), "region_candidate_id"
                ),
                role=str(pr_dict.get("role") or "participant"),
                sort_order=int(pr_dict.get("sort_order") or idx),
            )
        )

    payload = MirrorRegionCircuitCreate(
        resource_id=item.resource_id,
        batch_id=item.batch_id,
        llm_run_id=item.run_id,
        llm_item_id=item.id,
        granularity_level=str(norm.get("granularity_level") or norm.get("granularity") or ""),
        granularity_family=norm.get("granularity_family"),
        source_atlas=str(norm.get("source_atlas") or ""),
        source_version=norm.get("source_version"),
        circuit_name=str(norm.get("circuit_name") or norm.get("name") or ""),
        circuit_type=str(norm.get("circuit_type") or "unknown"),
        function_association=norm.get("function_association"),
        description=norm.get("description"),
        confidence=norm.get("confidence") if norm.get("confidence") is not None else item.confidence,
        evidence_text=norm.get("evidence_text") or item.evidence_text,
        uncertainty_reason=norm.get("uncertainty_reason") or item.uncertainty_reason,
        raw_payload_json={"llm_item_id": str(item.id), "parsed": item.parsed_response_json},
        normalized_payload_json=norm,
        circuit_regions=circuit_regions,
    )
    if not payload.circuit_name:
        raise LlmItemNormalizedOutputError("circuit_name is required in normalized_output_json")
    if not payload.granularity_level or not payload.source_atlas:
        raise LlmItemNormalizedOutputError(
            "granularity_level and source_atlas are required in normalized_output_json"
        )
    return await mirror_kg_service.create_mirror_circuit(session, payload)


async def create_mirror_triples_from_llm_item(
    session: AsyncSession,
    item_id: uuid.UUID,
) -> list[MirrorKgTriple]:
    item = await _load_item(session, item_id)
    if item.task_type != LlmTaskType.triple_candidate_generation:
        raise LlmItemTaskTypeMismatchError(LlmTaskType.triple_candidate_generation, item.task_type)
    norm = item.normalized_output_json or {}
    triples_raw = norm.get("triples") or norm.get("triple_candidates") or []
    if not isinstance(triples_raw, list) or not triples_raw:
        raise LlmItemNormalizedOutputError("normalized_output_json.triples must be a non-empty list")

    created: list[MirrorKgTriple] = []
    for t in triples_raw:
        t_dict = _require_dict(t, "triples[]")
        payload = MirrorKgTripleCreate(
            subject_type=str(t_dict.get("subject_type") or "term"),
            subject_id=_parse_uuid(t_dict.get("subject_id"), "subject_id"),
            subject_label=str(t_dict.get("subject_label") or t_dict.get("subject") or ""),
            predicate=str(t_dict.get("predicate") or ""),
            object_type=str(t_dict.get("object_type") or "term"),
            object_id=_parse_uuid(t_dict.get("object_id"), "object_id"),
            object_label=str(t_dict.get("object_label") or t_dict.get("object") or ""),
            triple_scope=str(t_dict.get("triple_scope") or TripleScope.same_granularity),
            resource_id=item.resource_id,
            batch_id=item.batch_id,
            llm_run_id=item.run_id,
            llm_item_id=item.id,
            granularity_level=str(norm.get("granularity_level") or t_dict.get("granularity_level") or ""),
            granularity_family=norm.get("granularity_family") or t_dict.get("granularity_family"),
            source_atlas=str(norm.get("source_atlas") or t_dict.get("source_atlas") or ""),
            source_version=norm.get("source_version") or t_dict.get("source_version"),
            confidence=t_dict.get("confidence") if t_dict.get("confidence") is not None else item.confidence,
            evidence_text=t_dict.get("evidence_text") or item.evidence_text,
            uncertainty_reason=t_dict.get("uncertainty_reason") or item.uncertainty_reason,
            raw_payload_json={"llm_item_id": str(item.id), "triple": t_dict},
            normalized_payload_json=t_dict,
        )
        if not payload.subject_label or not payload.predicate or not payload.object_label:
            raise LlmItemNormalizedOutputError(
                "each triple requires subject_label, predicate, object_label"
            )
        if not payload.granularity_level or not payload.source_atlas:
            raise LlmItemNormalizedOutputError(
                "granularity_level and source_atlas are required for triples"
            )
        created.append(await mirror_kg_service.create_mirror_triple(session, payload))
    return created
