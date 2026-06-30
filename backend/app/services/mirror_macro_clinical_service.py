"""Mirror KG macro_clinical alignment service (Step 8.6).

Schema foundation CRUD only — no LLM, no auto-approve/promote, no final_* / kg_*.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorKgTriple, MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import (
    MirrorCircuitFunction,
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorDualModelVerificationResult,
    MirrorDualModelVerificationRun,
    MirrorProjectionFunction,
)
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitFunctionCreate,
    MirrorCircuitProjectionMembershipCreate,
    MirrorCircuitStepCreate,
    MirrorDualModelVerificationResultCreate,
    MirrorDualModelVerificationRunCreate,
    MirrorProjectionFunctionCreate,
)


class MirrorCircuitNotFoundError(Exception):
    pass


class MirrorProjectionNotFoundError(Exception):
    pass


class MirrorCircuitStepNotFoundError(Exception):
    pass


class MirrorProjectionFunctionNotFoundError(Exception):
    pass


class MirrorCircuitFunctionNotFoundError(Exception):
    pass


class MirrorCircuitFunctionsNotInitializedError(Exception):
    """Raised when mirror_circuit_functions table has not been created (migration 033)."""

    migration_path = "backend/migrations/033_mirror_circuit_functions.sql"


class MirrorMembershipNotFoundError(Exception):
    pass


class MirrorDualModelRunNotFoundError(Exception):
    pass


class MirrorDualModelResultNotFoundError(Exception):
    pass


class SameGranularityValidationError(Exception):
    pass


class DuplicateStepOrderError(Exception):
    pass


class DuplicateMembershipError(Exception):
    pass


class VerificationObjectNotFoundError(Exception):
    pass


class InvalidStepReferenceError(Exception):
    pass


async def _get_circuit(session: AsyncSession, circuit_id: uuid.UUID) -> MirrorRegionCircuit:
    row = await session.get(MirrorRegionCircuit, circuit_id)
    if row is None:
        raise MirrorCircuitNotFoundError(str(circuit_id))
    return row


async def _get_projection(session: AsyncSession, projection_id: uuid.UUID) -> MirrorRegionConnection:
    row = await session.get(MirrorRegionConnection, projection_id)
    if row is None:
        raise MirrorProjectionNotFoundError(str(projection_id))
    return row


async def _get_step(session: AsyncSession, step_id: uuid.UUID) -> MirrorCircuitStep:
    row = await session.get(MirrorCircuitStep, step_id)
    if row is None:
        raise MirrorCircuitStepNotFoundError(str(step_id))
    return row


def _assert_same_atlas_granularity(
    *,
    label_a: str,
    atlas_a: str,
    level_a: str,
    family_a: str | None,
    label_b: str,
    atlas_b: str,
    level_b: str,
    family_b: str | None,
) -> None:
    if atlas_a != atlas_b:
        raise SameGranularityValidationError(
            f"{label_a} and {label_b} must share source_atlas (no cross-atlas merge)"
        )
    if level_a != level_b:
        raise SameGranularityValidationError(
            f"{label_a} and {label_b} must share granularity_level"
        )
    if family_a != family_b:
        raise SameGranularityValidationError(
            f"{label_a} and {label_b} must share granularity_family"
        )


async def _validate_circuit_step_refs(
    session: AsyncSession,
    payload: MirrorCircuitStepCreate,
) -> MirrorRegionCircuit:
    circuit = await _get_circuit(session, payload.circuit_id)
    _assert_same_atlas_granularity(
        label_a="circuit_step",
        atlas_a=payload.source_atlas,
        level_a=payload.granularity_level,
        family_a=payload.granularity_family,
        label_b="circuit",
        atlas_b=circuit.source_atlas,
        level_b=circuit.granularity_level,
        family_b=circuit.granularity_family,
    )
    if payload.region_candidate_id is not None:
        cand = await session.get(CandidateBrainRegion, payload.region_candidate_id)
        if cand is None:
            raise SameGranularityValidationError("region_candidate_id not found")
        _assert_same_atlas_granularity(
            label_a="circuit_step",
            atlas_a=payload.source_atlas,
            level_a=payload.granularity_level,
            family_a=payload.granularity_family,
            label_b="region candidate",
            atlas_b=cand.source_atlas,
            level_b=cand.granularity_level,
            family_b=cand.granularity_family,
        )
    dup_q = select(MirrorCircuitStep.id).where(
        MirrorCircuitStep.circuit_id == payload.circuit_id,
        MirrorCircuitStep.step_order == payload.step_order,
    )
    if (await session.execute(dup_q)).scalar_one_or_none() is not None:
        raise DuplicateStepOrderError(
            f"step_order {payload.step_order} already exists for circuit {payload.circuit_id}"
        )
    return circuit


async def create_circuit_step(
    session: AsyncSession,
    payload: MirrorCircuitStepCreate,
) -> MirrorCircuitStep:
    await _validate_circuit_step_refs(session, payload)
    data = payload.model_dump()
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    data.setdefault("mirror_status", MirrorStatus.llm_suggested)
    data.setdefault("review_status", MirrorReviewStatus.pending)
    row = MirrorCircuitStep(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_circuit_steps(
    session: AsyncSession,
    *,
    circuit_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorCircuitStep], int]:
    base = select(MirrorCircuitStep)
    if circuit_id:
        base = base.where(MirrorCircuitStep.circuit_id == circuit_id)
    if resource_id:
        base = base.where(MirrorCircuitStep.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorCircuitStep.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorCircuitStep.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorCircuitStep.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorCircuitStep.granularity_family == granularity_family)
    if mirror_status:
        base = base.where(MirrorCircuitStep.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorCircuitStep.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorCircuitStep.promotion_status == promotion_status)
    if llm_run_id:
        base = base.where(MirrorCircuitStep.llm_run_id == llm_run_id)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorCircuitStep.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_circuit_step(session: AsyncSession, step_id: uuid.UUID) -> MirrorCircuitStep:
    row = await session.get(MirrorCircuitStep, step_id)
    if row is None:
        raise MirrorCircuitStepNotFoundError(str(step_id))
    return row


async def _validate_projection_function_refs(
    session: AsyncSession,
    payload: MirrorProjectionFunctionCreate,
) -> MirrorRegionConnection:
    projection = await _get_projection(session, payload.projection_id)
    _assert_same_atlas_granularity(
        label_a="projection_function",
        atlas_a=payload.source_atlas,
        level_a=payload.granularity_level,
        family_a=payload.granularity_family,
        label_b="projection",
        atlas_b=projection.source_atlas,
        level_b=projection.granularity_level,
        family_b=projection.granularity_family,
    )
    return projection


async def _find_existing_projection_function_for_merge(
    session: AsyncSession,
    payload: MirrorProjectionFunctionCreate,
) -> MirrorProjectionFunction | None:
    """Find existing projection function with the same canonical key.

    Canonical key: (projection_id, function_term_key, function_category, relation_type)
    where function_term_key is function_term_en.strip().lower().
    Excludes records that are rejected, failed/promoted, or superseded.
    """
    blocked_review = frozenset({MirrorReviewStatus.rejected})
    blocked_promo = frozenset({MirrorPromotionStatus.failed, MirrorPromotionStatus.promoted})

    base = select(MirrorProjectionFunction).where(
        MirrorProjectionFunction.projection_id == payload.projection_id,
        MirrorProjectionFunction.function_category == payload.function_category,
        MirrorProjectionFunction.relation_type == payload.relation_type,
        MirrorProjectionFunction.review_status.notin_(blocked_review),
        MirrorProjectionFunction.promotion_status.notin_(blocked_promo),
    )
    rows = (
        await session.execute(
            base.order_by(MirrorProjectionFunction.created_at.desc())
        )
    ).scalars().all()

    func_term_norm = payload.function_term.strip().lower()
    for row in rows:
        if row.function_term and row.function_term.strip().lower() == func_term_norm:
            return row
    return None


async def create_projection_function(
    session: AsyncSession,
    payload: MirrorProjectionFunctionCreate,
) -> MirrorProjectionFunction:
    await _validate_projection_function_refs(session, payload)

    existing = await _find_existing_projection_function_for_merge(session, payload)
    if existing is not None:
        old_conf = existing.confidence or 0.0
        new_conf = payload.confidence or 0.0
        if new_conf > old_conf:
            existing.confidence = payload.confidence
            existing.evidence_text = payload.evidence_text
            existing.uncertainty_reason = payload.uncertainty_reason
            existing.llm_run_id = payload.llm_run_id
            existing.llm_item_id = payload.llm_item_id
            existing.mirror_status = MirrorStatus.llm_suggested
            await session.flush()
            await session.refresh(existing)
        return existing

    data = payload.model_dump()
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    data.setdefault("mirror_status", MirrorStatus.llm_suggested)
    data.setdefault("review_status", MirrorReviewStatus.pending)
    row = MirrorProjectionFunction(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_projection_functions(
    session: AsyncSession,
    *,
    projection_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorProjectionFunction], int]:
    base = select(MirrorProjectionFunction)
    if projection_id:
        base = base.where(MirrorProjectionFunction.projection_id == projection_id)
    if resource_id:
        base = base.where(MirrorProjectionFunction.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorProjectionFunction.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorProjectionFunction.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorProjectionFunction.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorProjectionFunction.granularity_family == granularity_family)
    if mirror_status:
        base = base.where(MirrorProjectionFunction.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorProjectionFunction.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorProjectionFunction.promotion_status == promotion_status)
    if llm_run_id:
        base = base.where(MirrorProjectionFunction.llm_run_id == llm_run_id)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorProjectionFunction.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_projection_function(
    session: AsyncSession, projection_function_id: uuid.UUID
) -> MirrorProjectionFunction:
    row = await session.get(MirrorProjectionFunction, projection_function_id)
    if row is None:
        raise MirrorProjectionFunctionNotFoundError(str(projection_function_id))
    return row


async def _validate_membership_refs(
    session: AsyncSession,
    payload: MirrorCircuitProjectionMembershipCreate,
) -> tuple[MirrorRegionCircuit, MirrorRegionConnection]:
    circuit = await _get_circuit(session, payload.circuit_id)
    projection = await _get_projection(session, payload.projection_id)
    _assert_same_atlas_granularity(
        label_a="circuit",
        atlas_a=circuit.source_atlas,
        level_a=circuit.granularity_level,
        family_a=circuit.granularity_family,
        label_b="projection",
        atlas_b=projection.source_atlas,
        level_b=projection.granularity_level,
        family_b=projection.granularity_family,
    )
    _assert_same_atlas_granularity(
        label_a="membership",
        atlas_a=payload.source_atlas,
        level_a=payload.granularity_level,
        family_a=payload.granularity_family,
        label_b="circuit",
        atlas_b=circuit.source_atlas,
        level_b=circuit.granularity_level,
        family_b=circuit.granularity_family,
    )
    if payload.source_step_id is not None:
        src_step = await _get_step(session, payload.source_step_id)
        if src_step.circuit_id != payload.circuit_id:
            raise InvalidStepReferenceError("source_step_id must belong to the same circuit")
    if payload.target_step_id is not None:
        tgt_step = await _get_step(session, payload.target_step_id)
        if tgt_step.circuit_id != payload.circuit_id:
            raise InvalidStepReferenceError("target_step_id must belong to the same circuit")
    if (
        payload.source_step_id is not None
        and payload.target_step_id is not None
        and payload.source_step_id == payload.target_step_id
    ):
        raise InvalidStepReferenceError("source_step_id and target_step_id must differ")
    dup_q = select(MirrorCircuitProjectionMembership.id).where(
        MirrorCircuitProjectionMembership.circuit_id == payload.circuit_id,
        MirrorCircuitProjectionMembership.projection_id == payload.projection_id,
        MirrorCircuitProjectionMembership.source_step_id == payload.source_step_id,
        MirrorCircuitProjectionMembership.target_step_id == payload.target_step_id,
    )
    if (await session.execute(dup_q)).scalar_one_or_none() is not None:
        raise DuplicateMembershipError(
            "membership with same circuit, projection, source_step, target_step already exists"
        )
    return circuit, projection


async def create_circuit_projection_membership(
    session: AsyncSession,
    payload: MirrorCircuitProjectionMembershipCreate,
) -> MirrorCircuitProjectionMembership:
    await _validate_membership_refs(session, payload)
    data = payload.model_dump()
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    data.setdefault("mirror_status", MirrorStatus.llm_suggested)
    data.setdefault("review_status", MirrorReviewStatus.pending)
    row = MirrorCircuitProjectionMembership(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_circuit_projection_memberships(
    session: AsyncSession,
    *,
    circuit_id: uuid.UUID | None = None,
    projection_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    verification_status: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorCircuitProjectionMembership], int]:
    base = select(MirrorCircuitProjectionMembership)
    if circuit_id:
        base = base.where(MirrorCircuitProjectionMembership.circuit_id == circuit_id)
    if projection_id:
        base = base.where(MirrorCircuitProjectionMembership.projection_id == projection_id)
    if resource_id:
        base = base.where(MirrorCircuitProjectionMembership.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorCircuitProjectionMembership.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorCircuitProjectionMembership.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorCircuitProjectionMembership.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(MirrorCircuitProjectionMembership.granularity_family == granularity_family)
    if verification_status:
        base = base.where(MirrorCircuitProjectionMembership.verification_status == verification_status)
    if mirror_status:
        base = base.where(MirrorCircuitProjectionMembership.mirror_status == mirror_status)
    if review_status:
        base = base.where(MirrorCircuitProjectionMembership.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorCircuitProjectionMembership.promotion_status == promotion_status)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorCircuitProjectionMembership.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_circuit_projection_membership(
    session: AsyncSession, membership_id: uuid.UUID
) -> MirrorCircuitProjectionMembership:
    row = await session.get(MirrorCircuitProjectionMembership, membership_id)
    if row is None:
        raise MirrorMembershipNotFoundError(str(membership_id))
    return row


async def create_dual_model_verification_run(
    session: AsyncSession,
    payload: MirrorDualModelVerificationRunCreate,
) -> MirrorDualModelVerificationRun:
    row = MirrorDualModelVerificationRun(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_dual_model_verification_runs(
    session: AsyncSession,
    *,
    verification_task_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorDualModelVerificationRun], int]:
    base = select(MirrorDualModelVerificationRun)
    if verification_task_type:
        base = base.where(
            MirrorDualModelVerificationRun.verification_task_type == verification_task_type
        )
    if resource_id:
        base = base.where(MirrorDualModelVerificationRun.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorDualModelVerificationRun.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorDualModelVerificationRun.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorDualModelVerificationRun.granularity_level == granularity_level)
    if status:
        base = base.where(MirrorDualModelVerificationRun.status == status)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorDualModelVerificationRun.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_dual_model_verification_run(
    session: AsyncSession, run_id: uuid.UUID
) -> MirrorDualModelVerificationRun:
    row = await session.get(MirrorDualModelVerificationRun, run_id)
    if row is None:
        raise MirrorDualModelRunNotFoundError(str(run_id))
    return row


async def _resolve_verification_object(
    session: AsyncSession,
    object_type: str,
    object_id: uuid.UUID,
) -> None:
    lookup: dict[str, type] = {
        "circuit_projection_membership": MirrorCircuitProjectionMembership,
        "projection_function": MirrorProjectionFunction,
        "circuit_step": MirrorCircuitStep,
        "circuit": MirrorRegionCircuit,
        "projection": MirrorRegionConnection,
        "triple": MirrorKgTriple,
    }
    model = lookup.get(object_type)
    if model is None:
        raise VerificationObjectNotFoundError(f"unsupported object_type: {object_type}")
    row = await session.get(model, object_id)
    if row is None:
        raise VerificationObjectNotFoundError(f"{object_type} {object_id} not found")


async def create_dual_model_verification_result(
    session: AsyncSession,
    payload: MirrorDualModelVerificationResultCreate,
) -> MirrorDualModelVerificationResult:
    run = await get_dual_model_verification_run(session, payload.run_id)
    if run is None:
        raise MirrorDualModelRunNotFoundError(str(payload.run_id))
    await _resolve_verification_object(session, payload.object_type, payload.object_id)
    row = MirrorDualModelVerificationResult(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_dual_model_verification_results(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    consensus_status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorDualModelVerificationResult], int]:
    base = select(MirrorDualModelVerificationResult)
    if run_id:
        base = base.where(MirrorDualModelVerificationResult.run_id == run_id)
    if object_type:
        base = base.where(MirrorDualModelVerificationResult.object_type == object_type)
    if object_id:
        base = base.where(MirrorDualModelVerificationResult.object_id == object_id)
    if consensus_status:
        base = base.where(MirrorDualModelVerificationResult.consensus_status == consensus_status)
    if resource_id:
        base = base.where(MirrorDualModelVerificationResult.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorDualModelVerificationResult.batch_id == batch_id)
    if source_atlas:
        base = base.where(MirrorDualModelVerificationResult.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(MirrorDualModelVerificationResult.granularity_level == granularity_level)
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(
            base.order_by(MirrorDualModelVerificationResult.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_dual_model_verification_result(
    session: AsyncSession, result_id: uuid.UUID
) -> MirrorDualModelVerificationResult:
    row = await session.get(MirrorDualModelVerificationResult, result_id)
    if row is None:
        raise MirrorDualModelResultNotFoundError(str(result_id))
    return row


def _is_mirror_circuit_functions_missing(exc: BaseException) -> bool:
    msg = str(getattr(exc, "orig", exc)).lower()
    if "mirror_circuit_functions" not in msg:
        return False
    missing_markers = (
        "does not exist",
        "undefinedtable",
        "undefined table",
        "不存在",  # zh_CN PostgreSQL: relation "..." does not exist
        "undefined_object",
        "42p01",  # PostgreSQL undefined_table
    )
    return any(marker in msg for marker in missing_markers)


async def _run_mirror_circuit_function_query(coro):
    try:
        return await coro
    except ProgrammingError as exc:
        if _is_mirror_circuit_functions_missing(exc):
            raise MirrorCircuitFunctionsNotInitializedError from exc
        raise
    except DBAPIError as exc:
        if _is_mirror_circuit_functions_missing(exc):
            raise MirrorCircuitFunctionsNotInitializedError from exc
        raise


async def list_mirror_circuit_functions(
    session: AsyncSession,
    *,
    circuit_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    function_domain: str | None = None,
    function_role: str | None = None,
    effect_type: str | None = None,
    mirror_status: str | None = None,
    review_status: str | None = None,
    validation_status: str | None = None,
    promotion_status: str | None = None,
    status: str | None = None,
    llm_run_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorCircuitFunction], int]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)

    async def _query() -> tuple[list[MirrorCircuitFunction], int]:
        base = select(MirrorCircuitFunction)
        if circuit_id:
            base = base.where(MirrorCircuitFunction.circuit_id == circuit_id)
        if resource_id:
            base = base.where(MirrorCircuitFunction.resource_id == resource_id)
        if batch_id:
            base = base.where(MirrorCircuitFunction.batch_id == batch_id)
        if source_atlas:
            base = base.where(MirrorCircuitFunction.source_atlas == source_atlas)
        if granularity_level:
            base = base.where(MirrorCircuitFunction.granularity_level == granularity_level)
        if granularity_family:
            base = base.where(MirrorCircuitFunction.granularity_family == granularity_family)
        if function_domain:
            base = base.where(MirrorCircuitFunction.function_domain == function_domain)
        if function_role:
            base = base.where(MirrorCircuitFunction.function_role == function_role)
        if effect_type:
            base = base.where(MirrorCircuitFunction.effect_type == effect_type)
        if mirror_status:
            base = base.where(MirrorCircuitFunction.mirror_status == mirror_status)
        if review_status:
            base = base.where(MirrorCircuitFunction.review_status == review_status)
        if validation_status:
            base = base.where(MirrorCircuitFunction.validation_status == validation_status)
        if promotion_status:
            base = base.where(MirrorCircuitFunction.promotion_status == promotion_status)
        if status:
            base = base.where(MirrorCircuitFunction.status == status)
        if llm_run_id:
            base = base.where(MirrorCircuitFunction.llm_run_id == llm_run_id)
        if q:
            pattern = f"%{q.strip()}%"
            base = base.where(
                or_(
                    MirrorCircuitFunction.function_term_en.ilike(pattern),
                    MirrorCircuitFunction.function_term_cn.ilike(pattern),
                    MirrorCircuitFunction.description.ilike(pattern),
                )
            )
        total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        rows = (
            await session.execute(
                base.order_by(MirrorCircuitFunction.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
        return list(rows), total

    return await _run_mirror_circuit_function_query(_query())


async def get_mirror_circuit_function(
    session: AsyncSession,
    circuit_function_id: uuid.UUID,
) -> MirrorCircuitFunction:
    async def _query() -> MirrorCircuitFunction:
        row = await session.get(MirrorCircuitFunction, circuit_function_id)
        if row is None:
            raise MirrorCircuitFunctionNotFoundError(str(circuit_function_id))
        return row

    return await _run_mirror_circuit_function_query(_query())


async def _validate_circuit_function_refs(
    session: AsyncSession,
    payload: MirrorCircuitFunctionCreate,
) -> MirrorRegionCircuit:
    circuit = await _get_circuit(session, payload.circuit_id)
    _assert_same_atlas_granularity(
        label_a="circuit_function",
        atlas_a=payload.source_atlas,
        level_a=payload.granularity_level,
        family_a=payload.granularity_family,
        label_b="circuit",
        atlas_b=circuit.source_atlas,
        level_b=circuit.granularity_level,
        family_b=circuit.granularity_family,
    )
    return circuit


async def _find_existing_circuit_function_for_merge(
    session: AsyncSession,
    payload: MirrorCircuitFunctionCreate,
) -> MirrorCircuitFunction | None:
    """Find existing circuit function with the same canonical key.

    Canonical key: (circuit_id, function_term_key, function_domain, function_role, effect_type)
    where function_term_key is function_term_en.strip().lower().
    Excludes records that are rejected, failed/promoted, or superseded.
    """
    blocked_review = frozenset({MirrorReviewStatus.rejected})
    blocked_promo = frozenset({MirrorPromotionStatus.failed, MirrorPromotionStatus.promoted})

    base = select(MirrorCircuitFunction).where(
        MirrorCircuitFunction.circuit_id == payload.circuit_id,
        MirrorCircuitFunction.function_domain == payload.function_domain,
        MirrorCircuitFunction.function_role == payload.function_role,
        MirrorCircuitFunction.effect_type == payload.effect_type,
        MirrorCircuitFunction.review_status.notin_(blocked_review),
        MirrorCircuitFunction.promotion_status.notin_(blocked_promo),
    )
    rows = (
        await session.execute(
            base.order_by(MirrorCircuitFunction.created_at.desc())
        )
    ).scalars().all()

    func_term_norm = (payload.function_term_en or "").strip().lower()
    for row in rows:
        if row.function_term_en and row.function_term_en.strip().lower() == func_term_norm:
            return row
    return None


async def create_circuit_function(
    session: AsyncSession,
    payload: MirrorCircuitFunctionCreate,
) -> MirrorCircuitFunction:
    await _validate_circuit_function_refs(session, payload)

    existing = await _find_existing_circuit_function_for_merge(session, payload)
    if existing is not None:
        old_conf = existing.confidence or 0.0
        new_conf = payload.confidence or 0.0
        if new_conf > old_conf:
            existing.function_term_en = payload.function_term_en
            existing.function_term_cn = payload.function_term_cn
            existing.function_domain = payload.function_domain
            existing.function_role = payload.function_role
            existing.effect_type = payload.effect_type
            existing.confidence_score = payload.confidence_score
            existing.confidence = payload.confidence
            existing.evidence_text = payload.evidence_text
            existing.uncertainty_reason = payload.uncertainty_reason
            existing.description = payload.description
            existing.remark = payload.remark
            existing.llm_run_id = payload.llm_run_id
            existing.llm_item_id = payload.llm_item_id
            existing.mirror_status = MirrorStatus.llm_suggested
            await session.flush()
            await session.refresh(existing)
        return existing

    data = payload.model_dump()
    data["promotion_status"] = MirrorPromotionStatus.not_promoted
    data.setdefault("mirror_status", MirrorStatus.llm_suggested)
    data.setdefault("review_status", MirrorReviewStatus.pending)
    row = MirrorCircuitFunction(**data)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row
